import threading,time,os
from pathlib import Path
from core import parse_document,Cancelled
from source_structure import cases,preflight
from correspondence import write,KINDS,VERSION,evidence
from diagnostics import DiagnosticRun,failure_info

class State:
    def __init__(self,model,runtime,auto_run=True,diagnostics_dir=None):
        self.model=Path(model);self.runtime=Path(runtime);self.auto_run=auto_run
        self.lock=threading.RLock();self.cancel=threading.Event();self.worker=None;self.engine=None;self.last_seen=time.monotonic();self.revision=0
        self.diagnostics_dir=Path(diagnostics_dir) if diagnostics_dir else Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.cache')))/'ClinicCorrespondence-v17-r19'/'diagnostics'
        self.source_bytes=b'';self.source_name='';self.doc=None;self.cases=[];self.selected=None;self.kind='update';self.cache={};self.reset()
    def reset(self):
        self.status='empty' if self.doc is None else 'imported';self.message='Import an original clinical record.';self.result=None;self.audit=None;self.live={'stage':'empty','generated_characters':0};self.started=None;self.elapsed=0;self.revision+=1;self.trace=None;self.failure=None;self.logging_error=None
    def new_trace(self):
        self.trace=DiagnosticRun(self.diagnostics_dir,VERSION,self.source_name,self.source_bytes,self.model,self.runtime)
        self.trace.manifest['kind']=self.kind
        if self.selected:self.trace.manifest.update(patient_alias=self.selected.alias,case_key=self.selected.key,kind=self.kind)
        if self.doc:self.trace.json('source/extracted_document.json',self.doc)
        if self.selected:self.trace.json('source/selected_case.json',self.selected)
        self.trace.json('selection.json',{'kind':self.kind,'case_key':self.selected.key if self.selected else None})
        if self.trace.errors:raise OSError('Diagnostic logging failed: '+'; '.join(self.trace.errors))
        return self.trace
    def failed(self,exc):
        stage=self.live.get('stage','unknown')
        self.failure=failure_info(exc,stage,self.live.get('attempt',0));self.audit=getattr(exc,'audit',{})
        if self.trace:self.trace.finish('failed',exc,self.audit)
        self.status='error';self.message=self.failure['message'];self.live['stage']='error'
        if not self.trace:self.logging_error='A diagnostic folder could not be created: '+self.failure['message']
    def debug_output(self):
        if self.status not in ('error','cancelled') or not self.audit:return None
        candidate=self.audit.get('candidate_output');raw=self.audit.get('raw_response','')
        if not candidate and not raw:return None
        return {'accepted':False,'mode':'candidate_letter' if candidate else 'raw_model_output','subject':candidate.get('subject','') if candidate else '',
                'body':candidate['body'] if candidate else raw,'raw_response':raw,'attempt':self.live.get('attempt',1),'reason':(self.failure or {}).get('message',self.message)}
    def debug_export(self):
        with self.lock:
            self.idle();output=self.debug_output()
            if not output:raise ValueError('No rejected model output is available for troubleshooting.')
            return 'NOT ACCEPTED - TROUBLESHOOTING ONLY\nReason: '+output['reason']+'\n\nSubject: '+output['subject']+'\n\n'+output['body']+'\n'
    def idle(self):
        if self.worker and self.worker.is_alive():raise ValueError('Stop and wait for the local analysis before changing records.')
    def load(self,name,data):
        with self.lock:
            self.idle();self.doc=None;self.cases=[];self.selected=None;self.cache={};self.reset();self.source_name=name;self.source_bytes=data;self.live['stage']='importing'
            try:
                self.new_trace();self.doc=parse_document(name,data);self.trace.json('source/extracted_document.json',self.doc)
                self.cases=cases(self.doc);self.trace.json('source/parsed_cases.json',self.cases);self.selected=self.cases[0]
                self.trace.json('source/selected_case.json',self.selected);self.live['stage']='preflight';self.trace.progress('preflight');preflight(self.selected)
                self.status='imported';self.message='Source extracted. Local model analysis has not completed.'
                self.trace.manifest['status']='imported';self.trace.persist()
            except Exception as e:self.failed(e);return
            if self.auto_run:self.launch()
    def select_case(self,key):
        with self.lock:
            self.idle();selected=next((c for c in self.cases if c.key==str(key)),None)
            if selected is None:raise ValueError('Unknown patient selection.')
            self.selected=selected;self.reset();self.restore_or_launch()
    def select_kind(self,kind):
        with self.lock:
            self.idle()
            if kind not in KINDS:raise ValueError('Unknown letter type.')
            self.kind=kind;self.reset();self.restore_or_launch()
    def restore_or_launch(self):
        key=(self.selected.key,self.kind) if self.selected else None
        if key in self.cache:
            self.result,self.audit=self.cache[key];self.status='done';self.message='Previously generated draft from this selected source. Review before use.';self.live['stage']='finished'
            self.elapsed=self.audit.get('seconds',0);self.live['generated_characters']=len(self.audit.get('raw_response',''))
            self.live['attempt']=2 if self.audit.get('prior_rejected_attempts') else 1
            if self.doc is not None:
                try:
                    self.new_trace()
                    self.trace.finish('cached',audit={'model_called':False,'cache_reused':True,'original_diagnostic_run_id':self.audit.get('diagnostic_run_id'),'original_model_audit':self.audit},result=self.result)
                except Exception as exc:self.logging_error='Cached-view diagnostic save failed: '+str(exc)
        elif self.auto_run and self.selected:self.launch()
    def launch(self):
        with self.lock:
            self.idle()
            if self.selected is None:raise ValueError('Import a record with a recognised patient first.')
            self.live={'stage':'preflight','generated_characters':0}
            try:
                if not self.trace or self.trace.manifest['status']!='imported':self.new_trace()
                self.trace.json('source/selected_case.json',self.selected);self.trace.json('selection.json',{'kind':self.kind,'case_key':self.selected.key})
                self.trace.manifest.update(patient_alias=self.selected.alias,case_key=self.selected.key,kind=self.kind)
                self.trace.progress('preflight');preflight(self.selected)
            except Exception as e:self.result=None;self.failed(e);return
            self.result=None;self.audit=None;self.failure=None;self.cancel.clear();self.status='running';self.message='Local 4B is writing the selected letter. No draft is published before checks.';self.started=time.monotonic();self.live={'stage':'verifying','generated_characters':0};self.revision+=1
            self.trace.manifest['status']='running';self.trace.persist()
            self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start()
    def run(self):
        case=self.selected;kind=self.kind;sha=self.doc['sha256'];started=time.monotonic()
        def engine(e):
            with self.lock:self.engine=e
        def progress(stage,**values):
            with self.lock:
                self.live.update(stage=stage,**values)
                if self.trace:self.trace.progress(stage,**values)
        try:
            result,audit=write(case,kind,self.model,self.runtime,self.cancel,engine,progress,diagnostic=self.trace)
            with self.lock:
                if self.cancel.is_set():raise Cancelled()
                audit['diagnostic_run_id']=self.trace.id
                result.update(source_sha=sha,case_key=case.key,version=VERSION);self.result=result;self.audit=audit;self.cache[(case.key,kind)]=(result,audit);self.status='done';self.message='Local model and program checks completed. Review the source and draft.';self.live['stage']='finished'
                self.trace.finish('passed',audit=audit,result=result)
        except Cancelled as e:
            with self.lock:
                self.status='cancelled';self.message='Local analysis stopped. No unfinished letter published.';self.live['stage']='cancelled';self.audit=getattr(e,'audit',{})
                self.trace.finish('cancelled',e,self.audit)
        except Exception as e:
            with self.lock:self.failed(e)
        finally:
            with self.lock:self.elapsed=time.monotonic()-started;self.started=None;self.revision+=1
    def stop(self):
        self.cancel.set()
        with self.lock:engine=self.engine
        if engine:engine.stop()
    def clear(self):
        with self.lock:self.idle();self.doc=None;self.cases=[];self.selected=None;self.cache={};self.source_bytes=b'';self.source_name='';self.kind='update';self.reset()
    def diagnostic_archive(self):
        with self.lock:
            self.idle()
            if not self.trace:raise ValueError('No diagnostic record is available for the current analysis.')
            return self.trace.archive()
    def export(self,payload):
        with self.lock:
            if self.status!='done' or self.result is None:raise ValueError('No completed letter is available.')
            if payload.get('source_sha')!=self.doc['sha256'] or str(payload.get('case_key'))!=self.selected.key or payload.get('kind')!=self.kind:raise ValueError('Source or patient changed. Review the selected draft again.')
            if payload.get('reviewed') is not True:raise ValueError('Review and confirm the draft first.')
            subject=payload.get('subject');body=payload.get('body')
            if not isinstance(subject,str) or not subject.strip() or len(subject)>300 or '\r' in subject or '\n' in subject or not isinstance(body,str) or not body.strip() or len(body)>12000:raise ValueError('Invalid draft content.')
            document={'version':VERSION,'source_sha':self.doc['sha256'],'case_key':self.selected.key,'kind':self.kind,'subject':subject.strip(),'body':body.strip(),'method':self.result['method'],'edited_by_user':subject!=self.result['subject'] or body!=self.result['body'],'reviewed':True,'sent':False}
            if self.trace:
                revision=str(time.time_ns())
                self.trace.json('reviewed_drafts/'+revision+'.json',document)
                self.trace.text('reviewed_drafts/'+revision+'.txt','Subject: '+document['subject']+'\n\n'+document['body']+'\n')
                self.trace.event('draft_reviewed',revision=revision,edited_by_user=document['edited_by_user'],sent=False)
                self.trace.save_archive()
            return document
    def snapshot(self):
        with self.lock:
            self.last_seen=time.monotonic()
            return {'version':VERSION,'revision':self.revision,'status':self.status,'message':self.message,'failure':self.failure,'debug_output':self.debug_output(),'diagnostic':self.trace.snapshot() if self.trace else None,'logging_error':self.logging_error,'document':{k:self.doc[k] for k in ('filename','sha256','pages')} if self.doc else None,'cases':[{'key':c.key,'alias':c.alias,'encounters':len(c.encounters)} for c in self.cases],'selected_case':self.selected.key if self.selected else None,'kind':self.kind,'result':self.result,'progress':{**self.live,'seconds':round(time.monotonic()-self.started if self.started else self.elapsed,1)},'model_ready':self.model.is_file() and self.runtime.is_file(),'audit':{k:self.audit[k] for k in ('version','model_called','accepted','seconds','peak_rss_mib','input_tokens') if k in self.audit} if self.audit else None}
