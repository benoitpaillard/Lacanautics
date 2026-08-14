#!/usr/bin/env python3
"""Build Lacanautics v4 directly from the official Adour-Garonne GeoPDF."""
from __future__ import annotations

import json, math, re, ssl, urllib.request
from pathlib import Path

import fitz
import numpy as np
from PIL import Image
from scipy import ndimage
from shapely import contains_xy
from shapely.geometry import shape
from shapely.ops import unary_union

ROOT=Path('.')
URL='https://adour-garonne.eaufrance.fr/upload/DOC/FICHES/LACS/BATHYMETRIE/FRFL49_Bathym.pdf'
ISLANDS=ROOT/'data/lacanau_islands.geojson'
OUT_IMG=ROOT/'bathymetry-geopdf-v4.webp'
OUT_META=ROOT/'data/lacanau_geopdf_v4.json'
OUT_REPORT=ROOT/'data/lacanau_geopdf_v4_report.json'

PALETTE=np.asarray([
    [182,237,240], [145,205,237], [107,174,232], [61,144,227],
    [32,114,214], [32,76,189], [25,44,168], [9,9,145]
],dtype=np.float32)
DISPLAY=np.asarray([
    [217,246,242], [198,239,238], [175,229,236], [150,217,235],
    [97,185,230], [50,127,205], [49,88,180], [37,28,88]
],dtype=np.uint8)

PUBLISHED_MEAN_DEPTH_M=2.4


def download_pdf():
    ctx=ssl._create_unverified_context()
    req=urllib.request.Request(URL,headers={'User-Agent':'Lacanautics/4.0'})
    with urllib.request.urlopen(req,timeout=90,context=ctx) as r:
        return r.read()


def parse_geopdf(doc):
    page=doc[0]
    page_obj=doc.xref_object(page.xref,compressed=False)
    pairs=[]
    pat=r'/BBox\s*\[\s*([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s*\]\s*/Measure\s+(\d+)\s+0\s+R'
    for m in re.finditer(pat,page_obj,re.S):
        a,b,c,d=[float(x) for x in m.groups()[:4]]
        pairs.append({'pdf_bbox':[a,b,c,d],'measure_xref':int(m.group(5)),'area':abs(c-a)*abs(b-d)})
    if not pairs:
        raise RuntimeError('No GeoPDF viewport found')
    vp=max(pairs,key=lambda x:x['area'])
    mo=doc.xref_object(vp['measure_xref'],compressed=False)
    mg=re.search(r'/GPTS\s*\[([^\]]+)\]',mo,re.S)
    if not mg:
        raise RuntimeError('GeoPDF GPTS not found')
    vals=[float(v) for v in re.findall(r'[-+]?\d+(?:\.\d+)?',mg.group(1))]
    if len(vals)!=8:
        raise RuntimeError(f'Unexpected GPTS {vals}')
    pts=[(vals[i],vals[i+1]) for i in range(0,8,2)]
    lats=[p[0] for p in pts]; lons=[p[1] for p in pts]
    a,b,c,d=vp['pdf_bbox']
    clip=fitz.Rect(min(a,c),page.rect.height-max(b,d),max(a,c),page.rect.height-min(b,d))
    return {
        'viewport_pdf_bbox':vp['pdf_bbox'],
        'viewport_clip':[clip.x0,clip.y0,clip.x1,clip.y1],
        'gpts_latlon':pts,
        'bbox':{'west':min(lons),'south':min(lats),'east':max(lons),'north':max(lats)},
        'clip':clip,
    }


def native_render(page,clip):
    target_w=1924
    zoom=target_w/clip.width
    pix=page.get_pixmap(matrix=fitz.Matrix(zoom,zoom),clip=clip,alpha=False)
    return np.asarray(Image.frombytes('RGB',[pix.width,pix.height],pix.samples)), {
        'width':pix.width,'height':pix.height,'zoom':zoom
    }


def segment(rgb):
    f=rgb.astype(np.float32)
    dist=np.empty((rgb.shape[0],rgb.shape[1],8),dtype=np.float32)
    for k,p in enumerate(PALETTE):
        d=f-p[None,None,:]
        dist[:,:,k]=np.sqrt(np.sum(d*d,axis=2,dtype=np.float32))
    cls=np.argmin(dist,axis=2).astype(np.int8)
    md=np.min(dist,axis=2)

    assigned=ndimage.binary_closing(md<48.0,structure=np.ones((3,3),bool),iterations=1)
    lab,_=ndimage.label(assigned)
    counts=np.bincount(lab.ravel())
    if len(counts)<=1:
        raise RuntimeError('Could not identify bathymetry components')
    counts[0]=0
    if counts.max()<10000:
        raise RuntimeError('Could not identify lake bathymetry')

    lake=lab==int(np.argmax(counts))
    # Fill small cartographic gaps, but not arbitrarily every enclosed land hole.
    closed=ndimage.binary_closing(lake,structure=np.ones((5,5),bool),iterations=2)
    holes=closed & ~lake
    hl,n=ndimage.label(holes)
    hc=np.bincount(hl.ravel()) if n else np.array([0])
    small=np.zeros_like(lake)
    for i in range(1,len(hc)):
        if hc[i] <= 900:
            small |= hl==i
    lake |= small

    valid=(md<58.0)&lake
    _,inds=ndimage.distance_transform_edt(~valid,return_indices=True)
    filled=cls[inds[0],inds[1]]
    classes=np.where(lake,filled,-1).astype(np.int8)
    return classes,md


def island_union():
    if not ISLANDS.exists():
        return None
    fc=json.loads(ISLANDS.read_text(encoding='utf-8')); gs=[]
    for f in fc.get('features',[]):
        try:
            g=shape(f['geometry']).buffer(0)
            if not g.is_empty:
                gs.append(g)
        except Exception:
            pass
    return unary_union(gs).buffer(0) if gs else None


def apply_islands(classes,bbox):
    isl=island_union()
    if isl is None or isl.is_empty:
        return classes,0
    h,w=classes.shape
    xs=np.linspace(bbox['west'],bbox['east'],w,endpoint=False)+(bbox['east']-bbox['west'])/(2*w)
    ys=np.linspace(bbox['north'],bbox['south'],h,endpoint=False)-(bbox['north']-bbox['south'])/(2*h)
    masked=0
    for j0 in range(0,h,128):
        j1=min(h,j0+128)
        LAT,LON=np.meshgrid(ys[j0:j1],xs,indexing='ij')
        m=contains_xy(isl,LON,LAT)
        a=classes[j0:j1]
        masked+=int(((a>=0)&m).sum())
        a[m]=-1
        classes[j0:j1]=a
    return classes,masked


def crop_and_georef(classes,bbox,pad=8):
    yy,xx=np.where(classes>=0)
    if not len(xx):
        raise RuntimeError('No bathymetry pixels after segmentation')
    h,w=classes.shape
    x0=max(0,int(xx.min())-pad); x1=min(w,int(xx.max())+1+pad)
    y0=max(0,int(yy.min())-pad); y1=min(h,int(yy.max())+1+pad)
    west=bbox['west']+(x0/w)*(bbox['east']-bbox['west'])
    east=bbox['west']+(x1/w)*(bbox['east']-bbox['west'])
    north=bbox['north']-(y0/h)*(bbox['north']-bbox['south'])
    south=bbox['north']-(y1/h)*(bbox['north']-bbox['south'])
    return classes[y0:y1,x0:x1], {'west':west,'south':south,'east':east,'north':north}, [x0,y0,x1,y1]


def save_rgba(classes):
    h,w=classes.shape
    rgba=np.zeros((h,w,4),dtype=np.uint8)
    good=classes>=0
    rgba[good,:3]=DISPLAY[classes[good]]
    rgba[good,3]=255
    Image.fromarray(rgba,'RGBA').save(OUT_IMG,'WEBP',lossless=True,method=6)


def main():
    raw=download_pdf()
    doc=fitz.open(stream=raw,filetype='pdf')
    geo=parse_geopdf(doc)
    rgb,render=native_render(doc[0],geo['clip'])
    classes,md=segment(rgb)
    pre_island_water=classes>=0
    classes,masked=apply_islands(classes,geo['bbox'])
    cropped,cb,crop_px=crop_and_georef(classes,geo['bbox'])

    vals=cropped[cropped>=0]
    class_mid_mean=float(np.mean(vals.astype(np.float32)+0.5))
    # Fail closed if extraction is visibly inconsistent with the published Lacanau mean depth.
    if abs(class_mid_mean-PUBLISHED_MEAN_DEPTH_M)>0.35:
        raise RuntimeError(f'QC failed: reconstructed mean {class_mid_mean:.3f} m vs published {PUBLISHED_MEAN_DEPTH_M:.2f} m')
    deep_frac=float(np.mean(vals==7))
    if deep_frac>0.02:
        raise RuntimeError(f'QC failed: 7–8 m class occupies implausible {100*deep_frac:.2f}% of water area')

    save_rgba(cropped)
    h,w=cropped.shape
    lat0=(cb['south']+cb['north'])/2
    mppx=(cb['east']-cb['west'])*111320*math.cos(math.radians(lat0))/w
    mppy=(cb['north']-cb['south'])*111320/h
    counts={str(k):int((cropped==k).sum()) for k in range(8)}

    meta={
        'version':'4.0',
        'source_url':URL,
        'source':'Adour-Garonne FRFL49_Bathym GeoPDF',
        'creator':doc.metadata.get('creator'),
        'water_level_reference_ngf_m':13.21,
        'vertical_definition':'official 1 m classes: 0=0–1 m ... 7=7–8 m',
        'bbox':cb,
        'width':w,
        'height':h,
        'palette_rgb':DISPLAY.tolist(),
        'georef_method':'embedded GeoPDF GPTS/LPTS; no manual calibration',
        'native_resolution_m_per_px':[mppx,mppy],
    }
    OUT_META.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')

    good_md=md[pre_island_water]
    report={
        'version':'4.0',
        'pdf_bytes':len(raw),
        'pdf_metadata':doc.metadata,
        'geopdf':{k:v for k,v in geo.items() if k!='clip'},
        'render':render,
        'crop_px':crop_px,
        'output':meta,
        'class_pixels':counts,
        'water_pixels':int(len(vals)),
        'area_weighted_class_midpoint_mean_m':class_mid_mean,
        'published_mean_depth_m':PUBLISHED_MEAN_DEPTH_M,
        'deepest_class_fraction':deep_frac,
        'osm_island_pixels_removed':masked,
        'segmentation_distance':{
            'median_rgb_distance':float(np.median(good_md)),
            'p95_rgb_distance':float(np.percentile(good_md,95)),
        },
        'warning':'Official cartographic depth classes, not raw soundings. Not a certified navigation chart.',
    }
    OUT_REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
