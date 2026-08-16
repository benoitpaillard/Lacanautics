#!/usr/bin/env python3
from __future__ import annotations

import json, math, time
from pathlib import Path
import requests
from shapely.geometry import shape, Point, Polygon, MultiPolygon, mapping
from shapely.ops import unary_union

ROOT=Path('.')
OUT=ROOT/'data/shoreline_diagnostic'
OUT.mkdir(parents=True,exist_ok=True)
BBOX=(-1.155,44.925,-1.075,45.01)  # west,south,east,north
SEED=Point(-1.116,44.982)


def get_bdtopo():
    url='https://data.geopf.fr/wfs/ows'
    attempts=[
        dict(SERVICE='WFS',REQUEST='GetFeature',VERSION='2.0.0',TYPENAMES='BDTOPO_V3:surface_hydrographique',SRSNAME='urn:ogc:def:crs:OGC:1.3:CRS84',BBOX=f'{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]},urn:ogc:def:crs:OGC:1.3:CRS84',OUTPUTFORMAT='application/json',COUNT='1000'),
        dict(SERVICE='WFS',REQUEST='GetFeature',VERSION='2.0.0',TYPENAMES='BDTOPO_V3:surface_hydrographique',SRSNAME='EPSG:4326',BBOX=f'{BBOX[1]},{BBOX[0]},{BBOX[3]},{BBOX[2]},EPSG:4326',OUTPUTFORMAT='application/json',COUNT='1000'),
    ]
    last=None
    for params in attempts:
        r=requests.get(url,params=params,timeout=60)
        last=(r.status_code,r.text[:500])
        if r.ok and r.text.lstrip().startswith('{'):
            data=r.json()
            if data.get('features'):
                return data,r.url
    raise RuntimeError(f'BDTOPO WFS failed: {last}')


def osm_way_poly(el):
    g=el.get('geometry') or []
    pts=[(p['lon'],p['lat']) for p in g]
    if len(pts)>=4 and pts[0]!=pts[-1]: pts.append(pts[0])
    try:
        p=Polygon(pts)
        return p.buffer(0) if not p.is_valid else p
    except Exception:
        return None


def get_osm_wetlands():
    s,w,n,e=BBOX[1],BBOX[0],BBOX[3],BBOX[2]
    q=f'''[out:json][timeout:90];(
      way["natural"="wetland"]({s},{w},{n},{e});
      relation["natural"="wetland"]({s},{w},{n},{e});
      way["wetland"]({s},{w},{n},{e});
      relation["wetland"]({s},{w},{n},{e});
    );out geom;'''
    endpoints=['https://overpass-api.de/api/interpreter','https://overpass.kumi.systems/api/interpreter']
    for ep in endpoints:
        try:
            r=requests.post(ep,data={'data':q},timeout=120)
            if not r.ok: continue
            d=r.json(); polys=[]; tags=[]
            for el in d.get('elements',[]):
                if el.get('type')=='way':
                    p=osm_way_poly(el)
                    if p and not p.is_empty:
                        polys.append(p); tags.append(el.get('tags',{}))
                elif el.get('type')=='relation':
                    outers=[]
                    for m in el.get('members',[]):
                        if m.get('role')=='outer' and m.get('geometry'):
                            pts=[(p['lon'],p['lat']) for p in m['geometry']]
                            if len(pts)>=4:
                                if pts[0]!=pts[-1]: pts.append(pts[0])
                                try:
                                    p=Polygon(pts).buffer(0)
                                    if not p.is_empty: outers.append(p)
                                except Exception: pass
                    if outers:
                        polys.append(unary_union(outers)); tags.append(el.get('tags',{}))
            return d,polys,tags,ep
        except Exception:
            pass
    return {'elements':[]},[],[],None

bd,bd_url=get_bdtopo()
features=[]
for f in bd.get('features',[]):
    try: geom=shape(f['geometry']).buffer(0)
    except Exception: continue
    props=f.get('properties',{})
    features.append((geom,props))

summary=[]
for geom,p in features:
    summary.append({
        'nature':p.get('nature') or p.get('NATURE'),
        'persistance':p.get('persistance') or p.get('PERSISTANC'),
        'name':p.get('cpx_toponyme_de_plan_d_eau') or p.get('nom_p_eau') or p.get('NOM_P_EAU'),
        'contains_seed':bool(geom.contains(SEED)),
        'area_deg2':geom.area,
    })

permanent=[]
for geom,p in features:
    nature=(p.get('nature') or p.get('NATURE') or '').lower()
    pers=(p.get('persistance') or p.get('PERSISTANC') or '').lower()
    if pers=='permanent' and nature!='marais': permanent.append(geom)
perm_union=unary_union(permanent).buffer(0) if permanent else MultiPolygon([])
seed_parts=[]
if perm_union.geom_type=='Polygon':
    seed_parts=[perm_union]
elif perm_union.geom_type=='MultiPolygon':
    seed_parts=list(perm_union.geoms)
main=[g for g in seed_parts if g.buffer(1e-8).contains(SEED)]
if not main and seed_parts:
    main=[max(seed_parts,key=lambda g:g.area)]
main_water=unary_union(main).buffer(0) if main else MultiPolygon([])

osm_raw,wet_polys,wet_tags,osm_ep=get_osm_wetlands()
wet_union=unary_union(wet_polys).buffer(0) if wet_polys else MultiPolygon([])
overlap=main_water.intersection(wet_union) if not main_water.is_empty and not wet_union.is_empty else MultiPolygon([])

# Write small source artefacts for inspection.
(OUT/'bdtopo_surface_hydrographique.geojson').write_text(json.dumps(bd),encoding='utf-8')
(OUT/'osm_wetlands.json').write_text(json.dumps(osm_raw),encoding='utf-8')
(OUT/'main_permanent_nonmarsh.geojson').write_text(json.dumps({'type':'Feature','properties':{},'geometry':mapping(main_water)}),encoding='utf-8')

report={
    'bbox_wgs84':BBOX,
    'bdtopo_wfs_url':bd_url,
    'bdtopo_feature_count':len(features),
    'bdtopo_features':sorted(summary,key=lambda x:x['area_deg2'],reverse=True)[:40],
    'permanent_nonmarsh_count':len(permanent),
    'main_water_geom_type':main_water.geom_type,
    'main_water_area_deg2':main_water.area,
    'osm_endpoint':osm_ep,
    'osm_wetland_polygon_count':len(wet_polys),
    'osm_wetland_tags':wet_tags[:30],
    'main_water_intersection_osm_wetland_area_deg2':overlap.area,
    'main_water_intersection_osm_wetland_fraction':(overlap.area/main_water.area if main_water.area else 0),
}
(OUT/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2,ensure_ascii=False))
