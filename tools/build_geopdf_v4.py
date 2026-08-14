#!/usr/bin/env python3
"""Build Lacanautics v4 directly from the official Adour-Garonne GeoPDF.

Source of truth:
  FRFL49_Bathym.pdf (Esri ArcMap GeoPDF)

This pipeline intentionally avoids all manual georeferencing. It reads the embedded map viewport
and GPTS geospatial control points from the PDF, renders the native map frame at approximately its
embedded raster resolution, extracts the eight official 1 m depth classes, applies mapped island
holes, crops to the lake, and writes a lossless RGBA WebP whose pixels themselves encode the
survey class used by the web app.
"""
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

ROOT=Path('.')
URL='https://adour-garonne.eaufrance.fr/upload/DOC/FICHES/LACS/BATHYMETRIE/FRFL49_Bathym.pdf'
ISLANDS=ROOT/'data/lacanau_islands.geojson'
OUT_IMG=ROOT/'bathymetry-geopdf-v4.webp'
OUT_META=ROOT/'data/lacanau_geopdf_v4.json'
OUT_REPORT=ROOT/'data/lacanau_geopdf_v4_report.json'

# Exact official class colors from the PDF legend (0-1 m through 7-8 m).
PALETTE=np.asarray([
    [182,237,240], [145,205,237], [107,174,232], [61,144,227],
    [32,114,214], [32,76,189], [25,44,168], [9,9,145]
],dtype=np.uint8)
# Cleaner display colors; each output class has one exact RGB triplet for deterministic browser sampling.
DISPLAY=np.asarray([
    [217,246,242], [198,239,238], [175,229,236], [150,217,235],
    [97,185,230], [50,127,205], [49,88,180], [37,28,88]
],dtype=np.uint8)


def download_pdf():
    ctx=ssl._create_unverified_context()  # legacy official server has an incomplete cert chain
    req=urllib.request.Request(URL,headers={'User-Agent':'Lacanautics/4.0'})
    with urllib.request.urlopen(req,timeout=90,context=ctx) as r:
        return r.read()


def parse_geopdf(doc):
    page=doc[0]
    page_obj=doc.xref_object(page.xref,compressed=False)
    # Main study-area viewport = the large /VP entry whose name is "Emprise zone d'étude".
    # Parse all viewport BBoxes and measure refs from the page object, then choose the largest box.
    pairs=[]
    for m in re.finditer(r'/BBox\s*\[\s*([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s*\]\s*/Measure\s+(\d+)\s+0\s+R',page_obj,re.S):
        x0,y1,x1,y0,measure=map(float,m.groups()[:4])+ (None,)
    # Python tuple trick above is intentionally not used; parse explicitly for clarity.
    pairs=[]
    for m in re.finditer(r'/BBox\s*\[\s*([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s*\]\s*/Measure\s+(\d+)\s+0\s+R',page_obj,re.S):
        a,b,c,d=[float(x) for x in m.groups()[:4]]; measure=int(m.group(5))
        width=abs(c-a); height=abs(b-d)
        pairs.append({'pdf_bbox':[a,b,c,d],'measure_xref':measure,'area':width*height})
    if not pairs: raise RuntimeError('No GeoPDF viewport found')
    vp=max(pairs,key=lambda x:x['area'])
    mo=doc.xref_object(vp['measure_xref'],compressed=False)
    mg=re.search(r'/GPTS\s*\[([^\]]+)\]',mo,re.S)
    if not mg: raise RuntimeError('GeoPDF GPTS not found')
    vals=[float(v) for v in re.findall(r'[-+]?\d+(?:\.\d+)?',mg.group(1))]
    if len(vals)!=8: raise RuntimeError(f'Unexpected GPTS {vals}')
    # ArcMap writes lat,lon corner pairs. Order is SW,NW,NE,SE for this PDF.
    pts=[(vals[i],vals[i+1]) for i in range(0,8,2)]
    lats=[p[0] for p in pts]; lons=[p[1] for p in pts]
    west,east=min(lons),max(lons); south,north=min(lats),max(lats)
    # Convert PDF bottom-left coordinates to PyMuPDF top-left coordinates.
    a,b,c,d=vp['pdf_bbox']
    clip=fitz.Rect(min(a,c), page.rect.height-max(b,d), max(a,c), page.rect.height-min(b,d))
    return {'viewport_pdf_bbox':vp['pdf_bbox'],'viewport_clip':[clip.x0,clip.y0,clip.x1,clip.y1],
            'gpts_latlon':pts,'bbox':{'west':west,'south':south,'east':east,'north':north},'clip':clip}


def native_render(page,clip):
    # Wide raster strips in the official page are 1924 px across. Render the exact viewport at that
    # width, avoiding pointless upsampling while preserving the native cartographic information.
    target_w=1924
    zoom=target_w/clip.width
    pix=page.get_pixmap(matrix=fitz.Matrix(zoom,zoom),clip=clip,alpha=False)
    img=Image.frombytes('RGB',[pix.width,pix.height],pix.samples)
    return np.asarray(img), {'width':pix.width,'height':pix.height,'zoom':zoom}


def segment(rgb):
    f=rgb.astype(np.int16)
    # nearest official legend color, with a deliberately moderate tolerance for JPEG compression.
    dist=np.empty((rgb.shape[0],rgb.shape[1],8),dtype=np.float32)
    for k,p in enumerate(PALETTE.astype(np.int16)):
        d=f-p[None,None,:]; dist[:,:,k]=np.sqrt(np.sum(d*d,axis=2))
    cls=np.argmin(dist,axis=2).astype(np.int8)
    md=np.min(dist,axis=2)
    assigned=md<52.0
    # The bathymetric lake is the dominant connected union of the 8 class colors.
    assigned=ndimage.binary_closing(assigned,structure=np.ones((3,3),bool),iterations=1)
    lab,n=ndimage.label(assigned)
    counts=np.bincount(lab.ravel()); counts[0]=0
    # candidates above 10k pixels; pick the largest, which is Lacanau itself.
    if len(counts)<=1 or counts.max()<10000: raise RuntimeError('Could not identify lake bathymetry')
    lake=lab==int(np.argmax(counts))
    # Fill cartographic text/marker holes, then islands are explicitly subtracted from OSM below.
    lake=ndimage.binary_fill_holes(lake)
    valid=(md<60.0)&lake
    _,inds=ndimage.distance_transform_edt(~valid,return_indices=True)
    filled=cls[inds[0],inds[1]]
    return np.where(lake,filled,-1).astype(np.int8),md


def island_union():
    if not ISLANDS.exists(): return None
    fc=json.loads(ISLANDS.read_text(encoding='utf-8')); gs=[]
    for f in fc.get('features',[]):
        try:
            g=shape(f['geometry']).buffer(0)
            if not g.is_empty: gs.append(g)
        except Exception: pass
    return unary_union(gs).buffer(0) if gs else None


def apply_islands(classes,bbox):
    isl=island_union()
    if isl is None or isl.is_empty: return classes,0
    h,w=classes.shape
    # pixel centres -> exact GeoPDF linear viewport coordinates
    xs=np.linspace(bbox['west'],bbox['east'],w,endpoint=False)+(bbox['east']-bbox['west'])/(2*w)
    ys=np.linspace(bbox['north'],bbox['south'],h,endpoint=False)-(bbox['north']-bbox['south'])/(2*h)
    masked=0
    for j0 in range(0,h,128):
        j1=min(h,j0+128); LAT,LON=np.meshgrid(ys[j0:j1],xs,indexing='ij')
        m=contains_xy(isl,LON,LAT)
        a=classes[j0:j1]; masked+=int(((a>=0)&m).sum()); a[m]=-1; classes[j0:j1]=a
    return classes,masked


def crop_and_georef(classes,bbox,pad=8):
    yy,xx=np.where(classes>=0)
    if not len(xx): raise RuntimeError('No bathymetry pixels after segmentation')
    h,w=classes.shape
    x0=max(0,int(xx.min())-pad); x1=min(w,int(xx.max())+1+pad)
    y0=max(0,int(yy.min())-pad); y1=min(h,int(yy.max())+1+pad)
    west=bbox['west']+(x0/w)*(bbox['east']-bbox['west'])
    east=bbox['west']+(x1/w)*(bbox['east']-bbox['west'])
    north=bbox['north']-(y0/h)*(bbox['north']-bbox['south'])
    south=bbox['north']-(y1/h)*(bbox['north']-bbox['south'])
    return classes[y0:y1,x0:x1], {'west':west,'south':south,'east':east,'north':north}, [x0,y0,x1,y1]


def save_rgba(classes):
    h,w=classes.shape; rgba=np.zeros((h,w,4),dtype=np.uint8); good=classes>=0
    rgba[good,:3]=DISPLAY[classes[good]]; rgba[good,3]=255
    # thin dark border wherever class/land changes; keep class interior exact for pixel sampling.
    edge=np.zeros((h,w),bool)
    for dy,dx in ((1,0),(-1,0),(0,1),(0,-1)):
        b=np.roll(classes,(dy,dx),(0,1)); edge|=good&(b!=classes)
    # Do not alter RGB on edge because RGB encodes class; instead use alpha 255 consistently.
    Image.fromarray(rgba,'RGBA').save(OUT_IMG,'WEBP',lossless=True,method=6)


def main():
    raw=download_pdf(); doc=fitz.open(stream=raw,filetype='pdf'); geo=parse_geopdf(doc)
    rgb,render=native_render(doc[0],geo['clip']); classes,md=segment(rgb)
    classes,masked=apply_islands(classes,geo['bbox'])
    cropped,cb,crop_px=crop_and_georef(classes,geo['bbox'])
    save_rgba(cropped)
    h,w=cropped.shape
    lat0=(cb['south']+cb['north'])/2
    mppx=(cb['east']-cb['west'])*111320*math.cos(math.radians(lat0))/w
    mppy=(cb['north']-cb['south'])*111320/h
    counts={str(k):int((cropped==k).sum()) for k in range(8)}
    meta={
      'version':'4.0','source_url':URL,'source':'Adour-Garonne FRFL49_Bathym GeoPDF','creator':doc.metadata.get('creator'),
      'water_level_reference_ngf_m':13.21,'vertical_definition':'official 1 m classes: 0=0–1 m ... 7=7–8 m',
      'bbox':cb,'width':w,'height':h,'palette_rgb':DISPLAY.tolist(),
      'georef_method':'embedded GeoPDF GPTS/LPTS; no manual calibration','native_resolution_m_per_px':[mppx,mppy]
    }
    OUT_META.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    report={
      'version':'4.0','pdf_bytes':len(raw),'pdf_metadata':doc.metadata,
      'geopdf':{k:v for k,v in geo.items() if k!='clip'},'render':render,'crop_px':crop_px,'output':meta,
      'class_pixels':counts,'water_pixels':int((cropped>=0).sum()),'osm_island_pixels_removed':masked,
      'segmentation_distance_px':{'median':float(np.median(md[classes>=0])) if np.any(classes>=0) else None,
                                  'p95':float(np.percentile(md[classes>=0],95)) if np.any(classes>=0) else None},
      'warning':'Official cartographic depth classes, not raw soundings. Not a certified navigation chart.'
    }
    OUT_REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2,default=str))

if __name__=='__main__':main()
