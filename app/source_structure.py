"""Format adapters with original-row provenance. No clinical language generation."""
import re
from datetime import date,datetime
from gp_brief import Case,Encounter,MARKER,header_date
from brief_auto import letterhead_prefix,nookal_header,sections

def clean(text):
    t=text.strip().replace('\u00a0',' ')
    t=re.sub(r'^#{1,6}\s+','',t);t=re.sub(r'^[-*+]\s+','',t)
    return t.replace('**','').replace('__','').strip()

def encounter_date(text):
    t=clean(text)
    for fn in (header_date,nookal_header):
        try:
            x=fn(t)
            if x is not None:return x
        except ValueError:raise ValueError('Invalid consultation date; correct the source date before analysis.')
    m=re.fullmatch(r'(?:Session date|Consultation date|Visit date|Appointment date|Date)\s*[:：]?\s*(.+)',t,re.I)
    if m:t=m[1].strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',t):
        try:return date.fromisoformat(t),False
        except ValueError:raise ValueError('Invalid consultation date.')
    for fmt in ('%d/%m/%Y','%d %b %Y','%d %B %Y'):
        try:return datetime.strptime(t,fmt).date(),False
        except ValueError:pass
    # Dated Markdown note heading; narrative injury dates are never a boundary.
    if re.match(r'^#{1,6}\s+',text):
        m=re.match(r'^(\d{4}-\d{2}-\d{2})(?:\s|[·|:–_-]).*',t)
        if m:return date.fromisoformat(m[1]),False
    return None

ROLE_MAP={'subjective':'S/','current history':'S/','s':'S/','objective':'O/','objective examination':'O/','active movements':'O/','o':'O/','assessment':'A/','provisional diagnosis':'A/','provisional diagnosis + prognosis':'A/','a':'A/','treatment':'Rx/','intervention':'Rx/','rx':'Rx/','home programme':'HEP prescribed:','home program':'HEP prescribed:','exercises':'HEP prescribed:','hep':'HEP prescribed:','plan':'P/','future plan':'P/','p':'P/','post treatment':'//','post-treatment':'//'}
META_MAP={'client':'Client','patient name':'Client','patient':'Client','name':'Client','patient id':'Patient ID','case id':'Case ID','claim number':'Claim number','dob':'DOB','date of birth':'DOB','date of injury':'Date of injury','provider':'Provider','practice':'Practice'}
OTHER={'previous history','social history','shx','body chart','investigations','ic / warnings / tests','performed','finalised'}

def normalized_rows(doc):
    rows=[];pending=None
    # Metadata needed for patient identity can be read separately; clinical text
    # marked secondary by the Markdown adapter never enters model evidence.
    for original in doc['lines']:
        t=clean(original['text'])
        if not t or t.startswith('```') or re.fullmatch(r'[-| :]+',t):continue
        row={**original,'text':t,'source_ids':[original['id']],'source_quotes':[original['text']]}
        parsed_header=encounter_date(original['text'])
        if parsed_header is not None:
            row['explicit_encounter_date']=parsed_header[0].isoformat() if parsed_header[0] else None;row['explicit_initial']=parsed_header[1]
        if t.startswith('|'):
            cells=[c.strip() for c in t.strip('|').split('|')]
            if len(cells)==2 and cells[0].lower() in META_MAP and cells[0].lower()!='name':t=META_MAP[cells[0].lower()]+' '+cells[1];row['text']=t
            elif len(cells)==2 and cells[0].lower()=='name':row['nonclinical_metadata']=True
        if re.match(r'^Name\s*[:：]',t,re.I):row['nonclinical_metadata']=True;rows.append(row);continue
        m=re.fullmatch(r'(Client|Patient name|Patient|Patient ID|Case ID|Claim number|DOB|Date of birth|Date of injury|Provider|Practice)\s*[:：]?\s*',t,re.I)
        if m:pending=(META_MAP[m[1].lower()],row);continue
        if pending:
            label,old=pending
            metadata_date=label in ('DOB','Date of injury') and bool(re.fullmatch(r'\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]+\s+\d{4}',t))
            next_is_label=t.lower().rstrip(':：') in META_MAP or t.lower().rstrip(':：/') in ROLE_MAP
            if (metadata_date or not encounter_date(t)) and not next_is_label and not re.match(r'^(?:S|O|A|P|Rx)\s*[/：:]|^#{1,6}',t,re.I):
                row={**old,'text':label+' '+t,'source_ids':old['source_ids']+row['source_ids'],'source_quotes':old['source_quotes']+row['source_quotes']};t=row['text']
            else:rows.append(old)
            pending=None
        m=re.match(r'^(Client|Patient name|Patient|Patient ID|Case ID|Claim number|DOB|Date of birth|Date of injury|Provider|Practice)\s*[:：]\s*(.+)$',t,re.I)
        if m:row['text']=META_MAP[m[1].lower()]+' '+m[2].strip()
        elif re.fullmatch(r'#\s+PT-\d+\s+.+',original['text']):
            row['text']='Client '+re.sub(r'^#\s+PT-\d+\s+','',original['text']).strip();row['identity_from_profile_title']=True
        rows.append(row)
    if pending:rows.append(pending[1])
    return rows

def cases(doc):
    rows=normalized_rows(doc);primary=[r for r in rows if r.get('primary',True)]
    # A profile title is identity metadata, not evidence of symptoms or plans.
    names=[r for r in rows if r['text'].startswith('Client ')]
    for row in names:
        value=row['text'][7:]
        value=re.split(r'\s{2,}[A-Za-z][A-Za-z ]{0,30}:',value,1)[0].strip()
        row['text']='Client '+value
    titles=[r for r in names if r.get('identity_from_profile_title')]
    def name_key(value):return sorted(w for w in re.findall(r'[a-z]+',value.lower()) if w not in ('mr','mrs','ms','miss','dr'))
    def same_profile_name(row):
        title=set(name_key(titles[0]['text'][7:]));value=set(name_key(row['text'][7:]))
        return value==title or len(title)>=2 and title<=value and len(value)<=len(title)+2
    has_markers=any(MARKER.fullmatch(r['text']) for r in primary)
    if not names and not has_markers:
        pids={r['text'][11:].strip() for r in rows if r['text'].startswith('Patient ID ')}
        if len(pids)==1:
            name={**next(r for r in rows if r['text'].startswith('Patient ID ')),'text':'Client '+next(iter(pids))}
            names=[name];primary=[name]+primary
        else:raise ValueError('Text was extracted, but no unambiguous patient identifier was recognised. Import a record with Client/Patient name/Patient ID, or a verified profile title. No clinical draft was generated.')
    grouped={}
    if has_markers:
        active=None
        for row in primary:
            m=MARKER.fullmatch(row['text'])
            if m:
                alias=(m[2] or m[1]).upper();key=(alias,'')
                if key in grouped:raise ValueError('Repeated patient marker: verify the case boundary.')
                active=Case(str(len(grouped)+1),alias,[]);grouped[key]=active
            elif active:active.lines.append(row)
            elif not letterhead_prefix([row]):raise ValueError('Unassigned text before patient marker.')
    elif titles and all(same_profile_name(r) for r in names):
        alias=titles[0]['text'][7:]
        grouped[(alias,'')]=Case('1',alias,primary)
    elif not any(r['text'].startswith('Client ') for r in primary):
        # Local profile adapter: use title only for identity; only ## Notes content
        # becomes clinical evidence. Other secondary summaries stay excluded.
        aliases={r['text'][7:] for r in names}
        if len(aliases)!=1:raise ValueError('Conflicting profile identities.')
        grouped[(next(iter(aliases)),'')]=Case('1',next(iter(aliases)),primary)
    else:
        if titles:raise ValueError('Profile title and original note use different patient names or aliases. Verify identity before conversion or analysis; no clinical draft generated.')
        starts=[i for i,r in enumerate(primary) if r['text'].startswith('Client ')]
        prefix=primary[:starts[0]]
        if not letterhead_prefix(prefix):raise ValueError('Unassigned identity or clinical content before the first patient. No draft generated; verify the record boundary.')
        administrative_text={r['text'] for r in prefix}
        primary=[{**r,'administrative_header':True} if r['text'] in administrative_text else r for r in primary]
        for n,start in enumerate(starts):
            block=primary[start:starts[n+1] if n+1<len(starts) else len(primary)]
            alias=block[0]['text'][7:].strip();claims=tuple(sorted({r['text'] for r in block if r['text'].startswith(('Patient ID ','DOB ','Claim number ','Case ID '))}))
            key=(alias,claims)
            if key not in grouped:grouped[key]=Case(str(len(grouped)+1),alias,[])
            if n==0:grouped[key].lines.extend({**r,'administrative_header':True} for r in prefix)
            grouped[key].lines.extend(block)
    for case in grouped.values():populate(case)
    return list(grouped.values())

def populate(case):
    current=None;seen={};role=None;heading=None;out=[]
    for row in case.lines:
        t=row['text'];parsed=(date.fromisoformat(row['explicit_encounter_date']) if row['explicit_encounter_date'] else None,row.get('explicit_initial',False)) if 'explicit_encounter_date' in row else encounter_date(t)
        if parsed is not None:
            # Only an exactly repeated timestamp header is a page continuation.
            if nookal_header(t) and t in seen:current=seen[t];role=None;continue
            current=Encounter(*parsed);out.append(current);seen[t]=current;role=None;continue
        if row.get('administrative_header') or row.get('nonclinical_metadata') or t.startswith(('Client ','Patient ID ','Case ID ','Claim number ','DOB ','Date of injury ','Provider ','Practice ')):continue
        if current is None:
            current=Encounter(None,False);out.append(current)
        lower=t.lower().rstrip(':：/').strip()
        if lower in ROLE_MAP:role=ROLE_MAP[lower];heading=lower;continue
        if lower in OTHER or t.startswith(('Finalised ','## Notes')):role=None;continue
        m=re.match(r'^([^:：]+)\s*[:：]\s*(.+)$',t)
        if m and m[1].strip().lower() in ROLE_MAP:
            heading=m[1].strip().lower();role=ROLE_MAP[heading];current.lines.append({**row,'text':role+' '+m[2],'source_heading':heading});continue
        if m and m[1].strip().lower() in OTHER:role=None;continue
        m=re.match(r'^(S|O|A|P|Rx)\s*[/：:]\s*(.*)$',t,re.I)
        if m:
            role=ROLE_MAP[m[1].lower()]
            if m[2]:current.lines.append({**row,'text':role+' '+m[2]})
            continue
        if t.startswith('//'):current.lines.append(row);role='//';continue
        if re.match(r'^(?:HEP prescribed|HEP adherence|Current capacity|Patient-agreed goal|Planned intervention|Treatment rationale|Current work capacity|SOM):',t,re.I):current.lines.append(row);role=None;continue
        if role:current.lines.append({**row,'text':role+' '+t,'source_heading':heading})
        else:current.lines.append(row)
    case.encounters=[e for e in out if any(re.match(r'^(?:S/|O/|A/|P/|Rx/|HEP prescribed:)',r['text']) for r in e.lines)]
    if not case.encounters:raise ValueError('Patient identified, but no SOAP/treatment sections were recognised. The file may be a profile summary rather than original treatment notes. No clinical draft generated.')
    if any(e.date is None for e in case.encounters) and any(e.date for e in case.encounters):
        # An explicit undated initial assessment is retained without a fake date.
        pass

def preflight(case):
    dated=[e for e in case.encounters if e.date]
    if len({e.date for e in dated})!=len(dated):raise ValueError('Several distinct notes share a consultation date. Resolve the encounter order before analysing progress.')
    latest=max(dated,key=lambda e:e.date) if dated else case.encounters[-1]
    s=sections(latest)
    usable=s['subjective']+s['objective']+s['treatment']
    if not usable or sum(len(r['text']) for r in usable)<25:raise ValueError('The latest note lacks a usable symptom, examination or treatment record. No model draft generated.')
    return latest
