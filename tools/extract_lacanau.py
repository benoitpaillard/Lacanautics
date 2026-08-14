#!/usr/bin/env python3
from __future__ import annotations
import csv, io, json, re, statistics, unicodedata, urllib.request, zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

URL="https://data.ofb.fr/catalogue/data-eaufrance/api/records/c31746f7-311a-41c7-b995-6cb78a2ddc25/attachments/points_bruts_bathy_20161020.zip"
OUT=Path('data'); OUT.mkdir(exist_ok=True)
ZIP=OUT/'points_bruts_bathy_20161020.zip'

def norm(s):
    s=unicodedata.normalize('NFKD',str(s or '')).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+','',s)

def fnum(v):
    try:return float(str(v).strip().replace(',','.'))
    except:return None

def download():
    if ZIP.exists() and ZIP.stat().st_size>1_000_000:return
    req=urllib.request.Request(URL,headers={'User-Agent':'Lacanautics/1.0'})
    with urllib.request.urlopen(req,timeout=120) as r, ZIP.open('wb') as f:
        while chunk:=r.read(1024*1024): f.write(chunk)

def decode(b):
    for e in ('utf-8-sig','cp1252','latin-1'):
        try:return b.decode(e)
        except UnicodeDecodeError:pass
    return b.decode('latin-1','replace')

def main():
    download()
    with zipfile.ZipFile(ZIP) as z:
        tab=max([n for n in z.namelist() if n.lower().endswith(('.tab','.csv','.txt'))],key=lambda n:z.getinfo(n).file_size)
        txt=decode(z.read(tab)); sample=txt[:10000]
        try: delim=csv.Sniffer().sniff(sample,delimiters=';\t,|').delimiter
        except csv.Error: delim='\t'
        rows=list(csv.reader(io.StringIO(txt),delimiter=delim))
        info_names=[n for n in z.namelist() if n.lower().endswith('.info')]
        info=decode(z.read(info_names[0])) if info_names else ''
    h=rows[0]; nh=[norm(x) for x in h]
    def idx(*names):
        for n in map(norm,names):
            if n in nh:return nh.index(n)
        return None
    I={
      'code':idx('code_gene','codegene','code'),
      'name':idx('nom_bdcarthage','nombdcarthage','nom'),
      'date':idx('dtg_bathy','dtgbathy','date'),
      'lon':idx('lon','longitude'),
      'lat':idx('lat','latitude'),
      'depth':idx('prof','profondeur','depth')}
    if None in (I['lon'],I['lat'],I['depth']): raise RuntimeError(f'Bad header {h} -> {I}')
    matched=[]
    for r in rows[1:]:
        code=r[I['code']] if I['code'] is not None else ''
        name=r[I['name']] if I['name'] is not None else ''
        nc,nn=norm(code),norm(name)
        if 'lacanau' in nn or nc in {'fl49','frfl49'} or nc.endswith('fl49'):
            matched.append(r)
    if not matched: raise RuntimeError('No Lacanau rows found')
    with (OUT/'lacanau_soundings_raw.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f); w.writerow(h); w.writerows(matched)
    pts=[]; bad=Counter()
    for r in matched:
        lon,lat,d=fnum(r[I['lon']]),fnum(r[I['lat']]),fnum(r[I['depth']])
        if None in (lon,lat,d): bad['bad_numeric']+=1; continue
        if not(-1.25<lon<-1.0 and 44.85<lat<45.1): bad['outside_bbox']+=1; continue
        if d<0: bad['negative_depth']+=1; continue
        pts.append({'lon':lon,'lat':lat,'depth':d,'date':r[I['date']] if I['date'] is not None else '', 'code':r[I['code']] if I['code'] is not None else '', 'name':r[I['name']] if I['name'] is not None else 'Lac de Lacanau'})
    if not pts: raise RuntimeError(f'No valid Lacanau points, matched={len(matched)}, bad={bad}')
    groups=defaultdict(list); meta={}
    for p in pts:
        k=(round(p['lon'],7),round(p['lat'],7)); groups[k].append(p['depth']); meta[k]=p
    features=[]
    for k,ds in groups.items():
        p=meta[k]
        features.append({'type':'Feature','geometry':{'type':'Point','coordinates':[k[0],k[1]]},'properties':{'depth_m':round(statistics.median(ds),3),'n':len(ds),'date':p['date']}})
    geo={'type':'FeatureCollection','name':'Lac de Lacanau official bathymetry soundings','source':URL,'license':'Licence Ouverte / Open Licence 2.0','features':features}
    (OUT/'lacanau_soundings.geojson').write_text(json.dumps(geo,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    depths=[p['depth'] for p in pts]; lons=[p['lon'] for p in pts]; lats=[p['lat'] for p in pts]
    report={
      'generated_utc':datetime.now(timezone.utc).isoformat(),
      'official_source':URL,'archive_member':tab,'header':h,'columns':I,
      'archive_rows_excluding_header':len(rows)-1,'matched_lacanau_rows':len(matched),
      'valid_lacanau_soundings':len(pts),'unique_lonlat_soundings':len(features),
      'depth_m':{'min':min(depths),'max':max(depths),'median':statistics.median(depths)},
      'wgs84_bbox':{'west':min(lons),'south':min(lats),'east':max(lons),'north':max(lats)},
      'dates':sorted({p['date'] for p in pts if p['date']}),
      'codes':dict(Counter(p['code'] for p in pts)), 'names':dict(Counter(p['name'] for p in pts)),
      'rejected':dict(bad),'archive_info':info[:12000],
      'note':'Coordinates in the official archive are already longitude/latitude; depths are preserved as published.'}
    (OUT/'lacanau_soundings_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
