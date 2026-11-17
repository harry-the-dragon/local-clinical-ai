"""Full, local-only troubleshooting records. Clinical input/output is not redacted."""
import dataclasses
import datetime
import hashlib
import io
import json
import os
import platform
import re
import sys
import threading
import time
import traceback
import uuid
import zipfile
from pathlib import Path

import psutil


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def serial(value):
    if dataclasses.is_dataclass(value):return dataclasses.asdict(value)
    if isinstance(value,Path):return str(value)
    if isinstance(value,(datetime.date,datetime.datetime)):return value.isoformat()
    raise TypeError(type(value).__name__)


def failure_info(exc,stage='unknown',attempt=0):
    message=str(exc) or type(exc).__name__
    low=message.lower();code='unexpected_error'
    if 'memory' in low or 'bad_alloc' in low:code='memory_or_runtime_failure'
    elif 'missing' in low and ('model' in low or 'runtime' in low):code='missing_model_or_runtime'
    elif 'checksum' in low:code='model_checksum_mismatch'
    elif 'token' in low and ('4096' in low or 'truncat' in low):code='input_context_limit'
    elif 'timed out' in low or 'timeout' in low:code='timeout'
    elif 'repeated' in low or 'recurs excessively' in low:code='repeated_model_text'
    elif 'abbreviation' in low:code='unexpanded_abbreviation'
    elif 'unfinished model output' in low:code='incomplete_model_output'
    elif isinstance(exc,json.JSONDecodeError):code='invalid_model_json' if stage!='importing' else 'invalid_document'
    elif stage=='importing':code='document_import_failed'
    elif stage=='preflight':code='source_preflight_failed'
    elif stage=='checking' or isinstance(exc,ValueError) and ('source' in low or 'documented' in low or 'numerical' in low or 'letter' in low):code='draft_validation_failed'
    elif stage=='loading':code='model_start_failed'
    elif isinstance(exc,OSError):code='local_io_or_connection_failed'
    info={'code':code,'stage':stage,'attempt':attempt,'exception_type':type(exc).__name__,'message':message}
    if hasattr(exc,'validation_details'):info['validation_details']=exc.validation_details
    return info

def archive_directory(directory):
    directory=Path(directory);buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
        for file in sorted(directory.rglob('*')):
            if file.is_file() and file.suffix!='.tmp':archive.write(file,arcname=directory.name+'/'+file.relative_to(directory).as_posix())
    return buffer.getvalue()


class DiagnosticRun:
    def __init__(self,root,version,filename,data,model,runtime):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.id=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:12]
        self.directory=self.root/self.id;self.directory.mkdir()
        self.lock=threading.RLock();self.start=time.monotonic();self.finished=None;self.attempt=0;self.stage='importing';self.errors=[];self.last_checkpoint=0
        self.archive_path=self.root/('Clinic_Diagnostic_'+self.id+'.zip')
        self.indexed=False
        self.manifest={'schema':1,'run_id':self.id,'version':version,'created_utc':now(),'status':'running','stage':self.stage,'attempt':0,'failure':None,'attempts':[],
                       'original_filename':filename,'input_bytes':len(data),'input_sha256':hashlib.sha256(data).hexdigest(),'clinical_content_redacted':False,'automatically_uploaded':False}
        suffix=Path(filename).suffix.lower()
        if not re.fullmatch(r'\.[a-z0-9]{1,8}',suffix):suffix='.bin'
        self.binary('source/original'+suffix,data)
        self.json('environment.json',{'version':version,'platform':platform.platform(),'python':sys.version,'machine':platform.machine(),'processor':platform.processor(),
                  'cpu_count':psutil.cpu_count(),'physical_cpu_count':psutil.cpu_count(logical=False),'memory':psutil.virtual_memory()._asdict(),
                  'model':{'path':str(model),'exists':Path(model).is_file(),'bytes':Path(model).stat().st_size if Path(model).is_file() else None},
                  'runtime':{'path':str(runtime),'exists':Path(runtime).is_file()},'transport_credentials_recorded':False})
        self.event('run_created',filename=filename,input_sha256=self.manifest['input_sha256'])
        self.persist()

    def _store(self,name,data,append=False):
        with self.lock:
            try:
                path=self.directory/name;path.parent.mkdir(parents=True,exist_ok=True)
                if append:
                    with path.open('ab') as f:f.write(data)
                else:
                    temporary=path.with_name(path.name+'.tmp');temporary.write_bytes(data);temporary.replace(path)
                return True
            except Exception as exc:
                message=f'{name}: {type(exc).__name__}: {exc}'
                if message not in self.errors:self.errors.append(message)
                return False

    def binary(self,name,data):return self._store(name,data)
    def text(self,name,text):return self.binary(name,text.encode('utf-8'))
    def json(self,name,value):return self.text(name,json.dumps(value,ensure_ascii=False,indent=2,default=serial)+'\n')
    def event(self,event,**values):
        return self._store('events.jsonl',(json.dumps({'time_utc':now(),'elapsed_seconds':round(time.monotonic()-self.start,3),'event':event,**values},ensure_ascii=False,default=serial)+'\n').encode('utf-8'),True)
    def persist(self):
        end=self.finished if self.finished is not None else time.monotonic()
        self.manifest.update(updated_utc=now(),elapsed_seconds=round(end-self.start,3),
            attempt_processing_seconds=round(sum(a.get('seconds') or 0 for a in self.manifest['attempts']),3),logging_errors=list(self.errors))
        self.json('report.json',self.manifest)
    def progress(self,stage,**values):
        with self.lock:
            changed=stage!=self.stage;self.stage=stage
            self.manifest.update(stage=stage,**values)
            if changed:self.event('stage_changed',stage=stage,**values)
            if changed or time.monotonic()-self.last_checkpoint>=1:
                self.last_checkpoint=time.monotonic();self.persist()
    def begin_attempt(self,number):
        self.attempt=number;self.stage='verifying';self.manifest.update(stage=self.stage,attempt=number,status='running')
        self.event('attempt_started',attempt=number);self.persist()
    def attempt_file(self,name):return f'attempt_{self.attempt}/{name}'
    def prompt(self,prompt,context):
        self.text(self.attempt_file('system_prompt.txt'),prompt)
        self.text(self.attempt_file('model_input.json'),context)
    def model_request(self,payload,tokens):
        self.json(self.attempt_file('request.json'),payload)
        self.event('model_request',attempt=self.attempt,input_tokens=tokens,max_tokens=payload['max_tokens'])
    def stream_line(self,line):self._store(self.attempt_file('stream.sse'),line,True)
    def output(self,text,finish_reason=None):
        self.text(self.attempt_file('response.txt'),text)
        self.manifest.update(generated_characters=len(text),finish_reason=finish_reason)
    def context(self,name,value):self.json(self.attempt_file(name),value)
    def finish_attempt(self,audit,error=None):
        with self.lock:
            self.json(self.attempt_file('audit.json'),audit)
            if 'raw_response' in audit:self.output(audit['raw_response'],audit.get('finish_reason'))
            if audit.get('candidate_output'):
                candidate=audit['candidate_output'];self.json(self.attempt_file('candidate_output.json'),candidate)
                self.text(self.attempt_file('candidate_output.txt'),'Subject: '+candidate['subject']+'\n\n'+candidate['body']+'\n')
            item={'attempt':self.attempt,'accepted':bool(audit.get('accepted')),'seconds':audit.get('seconds'),'generated_characters':len(audit.get('raw_response','')),'finish_reason':audit.get('finish_reason')}
            if error:
                item['failure']=failure_info(error,self.stage,self.attempt)
                self.text(self.attempt_file('exception.txt'),''.join(traceback.format_exception(error)))
            self.manifest['attempts'].append(item);self.event('attempt_finished',**item);self.persist()
    def finish(self,status,error=None,audit=None,result=None):
        with self.lock:
            self.finished=time.monotonic();self.manifest['finished_utc']=now()
            self.manifest['status']=status
            if error:
                self.manifest['failure']=failure_info(error,self.stage,self.attempt)
                self.text('exception.txt',''.join(traceback.format_exception(error)))
            if audit is not None:self.json('final_audit.json',audit)
            if result is not None:self.json('accepted_result.json',result)
            candidate=result or (audit or {}).get('candidate_output')
            failure=self.manifest.get('failure');context='Stage: '+self.stage+'\nAttempt: '+str(self.attempt)+'\n'+('Reason: '+failure['message']+'\n' if failure else '')
            if candidate:
                self.json('final_output.json',{'status':status,'accepted':status in ('passed','cached'),'attempt':self.attempt,'failure':failure,'candidate':candidate})
                label='CHECKS PASSED - REVIEW REQUIRED' if status=='passed' else 'CACHED PREVIOUSLY CHECKED DRAFT - REVIEW REQUIRED' if status=='cached' else 'NOT ACCEPTED - TROUBLESHOOTING OUTPUT'
                self.text('final_output.txt',label+'\n'+context+'\nSubject: '+candidate['subject']+'\n\n'+candidate['body']+'\n')
            elif (audit or {}).get('raw_response'):
                self.text('final_output.txt','NO ACCEPTED LETTER - RAW MODEL OUTPUT\n'+context+'\n'+audit['raw_response'])
            else:self.text('final_output.txt','No model output was generated.\nReason: '+str(error or status)+'\n')
            self.event('run_finished',status=status,failure=self.manifest['failure']);self.persist()
            self.text('READ_ME.txt','LOCAL TROUBLESHOOTING RECORD - FULL ORIGINAL CONTENT\n'
                'This folder contains the unmodified source file, extracted text, selected patient/notes, exact model prompts and requests, raw streamed outputs, each rejected attempt, runtime logs, exception tracebacks and environment details when available.\n'
                'Clinical content has NOT been redacted. Nothing is automatically uploaded. A rejected response is diagnostic evidence, not an approved letter.\n'
                f'Run: {self.id}\nBuild: {self.manifest["version"]}\nStatus: {status}\n'
                f'Reason: {(self.manifest.get("failure") or {}).get("message","See report.json and attempt folders.")}\n'
                'If a process or the computer stops abruptly, the record may end at the last checkpoint; that alone does not prove an out-of-memory error.\n')
            self.write_index()
            self.save_archive()
    def write_index(self):
        if self.indexed:return
        try:
            row={k:self.manifest.get(k) for k in ('run_id','created_utc','finished_utc','version','patient_alias','case_key','kind','original_filename','status','failure')}
            row['archive_filename']=self.archive_path.name
            with (self.root/'RUN_INDEX.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False,default=serial)+'\n')
            self.indexed=True
        except Exception as exc:
            self.errors.append('Run index: '+type(exc).__name__+': '+str(exc));self.persist()
    def snapshot(self):
        with self.lock:
            return {'run_id':self.id,'directory':str(self.directory.resolve()),'status':self.manifest['status'],'failure':self.manifest.get('failure'),
                    'archive_path':str(self.archive_path.resolve()) if self.archive_path.exists() else None,
                    'attempts':list(self.manifest['attempts']),'logging_errors':list(self.errors),'full_original_content':True,'automatically_saved':not self.errors}
    def save_archive(self):
        """Every finished analysis gets a ZIP without a download or extra click."""
        with self.lock:
            try:
                self.manifest['automatic_archive_filename']=self.archive_path.name
                data,_=self.archive();temporary=self.archive_path.with_suffix('.zip.tmp')
                temporary.write_bytes(data);temporary.replace(self.archive_path)
            except Exception as exc:
                message='Automatic diagnostic ZIP: '+type(exc).__name__+': '+str(exc)
                if message not in self.errors:self.errors.append(message)
                self.persist()
    def archive(self):
        with self.lock:
            self.persist();return archive_directory(self.directory),f'Clinic_Diagnostic_{self.id}.zip'


def recover_interrupted(root):
    """Called after owning the application lock; an abrupt stop has unknown cause."""
    root=Path(root)
    if not root.exists():return
    for path in root.glob('*/report.json'):
        try:
            record=json.loads(path.read_text(encoding='utf-8'))
            if record.get('status')!='running':continue
            record.update(status='interrupted',recovered_utc=now(),failure={'code':'previous_process_interrupted','stage':record.get('stage'),'attempt':record.get('attempt'),
                'message':'The previous application ended without a final result. Exact cause unknown; inspect the last checkpoint and runtime logs.'})
            record['automatic_archive_filename']='Clinic_Diagnostic_'+path.parent.name+'.zip'
            temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)
            output=path.parent/'final_output.txt'
            if not output.exists():
                attempts=sorted((p for p in path.parent.glob('attempt_*') if p.is_dir() and p.name.split('_')[-1].isdigit()),key=lambda p:int(p.name.split('_')[-1]))
                last=attempts[-1] if attempts else None
                candidate=last/'candidate_output.txt' if last else None
                raw=last/'response.txt' if last else None
                evidence=candidate if candidate and candidate.is_file() else raw if raw and raw.is_file() else None
                output.write_bytes(b'INTERRUPTED - NOT ACCEPTED - LAST SAVED OUTPUT\n'+(evidence.read_bytes() if evidence else b'No model output was available at the last checkpoint.\n'))
            target=root/('Clinic_Diagnostic_'+path.parent.name+'.zip');temporary=target.with_suffix('.zip.tmp')
            row={k:record.get(k) for k in ('run_id','created_utc','recovered_utc','version','patient_alias','case_key','kind','original_filename','status','failure')};row['archive_filename']=target.name
            with (root/'RUN_INDEX.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False,default=serial)+'\n')
            temporary.write_bytes(archive_directory(path.parent));temporary.replace(target)
        except (OSError,ValueError):pass
