#!/usr/bin/env python3
"""Fetch mapped islands in Lac de Lacanau from OpenStreetMap/Overpass as GeoJSON polygons."""
import json, urllib.parse, urllib.request
from pathlib import Path

OUT=Path('data/lacanau_islands.geojson')
# Slightly larger than the lake.
S,W,N,E=44.929,-1.151,45.008,-1.080
QUERY=f'''[out:json][timeout:60];(
  way[place~"island|islet"]({S},{W},{N},{E});
  relation[place~"island|islet"]({S},{W},{N},{E});
  way[name~"Boucs|Oiseaux|S.mignan|Vire Vieille",i]({S},{W},{N},{E});
  relation[name~"Boucs|Oiseaux|S.mignan|Vire Vieille",i]({S},{W},{N},{E});
);out geom;'''

def ring_from_geom(g):
    pts=[[p['lon'],p['lat']] for p in g if 'lon' in p and 'lat' in p]
    if len(pts)>=3 and pts[0]!=pts[-1]: pts.append(pts[0])
    return pts if len(pts)>=4 else None

def main():
    data=urllib.parse.urlencode({'data':QUERY}).encode()
    req=urllib.request.Request('https://overpass-api.de/api/interpreter',data=data,headers={'User-Agent':'Lacanautics/2.1'})
    with urllib.request.urlopen(req,timeout=90) as r: obj=json.load(r)
    feats=[]; seen=set()
    for e in obj.get('elements',[]):
        tags=e.get('tags',{}); name=tags.get('name','')
        key=(e.get('type'),e.get('id'))
        if key in seen: continue
        seen.add(key)
        if e.get('type')=='way':
            ring=ring_from_geom(e.get('geometry',[]))
            if ring:
                feats.append({'type':'Feature','properties':{'name':name,'osm_type':'way','osm_id':e['id']},'geometry':{'type':'Polygon','coordinates':[ring]}})
        elif e.get('type')=='relation':
            outers=[]; inners=[]
            for m in e.get('members',[]):
                ring=ring_from_geom(m.get('geometry',[]))
                if not ring: continue
                (inners if m.get('role')=='inner' else outers).append(ring)
            for outer in outers:
                # Relation holes are uncommon here; attach contained inners conservatively.
                feats.append({'type':'Feature','properties':{'name':name,'osm_type':'relation','osm_id':e['id']},'geometry':{'type':'Polygon','coordinates':[outer]+inners}})
    fc={'type':'FeatureCollection','source':'OpenStreetMap contributors via Overpass API','license':'ODbL','features':feats}
    OUT.write_text(json.dumps(fc,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'features':len(feats),'names':[f['properties'].get('name') for f in feats]},ensure_ascii=False,indent=2))
    if not feats: raise SystemExit('No island polygons returned by Overpass')
if __name__=='__main__': main()
