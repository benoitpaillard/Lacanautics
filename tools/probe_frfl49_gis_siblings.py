#!/usr/bin/env python3
from __future__ import annotations
import itertools,json,ssl,urllib.request,urllib.error
from pathlib import Path
BASES=[
 'https://adour-garonne.eaufrance.fr/upload/DOC/FICHES/LACS/BATHYMETRIE/',
 'https://adour-garonne.eaufrance.fr/upload/DATA/THEMATIQUES/QUALITE/LACS/BATHYMETRIE/',
 'https://adour-garonne.eaufrance.fr/upload/DATA/THEMATIQUES/QUALITE/LACS/BATHY/',
]
NAMES=['FRFL49_Bathym','FRFL49_Bathymetrie','FRFL49_Bathy','FRFL49_bathym','S1215013_Bathym','S1215013_Bathymetrie','S1215013_bathy']
EXTS=['zip','7z','tar.gz','shp','dbf','shx','prj','lyr','lyrx','mxd','tif','tiff','asc','grd','xyz','csv','gpkg','geojson','kml','kmz','gdb.zip','pdf']
OUT=Path('data/frfl49_gis_sibling_probe.json')
CTX=ssl._create_unverified_context();UA={'User-Agent':'Lacanautics/3.3'}

def check(url):
    req=urllib.request.Request(url,headers={**UA,'Range':'bytes=0-1023'})
    try:
        with urllib.request.urlopen(req,timeout=12,context=CTX) as r:
            b=r.read(1024);return {'url':url,'status':r.status,'content_type':r.headers.get('Content-Type'),'content_length':r.headers.get('Content-Length'),'first_bytes_hex':b[:32].hex()}
    except urllib.error.HTTPError as e:return {'url':url,'status':e.code,'content_type':e.headers.get('Content-Type') if e.headers else None}
    except Exception as e:return {'url':url,'error':type(e).__name__+': '+str(e)[:200]}

def main():
    results=[]
    for base,name,ext in itertools.product(BASES,NAMES,EXTS):
        r=check(base+name+'.'+ext)
        if r.get('status') not in (404,403) or r.get('error'):
            results.append(r);print(r)
    good=[r for r in results if r.get('status') in (200,206)]
    rep={'tested':len(BASES)*len(NAMES)*len(EXTS),'nonstandard_results':results,'successful':good}
    OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(rep,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
