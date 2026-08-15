#!/usr/bin/env python3
from pathlib import Path

p = Path('hires.html')
s = p.read_text(encoding='utf-8')
s = s.replace("bathymetry-2012-v3.webp?v=42", "bathymetry-2012-v3.webp?v=31h1")
s = s.replace("badge.textContent='SURVEY v3.1 · previous'", "badge.textContent='SURVEY v3.1 · harmonized'")
s = s.replace(
    "warn.textContent='Survey v3.1 comparison view. Tap 3.1 to return to Vector 4.5.'",
    "warn.textContent='Survey v3.1: original 10 m survey grid rendered with the same 0–8 m colors, land tone and contour styling as Vector 4.5. Tap 3.1 to return to Vector 4.5.'"
)
s = s.replace("meta.textContent='Survey v3.1 comparison'", "meta.textContent='Survey v3.1 · 10 m grid · harmonized scale'")
# Keep one shared legend for both views; its colors are the canonical v4.1/v4.5 palette.
if 'bathymetry-2012-v3.webp?v=31h1' not in s:
    raise SystemExit('harmonized survey asset reference not applied')
if "SURVEY v3.1 · harmonized" not in s:
    raise SystemExit('harmonized survey badge not applied')
p.write_text(s, encoding='utf-8')

swp = Path('sw.js')
sw = swp.read_text(encoding='utf-8')
import re
sw = re.sub(r"const CACHE='[^']+';", "const CACHE='lacanautics-v4.5-taubin-gpsmax-harmonized-v31';", sw, count=1)
swp.write_text(sw, encoding='utf-8')
print('Activated harmonized v3.1 appearance and cache identity')
