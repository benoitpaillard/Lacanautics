#!/usr/bin/env python3
from pathlib import Path

p = Path('hires.html')
s = p.read_text()
repls = {
    "Vector 4.3: source-pixel staircases removed before bounded curve fitting; p95 displacement on broad 0–5 m bands is ≤1.5 native pixels. Tap VECTOR for corrected raster 4.1, then v3.1. Not a certified chart.":
    "Vector 4.5: Taubin-smoothed 1–5 m isobaths suppress short scallops without shrinkage; shoreline and 6–8 m zones retain v4.4 geometry. GPS still samples untouched 4.1 classes. Not a certified chart.",
    "Tap RASTER for v3.1, then vector 4.4.": "Tap RASTER for v3.1, then vector 4.5.",
    "Tap 3.1 to return to vector 4.4.": "Tap 3.1 to return to vector 4.5.",
    "mode==='vector'?'4.4 smooth vector'": "mode==='vector'?'4.5 Taubin vector'",
    "mode==='vector'?'4.2 vector depth '": "mode==='vector'?'4.5 vector depth '",
}
for old, new in repls.items():
    s = s.replace(old, new)

# These version strings are stale UI labels only; v4.4 references describing the
# retained parent geometry are intentionally allowed elsewhere in explanatory copy.
for stale in (
    'Vector 4.3: source-pixel',
    'then vector 4.4.',
    'return to vector 4.4.',
    "?'4.4 smooth vector'",
    "?'4.2 vector depth '",
):
    assert stale not in s, stale
assert 'bathymetry-geopdf-v45-taubin.svg?v=45' in s
assert 'VECTOR 4.5 · Taubin-smoothed' in s
p.write_text(s)
