#!/usr/bin/env python3
from pathlib import Path
import io

import cairosvg
from PIL import Image

ROOT = Path('.')
JOBS = [
    ('bathymetry-geopdf-v45-taubin.svg', 'bathymetry-geopdf-v45-mobile.webp', 1942),
    ('bathymetry-2012-v31.svg', 'bathymetry-2012-v31-mobile.webp', 1964),
]

for src_name, out_name, width in JOBS:
    src = ROOT / src_name
    out = ROOT / out_name
    png = cairosvg.svg2png(bytestring=src.read_bytes(), output_width=width)
    image = Image.open(io.BytesIO(png)).convert('RGB')
    image.save(out, 'WEBP', lossless=True, method=6)
    print(f'{out}: {image.width}x{image.height}, {out.stat().st_size} bytes')
