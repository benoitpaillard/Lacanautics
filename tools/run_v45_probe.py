#!/usr/bin/env python3
"""Run the selected v4.5 fairing strength with an exact shoreline-domain clip."""
import json
import re
import sys

sys.path.insert(0, "tools")
import build_vector_v45_lowpass as m

PROBE_SCALE = 0.45

# The tiny 7–8 m zones have only 41 source contour vertices in v4.4. Preserve their
# v4.4 geometry exactly instead of trying to fair features that are below the useful
# geometric scale for this map.
m.v.MIN_SPLINE_PERIMETER_PX[7] = 1.0e9

# The v4.5 fairing can move the 1 m contour by a sub-pixel amount across the
# shoreline at a handful of raster cells. Bathymetric zones are physically defined
# only inside the lake, so use the shoreline as an exact domain constraint both in
# QC raster masks and in the rendered SVG. This preserves the stronger fairing
# without allowing any depth colour/line to appear on land.
_original_build_trial = m.v.build_trial


def build_trial_shore_clipped(pal, cls, fairing_scale):
    path_sets, ring_sets, masks, stats, _ = _original_build_trial(pal, cls, fairing_scale)
    lake = masks[0].copy()
    for k in range(1, len(masks)):
        masks[k] &= lake
    nested = []
    for k in range(1, len(masks)):
        nested.append(int((masks[k] & ~masks[k - 1]).sum()))
    return path_sets, ring_sets, masks, stats, nested


m.v.FAIRING_SCALE_TRIALS = [PROBE_SCALE]
m.v.fit_periodic_spline = m.fit_periodic_lowpass
m.v.build_trial = build_trial_shore_clipped
m.v.main()

# Match rendering to the QC domain constraint. All nonzero depth fills and isobath
# strokes are clipped by the v4.5 shoreline path, using even-odd semantics so lake
# holes/islands remain holes.
svg = m.v.OUT_SVG.read_text()
match = re.search(r'<path id="depth-fill-0" d="([^"]+)"', svg)
if not match:
    raise RuntimeError("could not locate v4.5 shoreline path for domain clip")
shore_d = match.group(1)
defs = (
    '<defs><clipPath id="lake-domain-v45">'
    f'<path d="{shore_d}" clip-rule="evenodd"/>'
    '</clipPath></defs>'
)
svg = svg.replace('<g id="depth-bands">', defs + '<g id="depth-bands">', 1)
svg = re.sub(
    r'<path id="depth-fill-([1-7])"',
    r'<path id="depth-fill-\1" clip-path="url(#lake-domain-v45)"',
    svg,
)
svg = re.sub(
    r'<path id="isobath-([1-7])m"',
    r'<path id="isobath-\1m" clip-path="url(#lake-domain-v45)"',
    svg,
)
m.v.OUT_SVG.write_text(svg)

report = json.loads(m.v.OUT_REPORT.read_text())
report["method"] = (
    "Gaussian depth-threshold occupancy -> 0.5 iso-contours -> uniform arc-length "
    "resampling -> periodic Gaussian low-pass of x(s),y(s) targeting grid/scallop "
    "wavelength -> periodic cubic spline / exact SVG cubic Bezier spans -> exact "
    "shoreline-domain clipping; 7–8 m micro-features retain v4.4 geometry"
)
report["fairing_filter"] = {
    "type": "periodic Gaussian low-pass in contour arc length",
    "base_sigma_by_threshold_px": m.BASE_ARCLENGTH_SIGMA_PX,
    "sigma_multipliers": m.SIGMA_MULTIPLIERS,
    "svg_knot_spacing_px": m.SVG_KNOT_SPACING_PX,
    "hard_displacement_limits_px": m.v.MAX_DISP_BY_THRESHOLD_PX,
    "selected_scale": PROBE_SCALE,
    "unfaired_thresholds_m": [7],
    "interpretation": "broad-zone sigma is about 0.74 source px at the selected scale, approximately halving a 4 px scallop while retaining about 97% of a 20 px feature",
}
report["shoreline_domain_clip"] = {
    "enabled": True,
    "reason": "bathymetric layers are defined only inside the lake; removes sub-pixel fairing spill onto land",
    "clip_id": "lake-domain-v45",
}
m.v.OUT_REPORT.write_text(json.dumps(report, indent=2))
