"""Compile and smoke-test the book-borrowing sample without retaining class files."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[2]
    source = root / 'samples/book_borrow/src/experiment/bookBorrowSystem.java'
    report = {'source_path': source.relative_to(root).as_posix(),
              'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'scope': 'Compilation, menu exit and initial book listing only',
              'checks': [], 'status': 'FAIL'}
    try:
        for executable in ('java', 'javac'):
            if not shutil.which(executable):
                raise RuntimeError(f'{executable} not found in PATH; install JDK 17 or newer')
            version = subprocess.run([executable, '-version'], capture_output=True,
                                     encoding='utf-8', errors='replace', timeout=15, check=True)
            report[executable + '_version'] = (version.stdout + version.stderr).strip()
        with tempfile.TemporaryDirectory(prefix='book-borrow-smoke-') as build:
            subprocess.run(['javac', '-encoding', 'UTF-8', '--release', '17',
                            '-d', build, str(source)], capture_output=True,
                           encoding='utf-8', errors='replace', timeout=60, check=True)
            report['checks'].append({'name': 'compile_release_17', 'status': 'PASS'})
            cases = [('menu_exit', '9\n', ['-----图书借阅系统-----', '谢谢使用！']),
                     ('initial_books', '2\n0\n9\n', ['数据结构', '数据库', '离散数学', '谢谢使用！'])]
            for name, user_input, expected in cases:
                result = subprocess.run(['java', '-Dfile.encoding=UTF-8',
                                         '-Dstdout.encoding=UTF-8', '-Dstderr.encoding=UTF-8',
                                         '-cp', build, 'experiment.bookBorrowSystem'],
                                        input=user_input.encode('utf-8'), capture_output=True,
                                        timeout=15, check=True)
                output_text = result.stdout.decode('utf-8')
                if not all(value in output_text for value in expected):
                    raise RuntimeError(f'{name}: expected output missing')
                report['checks'].append({'name': name, 'status': 'PASS'})
        report['status'] = 'PASS'
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        report['error'] = str(exc)
    output = root / 'reports/book_borrow_sample.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
