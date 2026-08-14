#!/usr/bin/env python3
"""Build a high-definition Lacanautics layer from the published Aquabio 2012 map.

Philosophy:
- horizontal shapes come from the original 2048x1448 published 2012 map;
- vertical information remains the published 1 m class (0-1, ..., 7-8 m), not invented 0.5 m contours;
- the existing 2008 OFB WGS84 soundings are used only to optimize/validate a small georeferencing
  correction and a possible global level offset;
- mapped OSM islands are removed from the output.

Outputs:
  bathymetry-2012-v3.webp          clean high-resolution class raster
  data/lacanau_2012_bands_v3.json compact 10 m depth-band lookup grid
  data/lacanau_2012_hybrid_report.json calibration/QC report
"""
from __future__ import annotations

import json, math
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.optimize import differential_evolution, minimize
from shapely.geometry import shape
from shapely.ops import unary_union
from shapely import contains_xy

ROOT=Path('.')
IMG_PATH=ROOT/'data/lacanau_2012_best.png'
SOUND_PATH=ROOT/'data/lacanau_soundings.geojson'
ISLAND_PATH=ROOT/'data/lacanau_islands.geojson'
V2_GRID=ROOT/'data/lacanau_depth_grid_v2.json'
OUT_IMG=ROOT/'bathymetry-2012-v3.webp'
OUT_GRID=ROOT/'data/lacanau_2012_bands_v3.json'
OUT_REPORT=ROOT/'data/lacanau_2012_hybrid_report.json'

# Initial manual calibration from the original 1024x724 publication.
G_LON_W,G_LON_E=-1.14573,-1.09121
G_X_W,G_X_E=436.0,735.0
G_LAT_N,G_LAT_S=45.00505,44.93401
G_Y_N,G_Y_S=110.0,676.0

# Legend patch centres measured on the 1024x724 publication. They are scaled automatically.
LEGEND_X=37.0
LEGEND_Y=[475.0,498.0,522.0,546.0,570.0,594.0,618.0,642.0]
# Display palette deliberately close to the printed map but cleaner and higher contrast.
DISPLAY=np.asarray([
 [207,244,242],[174,229,238],[126,199,232],[80,163,218],
 [48,129,203],[45,91,181],[42,61,158],[30,28,126]
],dtype=np.uint8)


def load_palette(rgb):
    h,w,_=rgb.shape; sx=w/1024.0; sy=h/724.0
    pals=[]
    for yb in LEGEND_Y:
        x=int(round(LEGEND_X*sx)); y=int(round(yb*sy))
        rx=max(3,int(round(4*sx))); ry=max(3,int(round(4*sy)))
        patch=rgb[max(0,y-ry):min(h,y+ry+1),max(0,x-rx):min(w,x+rx+1)]
        pals.append(np.median(patch.reshape(-1,3),axis=0))
    return np.asarray(pals,dtype=np.float32)


def segment_classes(rgb,palette):
    h,w,_=rgb.shape
    cls=np.empty((h,w),dtype=np.int8); mind=np.empty((h,w),dtype=np.float32)
    f=rgb.astype(np.float32)
    for y0 in range(0,h,128):
        y1=min(h,y0+128); a=f[y0:y1,:,None,:]
        d=np.sum((a-palette[None,None,:,:])**2,axis=3)
        cls[y0:y1]=np.argmin(d,axis=2).astype(np.int8)
        mind[y0:y1]=np.sqrt(np.min(d,axis=2))
    # Flat printed colours remain quite close after WEBP compression. Restrict to the largest
    # connected colour component to eliminate legend/map-of-France/background blue pixels.
    assigned=mind<58.0
    lab,n=ndimage.label(assigned)
    if n<1: raise RuntimeError('No bathymetric colour component found')
    counts=np.bincount(lab.ravel()); counts[0]=0; main=int(np.argmax(counts))
    lake0=lab==main
    # Close tiny compression gaps and fill text/marker holes. True islands are re-applied from OSM.
    lake=ndimage.binary_closing(lake0,structure=np.ones((5,5),bool),iterations=1)
    lake=ndimage.binary_fill_holes(lake)
    valid=assigned & lake
    if valid.sum()<10000: raise RuntimeError(f'Bathymetric segmentation too small: {valid.sum()} px')
    # Nearest printed-class fill for red/purple markers and anti-aliased gaps inside water.
    _,inds=ndimage.distance_transform_edt(~valid,return_indices=True)
    filled=cls[inds[0],inds[1]]
    return np.where(lake,filled,-1).astype(np.int8),lake,mind


def soundings():
    fc=json.loads(SOUND_PATH.read_text())
    out=[]
    for f in fc['features']:
        lon,lat=map(float,f['geometry']['coordinates']); d=float(f['properties']['depth_m'])
        if 0<=d<=8: out.append((lon,lat,d))
    a=np.asarray(out,float)
    # Spatial thinning avoids dense repeated sonar tracks dominating the affine calibration.
    lat0=float(np.median(a[:,1])); mx=111320*math.cos(math.radians(lat0)); my=111320
    bx=np.floor((a[:,0]-a[:,0].min())*mx/30).astype(int)
    by=np.floor((a[:,1]-a[:,1].min())*my/30).astype(int)
    groups={}
    for row,x,y in zip(a,bx,by): groups.setdefault((x,y),[]).append(row)
    thin=[]
    for rows in groups.values():
        r=np.asarray(rows); thin.append([np.median(r[:,0]),np.median(r[:,1]),np.median(r[:,2])])
    return a,np.asarray(thin,float)


def initial_px(lon,lat,w,h):
    sx=w/1024.0; sy=h/724.0
    x=(G_X_W+(lon-G_LON_W)*(G_X_E-G_X_W)/(G_LON_E-G_LON_W))*sx
    y=(G_Y_N+(G_LAT_N-lat)*(G_Y_S-G_Y_N)/(G_LAT_N-G_LAT_S))*sy
    return x,y


def transform_from_initial(x0,y0,p,cx,cy):
    dx,dy,sx,sy,theta,_off=p; c=math.cos(theta); s=math.sin(theta)
    X=x0-cx; Y=y0-cy
    x=c*sx*X-s*sy*Y+cx+dx
    y=s*sx*X+c*sy*Y+cy+dy
    return x,y


def sample_classes(class_src,x,y):
    h,w=class_src.shape; xi=np.rint(x).astype(int); yi=np.rint(y).astype(int)
    ok=(xi>=0)&(xi<w)&(yi>=0)&(yi<h)
    val=np.full(len(xi),-1,dtype=np.int16)
    q=np.flatnonzero(ok); val[q]=class_src[yi[q],xi[q]]
    return val


def calibrate(class_src,thin,w,h):
    lon,lat,d=thin[:,0],thin[:,1],thin[:,2]
    x0,y0=initial_px(lon,lat,w,h); cx=float(np.median(x0)); cy=float(np.median(y0))
    def loss(p):
        x,y=transform_from_initial(x0,y0,p,cx,cy); k=sample_classes(class_src,x,y)
        ok=k>=0
        valid=float(ok.mean())
        if valid<0.5:return 10+(0.5-valid)*20
        da=d+p[5]; lo=k[ok].astype(float); hi=lo+1.0; q=da[ok]
        err=np.maximum(lo-q,0)+np.maximum(q-hi,0)
        # robust interval error + invalid positioning + weak prior around original georef
        robust=np.mean(np.where(err<0.5,err*err,0.25+(err-0.5)*0.5))
        dx,dy,sx,sy,theta,off=p
        reg=0.002*((dx/30)**2+(dy/30)**2)+0.03*((sx-1)/0.025)**2+0.03*((sy-1)/0.025)**2+0.015*(theta/0.025)**2+0.002*(off/0.5)**2
        return robust+0.7*(1-valid)+reg
    bounds=[(-80,80),(-80,80),(0.97,1.03),(0.97,1.03),(-math.radians(2),math.radians(2)),(-0.8,0.8)]
    de=differential_evolution(loss,bounds,seed=42,popsize=8,maxiter=45,tol=2e-4,polish=False,workers=1,updating='immediate')
    loc=minimize(loss,de.x,method='Nelder-Mead',options={'maxiter':800,'xatol':1e-4,'fatol':1e-5})
    p=loc.x if loc.fun<=de.fun else de.x
    def metrics(p):
        x,y=transform_from_initial(x0,y0,p,cx,cy); k=sample_classes(class_src,x,y); ok=k>=0
        da=d+p[5]; lo=k[ok].astype(float); hi=lo+1; q=da[ok]
        err=np.maximum(lo-q,0)+np.maximum(q-hi,0)
        mid=lo+0.5
        return {'valid_fraction':float(ok.mean()),'in_band_fraction_of_valid':float((err==0).mean()) if ok.any() else 0,
                'mean_interval_error_m':float(err.mean()) if ok.any() else None,
                'median_abs_midpoint_error_m':float(np.median(np.abs(q-mid))) if ok.any() else None,
                'objective':float(loss(p))}
    return p,cx,cy,metrics(np.array([0,0,1,1,0,0],float)),metrics(p)


def island_union():
    if not ISLAND_PATH.exists():return None
    fc=json.loads(ISLAND_PATH.read_text()); gs=[]
    for f in fc.get('features',[]):
        try:
            g=shape(f['geometry']).buffer(0)
            if not g.is_empty:gs.append(g)
        except Exception:pass
    return unary_union(gs).buffer(0) if gs else None


def geographic_classes(class_src,p,cx,cy,w,h,bbox,step_m):
    west,south,east,north=bbox
    lat0=(south+north)/2; mx=111320*math.cos(math.radians(lat0)); my=111320
    nx=int(round((east-west)*mx/step_m))+1; ny=int(round((north-south)*my/step_m))+1
    lons=np.linspace(west,east,nx); lats=np.linspace(south,north,ny)
    out=np.full((ny,nx),-1,dtype=np.int8)
    # rows are generated south -> north to match app lookup convention
    for j0 in range(0,ny,100):
        j1=min(ny,j0+100); LAT,LON=np.meshgrid(lats[j0:j1],lons,indexing='ij')
        x0,y0=initial_px(LON.ravel(),LAT.ravel(),w,h)
        xx,yy=transform_from_initial(x0,y0,p,cx,cy)
        out[j0:j1]=sample_classes(class_src,xx,yy).reshape(j1-j0,nx)
    isl=island_union()
    if isl is not None and not isl.is_empty:
        for j0 in range(0,ny,100):
            j1=min(ny,j0+100); LAT,LON=np.meshgrid(lats[j0:j1],lons,indexing='ij')
            mask=contains_xy(isl,LON,LAT)
            a=out[j0:j1]; a[mask]=-1; out[j0:j1]=a
    return out,lons,lats


def save_clean_webp(bands,path):
    # bands rows south->north; image must be north at top.
    a=np.flipud(bands); h,w=a.shape
    rgba=np.zeros((h,w,4),dtype=np.uint8); good=a>=0
    rgba[good,:3]=DISPLAY[a[good]]; rgba[good,3]=255
    # crisp class and shoreline boundaries
    edge=np.zeros((h,w),bool)
    for sh in ((1,0),(-1,0),(0,1),(0,-1)):
        b=np.roll(a,sh,axis=(0,1)); edge|=good & (b!=a)
    rgba[edge,:3]=np.array([25,67,80],dtype=np.uint8)
    rgba[edge,3]=210
    Image.fromarray(rgba,'RGBA').save(path,'WEBP',lossless=True,method=6)


def main():
    img=Image.open(IMG_PATH).convert('RGB'); rgb=np.asarray(img); h,w=rgb.shape[:2]
    palette=load_palette(rgb)
    class_src,lake_mask,mind=segment_classes(rgb,palette)
    all_snd,thin=soundings()
    p,cx,cy,initial_metrics,opt_metrics=calibrate(class_src,thin,w,h)

    if V2_GRID.exists():
        b=json.loads(V2_GRID.read_text())['bbox']; bbox=(float(b['west']),float(b['south']),float(b['east']),float(b['north']))
    else:bbox=(-1.146,44.931,-1.083,45.006)

    # 10 m compact numeric band grid; 5 m visual grid preserves more of the 2048 source detail.
    bands10,lons10,lats10=geographic_classes(class_src,p,cx,cy,w,h,bbox,10.0)
    bands5,lons5,lats5=geographic_classes(class_src,p,cx,cy,w,h,bbox,5.0)
    save_clean_webp(bands5,OUT_IMG)

    rows=[''.join('.' if v<0 else str(int(v)) for v in row) for row in bands10]
    grid={'version':'3.0','source':'Aquabio/Agence de l Eau Adour-Garonne published 2012 bathymetry','vertical_definition':'official 1 m classes; character 0 means 0-1 m ... 7 means 7-8 m; . means land/no class',
          'bbox':{'west':bbox[0],'south':bbox[1],'east':bbox[2],'north':bbox[3]},'nx':len(lons10),'ny':len(lats10),'step_m':10.0,
          'rows_south_to_north':rows,'water_level_reference_ngf_m':13.21}
    OUT_GRID.write_text(json.dumps(grid,separators=(',',':')),encoding='utf-8')

    valid=bands10>=0; vals=bands10[valid]
    counts={str(k):int((vals==k).sum()) for k in range(8)}
    mean_mid=float(np.mean(vals.astype(float)+0.5)) if len(vals) else None
    report={'version':'3.0','source_image':{'width':w,'height':h,'palette_rgb':np.rint(palette).astype(int).tolist()},
      'segmentation':{'source_water_pixels':int((class_src>=0).sum()),'source_image_pixels':int(h*w),'class_pixels':{str(k):int((class_src==k).sum()) for k in range(8)}},
      'calibration':{'soundings_all':int(len(all_snd)),'soundings_spatially_thinned':int(len(thin)),
        'initial_metrics':initial_metrics,'optimized_metrics':opt_metrics,
        'optimized_parameters':{'dx_px':float(p[0]),'dy_px':float(p[1]),'scale_x':float(p[2]),'scale_y':float(p[3]),'rotation_deg':float(math.degrees(p[4])),'2008_to_2012_depth_offset_m':float(p[5])}},
      'output':{'numeric_grid_step_m':10.0,'visual_grid_step_m':5.0,'bands10_shape':[int(x) for x in bands10.shape],'water_cells_10m':int(valid.sum()),'class_cells':counts,
        'area_weighted_class_midpoint_mean_m':mean_mid,'published_mean_depth_m':2.4,'published_max_depth_m':7.3},
      'interpretation':'Display the official 1 m class at GPS position. The 2008 sounding model is validation/calibration evidence, not the source of fine contour geometry.',
      'warning':'Not a certified navigation chart. Published classes were mapped at a stated plan-water elevation of 13.21 m NGF.'}
    OUT_REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
