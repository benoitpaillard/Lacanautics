#!/usr/bin/env python3
from pathlib import Path

# Final production settings: smooth the visibly scalloped 1–5 m contours only.
builder = Path('tools/build_vector_v45_taubin.py')
s = builder.read_text()
s = s.replace('TARGET_ITERATIONS = [0, 4, 4, 4, 3, 2, 1, 0]', 'TARGET_ITERATIONS = [0, 4, 4, 4, 3, 2, 0, 0]')
s = s.replace('# Shoreline and the tiny 7–8 m pockets stay exactly on the v4.4 geometry.', '# Shoreline and the small 6–8 m zones stay exactly on the v4.4 geometry.')
builder.write_text(s)

h = Path('hires.html').read_text()
h = h.replace('bathymetry-geopdf-v44-smooth.svg?v=44', 'bathymetry-geopdf-v45-taubin.svg?v=45')
h = h.replace('Smooth corrected GeoPDF bathymetry with integer isobaths', 'Taubin-smoothed corrected GeoPDF bathymetry with integer isobaths')
h = h.replace('VECTOR 4.4 · smooth isobaths', 'VECTOR 4.5 · Taubin-smoothed')
h = h.replace('Vector 4.4: smooth iso-contours reconstructed from the corrected 4.1 depth classes, with labelled 1 m depth lines. The visual low-pass filter removes raster/scallop frequency; GPS still samples the untouched 4.1 classes. Not a certified chart.', 'Vector 4.5: the v4.4 interior isobaths are Taubin-smoothed to suppress short scallops without shrinkage, then simplified and safely clipped to their parent depth band. Shoreline and 6–8 m zones stay on v4.4 geometry. GPS still samples untouched 4.1 classes. Not a certified chart.')
h = h.replace('The corrected GeoPDF 4.1 bathymetry is rendered as <b>smooth SVG iso-contours</b>. Each integer depth threshold is low-pass filtered before extracting its 0.5 contour, so the curve is reconstructed directly instead of rounding raster corners. The 1–7 m isobaths are drawn and labelled on top.', 'The corrected GeoPDF 4.1 bathymetry is rendered as <b>compact Taubin-smoothed SVG iso-contours</b>. The proven v4.4 contours are non-shrinking low-pass filtered only where the scalloping is visible, then simplified and nested by clipping. The 1–7 m isobaths are drawn and labelled on top.')
h = h.replace('Source sampling ≈5.66 m/pixel. Broad visual contours use σ≈1.3 source pixels; deeper small zones use lighter smoothing. GPS depth lookup is unchanged. Vertical definition remains the official 1 m bands.', 'Source sampling ≈5.66 m/pixel. Taubin smoothing uses λ=0.50, μ=−0.53 on the 1–5 m contours; shoreline and 6–8 m zones retain v4.4 geometry. GPS depth lookup is unchanged. Vertical definition remains the official 1 m bands.')
h = h.replace('Lacanautics Vector v4.4', 'Lacanautics Vector v4.5')
h = h.replace('Vector 4.4 →', 'Vector 4.5 →')
h = h.replace('<small>4.4</small>', '<small>4.5</small>')
# Catch dynamic UI strings while avoiding changes to source-data versions.
h = h.replace("'VECTOR 4.4", "'VECTOR 4.5").replace('"VECTOR 4.4', '"VECTOR 4.5')
assert 'bathymetry-geopdf-v44-smooth.svg?v=44' not in h
assert 'bathymetry-geopdf-v45-taubin.svg?v=45' in h
assert 'Lacanautics Vector v4.5' in h
Path('hires.html').write_text(h)

Path('index.html').write_text('''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#eef0e8"><link rel="manifest" href="manifest.webmanifest"><title>Lacanautics Vector v4.5</title><script>location.replace('./hires.html?v=45')</script></head><body style="font-family:system-ui;background:#eef0e8;color:#17343d"><p>Loading Lacanautics Vector v4.5…</p><p><a href="./hires.html?v=45">Open the map</a></p></body></html>''')

Path('sw.js').write_text("""const CACHE='lacanautics-v4.5-taubin';
const CORE=['./','./index.html','./hires.html','./manifest.webmanifest','./bathymetry-geopdf-v45-taubin.svg','./bathymetry-geopdf-v41-native.webp','./bathymetry-geopdf-v41-classes.webp','./data/lacanau_geopdf_v41.json','./bathymetry-2012-v3.webp','./data/lacanau_2012_bands_v3.json','./data/lacanau_lake_level.json'];
self.addEventListener('install',e=>{self.skipWaiting();e.waitUntil(caches.open(CACHE).then(c=>c.addAll(CORE)))});
self.addEventListener('activate',e=>{e.waitUntil(Promise.all([caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))),self.clients.claim()]))});
self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;const u=new URL(e.request.url),fresh=u.pathname.endsWith('.html')||u.pathname.endsWith('.json')||u.pathname.endsWith('.svg')||u.pathname.endsWith('.webp')||u.pathname.endsWith('/Lacanautics/')||u.pathname.endsWith('/Lacanautics');if(fresh){e.respondWith(fetch(e.request,{cache:'no-store'}).then(resp=>{if(resp.ok){const copy=resp.clone();caches.open(CACHE).then(c=>c.put(e.request,copy))}return resp}).catch(()=>caches.match(e.request).then(r=>r||caches.match('./index.html'))))}else{e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request).then(resp=>{if(resp.ok){const copy=resp.clone();caches.open(CACHE).then(c=>c.put(e.request,copy))}return resp})))}});
""")

Path('.github/workflows/validate-web.yml').write_text('''name: Validate web app

on:
  workflow_dispatch:
  push:
    branches: [main]
    paths:
      - 'hires.html'
      - 'index.html'
      - 'sw.js'
      - 'manifest.webmanifest'
      - 'bathymetry-geopdf-v45-taubin.svg'
      - 'data/lacanau_vector_v45_taubin_report.json'
      - 'bathymetry-geopdf-v41-classes.webp'
      - 'data/lacanau_geopdf_v41.json'
      - '.github/workflows/validate-web.yml'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Check referenced v4.5 assets
        run: |
          test -s bathymetry-geopdf-v45-taubin.svg
          test -s data/lacanau_vector_v45_taubin_report.json
          test -s bathymetry-geopdf-v41-classes.webp
          test -s data/lacanau_geopdf_v41.json
          test -s data/lacanau_lake_level.json
          python -m json.tool data/lacanau_vector_v45_taubin_report.json >/dev/null
          python -m json.tool data/lacanau_geopdf_v41.json >/dev/null
          python -m json.tool data/lacanau_lake_level.json >/dev/null
      - name: Check inline JavaScript syntax
        run: |
          python - <<'PY'
          import re, pathlib, json
          html=pathlib.Path('hires.html').read_text(encoding='utf-8')
          scripts=re.findall(r'<script>(.*?)</script>',html,re.S)
          assert scripts, 'No inline script found'
          pathlib.Path('/tmp/lacanautics-app.js').write_text('\\n'.join(scripts),encoding='utf-8')
          assert 'bathymetry-geopdf-v45-taubin.svg' in html
          assert 'VECTOR 4.5' in html
          r=json.loads(pathlib.Path('data/lacanau_vector_v45_taubin_report.json').read_text())
          assert r['nested_violations'] == [0]*7
          assert r['size_ratio_vs_v44'] < 0.5
          assert r['qc']['all_overlap_within_1m_fraction'] > 0.999
          PY
          node --check /tmp/lacanautics-app.js
      - name: Check compact SVG structure
        run: |
          grep -q 'geom-1' bathymetry-geopdf-v45-taubin.svg
          grep -q 'clip-0' bathymetry-geopdf-v45-taubin.svg
          grep -q "lacanautics-v4.5-taubin" sw.js
''')

print('Activated Lacanautics Vector v4.5 Taubin')
