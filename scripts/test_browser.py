"""Launch a fresh SQLite demo and exercise the real portal with headless Chromium."""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--prepare',action='store_true',help='Install locked frontend packages, build and install Chromium')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--playwright-module',type=Path,help='Optional installed Playwright package for a local rehearsal')
    args=parser.parse_args()
    repo=args.repository.resolve();backend=repo/'backend';frontend=repo/'frontend'
    npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
    node=shutil.which('node')
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    if not node:raise SystemExit('Node.js must be installed.')
    if args.prepare:
        if not npm:raise SystemExit('npm must be installed.')
        for command in ([npm,'ci'],[npm,'run','build'],[npm,'exec','--','playwright','install','chromium']):
            subprocess.run(command,cwd=frontend,check=True,creationflags=flags)
    module=(args.playwright_module or frontend/'node_modules'/'playwright').resolve()
    if not (frontend/'dist'/'index.html').is_file():
        raise SystemExit('Build the frontend first, or use --prepare.')
    if not (module/'package.json').is_file():
        raise SystemExit('Install frontend dependencies first, or use --prepare.')
    smoke=Path(__file__).resolve().parents[1]/'frontend'/'tests'/'ci-smoke.cjs'
    if not smoke.is_file():raise SystemExit('Browser acceptance script is missing.')
    output=(args.output or repo/'test-results'/'browser').resolve()
    output.mkdir(parents=True,exist_ok=True)
    report=output/'ui-test-result.json'
    if report.exists():report.unlink()

    with tempfile.TemporaryDirectory(prefix='supplypilot-browser-',ignore_cleanup_errors=True) as temp:
        data=Path(temp)
        env=dict(os.environ,DATABASE_URL='sqlite:///'+(data/'demo.db').as_posix(),
                 DATA_DIR=str(data),APP_MODE='local',AUTH_MODE='local',
                 DEMO_PASSWORD=secrets.token_hex(24),TOKEN_SECRET=secrets.token_hex(32))
        for command in ('migrate','seed'):
            subprocess.run([sys.executable,'-m','supplypilot.manage',command],cwd=backend,
                           env=env,check=True,creationflags=flags)
        server=subprocess.Popen([sys.executable,'-m','uvicorn','supplypilot.main:app',
            '--host','127.0.0.1','--port','0','--no-use-colors'],cwd=backend,env=env,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,creationflags=flags)
        logs=[];messages=queue.Queue()
        def collect():
            for line in server.stdout:
                logs.append(line);messages.put(line)
        reader=threading.Thread(target=collect,daemon=True);reader.start()
        try:
            base=None;deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                if server.poll() is not None:break
                try:line=messages.get(timeout=0.25)
                except queue.Empty:continue
                match=re.search(r'Uvicorn running on (http://127\.0\.0\.1:\d+)',line)
                if match:base=match.group(1);break
            if not base:
                raise RuntimeError('Temporary browser server failed to start:\n'+''.join(logs[-15:]))
            print('Started the isolated browser-test portal.',flush=True)
            child_env=dict(env,BASE_URL=base,UI_TEST_PASSWORD=env['DEMO_PASSWORD'],
                           UI_TEST_OUTPUT=str(output),PLAYWRIGHT_MODULE=str(module))
            browser_run=subprocess.run([node,str(smoke)],cwd=frontend,env=child_env,
                           timeout=300,creationflags=flags,capture_output=True,text=True)
            print(browser_run.stdout,flush=True)
            if browser_run.returncode:
                print(browser_run.stderr,flush=True)
                raise RuntimeError('Browser acceptance failed; see the browser output above.')
            result=json.loads(report.read_text())
            if result.get('passed') is not True:raise RuntimeError('Browser result did not pass.')
            print('Browser checks passed:',result['checks_passed'])
            print('Report:',report)
        finally:
            server.terminate()
            try:server.wait(timeout=10)
            except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
            reader.join(timeout=2)
            server.stdout.close()
            print('Stopped the temporary browser-test server.')
    print('Removed temporary browser-test data. Development data was not used.')


if __name__=='__main__':
    main()
