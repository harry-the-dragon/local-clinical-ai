'use strict';
const $=id=>document.getElementById(id),key=location.hash.slice(1)||sessionStorage.getItem('local-session')||'';if(location.hash)sessionStorage.setItem('local-session',key);history.replaceState(null,'',location.pathname);
let current=null,shown=null,busy=false,polling=false;const edits=new Map();
async function request(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'X-Session-Key':key,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});if(!r.ok){let e=await r.json();throw Error(e.error||'Local operation failed.');}return r;}
function error(e){$('error').textContent=e.message;}
function enabled(){const done=current?.status==='done';for(const id of ['copy','save'])$(id).disabled=!done||!$('reviewed').checked;}
function render(s){current=s;$('build').textContent=`Running backend: ${s.version}`;const running=s.status==='running';$('status').textContent=s.message;$('filename').textContent=s.document?`${s.document.filename} · ${s.document.pages} pages`: 'No record imported';
 const selection=JSON.stringify(s.cases);if($('patient').dataset.cases!==selection){$('patient').replaceChildren(...s.cases.map(c=>new Option(`${c.alias} · ${c.encounters} consultations`,c.key)));$('patient').dataset.cases=selection;}
 $('patient').value=s.selected_case||'';$('kind').value=s.kind;for(const id of ['file','demo','kind','patient','clear'])$(id).disabled=running||busy||(id==='patient'&&!s.cases.length);$('generate').disabled=running||busy||!s.selected_case;$('stop').disabled=!running;
 const stage=s.progress.stage;const labels={importing:'Reading source file',preflight:'Checking source structure',verifying:'Verifying local model',loading:'Loading model into memory',reading:'Reading source evidence',generating:'Writing letter',revising:'Rewriting after a precision check',checking:'Checking draft',finished:'Draft ready',error:'Analysis failed',cancelled:'Stopped'};
 $('timing').textContent=`${labels[stage]||stage} · attempt ${s.progress.attempt||'not started'} · ${Math.floor(s.progress.seconds)} seconds · ${s.progress.generated_characters||0} generated characters`;
 if(running)$('progress').removeAttribute('value');else $('progress').value=s.status==='done'?100:0;
 const failure=s.failure||s.diagnostic?.failure;$('failure-panel').hidden=!failure&&!s.logging_error;
 $('failure-reason').textContent=failure?.message||s.logging_error||'';
 $('failure-details').textContent=failure?`Code: ${failure.code}\nFailed during: ${labels[failure.stage]||failure.stage}\nAttempt: ${failure.attempt||'No model attempt started'}\nException: ${failure.exception_type||'Unknown'}${failure.validation_details?'\nCheck details: '+JSON.stringify(failure.validation_details,null,2):''}`:'';
 $('diagnostic-panel').hidden=!s.diagnostic&&!s.logging_error;
 $('diagnostic-location').textContent=s.diagnostic?`Automatic record: ${s.diagnostic.run_id}\nFolder: ${s.diagnostic.directory}\nAutomatic ZIP: ${s.diagnostic.archive_path||(['passed','failed','cancelled','cached'].includes(s.diagnostic.status)?'Not saved — see logging errors':'Pending until analysis finishes')}\nReadable output: final_output.txt inside the folder / ZIP`:'';
 $('debug-output-panel').hidden=!s.debug_output;const debugText=s.debug_output?`Reason: ${s.debug_output.reason}\n\n${s.debug_output.subject?'Subject: '+s.debug_output.subject+'\n\n':''}${s.debug_output.body}`:'';if($('debug-output-body').value!==debugText)$('debug-output-body').value=debugText;
 $('view-debug-output').hidden=!s.debug_output;
 $('body').closest('section').hidden=!!s.debug_output;
 $('debug-output-note').textContent=s.debug_output?`Attempt ${s.debug_output.attempt}: ${s.debug_output.mode==='candidate_letter'?'Last complete candidate letter':'Raw output; a complete letter was not produced'}. Not accepted by checks. Full original content is saved automatically for troubleshooting.`:'';
 $('debug-output-save').disabled=!s.debug_output||running||busy;
 $('attempt-history').textContent=(s.diagnostic?.attempts||[]).map(a=>`Attempt ${a.attempt}: ${a.accepted?'checks passed':'not accepted'} · ${a.seconds??'?'} seconds · ${a.generated_characters} characters${a.finish_reason?' · finish: '+a.finish_reason:''}${a.failure?'\n'+a.failure.code+': '+a.failure.message:''}`).join('\n\n');
 $('logging-error').textContent=[s.logging_error,...(s.diagnostic?.logging_errors||[])].filter(Boolean).join('\n');
 $('diagnostic-save').disabled=running||busy||!s.diagnostic;
 if(failure)$('diagnostic-panel').open=true;
 const identity=s.result?`${s.document.sha256}:${s.selected_case}:${s.kind}:${s.result.body}`:null;
 if(identity!==shown){shown=identity;const saved=edits.get(identity);$('subject').value=saved?.subject||s.result?.subject||'';$('body').value=saved?.body||s.result?.body||'';$('reviewed').checked=false;}
 for(const id of ['subject','body','reviewed'])$(id).disabled=!s.result||running;
 $('warnings').replaceChildren(...(s.result?.warnings||[]).map(w=>{let p=document.createElement('p');p.textContent=w;return p;}));
 $('words').textContent=s.result?`${s.result.word_count} words in generated paragraphs; edits remain yours.`:'';
 $('evidence').textContent=s.result?`Current note: ${s.result.latest_date||'Date not supplied'} · Comparison note: ${s.result.comparison_policy==='withheld_pending_anatomical_alignment'?'Not used pending anatomical alignment':s.result.comparison_date||'No dated comparison'}\nDelivered treatment categories: ${s.result.categories.map(c=>c.category).join('; ')||'No recognised category; check original record.'}\n\n`+s.result.source_rows.map(r=>`[${r.id}] ${r.phase} / ${r.role}: ${r.text}${r.immediate_response?' // immediate response: '+r.immediate_response:''}`).join('\n'):'';enabled();}
async function act(path,body={}){if(busy)return;busy=true;$('error').textContent='';try{render(await (await request(path,body)).json());}catch(e){error(e);}finally{busy=false;if(current)render(current);}}
$('file').addEventListener('change',async()=>{let f=$('file').files[0];if(!f)return;if(f.size>25*1024*1024){error(Error('File exceeds 25 MB.'));return;}let bytes=new Uint8Array(await f.arrayBuffer()),binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));await act('/api/import',{name:f.name,data:btoa(binary)});$('file').value='';});
$('demo').onclick=()=>act('/api/demo');$('patient').onchange=()=>act('/api/select-case',{case_key:$('patient').value});$('kind').onchange=()=>act('/api/kind',{kind:$('kind').value});$('generate').onclick=()=>act('/api/start');$('stop').onclick=()=>act('/api/cancel');$('clear').onclick=async()=>{await act('/api/clear');if(!current.document)edits.clear();};$('reviewed').onchange=enabled;
for(const id of ['subject','body'])$(id).addEventListener('input',()=>{if(shown)edits.set(shown,{subject:$('subject').value,body:$('body').value});$('reviewed').checked=false;enabled();});
function payload(){return {source_sha:current.document.sha256,case_key:current.selected_case,kind:current.kind,subject:$('subject').value,body:$('body').value,reviewed:$('reviewed').checked};}
$('save').onclick=async()=>{try{const r=await request('/api/export',payload()),blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`${current.kind}_draft.txt`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){error(e);}};
$('diagnostic-save').onclick=async()=>{try{const r=await request('/api/diagnostic-download',{}),blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`Clinic_Diagnostic_${current.diagnostic.run_id}.zip`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){error(e);}};
$('debug-output-save').onclick=async()=>{try{const r=await request('/api/debug-output',{}),blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`Rejected_Output_${current.diagnostic?.run_id||'local'}.txt`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){error(e);}};
$('view-debug-output').onclick=()=>$('debug-output-panel').scrollIntoView({block:'start',behavior:'smooth'});
$('copy').onclick=async()=>{try{await request('/api/review',payload());await navigator.clipboard.writeText(`Subject: ${$('subject').value}\n\n${$('body').value}`);$('error').textContent='Letter copied. Nothing has been sent.';}catch(e){error(e);}};
$('quit').onclick=async()=>{try{await request('/api/quit',{});sessionStorage.removeItem('local-session');edits.clear();$('status').textContent='Program closed.';clearInterval(timer);for(const e of document.querySelectorAll('button,input,select,textarea'))e.disabled=true;}catch(e){error(e);}};
async function poll(){if(polling||busy)return;polling=true;try{render(await(await request('/api/state')).json());}catch(e){error(e);}finally{polling=false;}}
const timer=setInterval(poll,800);poll();
