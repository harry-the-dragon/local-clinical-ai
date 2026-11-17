import argparse,base64,json,os,secrets,signal,subprocess,sys,threading,time,webbrowser
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parent))
from state import State
from diagnostics import recover_interrupted

ROOT=Path(__file__).resolve().parent
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass  # Never log patient requests or text.
    def respond(self,status,data,kind='application/json; charset=utf-8',filename=None):
        if not isinstance(data,bytes):data=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if filename:self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
        self.end_headers();self.wfile.write(data)
    def authorized(self):
        expected=f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host')!=expected:return False
        origin=self.headers.get('Origin')
        if origin and origin!='http://'+expected:return False
        return secrets.compare_digest(self.headers.get('X-Session-Key',''),self.server.token)
    def do_GET(self):
        path=urlsplit(self.path).path
        assets={'/':'index.html','/ui.js':'ui.js','/style.css':'style.css'}
        if path in assets:
            kinds={'/':'text/html; charset=utf-8','/ui.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8'}
            self.respond(200,(ROOT/assets[path]).read_bytes(),kinds[path]);return
        if not self.authorized():self.respond(403,{'error':'Local session authentication failed. Reopen the program.'});return
        if path=='/api/state':self.respond(200,self.server.state.snapshot())
        else:self.respond(404,{'error':'Unknown operation.'})
    def do_POST(self):
        if not self.authorized():self.respond(403,{'error':'Local session authentication failed.'});return
        if self.headers.get('Content-Type')!='application/json':self.respond(415,{'error':'Invalid request format.'});return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=35*1024*1024:self.respond(413,{'error':'File or request is too large.'});return
            body=json.loads(self.rfile.read(length));state=self.server.state;path=urlsplit(self.path).path
            if path=='/api/import':state.load(body['name'],base64.b64decode(body['data'],validate=True))
            elif path=='/api/demo':state.load('fictional-case.txt',(ROOT/'assets/demo.txt').read_bytes())
            elif path=='/api/select-case':state.select_case(body.get('case_key'))
            elif path=='/api/start':state.launch()
            elif path=='/api/kind':state.select_kind(body.get('kind'))
            elif path=='/api/cancel':state.stop()
            elif path=='/api/clear':
                state.clear()
            elif path=='/api/analysis-record':
                self.respond(200,json.dumps(state.snapshot(),ensure_ascii=False,indent=2).encode(),'application/json; charset=utf-8','local_analysis_record.json');return
            elif path=='/api/diagnostic-download':
                data,name=state.diagnostic_archive();self.respond(200,data,'application/zip',name);return
            elif path=='/api/debug-output':
                self.respond(200,state.debug_export().encode('utf-8'),'text/plain; charset=utf-8','rejected_troubleshooting_output.txt');return
            elif path=='/api/review':
                state.export(body);self.respond(200,{'reviewed':True,'sent':False});return
            elif path=='/api/export':
                document=state.export(body)
                text='Subject: '+document['subject']+'\n\n'+document['body']+'\n'
                self.respond(200,text.encode('utf-8'),'text/plain; charset=utf-8',document['kind']+'_draft.txt');return
            elif path=='/api/quit':
                state.stop();self.respond(200,{'message':'Program closed.'});threading.Thread(target=self.server.shutdown,daemon=True).start();return
            else:self.respond(404,{'error':'Unknown operation.'});return
            self.respond(200,state.snapshot())
        except Exception as e:self.respond(400,{'error':f'{type(e).__name__}: {e}'})

def open_window(url):
    if os.name=='nt':
        paths=[Path(os.environ.get(k,''))/'Microsoft/Edge/Application/msedge.exe' for k in ['PROGRAMFILES(X86)','PROGRAMFILES','LOCALAPPDATA']]
        edge=next((p for p in paths if p.is_file()),None)
        if edge:
            subprocess.Popen([str(edge),'--app='+url,'--inprivate'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW);return
    webbrowser.open(url)

def instance_lock(directory):
    directory.mkdir(parents=True,exist_ok=True);f=(directory/'session.lock').open('a+b');f.seek(0,2)
    if f.tell()==0:f.write(b'0');f.flush()
    f.seek(0)
    try:
        if os.name=='nt':
            import msvcrt;msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl;fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:f.close();return None
    return f

def main():
    bundle=ROOT.parent
    p=argparse.ArgumentParser();p.add_argument('--model',type=Path,default=bundle/'models/qwen3-4b-instruct-2507-q4_k_m.gguf');p.add_argument('--runtime',type=Path,default=bundle/('runtime/llama-server.exe' if os.name=='nt' else 'runtime/llama-server'));p.add_argument('--no-browser',action='store_true');p.add_argument('--state-dir',type=Path,default=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.cache')))/'ClinicCorrespondence-v17-r19');args=p.parse_args()
    lock=instance_lock(args.state_dir);session=args.state_dir/'session.json'
    if lock is None:
        if session.exists() and not args.no_browser:open_window(json.loads(session.read_text())['url'])
        return
    recover_interrupted(args.state_dir/'diagnostics')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True;server.token=secrets.token_hex(24);server.state=State(args.model.resolve(),args.runtime.resolve(),diagnostics_dir=args.state_dir/'diagnostics')
    url=f'http://127.0.0.1:{server.server_port}/#'+server.token
    session.write_text(json.dumps({'url':url,'pid':os.getpid()}))
    if os.name!='nt':session.chmod(0o600)
    if args.no_browser:print('Local UI ready. Session details in '+str(session.resolve()),flush=True)
    else:open_window(url)
    def watchdog():
        while not closing.wait(5):
            if time.monotonic()-server.state.last_seen>120:server.state.stop();server.shutdown();return
    closing=threading.Event();threading.Thread(target=watchdog,daemon=True).start()
    def stop(s,f):server.state.stop();threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:server.serve_forever(poll_interval=.25)
    finally:
        closing.set();server.state.stop()
        if server.state.worker:server.state.worker.join(15)
        server.server_close();session.unlink(missing_ok=True);lock.close()

if __name__=='__main__':
    try:main()
    except Exception:
        import traceback
        error_dir=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.cache')))/'ClinicCorrespondence-v17-r19';error_dir.mkdir(parents=True,exist_ok=True)
        (error_dir/'startup_error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise





