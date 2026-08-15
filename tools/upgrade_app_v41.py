#!/usr/bin/env python3
from pathlib import Path
p=Path('hires.html')
s=p.read_text()
repls=[
('Lacanautics GeoPDF v4','Lacanautics GeoPDF v4.1'),
("#map{position:absolute;inset:0;width:100%;height:100%;object-fit:fill;pointer-events:none}","#map,#contours{position:absolute;inset:0;width:100%;height:100%;object-fit:fill;pointer-events:none}#contours{z-index:2;opacity:.78}#track{z-index:3}"),
("#sampleCanvas{display:none}","#sampleCanvas,#classMap{display:none}"),
('<img id="map" src="bathymetry-geopdf-v4.webp?v=4" alt="Official Lac de Lacanau GeoPDF bathymetry">','<img id="map" src="bathymetry-geopdf-v41-native.webp?v=41" alt="Official native GeoPDF bathymetry"><img id="contours" src="bathymetry-geopdf-v41-contours.svg?v=41" alt="Official depth contours">'),
('<canvas id="sampleCanvas"></canvas>','<img id="classMap" src="bathymetry-geopdf-v41-classes.webp?v=41" alt="" aria-hidden="true"><canvas id="sampleCanvas"></canvas>'),
('GEOPDF v4 · exact georef','GEOPDF v4.1 · native + vector'),
('Official Adour-Garonne ArcMap GeoPDF · ~5.66 m source pixels · exact embedded WGS84 frame · 1 m depth bands @ 13.21 m NGF.','Official Adour-Garonne GeoPDF · native 1924 px strips with no PDF re-render · vector-traced 1 m boundaries · exact embedded WGS84 · 13.21 m NGF.'),
('This version is rebuilt directly from the official Adour-Garonne <b>FRFL49_Bathym GeoPDF</b>. Its embedded geographic control points are used exactly — no hand georeferencing and no sounding-fit correction.','This version uses the original raster strips embedded inside the official Adour-Garonne <b>FRFL49_Bathym GeoPDF</b>, without re-rendering the PDF. The official geospatial control points are preserved exactly.'),
('Your depth band is sampled from the same lossless map pixel shown under your GPS position.','The visible layer preserves the native source pixels, while GPS depth is sampled from a separate exact 8-class mask. Vector contour lines are traced at native half-pixel boundaries.'),
('Official 2012 cartographic classes, approximately 5.66 m per source pixel. Vertical definition remains 1 m.','Native GeoPDF pixels, approximately 5.65 m per source pixel. No smoothing is used to invent bathymetric detail; vertical definition remains 1 m.'),
("stage=$('#stage'),world=$('#world'),map=$('#map'),canvas=$('#sampleCanvas')","stage=$('#stage'),world=$('#world'),map=$('#map'),classMap=$('#classMap'),canvas=$('#sampleCanvas')"),
("META_URL='data/lacanau_geopdf_v4.json?v=4',LEVEL_URL='data/lacanau_lake_level.json?v=4'","META_URL='data/lacanau_geopdf_v41.json?v=41',LEVEL_URL='data/lacanau_lake_level.json?v=41'"),
("ctx.drawImage(map,0,0,W,H)","ctx.imageSmoothingEnabled=false;ctx.drawImage(classMap,0,0,W,H)"),
("Official GeoPDF · ${r[0]?r[0].toFixed(2):'~5.7'} m/px · exact WGS84","Native GeoPDF strips · ${r[0]?r[0].toFixed(2):'~5.7'} m/px · vector contours"),
("new Promise((resolve,reject)=>{if(map.complete&&map.naturalWidth)resolve();else{map.onload=resolve;map.onerror=()=>reject(Error('map image failed'))}})","new Promise((resolve,reject)=>{if(classMap.complete&&classMap.naturalWidth)resolve();else{classMap.onload=resolve;classMap.onerror=()=>reject(Error('class image failed'))}})"),
("GeoPDF v4 unavailable","GeoPDF v4.1 unavailable"),
]
for old,new in repls:
    if old not in s:
        raise SystemExit('Missing expected text: '+old[:120])
    s=s.replace(old,new)
p.write_text(s)

idx=Path('index.html').read_text().replace('Survey v3.1','GeoPDF v4.1').replace('hires.html?v=31','hires.html?v=41').replace('Lacanautics Survey v3.1','Lacanautics GeoPDF v4.1')
Path('index.html').write_text(idx)
sw=Path('sw.js').read_text()
sw=sw.replace("lacanautics-v4'","lacanautics-v4.1'")
old="'./bathymetry-geopdf-v4.webp','./data/lacanau_geopdf_v4.json'"
new="'./bathymetry-geopdf-v41-native.webp','./bathymetry-geopdf-v41-classes.webp','./bathymetry-geopdf-v41-contours.svg','./data/lacanau_geopdf_v41.json'"
if old not in sw: raise SystemExit('service worker v4 assets not found')
sw=sw.replace(old,new)
Path('sw.js').write_text(sw)
man=Path('manifest.webmanifest').read_text().replace('official GeoPDF bathymetry','native GeoPDF bathymetry with vector contour overlay')
Path('manifest.webmanifest').write_text(man)
print('Patched app to v4.1')
