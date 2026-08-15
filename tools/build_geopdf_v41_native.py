#!/usr/bin/env python3
from __future__ import annotations
import io, json, math, re, ssl, urllib.request
from pathlib import Path

import fitz
import numpy as np
from PIL import Image
from scipy import ndimage
from shapely import contains_xy
from shapely.geometry import shape
from shapely.ops import unary_union
from skimage.measure import find_contours

ROOT=Path('.')
URL='https://adour-garonne.eaufrance.fr/upload/DOC/FICHES/LACS/BATHYMETRIE/FRFL49_Bathym.pdf'
ISLANDS=ROOT/'data/lacanau_islands.geojson'
OUT_VIS=ROOT/'bathymetry-geopdf-v41-native.webp'
OUT_CLASS=ROOT/'bathymetry-geopdf-v41-classes.webp'
OUT_CONTOURS=ROOT/'bathymetry-geopdf-v41-contours.svg'
OUT_META=ROOT/'data/lacanau_geopdf_v41.json'
OUT_REPORT=ROOT/'data/lacanau_geopdf_v41_report.json'

PALETTE=np.asarray([
 [182,237,240],[145,205,237],[107,174,232],[61,144,227],
 [32,114,214],[32,76,189],[25,44,168],[9,9,145]
],dtype=np.float32)
DISPLAY=np.asarray([
 [217,246,242],[198,239,238],[175,229,236],[150,217,235],
 [97,185,230],[50,127,205],[49,88,180],[37,28,88]
],dtype=np.uint8)


def download():
    ctx=ssl._create_unverified_context()
    req=urllib.request.Request(URL,headers={'User-Agent':'Lacanautics/4.1'})
    with urllib.request.urlopen(req,timeout=90,context=ctx) as r:return r.read()


def parse_geo(doc):
    p=doc[0]; obj=doc.xref_object(p.xref,compressed=False); vps=[]
    for m in re.finditer(r'/BBox\s*\[\s*([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s*\]\s*/Measure\s+(\d+)\s+0\s+R',obj,re.S):
        a,b,c,d=[float(x) for x in m.groups()[:4]]; xref=int(m.group(5)); vps.append((abs(c-a)*abs(b-d),[a,b,c,d],xref))
    _,pb,xref=max(vps,key=lambda t:t[0]); mo=doc.xref_object(xref,compressed=False); mg=re.search(r'/GPTS\s*\[([^\]]+)\]',mo,re.S)
    vals=[float(v) for v in re.findall(r'[-+]?\d+(?:\.\d+)?',mg.group(1))]; pts=[(vals[i],vals[i+1]) for i in range(0,8,2)]
    lats=[a for a,b in pts]; lons=[b for a,b in pts]
    return {'west':min(lons),'south':min(lats),'east':max(lons),'north':max(lats)},pb,pts


def extract_native_mosaic(doc):
    p=doc[0]; strips=[]
    for img in p.get_images(full=True):
        xref=img[0]; info=doc.extract_image(xref); pil=Image.open(io.BytesIO(info['image'])).convert('RGB')
        rects=p.get_image_rects(xref)
        if pil.width!=1924 or not rects: continue
        # Main map strips all span the same ~924pt width; ignore small inset images.
        r=rects[0]
        if r.width<900: continue
        strips.append((r.y0,r.y1,xref,pil, [r.x0,r.y0,r.x1,r.y1]))
    strips.sort(key=lambda t:t[0])
    if len(strips)!=6: raise RuntimeError(f'Expected 6 native map strips, found {[(x[2],x[3].size,x[4]) for x in strips]}')
    if len({im.width for _,_,_,im,_ in strips})!=1: raise RuntimeError('Native strip widths differ')
    mosaic=Image.new('RGB',(1924,sum(im.height for _,_,_,im,_ in strips)))
    y=0; manifest=[]
    for y0,y1,xref,im,rect in strips:
        mosaic.paste(im,(0,y)); manifest.append({'xref':xref,'size':[im.width,im.height],'pdf_rect':rect,'mosaic_y':[y,y+im.height]}); y+=im.height
    return np.asarray(mosaic),manifest


def classify(rgb):
    f=rgb.astype(np.float32); d=((f[:,:,None,:]-PALETTE[None,None,:,:])**2).sum(axis=3)**0.5
    cls=np.argmin(d,axis=2).astype(np.int8); md=d.min(axis=2)
    assigned=ndimage.binary_closing(md<52,structure=np.ones((3,3),bool),iterations=1)
    lab,n=ndimage.label(assigned); cnt=np.bincount(lab.ravel()); cnt[0]=0
    lake=lab==int(np.argmax(cnt)); lake=ndimage.binary_fill_holes(lake)
    valid=(md<60)&lake; _,inds=ndimage.distance_transform_edt(~valid,return_indices=True); filled=cls[inds[0],inds[1]]
    return np.where(lake,filled,-1).astype(np.int8),md,lake


def islands():
    if not ISLANDS.exists(): return None
    fc=json.loads(ISLANDS.read_text()); gs=[]
    for f in fc.get('features',[]):
        try:
            g=shape(f['geometry']).buffer(0)
            if not g.is_empty:gs.append(g)
        except Exception: pass
    return unary_union(gs).buffer(0) if gs else None


def mask_islands(classes,bbox):
    g=islands()
    if g is None or g.is_empty:return classes,0
    h,w=classes.shape
    xs=bbox['west']+(np.arange(w)+.5)/w*(bbox['east']-bbox['west'])
    ys=bbox['north']-(np.arange(h)+.5)/h*(bbox['north']-bbox['south'])
    removed=0
    for j0 in range(0,h,128):
        j1=min(h,j0+128); LAT,LON=np.meshgrid(ys[j0:j1],xs,indexing='ij'); m=contains_xy(g,LON,LAT); a=classes[j0:j1]; removed+=int(((a>=0)&m).sum()); a[m]=-1; classes[j0:j1]=a
    return classes,removed


def crop(classes,rgb,bbox,pad=8):
    yy,xx=np.where(classes>=0); h,w=classes.shape
    x0=max(0,int(xx.min())-pad); x1=min(w,int(xx.max())+1+pad); y0=max(0,int(yy.min())-pad); y1=min(h,int(yy.max())+1+pad)
    cb={'west':bbox['west']+x0/w*(bbox['east']-bbox['west']),'east':bbox['west']+x1/w*(bbox['east']-bbox['west']),
        'north':bbox['north']-y0/h*(bbox['north']-bbox['south']),'south':bbox['north']-y1/h*(bbox['north']-bbox['south'])}
    return classes[y0:y1,x0:x1],rgb[y0:y1,x0:x1],cb,[x0,y0,x1,y1]


def save_images(classes,native):
    good=classes>=0; h,w=classes.shape
    # Visible layer: native PDF pixels, transparent off-water. This preserves every source pixel and JPEG edge nuance.
    vis=np.zeros((h,w,4),dtype=np.uint8); vis[good,:3]=native[good]; vis[good,3]=255
    Image.fromarray(vis,'RGBA').save(OUT_VIS,'WEBP',lossless=True,method=6)
    # Hidden deterministic sampling layer: exact class RGBs.
    out=np.zeros((h,w,4),dtype=np.uint8); out[good,:3]=DISPLAY[classes[good]]; out[good,3]=255
    Image.fromarray(out,'RGBA').save(OUT_CLASS,'WEBP',lossless=True,method=6)


def save_contours(classes):
    h,w=classes.shape; paths=[]; total=0
    # Contour k is boundary of water depth >= k m. Marching squares gives half-pixel faithful geometry.
    for k in range(1,8):
        mask=(classes>=k).astype(np.uint8)
        for arr in find_contours(mask,.5,fully_connected='high'):
            if len(arr)<8: continue
            # arr is row,col. Round only to .1 source pixel (~0.6 m), no smoothing.
            pts=[(float(c),float(r)) for r,c in arr]
            d='M '+' L '.join(f'{x:.1f},{y:.1f}' for x,y in pts)
            paths.append(f'<path d="{d}" data-depth="{k}"/>'); total+=len(pts)
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" preserveAspectRatio="none"><g fill="none" stroke="#173d49" stroke-width="0.7" vector-effect="non-scaling-stroke" opacity="0.78" stroke-linejoin="round" stroke-linecap="round">{''.join(paths)}</g></svg>'''
    OUT_CONTOURS.write_text(svg,encoding='utf-8'); return len(paths),total


def main():
    raw=download(); doc=fitz.open(stream=raw,filetype='pdf'); bbox,pdf_bbox,gpts=parse_geo(doc); rgb,manifest=extract_native_mosaic(doc)
    classes,md,lake=classify(rgb); classes,removed=mask_islands(classes,bbox); cc,native,cb,crop_px=crop(classes,rgb,bbox)
    save_images(cc,native); npaths,npts=save_contours(cc)
    h,w=cc.shape; lat0=(cb['south']+cb['north'])/2
    mppx=(cb['east']-cb['west'])*111320*math.cos(math.radians(lat0))/w; mppy=(cb['north']-cb['south'])*111320/h
    vals=cc[cc>=0].astype(float); mean=float(np.mean(vals+.5)); counts={str(k):int((cc==k).sum()) for k in range(8)}
    if abs(mean-2.4)>.08: raise RuntimeError(f'QC failed: mean depth {mean:.3f}')
    meta={'version':'4.1','source':'Adour-Garonne FRFL49_Bathym GeoPDF native image strips','source_url':URL,'water_level_reference_ngf_m':13.21,
      'vertical_definition':'official 1 m classes','bbox':cb,'width':w,'height':h,'palette_rgb':DISPLAY.tolist(),
      'visual_image':'bathymetry-geopdf-v41-native.webp','class_image':'bathymetry-geopdf-v41-classes.webp','contours_svg':'bathymetry-geopdf-v41-contours.svg',
      'georef_method':'embedded GeoPDF GPTS/LPTS; native raster strips extracted without PDF rendering','native_resolution_m_per_px':[mppx,mppy]}
    OUT_META.write_text(json.dumps(meta,indent=2),encoding='utf-8')
    report={'version':'4.1','pdf_bbox':pdf_bbox,'gpts':gpts,'native_mosaic':[rgb.shape[1],rgb.shape[0]],'strip_manifest':manifest,'crop_px':crop_px,'output':meta,
      'class_pixels':counts,'water_pixels':int(len(vals)),'area_weighted_class_midpoint_mean_m':mean,'published_mean_depth_m':2.4,
      'island_pixels_removed':removed,'contour_paths':npaths,'contour_vertices':npts,'segmentation_rgb_distance':{'median':float(np.median(md[lake])),'p95':float(np.percentile(md[lake],95))},
      'note':'Visible layer keeps native source pixels. Separate class raster is used for GPS lookup. SVG contours are traced at native pixel boundaries without smoothing.'}
    OUT_REPORT.write_text(json.dumps(report,indent=2),encoding='utf-8'); print(json.dumps(report,indent=2))

if __name__=='__main__':main()
