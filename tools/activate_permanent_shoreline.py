#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path('.')

# ---- Vector 4.5 builder ----
p=ROOT/'tools/build_vector_v45_taubin.py'
s=p.read_text(encoding='utf-8')
if 'import shoreline_mask' not in s:
    s=s.replace('import build_vector_v44 as v44\n','import build_vector_v44 as v44\nimport shoreline_mask\n',1)
s=s.replace(
    "    _, pal, cls = v44.load_classes()\n    svg, masks, layers, nested, labels = build_geometry(pal, cls)\n",
    "    _, pal, cls = v44.load_classes()\n    v41_meta = json.loads((ROOT / 'data/lacanau_geopdf_v41.json').read_text())\n    cls, shoreline_stats = shoreline_mask.mask_classes(cls, v41_meta['bbox'])\n    svg, masks, layers, nested, labels = build_geometry(pal, cls)\n",
    1,
)
s=s.replace(
    "        'depth_label_count': labels,\n        'layers': layers,\n",
    "        'depth_label_count': labels,\n        'shoreline_mask': shoreline_stats,\n        'layers': layers,\n",
    1,
)
s=s.replace(
    "'navigation_note': 'GPS lookup remains exact corrected v4.1 classes; Taubin smoothing is visual/cartographic only.',",
    "'navigation_note': 'Depth classes remain the corrected v4.1 source inside water, but both display and navigation lookup are clipped to the committed IGN permanent-water shoreline. Taubin smoothing remains visual/cartographic only.',",
)
s=s.replace(
    'GPS lookup remains untouched v4.1 classes.',
    'Depth classes come from corrected v4.1 and are clipped to the IGN permanent-water shoreline.',
)
p.write_text(s,encoding='utf-8')

# ---- Survey v3.1 builder ----
p=ROOT/'tools/build_v31_harmonized.py'
s=p.read_text(encoding='utf-8')
if 'import shoreline_mask' not in s:
    s=s.replace('from skimage.measure import approximate_polygon, find_contours\n','from skimage.measure import approximate_polygon, find_contours\n\nimport shoreline_mask\n',1)
s=s.replace(
    "    cls = load_classes(src)\n    ny, nx = cls.shape\n",
    "    cls = load_classes(src)\n    bbox = {k: float(src[k]) for k in ('west','south','east','north')}\n    cls, shoreline_stats = shoreline_mask.mask_classes(cls, bbox)\n    ny, nx = cls.shape\n",
    1,
)
s=s.replace(
    "'geometry_note': 'Original 10 m v3.1 class grid unchanged; boundaries are vectorized at cell edges with no smoothing.',",
    "'geometry_note': 'Original 10 m v3.1 depth classes are unchanged inside confirmed water; present-day land/water extent is clipped to the committed IGN permanent-water shoreline. Boundaries are vectorized at cell edges with no smoothing.',",
)
s=s.replace(
    "        'source_grid_size': [nx, ny],\n        'rings_by_threshold':",
    "        'source_grid_size': [nx, ny],\n        'shoreline_mask': shoreline_stats,\n        'rings_by_threshold':",
    1,
)
s=s.replace(
    'Original 10 m Survey v3.1 depth classes rendered with the same palette and line styling as Vector 4.5. Geometry is not smoothed.',
    'Original 10 m Survey v3.1 depth classes clipped to the IGN permanent-water shoreline and rendered with the same palette and line styling as Vector 4.5. Geometry is not smoothed.',
)
p.write_text(s,encoding='utf-8')

# ---- App: common shoreline gate for both lookup engines ----
p=ROOT/'index.html'
s=p.read_text(encoding='utf-8')
s=s.replace(
    "levelURL='data/lacanau_lake_level.json?v=411';",
    "levelURL='data/lacanau_lake_level.json?v=411',shorelineURL='data/lacanau_open_water_mask.geojson?v=1';",
    1,
)
s=s.replace(
    "lastSurveyBand=null,classCtx=null,probeActive=false",
    "lastSurveyBand=null,classCtx=null,shoreline=null,probeActive=false",
    1,
)
if 'function isOpenWater(lat,lon)' not in s:
    gate="""function pointInRing(lon,lat,ring){let inside=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){const xi=ring[i][0],yi=ring[i][1],xj=ring[j][0],yj=ring[j][1];if(((yi>lat)!=(yj>lat))&&(lon<(xj-xi)*(lat-yi)/(yj-yi)+xi))inside=!inside}return inside}\nfunction pointInPolygon(lon,lat,rings){if(!rings?.length||!pointInRing(lon,lat,rings[0]))return false;for(let i=1;i<rings.length;i++)if(pointInRing(lon,lat,rings[i]))return false;return true}\nfunction isOpenWater(lat,lon){if(!shoreline)return true;const g=shoreline.type==='Feature'?shoreline.geometry:shoreline;if(g.type==='Polygon')return pointInPolygon(lon,lat,g.coordinates);if(g.type==='MultiPolygon')return g.coordinates.some(p=>pointInPolygon(lon,lat,p));return true}\n"""
    s=s.replace('function v41Sample(lat,lon){',gate+'function v41Sample(lat,lon){',1)
s=s.replace(
    'function v41Sample(lat,lon){if(!v41||!classCtx)return null;',
    'function v41Sample(lat,lon){if(!v41||!classCtx||!isOpenWater(lat,lon))return null;',
    1,
)
s=s.replace(
    'function surveySample(lat,lon){if(!survey||',
    'function surveySample(lat,lon){if(!survey||!isOpenWater(lat,lon)||',
    1,
)
# Load shoreline independently; until it arrives lookup remains fail-open, avoiding startup breakage.
if 'fetch(shorelineURL).then' not in s:
    s=s.replace(
        "onresize=()=>fit();updateLevelInfo();if('serviceWorker'in navigator)",
        "onresize=()=>fit();fetch(shorelineURL).then(r=>{if(!r.ok)throw Error(r.status);return r.json()}).then(x=>{shoreline=x;if(probeActive&&lastProbe)showProbe(lastProbe.lat,lastProbe.lon);else if(last)updateDepth(last.coords.latitude,last.coords.longitude)}).catch(()=>{});updateLevelInfo();if('serviceWorker'in navigator)",
        1,
    )
# Explain the corrected shoreline in UI without clutter.
s=s.replace(
    'GPS still samples untouched 4.1 classes. Not a certified chart.',
    'Depth classes remain 2012/v4.1, but land/water is clipped to IGN permanent hydrography so intermittent lake fringes and marshes are land. Not a certified chart.',
)
s=s.replace(
    'bathymetry-geopdf-v45-mobile.webp?v=m1',
    'bathymetry-geopdf-v45-mobile.webp?v=m2',
)
s=s.replace(
    'bathymetry-2012-v31-mobile.webp?v=m1',
    'bathymetry-2012-v31-mobile.webp?v=m2',
)
s=s.replace('bathymetry-geopdf-v45-taubin.svg?v=45','bathymetry-geopdf-v45-taubin.svg?v=45s1')
s=s.replace('bathymetry-2012-v31.svg?v=31v1','bathymetry-2012-v31.svg?v=31v2')
s=s.replace(".png?v=1`", ".png?v=2`")
s=s.replace("register('./sw.js?v=singlepage8-panclamp')","register('./sw.js?v=singlepage9-shoreline')")
p.write_text(s,encoding='utf-8')

# ---- Service worker ----
p=ROOT/'sw.js'
s=p.read_text(encoding='utf-8')
s=s.replace('lacanautics-v4.5-singlepage8-panclamp','lacanautics-v4.5-singlepage9-shoreline')
if "'./data/lacanau_open_water_mask.geojson'" not in s:
    s=s.replace("'./data/lacanau_lake_level.json'", "'./data/lacanau_lake_level.json','./data/lacanau_open_water_mask.geojson'",1)
# Treat geojson as fresh/network-first too.
s=s.replace("/\\.(?:json|svg|webp|js)$/.test", "/\\.(?:json|geojson|svg|webp|js)$/.test")
p.write_text(s,encoding='utf-8')

# ---- Assertions ----
html=(ROOT/'index.html').read_text(encoding='utf-8')
assert 'function isOpenWater(lat,lon)' in html
assert '!isOpenWater(lat,lon)' in html
assert "shorelineURL='data/lacanau_open_water_mask.geojson?v=1'" in html
assert '.png?v=2`' in html
assert "sw.js?v=singlepage9-shoreline" in html
assert 'import shoreline_mask' in (ROOT/'tools/build_vector_v45_taubin.py').read_text()
assert 'import shoreline_mask' in (ROOT/'tools/build_v31_harmonized.py').read_text()
assert 'singlepage9-shoreline' in (ROOT/'sw.js').read_text()
print('Permanent-water shoreline clipping activated for both maps and both lookup engines.')
