'use strict';
const $ = id => document.getElementById(id);
let mode = 'A', busy = false, current = null, records = [], appStatus = null;
let preparationTimer = null;
const modeNames = {A:'直接大模型问答', B:'向量检索增强', C:'图谱与向量增强'};
const hints = {
  A:'A 模式不会提供源码。模型可能无法确定这个项目的实际实现，这也是基线测试的一部分。',
  B:'使用 Ollama 与 Milvus 检索同版本代码。此模式不会连接 Neo4j，源码从本地片段存储读取。',
  C:'先执行与 B 相同的向量检索，再通过 Neo4j 补充调用关系与共享字段上下文。'
};
function chunkOptions() {
  const strategy=$('chunking-strategy').value;
  const size=Number($('chunk-size').value), overlap=Number($('chunk-overlap').value);
  if(strategy==='character'&&(!Number.isInteger(size)||size<200||size>4000||!Number.isInteger(overlap)||overlap<0||overlap>Math.floor(size/2)))throw new Error('字符块长需为 200—4000 的整数，重叠为 0 到块长一半的整数。');
  if(strategy==='token'&&(!Number.isInteger(size)||size<64||size>2048||!Number.isInteger(overlap)||overlap<0||overlap>Math.floor(size/2)))throw new Error('Token 块长需为 64—2048 的整数，重叠为 0 到块长一半的整数。');
  if(strategy==='paragraph')return {chunking_strategy:strategy};
  return {chunking_strategy:strategy,chunk_size:size,chunk_overlap:strategy==='paragraph'?0:overlap};
}
function selectedProfile() {
  try{
    const options=chunkOptions();
    const id=options.chunking_strategy==='method'?'method':options.chunking_strategy==='ast'?'ast_statement_v1':options.chunking_strategy==='paragraph'?'paragraph_blank_v1':options.chunking_strategy==='token'?`token_qwen3_v1_${options.chunk_size}_${options.chunk_overlap}`:`character_${options.chunk_size}_${options.chunk_overlap}`;
    return appStatus?.index_profiles?.find(profile=>profile.profile_id===id) || null;
  }catch{return null;}
}
function chunkLabel(config) {
  if(config?.strategy==='paragraph')return config.profile_id==='paragraph_blank_v1'?'空行 / 段落':`历史段落 / 上限 ${config.chunk_size} Token`;
  if(config?.strategy==='token')return `Token ${config.chunk_size} / 重叠 ${config.chunk_overlap}`;
  if(config?.strategy==='ast')return 'AST 语句';
  return config?.strategy==='character'?`字符 ${config.chunk_size} / 重叠 ${config.chunk_overlap}`:'方法 / 字段';
}
function updateChunking() {
  const chars=$('chunking-strategy').value==='character';
  const paragraphs=$('chunking-strategy').value==='paragraph';
  const tokens=$('chunking-strategy').value==='token';
  $('chunk-size-label').hidden=!(chars||tokens);$('chunk-overlap-label').hidden=paragraphs||!(chars||tokens);
  $('chunk-size-unit').textContent=tokens?'每块 Token 数':'每块字符数';
  $('chunk-overlap-unit').textContent=tokens?'重叠 Token 数':'重叠字符数';
  $('chunk-size').min=tokens?64:200;$('chunk-size').max=tokens?2048:4000;$('chunk-size').step=tokens?1:100;
  $('chunk-overlap').max=Math.floor(Number($('chunk-size').value)/2);
  $('chunking-description').textContent=paragraphs?'只按空行（含仅空格或 Tab 的行）分段。':tokens?'使用 Qwen3 Embedding 分词器按真实 Token 数切分；保留原文，中文边界安全对齐，实际重叠可能略少。不按字符估算。':$('chunking-strategy').value==='ast'?'按 Java AST 方法体直接语句切分；条件、循环和 switch 保持完整，字段声明单独成块。复合语句不强制按字符截断。':chars?'按 Unicode 字符连续切分，空白和换行也计数；字符窗口可能跨方法或从行中间开始。':'按完整方法或字段声明切分，保留现有的 20 个片段。';
  const retrievalNote=$('top-k').parentElement.querySelector('p');
  retrievalNote.textContent=paragraphs?'先检索段落；C 补充同策略片段。段落由排版决定，可能拆开方法或语法结构。':tokens?'先检索 Token 窗口；C 补充同策略关联片段。块长只统计代码，不含符号前缀或回答 Token。':$('chunking-strategy').value==='ast'?'先检索 AST 语句；C 补充最多 3 个同策略图关联片段。细粒度片段不代表完整方法。':chars?'先检索字符窗口；C 再补充最多 3 个同策略关联片段，保留字符位置，不改用完整方法。':'先检索方法代码；C 额外补充最多 3 个图关联片段。每次请求使用相同的完整片段预算。';
  const profile=selectedProfile(), task=appStatus?.preparation;
  const status=$('chunking-status');
  if(task?.status==='running'){status.textContent=`准备中：${task.message}。请保持 Ollama 与数据库运行。`;status.className='chunking-status working';}
  else if(task?.status==='failed'){status.textContent=`上次准备失败：${task.message}`;status.className='chunking-status failed';}
  else{status.textContent=profile?`该配置已就绪 · ${profile.chunk_count} 个片段 · 切换后直接使用对应索引`:'该配置尚未准备。点击“准备该索引”生成向量；不会覆盖其他配置。';status.className=`chunking-status ${profile?'ready':''}`;}
  $('prepare-index').textContent=profile?'重新准备该索引':'准备该索引';
  $('snapshot-side').textContent=profile?.commit_sha?.slice(0,7)||appStatus?.snapshot?.slice(0,7)||'待准备';
  $('chunk-count').textContent=profile?.chunk_count ?? '—';
  updateControls();
}
function element(tag, text, className) {const node=document.createElement(tag); if(text!==undefined)node.textContent=text; if(className)node.className=className; return node;}
function showError(message) {$('error').textContent=message; $('error').hidden=false;}
function updateControls() {
  const preparing=appStatus?.preparation?.status==='running';
  const blocked=busy||preparing;
  const profile=selectedProfile();
  $('send').disabled=blocked || !$('question').value.trim();
  $('compare').disabled=blocked || !$('question').value.trim() || !profile?.graph_ready;
  $('top-k').disabled=blocked || mode==='A';
  document.querySelectorAll('[data-mode]').forEach(button=>button.disabled=blocked);
  $('question').disabled=blocked;
  ['chunking-strategy','chunk-size','chunk-overlap','prepare-index'].forEach(id=>$(id).disabled=blocked);
}
function setMode(next) {
  mode=next;
  document.querySelectorAll('[data-mode]').forEach(button=>{const active=button.dataset.mode===mode;button.classList.toggle('selected',active);button.setAttribute('aria-pressed',String(active));});
  $('mode-hint').querySelector('p').textContent=hints[mode];
  updateControls();
}
async function fetchJson(url, options) {
  const response=await fetch(url,options);
  const body=await response.json();
  if(!response.ok)throw new Error(body.error || '请求失败，请稍后再试');
  return body;
}
function download(data, filename) {
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}));
  const link=element('a');link.href=url;link.download=filename;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function formatAnswer(container,text) {
  container.replaceChildren();
  const blocks=text.split(/(```[\s\S]*?```)/g);
  for(const block of blocks){
    if(!block)continue;
    if(block.startsWith('```')){container.append(element('pre',block.replace(/^```[^\n]*\n?/, '').replace(/```$/, '')));continue;}
    for(const paragraph of block.split(/\n\n+/)){
      const heading=paragraph.match(/^#{1,3}\s+([^\n]+)$/);
      if(heading){container.append(element('h3',heading[1]));continue;}
      const p=element('p');
      const tokens=paragraph.split(/(\*\*[^*]+\*\*|`[^`]+`|\[E\d+\])/g);
      for(const token of tokens){
        if(token.startsWith('**')&&token.endsWith('**'))p.append(element('strong',token.slice(2,-2)));
        else if(token.startsWith('`')&&token.endsWith('`'))p.append(element('code',token.slice(1,-1)));
        else if(/^\[E\d+\]$/.test(token)){
          const link=element('button',token,'evidence-ref');
          link.addEventListener('click',()=>{
            const detail=document.querySelector(`details[data-evidence="${token.slice(1,-1)}"]`);
            if(detail){document.querySelector('[data-tab="evidence"]').click();detail.open=true;detail.scrollIntoView({block:'nearest',behavior:'smooth'});}
          });p.append(link);
        }else p.append(document.createTextNode(token));
      }
      container.append(p);
    }
  }
}
function renderEvidence(record) {
  $('evidence-list').replaceChildren(); $('evidence-count').textContent=record.evidence.length;
  $('evidence-empty').hidden=record.evidence.length>0;
  $('evidence-empty').querySelector('h3').textContent=record.mode==='A'?'本次未使用源码':'未找到可用证据';
  $('evidence-empty').querySelector('p').textContent=record.mode==='A'?'A 模式只发送问题与回答要求，不提供项目代码。':'请检查索引，或换一种问法。';
  for(const item of record.evidence){
    const detail=element('details',undefined,'evidence-card');detail.dataset.evidence=item.evidence_id;
    const summary=element('summary');summary.append(element('span',item.evidence_id));summary.append(element('strong',item.name));
    summary.append(element('small',`${item.origin==='graph'?'图谱补充':'向量召回'} · L${item.start_line}–${item.end_line}${item.score===null?'':` · ${Number(item.score).toFixed(3)}`}`));
    if(item.source_start_char!==undefined)summary.append(element('small',`字符 [${item.source_start_char}, ${item.source_end_char}) · ${item.character_count} 字符`));
    if(item.token_count!==undefined)summary.append(element('small',item.chunking_strategy==='paragraph'?`${item.token_count} Token · 段落 ${item.paragraph_index+1} / 子块 ${item.paragraph_part+1}`:`${item.token_count} Token · 源码 Token [${item.source_start_token}, ${item.source_end_token})`));
    if(item.ast_node_type)summary.append(element('small',`AST ${item.ast_node_type} · ${item.canonical_name}`));
    summary.title=`${item.file_path}\n${item.canonical_name}`;
    detail.append(summary,element('pre',item.code,'evidence-code'));$('evidence-list').append(detail);
  }
  const trace=$('trace-content');trace.replaceChildren();
  record.components.forEach((component,index)=>trace.append(element('div',`${String(index+1).padStart(2,'0')}  ${component}`,'trace-step')));
  if(record.graph_paths.length){
    trace.append(element('p','本次扩展关系','trace-caption'));
    const names={...record.symbol_names};record.evidence.filter(item=>!item.symbol_ids).forEach(item=>names[item.symbol_id]=item.name);
    for(const path of record.graph_paths){
      for(const rel of path.relations)trace.append(element('div',`${names[rel.source]||'共享字段'} → ${rel.type} → ${names[rel.target]||'共享字段'} · L${rel.line}`,'trace-path'));
    }
  }
  trace.append(element('p',`上下文 ${record.context_characters} 字符 · 每次问题独立调用`,'trace-caption'));
  if(record.commit_sha)trace.append(element('p',`源码快照 ${record.commit_sha.slice(0,12)}`,'trace-caption'));
  if(record.mode!=='A')trace.append(element('p',`切分：${chunkLabel(record.chunking)} · ${record.collection||'历史索引'}`,'trace-caption'));
}
function renderRecord(record) {
  current=record;
  $('empty-state').hidden=true;$('answer-section').hidden=false;
  $('result-mode').textContent=`方案 ${record.mode} · ${record.mode==='A'?'不使用代码切片':chunkLabel(record.chunking)}`;
  $('answered-question').textContent=record.question;
  formatAnswer($('answer-text'),record.answer);
  $('warnings').replaceChildren(...record.warnings.map(w=>element('p',w)));
  $('answer-meta').replaceChildren(...[
    `耗时 ${record.timings.total_seconds}s`,`${record.usage.total_tokens ?? '—'} token`,
    `返回模型 ${record.returned_model}`,new Date(record.created_at).toLocaleString('zh-CN'),'模型结论需结合源码复核'
  ].map(text=>element('span',text)));
  renderEvidence(record);
}
async function refresh(statusOnly=false) {
  try{
    appStatus=await fetchJson('/api/status');
    $('connection').classList.add('connected');$('connection').lastChild.textContent=' 平台已连接';
    if(!statusOnly){records=(await fetchJson('/api/history')).records;$('history-count').textContent=records.length;renderHistory();}
    updateChunking();
    if(appStatus.preparation?.status==='running'&&!preparationTimer)preparationTimer=setInterval(()=>refresh(true),2000);
    if(appStatus.preparation?.status!=='running'&&preparationTimer){clearInterval(preparationTimer);preparationTimer=null;}
  }catch(error){$('connection').classList.remove('connected');$('connection').lastChild.textContent=' 连接中断';showError(error.message);}
}
function navigate(historyView) {
  $('workbench').hidden=historyView;$('history-section').hidden=!historyView;
  $('nav-workbench').classList.toggle('active',!historyView);$('nav-history').classList.toggle('active',historyView);
  $('breadcrumb-current').textContent=historyView?'问答记录':'问询工作台';
}
function rememberRecord(record) {
  records.push(record);
  if (records.length > 100) records = records.slice(-100);
}

function renderHistory() {
  const list=$('history-list');list.replaceChildren();
  if(!records.length){list.append(element('div','还没有问答记录，回到工作台提出第一个问题。','history-empty'));return;}
  [...records].reverse().forEach(record=>{
    const button=element('button',undefined,'history-card');button.append(element('span',record.mode));
    const info=element('div');info.append(element('strong',record.question),element('p',`${new Date(record.created_at).toLocaleString('zh-CN')} · ${modeNames[record.mode]} · ${record.mode==='A'?'不切片':chunkLabel(record.chunking)} · ${record.timings.total_seconds}s`));
    button.append(info,element('small','查看 →'));button.addEventListener('click',()=>{navigate(false);setMode(record.mode);const config=record.chunking||record.requested_chunking||{strategy:'method'};$('chunking-strategy').value=config.strategy;$('chunk-size').value=config.chunk_size||800;$('chunk-overlap').value=config.chunk_overlap??100;updateChunking();renderRecord(record);$('question').value=record.question;onInput();});list.append(button);
  });
}
async function requestQuestion(selected,question,options) {
  return fetchJson('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:selected,question,top_k:Number($('top-k').value),...options})});
}
async function run(compare=false) {
  if(busy)return;
  const question=$('question').value.trim();if(!question)return;
  let options;try{options=chunkOptions();}catch(error){showError(error.message);return;}
  if((mode!=='A'||compare)&&!selectedProfile()){showError('该切分方式和参数尚未准备索引，请先点击“准备该索引”。');return;}
  busy=true;updateControls();$('error').hidden=true;$('loading').hidden=false;$('empty-state').hidden=true;$('comparison').hidden=true;
  const start=Date.now();const timer=setInterval(()=>$('elapsed').textContent=`${Math.round((Date.now()-start)/1000)}s`,500);
  try{
    if(compare){
      $('comparison-results').replaceChildren();$('comparison').hidden=false;
      for(const selected of ['A','B','C']){
        $('loading-label').textContent=`正在运行方案 ${selected}：${modeNames[selected]}…`;
        const card=element('div',undefined,'comparison-card');card.append(element('strong',`方案 ${selected} · ${modeNames[selected]}`));$('comparison-results').append(card);
        try{
          const record=await requestQuestion(selected,question,options);rememberRecord(record);card.append(element('p',record.answer));
          const button=element('button',`查看证据与详情 · ${record.timings.total_seconds}s`);button.addEventListener('click',()=>{setMode(selected);renderRecord(record);});card.append(button);renderRecord(record);
        }catch(error){card.append(element('p',error.message));}
      }
    }else{
      $('loading-label').textContent=`正在运行方案 ${mode}：${modeNames[mode]}…`;
      const record=await requestQuestion(mode,question,options);rememberRecord(record);renderRecord(record);
    }
    if(compare&&current)setMode(current.mode);
    $('history-count').textContent=records.length;renderHistory();
  }catch(error){showError(error.message);if(!current)$('empty-state').hidden=false;}
  finally{clearInterval(timer);$('loading').hidden=true;busy=false;updateControls();}
}
async function prepareIndex() {
  if(busy||appStatus?.preparation?.status==='running')return;
  let options;try{options=chunkOptions();}catch(error){showError(error.message);return;}
  busy=true;updateControls();$('error').hidden=true;
  try{
    const result=await fetchJson('/api/prepare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(options)});
    appStatus={...appStatus,preparation:result.preparation};
    await refresh(true);
  }catch(error){showError(error.message);}
  finally{busy=false;updateChunking();}
}
function onInput() {$('char-count').textContent=$('question').value.length;updateControls();}
document.querySelectorAll('[data-mode]').forEach(button=>button.addEventListener('click',()=>setMode(button.dataset.mode)));
document.querySelectorAll('[data-question]').forEach(button=>button.addEventListener('click',()=>{if(busy)return;$('question').value=button.dataset.question;onInput();$('question').focus();}));
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b===button));$('evidence-panel').hidden=button.dataset.tab!=='evidence';$('trace-panel').hidden=button.dataset.tab!=='trace';}));
$('question').addEventListener('input',onInput);$('question').addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key==='Enter'){event.preventDefault();run();}});
$('send').addEventListener('click',()=>run());$('compare').addEventListener('click',()=>run(true));
$('nav-workbench').addEventListener('click',()=>navigate(false));$('nav-history').addEventListener('click',()=>navigate(true));
$('refresh-status').addEventListener('click',()=>refresh());
['chunking-strategy','chunk-size','chunk-overlap'].forEach(id=>$(id).addEventListener('change',updateChunking));
$('prepare-index').addEventListener('click',prepareIndex);
$('export-current').addEventListener('click',()=>{if(current)download(current,`inquiry_${current.mode}_${current.id}.json`);});
$('export-history').addEventListener('click',()=>download(records,'inquiry_history.json'));
setMode('A');refresh();
