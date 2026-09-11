"""Explicit webpage-date fallback after scholarly metadata retrieval."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.utils import parsedate_to_datetime
import hashlib
import json
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from papers.conference_dates import PRIVATE, _save
from papers.conference_library import load_library
from papers.conference_date_sources import _date, safe_metadata_url
from papers.proceedings import normalize_title
from papers.candidate_ledger import atomic_write_json, utc_now


def nodes(value):
    if isinstance(value,list):
        for item in value: yield from nodes(item)
    elif isinstance(value,dict):
        yield value
        yield from nodes(value.get('@graph',[]))


def page_date(raw, url, title, headers):
    soup=BeautifulSoup(raw,'html.parser')
    expected=normalize_title(title)
    # Listing pages are allowed only when they actually contain this paper.
    if not expected or expected not in normalize_title(soup.get_text(' ',strip=True)):
        return {}
    candidates=[]
    def add(value,basis,evidence,priority):
        value=_date(value)
        if len(value)==10: candidates.append((priority,value,basis,evidence))
    for script in soup.select('script[type="application/ld+json"]'):
        try: data=list(nodes(json.loads(script.get_text())))
        except (ValueError,TypeError): continue
        for item in data:
            if normalize_title(str(item.get('name',item.get('headline','')))) != expected: continue
            add(item.get('datePublished'),'webpage_published','JSON-LD datePublished',0)
            add(item.get('dateModified'),'webpage_modified','JSON-LD dateModified',1)
    # Generic page metadata is used only on a page with this paper as a heading.
    heading=any(normalize_title(x.get_text(' ',strip=True))==expected for x in soup.select('h1,h2,#papertitle,.presentation-title'))
    if heading:
        for tag in soup.select('meta[content]'):
            key=str(tag.get('property',tag.get('name',''))).lower()
            if key in {'article:published_time','date','datepublished'}:
                add(tag['content'],'webpage_published',key,0)
            elif key in {'article:modified_time','last-modified','datemodified'}:
                add(tag['content'],'webpage_modified',key,1)
        # Date appearing on the paper's own presentation page, not related papers.
        text=soup.get_text(' ',strip=True)
        for pattern,fmt in [(r'\b([A-Z][a-z]{2} \d{1,2}, 20\d{2})\b','%b %d, %Y'),(r'\b(\d{1,2} [A-Z][a-z]+ 20\d{2})\b','%d %B %Y')]:
            for m in re.finditer(pattern,text):
                try: value=datetime.strptime(m[1],fmt).date().isoformat()
                except ValueError: continue
                add(value,'webpage_event',m[1],2)
                break
    text=soup.get_text(' ',strip=True)
    generated=re.search(r'Page generated (20\d{2}-\d{2}-\d{2})',text)
    if generated: add(generated[1],'webpage_generated',generated[0],3)
    modified=next((v for k,v in headers.items() if k.lower()=='last-modified'),None)
    if modified:
        try: add(parsedate_to_datetime(modified).date().isoformat(),'webpage_modified','HTTP Last-Modified: '+modified,4)
        except (ValueError,TypeError,OverflowError): pass
    if not candidates:return {}
    _,value,basis,evidence=min(candidates)
    return {'published':value,'date_source':{'url':url,'basis':basis,'evidence':evidence}}


def lookup(record):
    url=record['url'];target=url
    if not safe_metadata_url(url): return {'error':'unsupported_source'}
    for _ in range(5):
        response=requests.get(target,timeout=(10,40),allow_redirects=False,headers={'User-Agent':'LOKEN-webpage-date/1.0'})
        if response.status_code not in (301,302,303,307,308):break
        target=urljoin(target,response.headers.get('Location',''))
        if not safe_metadata_url(target):return {'error':'unsupported_redirect'}
    response.raise_for_status()
    if response.status_code!=200 or len(response.content)>20_000_000:return {'error':'invalid_response'}
    result=page_date(response.content,url,record['title'],response.headers)
    key=hashlib.sha256(url.encode()).hexdigest()
    path=PRIVATE/'web-fallback';path.mkdir(parents=True,exist_ok=True)
    (path/(key+'.html')).write_bytes(response.content)
    atomic_write_json(path/(key+'.json'),{'url':url,'resolved_url':target,'headers':{k:v for k,v in response.headers.items() if k.lower()=='last-modified'},'checked_at':utc_now(),'metadata':result})
    return result


def resolve(*,apply=False,limit=0):
    records=sorted((p for p in load_library()['papers'].values() if len(p['published'])<10),key=lambda p:(p.get('order_date',p['published']),p['title']),reverse=True)
    if limit:records=records[:limit]
    expected={p['id']:p for p in records};updates={};failed={}
    def fetch(record):
        try:return record,lookup(record)
        except (OSError,ValueError,requests.RequestException) as error:return record,{'error':str(error)[:250]}
    for start in range(0,len(records),20):
        with ThreadPoolExecutor(max_workers=5) as pool:batch=list(pool.map(fetch,records[start:start+20]))
        for record,result in batch:
            if result.get('published'):
                result['date_source']['previous_date']=record['published']
                updates[record['id']]=result
            else:failed[record['id']]=result
        atomic_write_json(PRIVATE/'web-fallback-report.json',{'updates':updates,'unresolved':failed,'applied':False})
        print(json.dumps({'checked':min(start+20,len(records)),'selected':len(records),'resolved':len(updates),'unresolved':len(failed)}),flush=True)
    _save(updates,expected,apply)
    report={'updates':updates,'unresolved':failed,'applied':apply,'checked_at':utc_now()}
    atomic_write_json(PRIVATE/'web-fallback-report.json',report)
    return {'selected':len(records),'resolved':len(updates),'unresolved':len(failed),'applied':apply}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true');parser.add_argument('--limit',type=int,default=0)
    args=parser.parse_args()
    if args.limit<0:parser.error('limit must be nonnegative')
    result=resolve(apply=args.apply,limit=args.limit)
    print(json.dumps(result))
    if result['unresolved']: raise SystemExit(3)

if __name__=='__main__':main()
