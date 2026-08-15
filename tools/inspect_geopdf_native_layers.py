#!/usr/bin/env python3
from __future__ import annotations
import json, ssl, urllib.request
from pathlib import Path
import fitz
import numpy as np
from PIL import Image

URL='https://adour-garonne.eaufrance.fr/upload/DOC/FICHES/LACS/BATHYMETRIE/FRFL49_Bathym.pdf'
OUT=Path('data/geopdf_native_layers_report.json')


def download():
    ctx=ssl._create_unverified_context()
    req=urllib.request.Request(URL,headers={'User-Agent':'Lacanautics/4.1'})
    with urllib.request.urlopen(req,timeout=90,context=ctx) as r:return r.read()


def rgb_stats(img):
    a=np.asarray(img.convert('RGB'))
    # compact stats useful for identifying bathymetry strips
    mean=a.reshape(-1,3).mean(axis=0)
    std=a.reshape(-1,3).std(axis=0)
    # fraction close to official bathymetry palette
    pal=np.asarray([[182,237,240],[145,205,237],[107,174,232],[61,144,227],[32,114,214],[32,76,189],[25,44,168],[9,9,145]],dtype=np.float32)
    flat=a.reshape(-1,3).astype(np.float32)
    sample=flat[::max(1,len(flat)//200000)]
    d=((sample[:,None,:]-pal[None,:,:])**2).sum(axis=2)**0.5
    return {'mean_rgb':[float(x) for x in mean],'std_rgb':[float(x) for x in std],'palette_fraction_lt30':float((d.min(axis=1)<30).mean()),'palette_fraction_lt60':float((d.min(axis=1)<60).mean())}


def main():
    raw=download(); doc=fitz.open(stream=raw,filetype='pdf'); p=doc[0]
    rep={'pdf_bytes':len(raw),'page_rect':[p.rect.x0,p.rect.y0,p.rect.x1,p.rect.y1],'images':[],'drawings':[]}
    for img in p.get_images(full=True):
        xref=img[0]
        info=doc.extract_image(xref)
        pil=Image.open(__import__('io').BytesIO(info['image']))
        rects=[]
        try:
            for rr in p.get_image_rects(xref,transform=True):
                if isinstance(rr,tuple):
                    r,m=rr
                    rects.append({'rect':[r.x0,r.y0,r.x1,r.y1],'matrix':[m.a,m.b,m.c,m.d,m.e,m.f]})
                else:rects.append({'rect':[rr.x0,rr.y0,rr.x1,rr.y1]})
        except Exception as e:rects=[{'error':repr(e)}]
        ent={'xref':xref,'width':pil.width,'height':pil.height,'ext':info.get('ext'),'bytes':len(info['image']),'placements':rects,'stats':rgb_stats(pil)}
        rep['images'].append(ent)
    for i,d in enumerate(p.get_drawings(extended=True)):
        r=d.get('rect'); fill=d.get('fill'); color=d.get('color'); items=d.get('items',[])
        if r is None: continue
        rep['drawings'].append({'index':i,'rect':[r.x0,r.y0,r.x1,r.y1],'fill':list(fill) if fill else None,'stroke':list(color) if color else None,'items':len(items),'layer':d.get('layer',''),'type':d.get('type')})
    OUT.write_text(json.dumps(rep,indent=2),encoding='utf-8')
    print(json.dumps(rep,indent=2))

if __name__=='__main__':main()
