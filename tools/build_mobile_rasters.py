#!/usr/bin/env python3
from pathlib import Path
import io
import re

import cairosvg
from PIL import Image

ROOT = Path('.')
# (source SVG, output WebP, logical app display width in CSS px)
JOBS = [
    ('bathymetry-geopdf-v45-taubin.svg', 'bathymetry-geopdf-v45-mobile.webp', 971),
    ('bathymetry-2012-v31.svg', 'bathymetry-2012-v31-mobile.webp', 1000),
]

for src_name, out_name, display_width in JOBS:
    src = ROOT / src_name
    out = ROOT / out_name
    text = src.read_text(encoding='utf-8')

    m = re.search(r'viewBox="0 0 ([0-9.]+) ([0-9.]+)"', text)
    if not m:
        raise RuntimeError(f'viewBox not found in {src_name}')
    view_w = float(m.group(1))

    # CairoSVG scales vector strokes with the output viewport. The browser SVG uses
    # non-scaling strokes, so compensate for the SVG's own viewBox->CSS enlargement
    # before making a 2x display raster. This preserves the apparent 0.62/0.72 px
    # contour widths used by the live SVGs.
    correction = view_w / float(display_width)
    if abs(correction - 1.0) > 1e-9:
        def fix_width(match):
            value = float(match.group(1)) * correction
            return f'stroke-width="{value:.4f}"'
        text = re.sub(r'stroke-width="([0-9.]+)"', fix_width, text)

    output_width = int(round(display_width * 2))
    png = cairosvg.svg2png(bytestring=text.encode('utf-8'), output_width=output_width)
    image = Image.open(io.BytesIO(png)).convert('RGB')
    image.save(out, 'WEBP', lossless=True, method=6)
    print(
        f'{out}: {image.width}x{image.height}, {out.stat().st_size} bytes, '
        f'viewBox={view_w:g}, display={display_width}px, stroke_correction={correction:.6f}'
    )
