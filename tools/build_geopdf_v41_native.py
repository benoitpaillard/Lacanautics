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
    req=urllib.request.Request(URL,headers={'User-Agent':'Lacanautics/4.1-fixed'})
    with urllib.request.urlopen(req,timeout=90,context=ctx) as r:return r.read()


def parse_geo(doc):
    p=doc[0]; obj=doc.xref_object(p.xref,compressed=False); vps=[]
    for m in re.finditer(r'/BBox\s*\[\s*([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s*\]\s*/Measure\s+(\d+)\s+0\s+R',obj,re.S):
        a,b,c,d=[float(x) for x in m.groups()[:4]]; xref=int(m.group(5)); vps.append((abs(c-a)*abs(b-d),[a,b,c,d],xref))
    _,pb,xref=max(vps,key=lambda t:t[0]); mo=doc.xref_object(xref,compressed=False); mg=re.search(r'/GPTS\s*\[([^\]]+)\]',mo,re.S)
    vals=[float(v) for v in re.findall(r'[-+]?\d+(?:\.\d+)?',mg.group(1))]; pts=[(vals[i],vals[i+1]) for i in range(0,8,2)]
    lats=[a for a,b in pts]; lons=[b for a,b in pts]
    return {'west':min(lons),'south':min(lats),'east':max(lons),'north':max(lats)},pb,pts


def extract_native_mosaic(doc,view_bbox,pdf_bbox):
    """Reconstruct the map exactly as ArcMap placed its six native strips.

    Two details matter:
    * every PDF image placement has a negative vertical matrix, therefore the extracted image bytes
      must be flipped top-to-bottom before compositing;
    * adjacent 273 px strips overlap by one source row. Their top positions are 272 px apart, so
      simple concatenation duplicates five rows and distorts/shuffles the lake.
    """
    p=doc[0]; strips=[]
    for img in p.get_images(full=True):
        xref=img[0]; info=doc.extract_image(xref); pil=Image.open(io.BytesIO(info['image'])).convert('RGB')
        rects=p.get_image_rects(xref)
        if pil.width!=1924 or not rects: continue
        r=rects[0]
        if r.width<900: continue
        strips.append({'y0':r.y0,'y1':r.y1,'x0':r.x0,'x1':r.x1,'xref':xref,'im':pil,'rect':[r.x0,r.y0,r.x1,r.y1]})
    strips.sort(key=lambda s:s['y0'])
    if len(strips)!=6: raise RuntimeError(f'Expected 6 native map strips, found {[(s["xref"],s["im"].size,s["rect"]) for s in strips]}')

    # Native scale from the actual PDF placements. All six strips use the same scale.
    sx=np.median([(s['x1']-s['x0'])/s['im'].width for s in strips])
    sy=np.median([(s['y1']-s['y0'])/s['im'].height for s in strips])
    top=min(s['y0'] for s in strips); left=min(s['x0'] for s in strips); right=max(s['x1'] for s in strips); bottom=max(s['y1'] for s in strips)
    offsets=[int(round((s['y0']-top)/sy)) for s in strips]
    out_h=max(off+s['im'].height for off,s in zip(offsets,strips))
    mosaic=Image.new('RGB',(1924,out_h))
    manifest=[]
    for off,s in zip(offsets,strips):
        # Required by the negative vertical PDF image transform.
        im=s['im'].transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        mosaic.paste(im,(0,off))
        manifest.append({'xref':s['xref'],'size':[im.width,im.height],'pdf_rect':s['rect'],'mosaic_y':[off,off+im.height],'flipped_y':True})

    # The image strips are slightly inset from the geospatial viewport. Map their actual placement,
    # not the whole viewport, to WGS84.
    vx0,vy_a,vx1,vy_b=pdf_bbox
    vleft=min(vx0,vx1); vright=max(vx0,vx1)
    vtop=p.rect.height-max(vy_a,vy_b); vbottom=p.rect.height-min(vy_a,vy_b)
    fx0=(left-vleft)/(vright-vleft); fx1=(right-vleft)/(vright-vleft)
    fy0=(top-vtop)/(vbottom-vtop); fy1=(bottom-vtop)/(vbottom-vtop)
    image_bbox={
      'west':view_bbox['west']+fx0*(view_bbox['east']-view_bbox['west']),
      'east':view_bbox['west']+fx1*(view_bbox['east']-view_bbox['west']),
      'north':view_bbox['north']-fy0*(view_bbox['north']-view_bbox['south']),
      'south':view_bbox['north']-fy1*(view_bbox['north']-view_bbox['south'])
    }
    stitch={'pixel_scale_pdf_pt':[float(sx),float(sy)],'native_offsets_y':offsets,'stitched_height':out_h,'expected_simple_concat_height':sum(s['im'].height for s in strips),'overlap_rows_removed':sum(s['im'].height for s in strips)-out_h}
    return np.asarray(mosaic),manifest,image_bbox,stitch


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
    vis=np.zeros((h,w,4),dtype=np.uint8); vis[good,:3]=native[good]; vis[good,3]=255
    Image.fromarray(vis,'RGBA').save(OUT_VIS,'WEBP',lossless=True,method=6)
    out=np.zeros((h,w,4),dtype=np.uint8); out[good,:3]=DISPLAY[classes[good]]; out[good,3]=255
    Image.fromarray(out,'RGBA').save(OUT_CLASS,'WEBP',lossless=True,method=6)


def save_contours(classes):
    h,w=classes.shape; paths=[]; total=0
    for k in range(1,8):
        mask=(classes>=k).astype(np.uint8)
        for arr in find_contours(mask,.5,fully_connected='high'):
            if len(arr)<8: continue
            pts=[(float(c),float(r)) for r,c in arr]
            d='M '+' L '.join(f'{x:.1f},{y:.1f}' for x,y in pts)
            paths.append(f'<path d="{d}" data-depth="{k}"/>'); total+=len(pts)
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" preserveAspectRatio="none"><g fill="none" stroke="#173d49" stroke-width="0.7" vector-effect="non-scaling-stroke" opacity="0.78" stroke-linejoin="round" stroke-linecap="round">{''.join(paths)}</g></svg>'''
    OUT_CONTOURS.write_text(svg,encoding='utf-8'); return len(paths),total


def compare_v3(classes,bbox):
    p=ROOT/'data/lacanau_2012_bands_v3.json'
    if not p.exists(): return None
    v=json.loads(p.read_text()); vb=v['bbox']; rows=v['rows_south_to_north']; nx=v['nx']; ny=v['ny']; h,w=classes.shape
    exact=within=tot=0; err=0.0
    for iy in range(0,ny,2):
        lat=vb['south']+(iy+.5)/ny*(vb['north']-vb['south']); row=rows[iy]
        if not (bbox['south']<=lat<=bbox['north']): continue
        py=int(np.clip((bbox['north']-lat)/(bbox['north']-bbox['south'])*h,0,h-1))
        for ix in range(0,nx,2):
            ch=row[ix]
            if ch=='.': continue
            lon=vb['west']+(ix+.5)/nx*(vb['east']-vb['west'])
            if not (bbox['west']<=lon<=bbox['east']): continue
            px=int(np.clip((lon-bbox['west'])/(bbox['east']-bbox['west'])*w,0,w-1)); pred=int(classes[py,px])
            if pred<0: continue
            d=abs(pred-int(ch)); tot+=1; exact+=d==0; within+=d<=1; err+=d
    return {'n':tot,'exact_fraction':exact/tot if tot else None,'within_1m_band_fraction':within/tot if tot else None,'mean_abs_class_difference':err/tot if tot else None}


def main():
    raw=download(); doc=fitz.open(stream=raw,filetype='pdf'); view_bbox,pdf_bbox,gpts=parse_geo(doc)
    rgb,manifest,image_bbox,stitch=extract_native_mosaic(doc,view_bbox,pdf_bbox)
    classes,md,lake=classify(rgb); classes,removed=mask_islands(classes,image_bbox); cc,native,cb,crop_px=crop(classes,rgb,image_bbox)
    save_images(cc,native); npaths,npts=save_contours(cc)
    h,w=cc.shape; lat0=(cb['south']+cb['north'])/2
    mppx=(cb['east']-cb['west'])*111320*math.cos(math.radians(lat0))/w; mppy=(cb['north']-cb['south'])*111320/h
    vals=cc[cc>=0].astype(float); mean=float(np.mean(vals+.5)); counts={str(k):int((cc==k).sum()) for k in range(8)}
    if abs(mean-2.4)>.08: raise RuntimeError(f'QC failed: mean depth {mean:.3f}')
    v3cmp=compare_v3(cc,cb)
    if v3cmp and (v3cmp['within_1m_band_fraction'] or 0)<.90: raise RuntimeError(f'QC failed against v3.1: {v3cmp}')
    meta={'version':'4.1-fixed','source':'Adour-Garonne FRFL49_Bathym GeoPDF native image strips','source_url':URL,'water_level_reference_ngf_m':13.21,
      'vertical_definition':'official 1 m classes','bbox':cb,'width':w,'height':h,'palette_rgb':DISPLAY.tolist(),
      'visual_image':'bathymetry-geopdf-v41-native.webp','class_image':'bathymetry-geopdf-v41-classes.webp','contours_svg':'bathymetry-geopdf-v41-contours.svg',
      'georef_method':'embedded GeoPDF GPTS/LPTS + exact native image placement; each strip vertically flipped per PDF matrix; 1-row strip overlaps stitched','native_resolution_m_per_px':[mppx,mppy]}
    OUT_META.write_text(json.dumps(meta,indent=2),encoding='utf-8')
    report={'version':'4.1-fixed','pdf_bbox':pdf_bbox,'gpts':gpts,'view_bbox':view_bbox,'native_image_bbox':image_bbox,'native_mosaic':[rgb.shape[1],rgb.shape[0]],'stitch':stitch,'strip_manifest':manifest,'crop_px':crop_px,'output':meta,
      'class_pixels':counts,'water_pixels':int(len(vals)),'area_weighted_class_midpoint_mean_m':mean,'published_mean_depth_m':2.4,'comparison_to_v3_1':v3cmp,
      'island_pixels_removed':removed,'contour_paths':npaths,'contour_vertices':npts,'segmentation_rgb_distance':{'median':float(np.median(md[lake])),'p95':float(np.percentile(md[lake],95))},
      'note':'Corrected native GeoPDF reconstruction. Visible layer keeps native pixels; contours are generated but not required for the default UI.'}
    OUT_REPORT.write_text(json.dumps(report,indent=2),encoding='utf-8'); print(json.dumps(report,indent=2))

if __name__=='__main__':main()
