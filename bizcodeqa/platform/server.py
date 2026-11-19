"""Loopback-only local web UI. Run python -m bizcodeqa.platform.server."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
from urllib.parse import urlsplit

from ..config import load_env
from .sample import ROOT
from .chunking import chunk_config
from .stores import state, index_profiles, ServiceError
from .qa import answer

WEB=ROOT/'web'
HISTORY=ROOT/'reports/platform/history.jsonl'
BUSY=threading.Lock()
HISTORY_LOCK=threading.Lock()
PREPARATION_LOCK=threading.Lock()
PREPARATION={'status':'idle'}


def preparation_status():
    with PREPARATION_LOCK:
        return dict(PREPARATION)


def prepare_in_background(config):
    def update(message):
        with PREPARATION_LOCK:
            PREPARATION['message']=message
    try:
        from .prepare import prepare
        result=prepare(config['strategy'],config.get('chunk_size',800),config.get('chunk_overlap',100),update)
        with PREPARATION_LOCK:
            PREPARATION.update(status='succeeded',message='索引准备完成',result=result)
    except Exception as exc:
        if isinstance(exc,(ServiceError,ValueError)):
            message=str(exc)
        else:
            message='索引准备失败，请确认 Ollama 模型、Milvus 和 Neo4j 已启动。原索引保持不变。'
        with PREPARATION_LOCK:
            PREPARATION.update(status='failed',message=message)
    finally:
        BUSY.release()


def history():
    if not HISTORY.exists():
        return []
    with HISTORY_LOCK:
        lines=HISTORY.read_text(encoding='utf-8').splitlines()[-100:]
    return [json.loads(line) for line in lines]


class Handler(BaseHTTPRequestHandler):
    server_version='CodeInquiry/1.0'

    def log_message(self, fmt, *args):
        # Do not log question text, request bodies or API credentials.
        pass

    def send(self,status,data,content_type='application/json; charset=utf-8'):
        body=json.dumps(data,ensure_ascii=False).encode() if not isinstance(data,bytes) else data
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def allowed_host(self):
        host=self.headers.get('Host','')
        port=self.server.server_port
        return host in (f'127.0.0.1:{port}',f'localhost:{port}')

    def do_GET(self):
        if not self.allowed_host():
            return self.send(403,{'error':'仅允许从本机地址访问'})
        path=urlsplit(self.path).path
        if path=='/api/status':
            index=state()
            return self.send(200,{'project':'Java 图书借阅系统','llm_model':os.getenv('LLM_MODEL','未配置'),
                                  'llm_configured':bool(os.getenv('LLM_API_KEY')),
                                  'index_ready':bool(index),'graph_ready':bool(index and index.get('graph_ready')),
                                  'snapshot':index['commit_sha'] if index else None,
                                  'chunk_count':len(index['chunks']) if index else 0,
                                  'entity_count':index['entity_count'] if index else 0,
                                  'relationship_count':index['relationship_count'] if index else 0,
                                  'embedding_model':index['embedding_model'] if index else 'qwen3-embedding:0.6b',
                                  'embedding_dimension':index['embedding_dimension'] if index else None,
                                  'index_profiles':index_profiles(),'preparation':preparation_status(),
                                  'status_scope':'索引登记状态；各服务可用性在实际请求时检查',
                                  'history_count':len(history()),'independent_question':True})
        if path=='/api/history':
            return self.send(200,{'records':history()})
        files={'/':('index.html','text/html; charset=utf-8'),
               '/app.js':('app.js','text/javascript; charset=utf-8'),
               '/style.css':('style.css','text/css; charset=utf-8')}
        if path in files:
            filename,mime=files[path]
            return self.send(200,(WEB/filename).read_bytes(),mime)
        return self.send(404,{'error':'页面不存在'})

    def do_POST(self):
        if not self.allowed_host():
            return self.send(403,{'error':'仅允许从本机地址访问'})
        origin=self.headers.get('Origin')
        if origin and origin not in (f'http://localhost:{self.server.server_port}',f'http://127.0.0.1:{self.server.server_port}'):
            return self.send(403,{'error':'不允许跨站请求'})
        if self.path not in ('/api/chat','/api/prepare'):
            return self.send(404,{'error':'接口不存在'})
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':
            return self.send(415,{'error':'请发送 JSON 请求'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16000:
                return self.send(413,{'error':'问题长度超出限制'})
            payload=json.loads(self.rfile.read(length))
            allowed={'chunking_strategy','chunk_size','chunk_overlap'}
            if self.path=='/api/chat':
                allowed.update({'mode','question','top_k'})
            if not isinstance(payload,dict) or set(payload)-allowed:
                raise ValueError('请求包含未支持的字段；平台使用独立问题，不接收对话历史或任意证据')
            config=chunk_config(payload.get('chunking_strategy','method'),payload.get('chunk_size',800),payload.get('chunk_overlap',100))
        except (ValueError,UnicodeError):
            return self.send(400,{'error':'无效的 JSON 请求或字段'})
        if not BUSY.acquire(blocking=False):
            return self.send(409,{'error':'已有问题或索引准备任务正在执行，请稍后再试'})
        if self.path=='/api/prepare':
            with PREPARATION_LOCK:
                PREPARATION.clear()
                PREPARATION.update(status='running',message='开始准备索引',config=config)
            try:
                threading.Thread(target=prepare_in_background,args=(config,),daemon=True).start()
            except Exception:
                with PREPARATION_LOCK:
                    PREPARATION.update(status='failed',message='无法启动索引准备任务')
                BUSY.release()
                return self.send(500,{'error':'无法启动索引准备任务'})
            return self.send(202,{'preparation':preparation_status()})
        try:
            result=answer(payload.get('mode','A'),payload.get('question',''),payload.get('top_k',5),
                          chunking_strategy=config['strategy'],chunk_size=config.get('chunk_size',800),
                          chunk_overlap=config.get('chunk_overlap',100))
            try:
                with HISTORY_LOCK:
                    HISTORY.parent.mkdir(parents=True,exist_ok=True)
                    with HISTORY.open('a',encoding='utf-8') as output:
                        output.write(json.dumps(result,ensure_ascii=False)+'\n')
            except OSError:
                result['warnings'].append('回答已生成，但本地记录保存失败。请立即导出结果。')
            return self.send(200,result)
        except ValueError as exc:
            return self.send(400,{'error':str(exc)})
        except ServiceError as exc:
            return self.send(503,{'error':str(exc)})
        except RuntimeError:
            return self.send(502,{'error':'大模型调用失败，请检查本地密钥、模型权限、额度或网络；不会显示密钥或上游错误原文。'})
        except Exception:
            return self.send(500,{'error':'平台请求失败，请检查本地服务配置。'})
        finally:
            BUSY.release()


def main():
    load_env(ROOT/'.env')
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--container',action='store_true',help='Only for Docker with loopback published port')
    args=parser.parse_args()
    server=ThreadingHTTPServer(('0.0.0.0' if args.container else '127.0.0.1',args.port),Handler)
    print(f'Code inquiry platform: http://127.0.0.1:{args.port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    main()
