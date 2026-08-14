#!/usr/bin/env python3
"""Build Lacanautics bathymetry v2.

Key changes from v1:
- full lake mask comes from the complete vector shoreline already in bathymetry.svg,
  instead of the convex hull of the survey tracks;
- smooth inverse-distance weighting (IDW) replaces piecewise-linear Delaunay triangles;
- shoreline points are added as zero-depth constraints;
- numeric grid includes a confidence class based on distance to an actual OFB sounding;
- isolated >8 m values are rejected after coordinate-level median aggregation.

The official soundings are GPS-referenced WGS84 points. The shoreline vector is only used as a
geographic mask/zero-depth constraint and remains approximate; it does not turn this into a
certified chart.
"""
from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.path import Path as MplPath
import numpy as np
from scipy.spatial import cKDTree

ROOT = Path(".")
SRC = ROOT / "data/lacanau_soundings.geojson"
OLD_SVG = ROOT / "bathymetry.svg"
OUT_GRID = ROOT / "data/lacanau_depth_grid_v2.json"
OUT_REPORT = ROOT / "data/lacanau_hires_v2_report.json"
OUT_SVG = ROOT / "bathymetry-v2.svg"

# Calibration used by the original vectorized source. Unlike v1, the official depth points do not
# use this transform; it is used only to place the old complete shoreline mask in WGS84.
G_LON_W, G_LON_E = -1.14573, -1.09121
G_X_W, G_X_E = 436.0, 735.0
G_LAT_N, G_LAT_S = 45.00505, 44.93401
G_Y_N, G_Y_S = 110.0, 676.0

GRID_M = 20.0
IDW_K = 16
IDW_POWER = 2.0
IDW_SMOOTH_M = 12.0
BOUNDARY_STEP_M = 35.0
MAX_EXTRAPOLATION_M = 500.0

LEVELS = np.arange(0.0, 8.01, 0.5)
COLORS = [
    "#d9f6f2", "#c6efee", "#afe5ec", "#96d9eb",
    "#7bc9e9", "#61b9e6", "#49a8df", "#3b94d7",
    "#327fcd", "#2f6bc2", "#3158b4", "#3548a5",
    "#343a93", "#312e80", "#2c246c", "#251c58",
]


def old_px_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon = G_LON_W + (x - G_X_W) * (G_LON_E - G_LON_W) / (G_X_E - G_X_W)
    lat = G_LAT_N - (y - G_Y_N) * (G_LAT_N - G_LAT_S) / (G_Y_S - G_Y_N)
    return lon, lat


def read_full_shoreline() -> np.ndarray:
    root = ET.parse(OLD_SVG).getroot()
    path_el = None
    for el in root.iter():
        if el.attrib.get("id") == "depth-0":
            path_el = el
            break
    if path_el is None:
        raise RuntimeError("depth-0 shoreline path not found in bathymetry.svg")
    d = path_el.attrib["d"]
    # depth-0 is a polygon made only of M/L-style coordinate pairs and Z.
    nums = [float(v) for v in re.findall(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", d)]
    if len(nums) < 20 or len(nums) % 2:
        raise RuntimeError("Could not parse shoreline path")
    px = np.asarray(list(zip(nums[0::2], nums[1::2])), dtype=float)
    ll = np.asarray([old_px_to_lonlat(x, y) for x, y in px], dtype=float)
    if not np.allclose(ll[0], ll[-1]):
        ll = np.vstack([ll, ll[0]])
    return ll


def densify_ring(xy: np.ndarray, step: float) -> np.ndarray:
    out = []
    for a, b in zip(xy[:-1], xy[1:]):
        dist = float(np.linalg.norm(b - a))
        n = max(1, int(math.ceil(dist / step)))
        for t in np.linspace(0.0, 1.0, n, endpoint=False):
            out.append(a * (1.0 - t) + b * t)
    return np.asarray(out, dtype=float)


def main() -> None:
    fc = json.loads(SRC.read_text(encoding="utf-8"))
    raw = []
    for f in fc["features"]:
        lon, lat = map(float, f["geometry"]["coordinates"])
        d = float(f["properties"]["depth_m"])
        raw.append((lon, lat, d))

    # Robust coordinate-level median, then reject values incompatible with the published lake max.
    groups = defaultdict(list)
    for lon, lat, d in raw:
        groups[(round(lon, 7), round(lat, 7))].append(d)
    points = []
    rejected = []
    for (lon, lat), ds in groups.items():
        d = float(np.median(ds))
        if d < 0:
            continue
        if d > 8.0:
            rejected.append([lon, lat, d])
            continue
        points.append((lon, lat, d))
    arr = np.asarray(points, dtype=float)

    shore_ll = read_full_shoreline()
    # Geographic frame is the full shoreline, with a tiny rendering margin.
    west = float(shore_ll[:, 0].min())
    east = float(shore_ll[:, 0].max())
    south = float(shore_ll[:, 1].min())
    north = float(shore_ll[:, 1].max())
    lat0 = (south + north) / 2.0
    mx = 111320.0 * math.cos(math.radians(lat0))
    my = 111320.0

    def to_xy(lon, lat):
        return np.column_stack(((np.asarray(lon) - west) * mx, (np.asarray(lat) - south) * my))

    shore_xy = to_xy(shore_ll[:, 0], shore_ll[:, 1])
    lake_path = MplPath(shore_xy, closed=True)
    boundary_xy = densify_ring(shore_xy, BOUNDARY_STEP_M)

    real_xy = to_xy(arr[:, 0], arr[:, 1])
    real_d = arr[:, 2]
    real_tree = cKDTree(real_xy)

    # Synthetic zero-depth constraints at the full shoreline. They prevent the IDW surface from
    # bleeding across land while still permitting conservative extrapolation into under-surveyed bays.
    source_xy = np.vstack([real_xy, boundary_xy])
    source_d = np.concatenate([real_d, np.zeros(len(boundary_xy), dtype=float)])
    source_tree = cKDTree(source_xy)

    width = float((east - west) * mx)
    height = float((north - south) * my)
    nx = int(round(width / GRID_M)) + 1
    ny = int(round(height / GRID_M)) + 1
    gx = np.linspace(0.0, width, nx)
    gy = np.linspace(0.0, height, ny)
    XX, YY = np.meshgrid(gx, gy)
    query = np.column_stack([XX.ravel(), YY.ravel()])
    inside = lake_path.contains_points(query, radius=1.0)

    Zflat = np.full(len(query), np.nan, dtype=float)
    Cflat = np.zeros(len(query), dtype=np.uint8)
    nearest_flat = np.full(len(query), np.nan, dtype=float)

    qi = np.flatnonzero(inside)
    q = query[qi]
    nearest_real, _ = real_tree.query(q, k=1)
    dists, ids = source_tree.query(q, k=min(IDW_K, len(source_xy)))
    if dists.ndim == 1:
        dists = dists[:, None]
        ids = ids[:, None]
    weights = 1.0 / np.power(dists * dists + IDW_SMOOTH_M * IDW_SMOOTH_M, IDW_POWER / 2.0)
    vals = source_d[ids]
    z = np.sum(weights * vals, axis=1) / np.sum(weights, axis=1)

    # Keep the full lake visible. Values far from any real sounding are retained only to 500 m and
    # are explicitly marked low confidence rather than silently turning into missing holes.
    good = nearest_real <= MAX_EXTRAPOLATION_M
    Zflat[qi[good]] = np.clip(z[good], 0.0, 8.0)
    nearest_flat[qi] = nearest_real
    c = np.where(nearest_real <= 75.0, 3,
        np.where(nearest_real <= 175.0, 2,
        np.where(nearest_real <= 325.0, 1, 0))).astype(np.uint8)
    Cflat[qi] = c

    Z = Zflat.reshape(ny, nx)
    C = Cflat.reshape(ny, nx)
    nearest_grid = nearest_flat.reshape(ny, nx)
    Zstore = np.where(np.isfinite(Z), np.round(Z / 0.05) * 0.05, np.nan)

    # Smooth-looking contours now come from IDW rather than triangular facets.
    zz = np.ma.masked_invalid(Z)
    fig_w = 6.0
    fig_h = fig_w * height / width
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=130)
    ax.set_position([0, 0, 1, 1])
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.contourf(XX, YY, zz, levels=LEVELS, colors=COLORS, antialiased=True, extend="max")
    ax.contour(XX, YY, zz, levels=np.arange(0.5, 8.0, 0.5), colors="#1b5367", linewidths=0.28, alpha=0.48)
    ax.contour(XX, YY, zz, levels=np.arange(1.0, 8.0, 1.0), colors="#153b49", linewidths=0.62, alpha=0.72)
    # Low-confidence region boundary, deliberately subtle.
    sparse = np.ma.masked_where(~np.isfinite(nearest_grid), nearest_grid)
    try:
        ax.contour(XX, YY, sparse, levels=[175, 325], colors=["#365c66", "#6c7578"], linewidths=[0.45, 0.65], linestyles=["dashed", "dotted"], alpha=0.45)
    except ValueError:
        pass
    # Full shoreline on top.
    ax.plot(shore_xy[:, 0], shore_xy[:, 1], color="#173d49", linewidth=0.8, alpha=0.78)
    fig.savefig(OUT_SVG, format="svg", transparent=True, pad_inches=0)
    plt.close(fig)

    rows = [[None if not np.isfinite(v) else float(v) for v in row] for row in Zstore]
    conf_rows = [[int(v) for v in row] for row in C]
    grid = {
        "version": "2.0",
        "source": "OFB/SIE official WGS84 soundings + vector shoreline mask",
        "method": f"shoreline-aware IDW k={IDW_K}, p={IDW_POWER}, smooth={IDW_SMOOTH_M:g}m; {GRID_M:g}m grid",
        "bbox": {"west": west, "south": south, "east": east, "north": north},
        "nx": nx,
        "ny": ny,
        "display_aspect": height / width,
        "confidence": {"0": "very low / >325m from sounding", "1": "low", "2": "medium", "3": "high"},
        "rows_south_to_north": rows,
        "confidence_rows_south_to_north": conf_rows,
    }
    OUT_GRID.write_text(json.dumps(grid, separators=(",", ":")), encoding="utf-8")

    valid = np.isfinite(Z)
    report = {
        "version": "2.0",
        "input_unique_soundings": len(raw),
        "used_soundings": len(points),
        "rejected_gt_8m_after_coordinate_median": rejected,
        "shoreline_vertices": int(len(shore_ll)),
        "shoreline_constraints": int(len(boundary_xy)),
        "depth_m": {"min": float(real_d.min()), "max": float(real_d.max()), "median": float(np.median(real_d))},
        "bbox_wgs84": {"west": west, "south": south, "east": east, "north": north},
        "grid": {
            "nx": nx,
            "ny": ny,
            "spacing_x_m": width / (nx - 1),
            "spacing_y_m": height / (ny - 1),
            "valid_cells": int(valid.sum()),
            "inside_lake_cells": int(inside.sum()),
        },
        "confidence_cells": {
            "high": int((C == 3).sum()),
            "medium": int((C == 2).sum()),
            "low": int((C == 1).sum()),
            "very_low_or_unresolved": int(((C == 0) & valid).sum()),
        },
        "warning": "Indicative bathymetry only. Shoreline mask is approximate and contours are interpolated, not surveyed contour lines.",
    }
    OUT_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
