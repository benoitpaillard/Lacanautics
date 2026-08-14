#!/usr/bin/env python3
"""Build a high-resolution Lacanau bathymetry surface from official OFB soundings.

Outputs:
- bathymetry-hires.svg: clean 0.5 m filled contours for the web app
- data/lacanau_depth_grid.json: regular WGS84 grid used for numeric depth lookup
- data/lacanau_hires_report.json: interpolation/QC diagnostics

The source soundings are median-aggregated at identical lon/lat positions. This automatically
rejects isolated ping spikes when repeated measurements exist at the same coordinate (e.g. the
known 33.8 m spike among ~1 m pings). A conservative 8 m cap is applied only after aggregation,
consistent with the published 7.3 m maximum for Lacanau; capped points are reported.
"""
import json, math
from pathlib import Path
from collections import defaultdict
import numpy as np
from scipy.interpolate import LinearNDInterpolator
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path('.')
SRC=ROOT/'data/lacanau_soundings.geojson'
OUT_GRID=ROOT/'data/lacanau_depth_grid.json'
OUT_REPORT=ROOT/'data/lacanau_hires_report.json'
OUT_SVG=ROOT/'bathymetry-hires.svg'

# Exact geographic frame used by the new app. Small margin around all official sounding points.
WEST,EAST=-1.1452,-1.0931
SOUTH,NORTH=44.9349,45.0052
LAT0=(SOUTH+NORTH)/2
COS=math.cos(math.radians(LAT0))
MX=111320*COS
MY=111320
LEVELS=np.arange(0,8.01,0.5)
COLORS=['#d7f5f2','#c5efee','#afe5ec','#96d8ea','#7bc9e9','#61b9e6','#49a8df','#388fd4',
        '#2f78c9','#2e64bc','#3152ae','#33439e','#33358c','#302a79','#2a2167','#241a55']

def xy(lon,lat): return ((lon-WEST)*MX,(lat-SOUTH)*MY)

def main():
    fc=json.loads(SRC.read_text())
    raw=[]
    for f in fc['features']:
        lon,lat=f['geometry']['coordinates']; d=float(f['properties']['depth_m'])
        if WEST<=lon<=EAST and SOUTH<=lat<=NORTH: raw.append((lon,lat,d))
    # Already median-deduped upstream; keep a second robust pass for reproducibility.
    g=defaultdict(list)
    for lon,lat,d in raw:g[(round(lon,7),round(lat,7))].append(d)
    pts=[]; capped=[]
    for (lon,lat),ds in g.items():
        d=float(np.median(ds))
        if d>8.0:
            capped.append([lon,lat,d]); continue
        if d>=0:pts.append((lon,lat,d))
    arr=np.asarray(pts,float)
    X=(arr[:,0]-WEST)*MX; Y=(arr[:,1]-SOUTH)*MY; D=arr[:,2]

    # 20 m regular grid: well below spacing along most survey tracks but not false centimetric detail.
    width=(EAST-WEST)*MX; height=(NORTH-SOUTH)*MY
    nx=int(round(width/20))+1; ny=int(round(height/20))+1
    gx=np.linspace(0,width,nx); gy=np.linspace(0,height,ny)
    XX,YY=np.meshgrid(gx,gy)
    interp=LinearNDInterpolator(np.column_stack([X,Y]),D,fill_value=np.nan)
    Z=interp(XX,YY)
    # Do not extrapolate outside the convex hull. Numerical values are rounded to 0.05 m in the grid
    # to avoid implying more precision than the measurements warrant.
    valid=np.isfinite(Z)
    Zstore=np.where(valid,np.round(Z/0.05)*0.05,np.nan)

    # Render a clean portrait SVG in true local geographic aspect ratio.
    fig_w=6.0; fig_h=fig_w*height/width
    fig,ax=plt.subplots(figsize=(fig_w,fig_h),dpi=120)
    ax.set_position([0,0,1,1]); ax.set_xlim(0,width); ax.set_ylim(0,height); ax.set_aspect('equal'); ax.axis('off')
    ax.set_facecolor('#f2f0e7')
    # Land/background is intentionally transparent; valid interpolated region only is filled.
    zz=np.ma.masked_invalid(np.clip(Z,0,8))
    ax.contourf(XX,YY,zz,levels=LEVELS,colors=COLORS,antialiased=True,extend='max')
    cs=ax.contour(XX,YY,zz,levels=np.arange(0.5,8.0,0.5),colors='#19455a',linewidths=0.28,alpha=0.55)
    # Stronger integer-metre contours.
    ax.contour(XX,YY,zz,levels=np.arange(1,8,1),colors='#153746',linewidths=0.6,alpha=0.75)
    fig.savefig(OUT_SVG,format='svg',transparent=True,pad_inches=0)
    plt.close(fig)

    # JSON grid, rows south->north. null = outside triangulated survey domain.
    rows=[]
    for row in Zstore:
        rows.append([None if not np.isfinite(v) else float(v) for v in row])
    grid={'source':'OFB/SIE points_bruts_bathy_20161020.zip','method':'Linear Delaunay interpolation; no extrapolation; 20 m grid; values rounded to 0.05 m',
          'bbox':{'west':WEST,'south':SOUTH,'east':EAST,'north':NORTH},'nx':nx,'ny':ny,'rows_south_to_north':rows}
    OUT_GRID.write_text(json.dumps(grid,separators=(',',':')))

    report={'input_unique_soundings':len(raw),'used_soundings':len(pts),'excluded_gt_8m_after_coordinate_median':capped,
            'used_depth_m':{'min':float(D.min()),'max':float(D.max()),'median':float(np.median(D))},
            'grid':{'nx':nx,'ny':ny,'spacing_x_m':width/(nx-1),'spacing_y_m':height/(ny-1),'valid_cells':int(valid.sum()),'total_cells':int(valid.size)},
            'bbox_wgs84':{'west':WEST,'south':SOUTH,'east':EAST,'north':NORTH},
            'warning':'Interpolated bathymetry is for situational awareness, not certified navigation. 0.5 m contours do not imply 0.5 m survey accuracy.'}
    OUT_REPORT.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
