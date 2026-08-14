#!/usr/bin/env python3
from __future__ import annotations
import json,re,ssl,urllib.parse,urllib.request
from pathlib import Path
from html.parser import HTMLParser

BASE='https://adour-garonne.eaufrance.fr'
OUT=Path('data/legacy_aeag_lacanau_probe.json')
CTX=ssl._create_unverified_context()
UA={'User-Agent':'Lacanautics/3.2 (+https://github.com/benoitpaillard/Lacanautics)'}

class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower()=='a':
            d=dict(attrs); h=d.get('href')
            if h:self.links.append(h)

def get(url,timeout=40):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=timeout,context=CTX) as r:
        return r.status,r.headers,r.read()

def text(b):
    for e in ('utf-8','cp1252','latin-1'):
        try:return b.decode(e)
        except:pass
    return b.decode('latin-1','replace')

def inspect_html(url):
    try:
        st,h,b=get(url); t=text(b); p=Links(); p.feed(t)
        links=[urllib.parse.urljoin(url,x) for x in p.links]
        interesting=[x for x in links if re.search(r'lacanau|S1215013|bathy|hydromorph|diag|morpho|\.zip$|\.shp$|\.gpkg$|\.csv$|\.xyz$|\.asc$|\.tif|\.grd|\.pdf$',x,re.I)]
        snippets=[]
        for m in re.finditer(r'(?i).{0,160}(?:S1215013|Lacanau|bathy\w*|hydromorph\w*).{0,240}',t,re.S):
            s=re.sub(r'<[^>]+>',' ',m.group(0));s=re.sub(r'\s+',' ',s).strip();snippets.append(s[:600])
            if len(snippets)>=40:break
        return {'url':url,'status':st,'content_type':h.get('Content-Type'),'bytes':len(b),'interesting_links':sorted(set(interesting)),'snippets':snippets,'all_links_count':len(links)}
    except Exception as e:return {'url':url,'error':repr(e)}

def main():
    urls=[
      BASE+'/station/S1215013',
      BASE+'/data/ficheSTQL?stql=S1215013&panel=desc',
      BASE+'/upload/DOC/FICHES/LACS/',
      BASE+'/upload/DOC/FICHES/LACS/DIAG/',
      BASE+'/upload/DATA/THEMATIQUES/QUALITE/LACS/',
      BASE+'/upload/DATA/THEMATIQUES/QUALITE/LACS/BATHY/',
      BASE+'/upload/DATA/THEMATIQUES/QUALITE/LACS/BATHYMETRIE/',
      BASE+'/upload/DATA/THEMATIQUES/QUALITE/LACS/HYDROMORPHO/',
      BASE+'/upload/DATA/THEMATIQUES/QUALITE/LACS/HYDROMORPHOLOGIE/',
      BASE+'/upload/DOC/FICHES/LACS/BATHY/',
      BASE+'/upload/DOC/FICHES/LACS/BATHYMETRIE/',
      BASE+'/upload/DOC/FICHES/LACS/HYDROMORPHO/',
    ]
    results=[inspect_html(u) for u in urls]
    # Also follow interesting same-server directory links one level deep, capped.
    seen=set(urls); extra=[]
    for r in results:
        for u in r.get('interesting_links',[]):
            if u in seen or not u.startswith(BASE):continue
            if len(extra)>=100:break
            seen.add(u)
            if u.endswith('/') or re.search(r'S1215013|lacanau|bathy|hydromorph|morpho',u,re.I): extra.append(inspect_html(u))
    report={'seed_results':results,'followed_results':extra}
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
