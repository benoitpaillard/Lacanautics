#!/usr/bin/env python3
import csv, io, json, os, re, ssl, urllib.request, zipfile
from pathlib import Path
URL='https://adour-garonne.eaufrance.fr/upload/DATA/THEMATIQUES/QUALITE/LACS/donnees_qualite_lac_2012.zip'
OUT=Path('data/aeag_2012_archive_report.json')

def dec(b):
    for e in ('utf-8-sig','cp1252','latin-1'):
        try:return b.decode(e)
        except:pass
    return b.decode('latin-1','replace')

def main():
    req=urllib.request.Request(URL,headers={'User-Agent':'Lacanautics/3.1'})
    ctx=ssl._create_unverified_context()  # legacy AEAG server has an incomplete TLS chain
    raw=urllib.request.urlopen(req,timeout=90,context=ctx).read()
    z=zipfile.ZipFile(io.BytesIO(raw))
    report={'url':URL,'zip_bytes':len(raw),'members':[],'lacanau_hits':[],'bathymetry_hits':[]}
    for n in z.namelist():
        info=z.getinfo(n); ent={'name':n,'bytes':info.file_size}; report['members'].append(ent)
        low=n.lower()
        if any(k in low for k in ('bathy','hydromorph','morpho','lacanau','s1215013')): report['bathymetry_hits'].append(ent)
        if low.endswith(('.csv','.txt','.tab','.xml','.json','.dbf')):
            b=z.read(n)
            if len(b)>15_000_000: continue
            t=dec(b)
            if re.search(r'S1215013|Lacanau',t,re.I):
                lines=t.splitlines(); hits=[]
                for i,line in enumerate(lines):
                    if re.search(r'S1215013|Lacanau',line,re.I):
                        hits.append({'line':i+1,'text':line[:1500]})
                        if len(hits)>=40: break
                report['lacanau_hits'].append({'file':n,'hits':hits,'header':lines[0][:2500] if lines else ''})
            if re.search(r'bathym|profondeur|hydromorph|morpholog',t,re.I):
                matches=[]
                for i,line in enumerate(t.splitlines()):
                    if re.search(r'bathym|profondeur|hydromorph|morpholog',line,re.I):
                        matches.append({'line':i+1,'text':line[:1500]})
                        if len(matches)>=40: break
                if matches: report['bathymetry_hits'].append({'file':n,'matches':matches})
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
