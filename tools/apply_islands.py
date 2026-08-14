#!/usr/bin/env python3
"""Subtract OSM island polygons from the Lacanautics v2.1 depth grid and re-render SVG."""
import json, math
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import shape
from shapely.ops import unary_union
from shapely import contains_xy

GRID=Path('data/lacanau_depth_grid_v2.json')
ISLANDS=Path('data/lacanau_islands.geojson')
SVG=Path('bathymetry-v2.svg')
REPORT=Path('data/lacanau_island_mask_report.json')
LEVELS=np.arange(0,8.01,0.5)
COLORS=['#d9f6f2','#c6efee','#afe5ec','#96d9eb','#7bc9e9','#61b9e6','#49a8df','#3b94d7','#327fcd','#2f6bc2','#3158b4','#3548a5','#343a93','#312e80','#2c246c','#251c58']

def main():
    g=json.loads(GRID.read_text())
    fc=json.loads(ISLANDS.read_text())
    geoms=[shape(f['geometry']).buffer(0) for f in fc['features'] if f.get('geometry')]
    geoms=[x for x in geoms if not x.is_empty]
    if not geoms: raise SystemExit('No valid island polygons')
    islands=unary_union(geoms)
    b=g['bbox']; nx,ny=g['nx'],g['ny']
    xs=np.linspace(b['west'],b['east'],nx); ys=np.linspace(b['south'],b['north'],ny)
    XXll,YYll=np.meshgrid(xs,ys)
    mask=contains_xy(islands,XXll,YYll)
    rows=g['rows_south_to_north']; conf=g['confidence_rows_south_to_north']
    Z=np.array([[np.nan if v is None else float(v) for v in r] for r in rows],float)
    C=np.array(conf,int)
    before=int(np.isfinite(Z).sum())
    Z[mask]=np.nan; C[mask]=0
    g['version']='2.1-islands'
    g['island_source']='OpenStreetMap contributors via Overpass API'
    g['rows_south_to_north']=[[None if not np.isfinite(v) else float(v) for v in r] for r in Z]
    g['confidence_rows_south_to_north']=[[int(v) for v in r] for r in C]
    GRID.write_text(json.dumps(g,separators=(',',':')))

    lat0=(b['south']+b['north'])/2; mx=111320*math.cos(math.radians(lat0)); my=111320
    width=(b['east']-b['west'])*mx; height=(b['north']-b['south'])*my
    x=np.linspace(0,width,nx); y=np.linspace(0,height,ny); XX,YY=np.meshgrid(x,y)
    zz=np.ma.masked_invalid(Z)
    fig_w=6; fig_h=fig_w*height/width
    fig,ax=plt.subplots(figsize=(fig_w,fig_h),dpi=130); ax.set_position([0,0,1,1]); ax.set_xlim(0,width); ax.set_ylim(0,height); ax.set_aspect('equal'); ax.axis('off')
    ax.contourf(XX,YY,zz,levels=LEVELS,colors=COLORS,antialiased=True,extend='max')
    ax.contour(XX,YY,zz,levels=np.arange(.5,8,.5),colors='#1b5367',linewidths=.28,alpha=.48)
    ax.contour(XX,YY,zz,levels=np.arange(1,8,1),colors='#153b49',linewidths=.62,alpha=.72)
    # Draw island outlines from OSM polygons.
    def draw_poly(poly):
        ext=np.asarray(poly.exterior.coords)
        xx=(ext[:,0]-b['west'])*mx; yy=(ext[:,1]-b['south'])*my
        ax.fill(xx,yy,facecolor='#f2f0e7',edgecolor='#173d49',linewidth=.8,zorder=20)
        for ring in poly.interiors:
            rr=np.asarray(ring.coords); ax.plot((rr[:,0]-b['west'])*mx,(rr[:,1]-b['south'])*my,color='#173d49',linewidth=.6,zorder=21)
    if islands.geom_type=='Polygon': draw_poly(islands)
    else:
        for p in islands.geoms: draw_poly(p)
    fig.savefig(SVG,format='svg',transparent=True,pad_inches=0); plt.close(fig)
    report={'version':g['version'],'island_features':len(fc['features']),'names':[f.get('properties',{}).get('name') for f in fc['features']], 'masked_grid_cells':int(mask.sum()),'valid_cells_before':before,'valid_cells_after':int(np.isfinite(Z).sum())}
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
