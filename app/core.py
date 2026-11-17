# Source-preserving utilities extracted from USB v16.6; no letter/form generator.

import base64, hashlib, io, json, re, secrets, socket, subprocess, threading, time, urllib.request

from pathlib import Path

import psutil

from pypdf import PdfReader

MODEL_SHA = '85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9'

class Cancelled(Exception): pass

def parse_document(name, data):
    if len(data)>25*1024*1024: raise ValueError('File exceeds 25 MB. Export a smaller single-patient record.')
    suffix=Path(name).suffix.lower()
    if suffix=='.pdf':
        reader=PdfReader(io.BytesIO(data))
        if reader.is_encrypted: raise ValueError('Export an unencrypted PDF locally first.')
        if not 1<=len(reader.pages)<=80: raise ValueError('PDF must contain 1–80 pages.')
        pages=[p.extract_text() or '' for p in reader.pages]
        empty=[i+1 for i,t in enumerate(pages) if len(t.strip())<10]
        if empty: raise ValueError('Insufficient extractable text on these pages. Scanned PDFs and OCR are not supported: '+', '.join(map(str,empty)))
    elif suffix=='.docx':
        import zipfile
        from xml.etree import ElementTree as ET
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            info=z.getinfo('word/document.xml')
            if info.file_size>5*1024*1024:raise ValueError('Word document text is too large.')
            root=ET.fromstring(z.read(info))
        ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        paragraphs=[]
        for p in root.iter(ns+'p'):
            parts=[]
            for el in p.iter():
                if el.tag==ns+'t':parts.append(el.text or '')
                elif el.tag in (ns+'br',ns+'cr'):parts.append('\n')
                elif el.tag==ns+'tab':parts.append('\t')
            paragraphs.append(''.join(parts))
        pages=['\n'.join(paragraphs)]
    elif suffix in ['.txt','.md']:
        pages=[data.decode('utf-8-sig')]
    else: raise ValueError('Use a text-based PDF, Word DOCX, UTF-8 TXT or Markdown file.')
    if sum(map(len,pages))>120000: raise ValueError('Text exceeds 120,000 characters. Export one encounter or fewer pages.')
    has_notes=suffix=='.md' and any(x.strip().lower()=='## notes' for x in pages[0].splitlines())
    profile_without_notes=suffix=='.md' and not has_notes and bool(re.match(r'^#\s+PT-\d+\b',pages[0]))
    primary=not has_notes and not profile_without_notes; lines=[]
    for page,text in enumerate(pages,1):
        for local,line in enumerate(text.replace('\x00','').splitlines(),1):
            if has_notes and line.strip().lower()=='## notes': primary=True
            lines.append({'id':len(lines)+1,'page':page,'page_line':local,'text':line,'primary':primary})
    if not any(x['text'].strip() for x in lines): raise ValueError('No usable text was extracted.')
    return {'filename':Path(name.replace('\\','/')).name,'sha256':hashlib.sha256(data).hexdigest(),'pages':len(pages),'lines':lines,'source_policy':'PDF/TXT provenance is user-confirmed original export; Markdown content before ## Notes is secondary. Does not certify source facts.'}

class Runtime:
    def __init__(self, model, runtime, cancel):
        self.model=Path(model);self.runtime=Path(runtime);self.cancel=cancel;self.proc=None
        self.key=secrets.token_hex(24);self.peak=0;self.diagnostic=None;self.log_handles=[]
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def check(self):
        if self.cancel.is_set(): raise Cancelled()
        if self.proc is not None:
            try:self.peak=max(self.peak,psutil.Process(self.proc.pid).memory_info().rss/2**20)
            except psutil.Error:pass
    def call(self,path,body=None,timeout=10):
        self.check()
        request=urllib.request.Request(f'http://127.0.0.1:{self.port}'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'})
        try:
            with self.opener.open(request,timeout=timeout) as response:result=json.load(response)
        except urllib.error.HTTPError as exc:
            data=exc.read()
            if self.diagnostic:self.diagnostic.binary(self.diagnostic.attempt_file('http_error_body.bin'),data)
            raise ValueError(f'Local model HTTP {exc.code} at {path}: '+data.decode('utf-8',errors='replace')) from exc
        self.check();return result
    def start(self):
        if not self.model.is_file() or not self.runtime.is_file(): raise ValueError('Local model or runtime is missing. Check that the complete portable folder was copied.')
        with socket.socket() as s:s.bind(('127.0.0.1',0));self.port=s.getsockname()[1]
        output=errors=subprocess.DEVNULL
        if self.diagnostic:
            directory=self.diagnostic.directory/f'attempt_{self.diagnostic.attempt}';directory.mkdir(parents=True,exist_ok=True)
            output=(directory/'runtime_stdout.log').open('ab');self.log_handles.append(output)
            errors=(directory/'runtime_stderr.log').open('ab');self.log_handles.append(errors)
            self.diagnostic.context('runtime_parameters.json',{'threads':4,'batch_threads':4,'context':4096,'gpu_layers':0,'parallel':1,'batch':128,'micro_batch':64,'reasoning':'off','cache_ram':0,'host':'127.0.0.1'})
        self.proc=subprocess.Popen([str(self.runtime),'-m',str(self.model),'-t','4','-tb','4','-c','4096','-ngl','0','-np','1','--host','127.0.0.1','--port',str(self.port),'--api-key',self.key,'--reasoning','off','--no-warmup','--no-repack','--cache-ram','0','-b','128','-ub','64'],stdout=output,stderr=errors,creationflags=subprocess.CREATE_NO_WINDOW if __import__('os').name=='nt' else 0)
        if self.diagnostic:self.diagnostic.event('runtime_started',attempt=self.diagnostic.attempt,pid=self.proc.pid)
        for _ in range(180):
            self.check()
            if self.proc.poll() is not None: raise ValueError(f'Local model failed to start (exit code {self.proc.returncode}). Inspect runtime_stderr.log for the actual reason.')
            try:
                if self.call('/health',timeout=2).get('status')=='ok':return
            except (OSError,ValueError):pass
            self.cancel.wait(1)
        raise ValueError('Model loading timed out.')
    def stop(self):
        try:
            if self.proc is not None and self.proc.poll() is None:
                self.proc.terminate()
                try:self.proc.wait(10)
                except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait(10)
        finally:
            if self.diagnostic and self.proc is not None:self.diagnostic.context('runtime_exit.json',{'pid':self.proc.pid,'exit_code':self.proc.poll(),'peak_rss_mib':self.peak})
            for handle in self.log_handles:handle.close()
            self.log_handles=[]
