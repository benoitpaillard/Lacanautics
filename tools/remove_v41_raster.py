#!/usr/bin/env python3
from pathlib import Path
import re

html_path = Path('hires.html')
s = html_path.read_text(encoding='utf-8')

# Replace the three-way vector/raster/survey renderer with a two-way vector/survey renderer.
pattern = r"function configure\(\)\{.*?\}\nPromise\.all"
replacement = """function configure(){if(mode==='vector'){B=v41.bbox;W=v41.width;H=v41.height;map.src='bathymetry-geopdf-v45-taubin.svg?v=45';badge.textContent='VECTOR 4.5 · Taubin-smoothed';warn.textContent='Vector 4.5: Taubin-smoothed 1–5 m isobaths suppress short scallops without shrinkage; shoreline and 6–8 m zones retain v4.4 geometry. GPS still samples untouched 4.1 classes. Not a certified chart.';layerBtn.innerHTML='<strong>VECTOR</strong><small>4.5</small>';meta.textContent='Sub-pixel SVG zones · source ~5.66 m/px'}else{B=survey.bbox;W=1000;const lat0=(B.south+B.north)/2*Math.PI/180,widthM=(B.east-B.west)*111320*Math.cos(lat0),heightM=(B.north-B.south)*111320;H=Math.round(W*heightM/widthM);map.src='bathymetry-2012-v3.webp?v=42';badge.textContent='SURVEY v3.1 · previous';warn.textContent='Survey v3.1 comparison view. Tap 3.1 to return to Vector 4.5.';layerBtn.innerHTML='<strong>3.1</strong><small>VIEW</small>';meta.textContent='Survey v3.1 comparison'}world.style.width=W+'px';world.style.height=H+'px';$('#track').setAttribute('viewBox',`0 0 ${W} ${H}`);points=[];line.setAttribute('points','');document.querySelectorAll('.poi').forEach(e=>{const p=ll(+e.dataset.lat,+e.dataset.lon);e.style.left=p.x+'px';e.style.top=p.y+'px'});ready=true;coord.textContent='GPS not started';fit()}
Promise.all"""
s2, n = re.subn(pattern, replacement, s, count=1, flags=re.S)
if n != 1:
    raise SystemExit(f'configure() replacement failed: {n}')
s = s2

# Two-way layer switch only.
s, n = re.subn(
    r"function toggleLayer\(\)\{mode=mode==='vector'\?'raster':mode==='raster'\?'v31':'vector';",
    "function toggleLayer(){mode=mode==='vector'?'v31':'vector';",
    s,
    count=1,
)
if n != 1:
    raise SystemExit('toggleLayer() replacement failed')

# Depth/share labels no longer need a raster branch.
s = s.replace("mode==='vector'?'4.5 Taubin vector':mode==='raster'?'4.1 raster':'3.1 survey'", "mode==='vector'?'4.5 Taubin vector':'3.1 survey'")
s = s.replace("mode==='vector'?'4.5 vector depth ':mode==='raster'?'4.1 raster depth ':'3.1 depth '", "mode==='vector'?'4.5 vector depth ':'3.1 depth '")

# User-facing comparison copy.
s = s.replace('Tap the <b>VECTOR</b> button to cycle through Vector 4.5 → corrected Raster 4.1 → Survey v3.1 for direct comparison.', 'Tap the <b>VECTOR</b> button to switch directly between Vector 4.5 and Survey v3.1 for comparison.')
s = s.replace('corrected Raster 4.1', 'Survey v3.1')

for forbidden in ("bathymetry-geopdf-v41-native.webp", "mode==='raster'", 'RASTER 4.1'):
    if forbidden in s:
        raise SystemExit(f'visible raster reference still present: {forbidden}')
html_path.write_text(s, encoding='utf-8')

# Remove the unused visible raster asset from the offline cache and bump cache identity.
sw_path = Path('sw.js')
sw = sw_path.read_text(encoding='utf-8')
sw = sw.replace("'./bathymetry-geopdf-v41-native.webp',", '')
sw = re.sub(r"const CACHE='[^']+';", "const CACHE='lacanautics-v4.5-taubin-gpsmax-noraster';", sw, count=1)
if 'bathymetry-geopdf-v41-native.webp' in sw:
    raise SystemExit('raster asset still present in service worker')
if 'bathymetry-geopdf-v41-classes.webp' not in sw:
    raise SystemExit('GPS class raster must remain cached')
sw_path.write_text(sw, encoding='utf-8')

# Delete only the visible corrected raster. The class raster stays for exact GPS depth lookup.
raster = Path('bathymetry-geopdf-v41-native.webp')
if raster.exists():
    raster.unlink()

print('Removed visible Raster 4.1 view; kept v4.1 class raster for GPS depth sampling.')
