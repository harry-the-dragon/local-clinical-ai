# Source-preserving utilities extracted from USB v16.6; no letter/form generator.

import re

from datetime import date

from gp_brief import Case,Encounter,MARKER,header_date,comparison,word_count,KNOWN_ABBREVIATIONS

HEADINGS={'subjective':'subjective','current history':'subjective','objective':'objective','objective examination':'objective','active movements':'objective','provisional diagnosis':'assessment','provisional diagnosis + prognosis':'assessment','treatment':'treatment','exercises':'home','plan':'plan','post treatment':'response','previous history':'other','social history':'other','shx':'other','ic / warnings / tests':'other','body chart':'other','ody chart':'other'}

def letterhead_prefix(rows):
    """Recognise bounded administrative letterhead, never arbitrary clinical prose.

    Context anchors permit a clinic name/address without caching a clinic name.
    All original rows are retained for source review, excluded from GP sections.
    """
    if not rows:return True
    known=r'^(?:LOCAL FORMAT CONVERSION - NOT AN OFFICIAL NOOKAL EXPORT$|Nookal\b|Clinical (?:notes|record)|Progress (?:notes|record)|Page\b|Practice |Provider |FICTIONAL\b|SYNTHETIC\b|SYN-\d+ \||\d+$)'
    if all(re.match(known,r['text'],re.I) for r in rows):return True
    if len(rows)>25:return False
    texts=[r['text'].strip() for r in rows]
    forbidden=r'^(?:Client\b|Patient\b|Name\s*:|DOB\b|MRN\b|Case ID\b|Claim number\b|S\s*[/：:]|O\s*[/：:]|A\s*[/：:]|Rx\s*[/：:]|P\s*[/：:]|HEP\b|Current history\b|Subjective\b|Objective\b|Treatment\b|Plan\b|Provisional diagnosis\b)'
    if any(re.search(forbidden,t,re.I) or re.search(r'\b(?:pain|injury|symptoms?|diagnos\w*|treatment|patient|weakness|stiffness|consultation)\b',t,re.I) for t in texts):return False
    abn=any(re.fullmatch(r'ABN\s*:?\s*[\d ]{11,16}',t,re.I) for t in texts)
    contacts=sum(bool(re.match(r'^(?:[TEWF]\s*:|Tel(?:ephone)?\s*:|Phone\s*:|Email\s*:|Fax\s*:|www\.)',t,re.I)) for t in texts)
    # Arbitrary text alone cannot authorise a boundary. Require contact context.
    if not (contacts>=2 or abn and contacts>=1):return False
    return all(len(t)<=150 and not re.search(r'[.!?]\s+\S',t) for t in texts)

def nookal_header(text):
    m=re.fullmatch(r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+(\d{1,2})(?:st|nd|rd|th)?\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4}),\s+\d{1,2}:\d{2}\s*(?:am|pm)\s+\S.*',text,re.I)
    if not m:return None
    months=('jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec')
    return date(int(m[3]),months.index(m[2].lower())+1,int(m[1])),False

def sections(encounter):
    out={k:[] for k in ('subjective','objective','assessment','treatment','home','plan','response','other')};role='other'
    for r in encounter.lines:
        t=r['text'].strip();lower=t.lower()
        if r.get('administrative_header'):continue
        if lower in HEADINGS:role=HEADINGS[lower];continue
        if re.match(r'^(?:Observation|Passive Accesory Joint Tests|Other Tests)$',t,re.I):continue
        if header_date(t) is not None or nookal_header(t) is not None or t.startswith(('Finalised ','Session date ','Client ','Patient ID','Case ID','Case ','DOB','Claim number','Provider','Practice','Occupation','Injury date','Date of injury','Pre-injury','Encounter ID','Completed session','Status ','Service code','SYNTHETIC','FICTIONAL','SYN-')):continue
        if re.match(r'^HEP (?:prescribed|adherence):',t,re.I):role='home';out[role].append(r);continue
        if re.match(r'^(?:Current capacity|Current pain|Mechanism/history):?',t,re.I):out['subjective'].append(r);continue
        if re.match(r'^Assessment:',t,re.I):role='assessment';out[role].append(r);continue
        if re.match(r'^(?:SOM:|Patient-agreed goal:|Risk screening:|Consent:|GP communication:|Follow-up status:)',t,re.I):role='other';out[role].append(r);continue
        m=re.match(r'^(S|O|A|Rx|P|HEP)\s*[/：:]\s*(.*)',t,re.I)
        if m:role={'s':'subjective','o':'objective','a':'assessment','rx':'treatment','p':'plan','hep':'home'}[m[1].lower()];out[role].append(r);continue
        if t.startswith('//'):out['response'].append(r);continue
        if t.lower() in ('performed','show all options','ic obtained'):continue
        out[role].append(r)
    return out

def source_text(rows):return ' '.join(re.sub(r'^(?:S|O|A|Rx|P|HEP)\s*[/：:]\s*','',r['text'],flags=re.I) for r in rows)

def measurements(rows):
    result={}
    for r in rows:
        text=r['text'].lstrip().removeprefix('//').split('//')[0]
        if re.search(r'grip\s*strength',text,re.I):
            for side,pattern in [('right',r'(?:\bR\b|\bRight\b)\s*[=:]?\s*(\d+(?:\.\d+)?)\s*kg'),('left',r'(?:\bL\b|\bLeft\b)\s*[=:]?\s*(\d+(?:\.\d+)?)\s*kg')]:
                m=re.search(pattern,text,re.I)
                if m:result['grip_'+side]=(float(m[1]),'kilograms',r['id'])
        for label,pattern in [('flexion',r'\bFlex(?:ion)?\s*[:=-]?\s*(\d+(?:\.\d+)?)\s*(deg(?:rees)?|[°\x27]|%)'),('abduction',r'\bAbd(?:uction)?\s*[:=-]?\s*(\d+(?:\.\d+)?)\s*(deg(?:rees)?|[°\x27]|%)'),('extension',r'\bExt(?:ension)?\s*[:=-]?\s*(\d+(?:\.\d+)?)\s*(deg(?:rees)?|[°\x27]|%)')]:
            m=re.search(pattern,text,re.I)
            if m:result[label]=(float(m[1]),'percent' if m[2]=='%' else 'degrees',r['id'])
    return result

def num(n):return f'{n:g}'

def date_text(d):return f'{d.day} {d.strftime("%B %Y")}'

def movement_sentence(current,previous,key,label,when):
    a=current.get(key);b=previous.get(key)
    if not a:return '',[]
    if b and a[1]==b[1]:
        if a[0]==b[0]:s=f'{label} before treatment was unchanged at {num(a[0])} {a[1]} compared with {when}.'
        else:s=f'{label} before treatment {"increased" if a[0]>b[0] else "decreased"} from {num(b[0])} to {num(a[0])} {a[1]} compared with {when}.'
        return s,[a[2],b[2]]
    return f'{label} before treatment was recorded at {num(a[0])} {a[1]}.',[a[2]]

def family_of(assessment,subjective):
    t=assessment.lower() or subjective.lower()
    if re.search(r'elbow|epicondyl|golfers|tennis elbow',t):return 'elbow'
    if re.search(r'shoulder|\brc\b|rotator cuff',t):return 'shoulder'
    if re.search(r'lumbar|\blsp\b|low(?:er)? back|disc/facet',t):return 'lumbar'
    if re.search(r'cervical|\bcsp\b|neck',t):return 'cervical'
    for f in ('ankle','knee','hip','wrist'):
        if f in t:return f
    return 'general'
