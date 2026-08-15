#!/usr/bin/env python3
from __future__ import annotations
import io, json, math, re, ssl, urllib.request
from itertools import product
from pathlib import Path
import fitz
import numpy as np
from PIL import Image
from scipy import ndimage

URL='https://adour-garonne.eaufrance.fr/upload/DOC/FICHES/LACS/BATHYMETRIE/FRFL49_Bathym.pdf'
PALETTE=np.asarray([[182,237,240],[145,205,237],[107,174,232],[61,144,227],[32,114,214],[32,76,189],[25,44,168],[9,9,145]],dtype=np.float32)
V3=Path('data/lacanau_2012_bands_v3.json')
OUT=Path('data/v41_vs_v31_diagnostic.json')

def download():
    ctx=ssl._create_unverified_context(); req=urllib.request.Request(URL,headers={'User-Agent':'Lacanautics diagnostics'})
    with urllib.request.urlopen(req,timeout=90,context=ctx) as r:return r.read()

def parse_geo(doc):
    p=doc[0]; obj=doc.xref_object(p.xref,compressed=False); vps=[]
    for m in re.finditer(r'/BBox\s*\[\s*([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s*\]\s*/Measure\s+(\d+)\s+0\s+R',obj,re.S):
        a,b,c,d=[float(x) for x in m.groups()[:4]]; vps.append((abs(c-a)*abs(b-d),[a,b,c,d],int(m.group(5))))
    _,pb,xref=max(vps,key=lambda t:t[0]); mo=doc.xref_object(xref,compressed=False)
    vals=[float(v) for v in re.findall(r'[-+]?\d+(?:\.\d+)?',re.search(r'/GPTS\s*\[([^\]]+)\]',mo,re.S).group(1))]
    pts=[(vals[i],vals[i+1]) for i in range(0,8,2)]; lats=[p[0] for p in pts]; lons=[p[1] for p in pts]
    return {'west':min(lons),'south':min(lats),'east':max(lons),'north':max(lats)},pb

def extract_strips(doc):
    p=doc[0]; strips=[]
    for img in p.get_images(full=True):
        xref=img[0]; info=doc.extract_image(xref); pil=Image.open(io.BytesIO(info['image'])).convert('RGB'); rects=p.get_image_rects(xref)
        if pil.width!=1924 or not rects: continue
        r=rects[0]
        if r.width<900: continue
        strips.append({'xref':xref,'y0':r.y0,'y1':r.y1,'x0':r.x0,'x1':r.x1,'im':pil})
    strips.sort(key=lambda s:s['y0'])
    if len(strips)!=6: raise RuntimeError(len(strips))
    return strips

def mosaic(strips,reverse=False,flip_y=False,flip_x=False):
    ss=list(reversed(strips)) if reverse else strips
    out=Image.new('RGB',(1924,sum(s['im'].height for s in ss))); y=0
    for s in ss:
        im=s['im']
        if flip_y: im=im.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        if flip_x: im=im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        out.paste(im,(0,y)); y+=im.height
    return np.asarray(out)

def classify(rgb):
    f=rgb.astype(np.float32); d=np.sqrt(((f[:,:,None,:]-PALETTE[None,None,:,:])**2).sum(axis=3)); cls=np.argmin(d,axis=2).astype(np.int8); md=d.min(axis=2)
    assigned=ndimage.binary_closing(md<52,structure=np.ones((3,3),bool),iterations=1); lab,_=ndimage.label(assigned); cnt=np.bincount(lab.ravel()); cnt[0]=0
    lake=lab==int(np.argmax(cnt)); lake=ndimage.binary_fill_holes(lake); valid=(md<60)&lake; _,inds=ndimage.distance_transform_edt(~valid,return_indices=True); filled=cls[inds[0],inds[1]]
    return np.where(lake,filled,-1).astype(np.int8)

def v3_points():
    j=json.loads(V3.read_text()); b=j['bbox']; rows=j['rows_south_to_north']; ny=j['ny']; nx=j['nx']
    # sample every second cell for speed, preserve south->north convention
    pts=[]
    for iy in range(0,ny,2):
        lat=b['south']+(iy+.5)/ny*(b['north']-b['south']); row=rows[iy]
        for ix in range(0,nx,2):
            ch=row[ix]
            if ch!='.':
                lon=b['west']+(ix+.5)/nx*(b['east']-b['west']); pts.append((lat,lon,int(ch)))
    return np.asarray(pts,float),b

def image_bbox_from_placement(view_bbox,pdf_bbox,strips):
    # Map the actual image placement rectangle into the viewport's geographic bbox.
    # PyMuPDF page coordinates are top-down. Viewport pdf bbox is [x0,yTopPDF,x1,yBottomPDF] in PDF bottom-up coordinates.
    vx0,vy_top_pdf,vx1,vy_bottom_pdf=pdf_bbox
    # Convert viewport to top-down using known page height later is awkward; actual strip placement spans can be treated fractionally
    # because x/y scales are linear. Derive placement fractions from page-space rectangles after converting viewport y via page height.
    raise RuntimeError

def score(classes,img_bbox,pts):
    h,w=classes.shape; lat=pts[:,0]; lon=pts[:,1]; truth=pts[:,2].astype(int)
    inside=(lon>=img_bbox['west'])&(lon<=img_bbox['east'])&(lat>=img_bbox['south'])&(lat<=img_bbox['north'])
    lat=lat[inside]; lon=lon[inside]; truth=truth[inside]
    x=np.clip(((lon-img_bbox['west'])/(img_bbox['east']-img_bbox['west'])*w).astype(int),0,w-1)
    y=np.clip(((img_bbox['north']-lat)/(img_bbox['north']-img_bbox['south'])*h).astype(int),0,h-1)
    pred=classes[y,x]; ok=pred>=0; pred=pred[ok]; truth=truth[ok]
    if len(pred)==0:return {'n':0}
    diff=np.abs(pred-truth)
    return {'n':int(len(pred)),'exact':float(np.mean(diff==0)),'within1':float(np.mean(diff<=1)),'mae_class':float(np.mean(diff)),'bias_class':float(np.mean(pred-truth))}

def main():
    raw=download(); doc=fitz.open(stream=raw,filetype='pdf'); view_bbox,pb=parse_geo(doc); strips=extract_strips(doc); pts,_=v3_points(); p=doc[0]
    # Actual native strip placement is slightly inset relative to GeoPDF viewport; compute exact geographic bbox from page coordinates.
    vx0,vyTopPDF,vx1,vyBottomPDF=pb
    v_top=p.rect.height-max(vyTopPDF,vyBottomPDF); v_bottom=p.rect.height-min(vyTopPDF,vyBottomPDF)
    ix0=min(s['x0'] for s in strips); ix1=max(s['x1'] for s in strips); iy0=min(s['y0'] for s in strips); iy1=max(s['y1'] for s in strips)
    fx0=(ix0-min(vx0,vx1))/abs(vx1-vx0); fx1=(ix1-min(vx0,vx1))/abs(vx1-vx0); fy0=(iy0-v_top)/(v_bottom-v_top); fy1=(iy1-v_top)/(v_bottom-v_top)
    img_bbox={'west':view_bbox['west']+fx0*(view_bbox['east']-view_bbox['west']),'east':view_bbox['west']+fx1*(view_bbox['east']-view_bbox['west']),
              'north':view_bbox['north']-fy0*(view_bbox['north']-view_bbox['south']),'south':view_bbox['north']-fy1*(view_bbox['north']-view_bbox['south'])}
    results=[]
    for reverse,flip_y,flip_x in product([False,True],[False,True],[False,True]):
        rgb=mosaic(strips,reverse,flip_y,flip_x); cls=classify(rgb); sc=score(cls,img_bbox,pts); sc.update({'reverse_strip_order':reverse,'flip_each_strip_y':flip_y,'flip_each_strip_x':flip_x}); results.append(sc)
    results.sort(key=lambda r:(r.get('exact',0),r.get('within1',0)) ,reverse=True)
    rep={'view_bbox':view_bbox,'pdf_bbox':pb,'actual_native_image_bbox':img_bbox,'strip_order_topdown':[s['xref'] for s in strips],'placements':[{k:s[k] for k in ('xref','x0','x1','y0','y1')} for s in strips], 'results':results,'winner':results[0]}
    OUT.write_text(json.dumps(rep,indent=2)); print(json.dumps(rep,indent=2))
if __name__=='__main__':main()
