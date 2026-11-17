# Source-preserving utilities extracted from USB v16.6; no letter/form generator.

from dataclasses import dataclass,field

from datetime import date

import re

@dataclass
class Encounter:
    date:date|None
    initial:bool
    lines:list=field(default_factory=list)

@dataclass
class Case:
    key:str
    alias:str
    lines:list
    encounters:list=field(default_factory=list)

WORDS={'one':1,'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10}

MONTHS={name:i for i,name in enumerate(('january','february','march','april','may','june','july','august','september','october','november','december'),1)}

MARKER=re.compile(r'^Patient\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b(?:\s*\(?([A-Za-z])\)?)?\s*$',re.I)

def header_date(text):
    """Parse explicit encounter headers, not dates buried in injury history."""
    t=text.strip();initial=bool(re.match(r'^Initial (?:consult|assessment)\b',t,re.I))
    if initial:t=re.sub(r'^Initial (?:consult|assessment)\s*','',t,flags=re.I).strip(' ()')
    m=re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})',t)
    if m:return date(int(m[3]),int(m[2]),int(m[1])),initial
    m=re.fullmatch(r'(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})',t)
    if m and m[2].lower() in MONTHS:return date(int(m[3]),MONTHS[m[2].lower()],int(m[1])),initial
    return (None,True) if initial and not t else None

def comparison(case):
    dated=sorted((e for e in case.encounters if e.date),key=lambda e:e.date)
    if not dated:raise ValueError('Latest encounter date is not documented')
    latest=dated[-1]
    month=latest.date.month-1 or 12;year=latest.date.year-(latest.date.month==1)
    last_month=[e for e in dated[:-1] if e.date.year==year and e.date.month==month]
    if last_month:return latest,last_month[-1],'previous_month'
    earlier=[e for e in dated[:-1] if e.date<latest.date]
    return latest,(earlier[-1] if earlier else None),'earlier_documented' if earlier else 'no_dated_comparison'

def word_count(text):return len(re.findall(r"\b[\w]+(?:[-’'][\w]+)*\b",text))

KNOWN_ABBREVIATIONS=re.compile(r'\b(?:HEP|ROM|AROM|PROM|TENS|PPIVMs?|MWM|GH|RC|TB|Rx|Lsp|Csp|Tsp|IMT|TOP|P1|R1|LLF|RLF|STR|TPR|HP)\b',re.I)
