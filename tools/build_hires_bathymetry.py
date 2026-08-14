#!/usr/bin/env python3
"""Build Lacanautics bathymetry v2.1.

Fixes the two mask problems seen in v2:
- the lake mask is reconstructed from the UNION of every vector depth layer, rather than treating
  the 0–1 m layer as the shoreline (which incorrectly cut out the deep centre);
- true holes that remain absent from every depth layer are preserved as land/islands, including
  the southern islands.

The depth surface uses shoreline-aware IDW on the official OFB WGS84 soundings. Every water cell
gets an indicative value; areas far from real soundings are not hidden, but are marked very-low
confidence. This is situational-awareness data, not a certified navigation chart.
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
import numpy as np
from scipy.spatial import cKDTree
from shapely import contains_xy
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection
from shapely.ops import unary_union

ROOT = Path(".")
SRC = ROOT / "data/lacanau_soundings.geojson"
OLD_SVG = ROOT / "bathymetry.svg"
OUT_GRID = ROOT / "data/lacanau_depth_grid_v2.json"
OUT_REPORT = ROOT / "data/lacanau_hires_v2_report.json"
OUT_SVG = ROOT / "bathymetry-v2.svg"

# Calibration of the original vectorized raster. Official sounding coordinates are NOT transformed
# through this; this affine transform is used only to turn the vector lake/island geometry into WGS84.
G_LON_W, G_LON_E = -1.14573, -1.09121
G_X_W, G_X_E = 436.0, 735.0
G_LAT_N, G_LAT_S = 45.00505, 44.93401
G_Y_N, G_Y_S = 110.0, 676.0

GRID_M = 20.0
IDW_K = 16
IDW_POWER = 2.0
IDW_SMOOTH_M = 12.0
BOUNDARY_STEP_M = 30.0

LEVELS = np.arange(0.0, 8.01, 0.5)
COLORS = [
    "#d9f6f2", "#c6efee", "#afe5ec", "#96d9eb",
    "#7bc9e9", "#61b9e6", "#49a8df", "#3b94d7",
    "#327fcd", "#2f6bc2", "#3158b4", "#3548a5",
    "#343a93", "#312e80", "#2c246c", "#251c58",
]

NUM_RE = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)")
SUBPATH_RE = re.compile(r"[Mm]([^Zz]+)[Zz]")


def old_px_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon = G_LON_W + (x - G_X_W) * (G_LON_E - G_LON_W) / (G_X_E - G_X_W)
    lat = G_LAT_N - (y - G_Y_N) * (G_LAT_N - G_LAT_S) / (G_Y_S - G_Y_N)
    return lon, lat


def path_evenodd_geometry(d: str):
    """Reproduce SVG fill-rule=evenodd from simple M ... Z polygon subpaths."""
    geom = GeometryCollection()
    for body in SUBPATH_RE.findall(d):
        nums = [float(v) for v in NUM_RE.findall(body)]
        if len(nums) < 6:
            continue
        if len(nums) % 2:
            nums = nums[:-1]
        coords = list(zip(nums[0::2], nums[1::2]))
        if len(coords) < 3:
            continue
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        poly = Polygon(coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty:
            continue
        geom = poly if geom.is_empty else geom.symmetric_difference(poly)
    return geom.buffer(0)


def read_water_geometry_px():
    """Union every bathymetric layer. Deep-water holes are filled by deeper layers; islands remain holes."""
    root = ET.parse(OLD_SVG).getroot()
    layers = []
    parsed = []
    for el in root.iter():
        ident = el.attrib.get("id", "")
        if not re.fullmatch(r"depth-\d+", ident):
            continue
        d = el.attrib.get("d", "")
        g = path_evenodd_geometry(d)
        if not g.is_empty:
            layers.append(g)
            parsed.append(ident)
    if not layers:
        raise RuntimeError("No depth-* vector layers found in bathymetry.svg")

    water = unary_union(layers).buffer(0)
    # Ignore tiny detached artefacts outside the main lake if vectorization produced any.
    if isinstance(water, MultiPolygon):
        water = max(water.geoms, key=lambda p: p.area)
    if not isinstance(water, Polygon):
        raise RuntimeError(f"Unexpected reconstructed water geometry: {water.geom_type}")
    return water, parsed


def densify_ring(xy: np.ndarray, step: float) -> np.ndarray:
    out = []
    for a, b in zip(xy[:-1], xy[1:]):
        dist = float(np.linalg.norm(b - a))
        n = max(1, int(math.ceil(dist / step)))
        for t in np.linspace(0.0, 1.0, n, endpoint=False):
            out.append(a * (1.0 - t) + b * t)
    return np.asarray(out, dtype=float)


def ring_px_to_ll(coords) -> np.ndarray:
    return np.asarray([old_px_to_lonlat(float(x), float(y)) for x, y in coords], dtype=float)


def main() -> None:
    fc = json.loads(SRC.read_text(encoding="utf-8"))
    raw = []
    for f in fc["features"]:
        lon, lat = map(float, f["geometry"]["coordinates"])
        d = float(f["properties"]["depth_m"])
        raw.append((lon, lat, d))

    # Coordinate-level robust median, then remove impossible persistent clusters.
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

    water_px, parsed_layers = read_water_geometry_px()
    outer_ll = ring_px_to_ll(water_px.exterior.coords)
    island_ll = [ring_px_to_ll(r.coords) for r in water_px.interiors]

    west = float(outer_ll[:, 0].min())
    east = float(outer_ll[:, 0].max())
    south = float(outer_ll[:, 1].min())
    north = float(outer_ll[:, 1].max())
    lat0 = (south + north) / 2.0
    mx = 111320.0 * math.cos(math.radians(lat0))
    my = 111320.0

    def ll_to_xy(ll: np.ndarray) -> np.ndarray:
        return np.column_stack(((ll[:, 0] - west) * mx, (ll[:, 1] - south) * my))

    outer_xy = ll_to_xy(outer_ll)
    holes_xy = [ll_to_xy(r) for r in island_ll]
    lake_local = Polygon(outer_xy, [h.tolist() for h in holes_xy]).buffer(0)
    if not lake_local.is_valid or lake_local.is_empty:
        raise RuntimeError("Invalid lake geometry after geographic transform")

    # Zero-depth constraints on both outer shoreline and island shorelines.
    boundary_parts = [densify_ring(outer_xy, BOUNDARY_STEP_M)]
    for h in holes_xy:
        boundary_parts.append(densify_ring(h, BOUNDARY_STEP_M))
    boundary_xy = np.vstack(boundary_parts)

    real_xy = np.column_stack(((arr[:, 0] - west) * mx, (arr[:, 1] - south) * my))
    real_d = arr[:, 2]
    real_tree = cKDTree(real_xy)

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
    inside = contains_xy(lake_local, query[:, 0], query[:, 1])

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

    # IMPORTANT v2.1 change: every cell inside water gets a value. Distance controls confidence,
    # not visibility, so there are no unexplained holes in the lake.
    Zflat[qi] = np.clip(z, 0.0, 8.0)
    nearest_flat[qi] = nearest_real
    c = np.where(
        nearest_real <= 75.0, 3,
        np.where(nearest_real <= 175.0, 2,
        np.where(nearest_real <= 325.0, 1, 0)),
    ).astype(np.uint8)
    Cflat[qi] = c

    Z = Zflat.reshape(ny, nx)
    C = Cflat.reshape(ny, nx)
    nearest_grid = nearest_flat.reshape(ny, nx)
    Zstore = np.where(np.isfinite(Z), np.round(Z / 0.05) * 0.05, np.nan)

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

    sparse = np.ma.masked_where(~np.isfinite(nearest_grid), nearest_grid)
    try:
        ax.contour(XX, YY, sparse, levels=[175, 325], colors=["#365c66", "#6c7578"], linewidths=[0.45, 0.65], linestyles=["dashed", "dotted"], alpha=0.45)
    except ValueError:
        pass

    # Shoreline and true island outlines. The transparent holes display as land in the app.
    ax.plot(outer_xy[:, 0], outer_xy[:, 1], color="#173d49", linewidth=0.85, alpha=0.82)
    for h in holes_xy:
        ax.plot(h[:, 0], h[:, 1], color="#173d49", linewidth=0.75, alpha=0.82)
    fig.savefig(OUT_SVG, format="svg", transparent=True, pad_inches=0)
    plt.close(fig)

    rows = [[None if not np.isfinite(v) else float(v) for v in row] for row in Zstore]
    conf_rows = [[int(v) for v in row] for row in C]
    grid = {
        "version": "2.1",
        "source": "OFB/SIE official WGS84 soundings + union-of-depth-layers lake/island mask",
        "method": f"full-water-mask IDW k={IDW_K}, p={IDW_POWER}, smooth={IDW_SMOOTH_M:g}m; {GRID_M:g}m grid",
        "bbox": {"west": west, "south": south, "east": east, "north": north},
        "nx": nx,
        "ny": ny,
        "display_aspect": height / width,
        "confidence": {
            "0": "very low / >325m from sounding",
            "1": "low / 175–325m",
            "2": "medium / 75–175m",
            "3": "high / <=75m",
        },
        "rows_south_to_north": rows,
        "confidence_rows_south_to_north": conf_rows,
    }
    OUT_GRID.write_text(json.dumps(grid, separators=(",", ":")), encoding="utf-8")

    valid = np.isfinite(Z)
    report = {
        "version": "2.1",
        "input_unique_soundings": len(raw),
        "used_soundings": len(points),
        "rejected_gt_8m_after_coordinate_median": rejected,
        "parsed_depth_layers": parsed_layers,
        "water_mask": {
            "exterior_vertices": len(outer_xy),
            "island_holes": len(holes_xy),
            "island_vertices": [len(h) for h in holes_xy],
            "shoreline_constraints": len(boundary_xy),
        },
        "depth_m": {
            "min": float(real_d.min()),
            "max": float(real_d.max()),
            "median": float(np.median(real_d)),
        },
        "bbox_wgs84": {"west": west, "south": south, "east": east, "north": north},
        "grid": {
            "nx": nx,
            "ny": ny,
            "spacing_x_m": width / (nx - 1),
            "spacing_y_m": height / (ny - 1),
            "valid_cells": int(valid.sum()),
            "inside_water_cells": int(inside.sum()),
        },
        "confidence_cells": {
            "high": int((C == 3).sum()),
            "medium": int((C == 2).sum()),
            "low": int((C == 1).sum()),
            "very_low": int(((C == 0) & valid).sum()),
        },
        "warning": "Indicative bathymetry only. Islands/shoreline come from a vectorized public map; contours are interpolated.",
    }
    OUT_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
