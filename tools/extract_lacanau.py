#!/usr/bin/env python3
"""Extract Lac de Lacanau soundings from the French SIE/OFB national lake bathymetry archive.

Source (Open Licence 2.0):
https://data.ofb.fr/catalogue/data-eaufrance/api/records/
c31746f7-311a-41c7-b995-6cb78a2ddc25/attachments/points_bruts_bathy_20161020.zip

The script intentionally keeps the source depth values as measured. Duplicate XY positions are
aggregated with the median only for the lightweight GeoJSON used by the web app; the raw matched
rows are also preserved as CSV.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import statistics
import sys
import unicodedata
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

URL = "https://data.ofb.fr/catalogue/data-eaufrance/api/records/c31746f7-311a-41c7-b995-6cb78a2ddc25/attachments/points_bruts_bathy_20161020.zip"
OUT = Path("data")
OUT.mkdir(exist_ok=True)
ZIP_PATH = OUT / "points_bruts_bathy_20161020.zip"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def download() -> None:
    if ZIP_PATH.exists() and ZIP_PATH.stat().st_size > 1_000_000:
        print(f"Using cached {ZIP_PATH} ({ZIP_PATH.stat().st_size:,} bytes)")
        return
    print("Downloading official OFB/SIE archive...")
    req = urllib.request.Request(URL, headers={"User-Agent": "Lacanautics/1.0 (+https://github.com/benoitpaillard/Lacanautics)"})
    with urllib.request.urlopen(req, timeout=120) as r, ZIP_PATH.open("wb") as f:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    print(f"Downloaded {ZIP_PATH.stat().st_size:,} bytes")


def decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1", errors="replace")


def detect_table(zf: zipfile.ZipFile):
    names = zf.namelist()
    print("Archive members:", names)
    candidates = [n for n in names if n.lower().endswith((".tab", ".csv", ".txt")) and not n.lower().endswith(".info")]
    if not candidates:
        raise RuntimeError(f"No tabular file found in archive: {names}")
    name = max(candidates, key=lambda n: zf.getinfo(n).file_size)
    text = decode(zf.read(name))
    sample = text[:10000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";\t,|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if sample.count("\t") > sample.count(";") else ";"
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if not rows:
        raise RuntimeError("Empty bathymetry table")
    return name, delimiter, rows


def header_index(header):
    nh = [norm(x) for x in header]
    print("Header:", header)
    print("Normalized header:", nh)

    def find(*names):
        wanted = [norm(x) for x in names]
        for w in wanted:
            if w in nh:
                return nh.index(w)
        for i, h in enumerate(nh):
            if any(w and (w in h or h in w) for w in wanted):
                return i
        return None

    return {
        "name": find("Nom_Plan_eau", "NomPlanEau", "Nom", "PlanEau"),
        "code": find("MS_CD", "CodeMasseEau", "CdMasseEau", "Code"),
        "date": find("Date", "DateReleve"),
        "x": find("CoordonneeX", "CoordX", "X"),
        "y": find("CoordonneeY", "CoordY", "Y"),
        "crs": find("CdProj", "Projection", "CodeProjection"),
        "depth": find("Profondeur", "Depth", "Prof"),
        "cbat": find("Cbat"),
        "cref": find("Cref"),
    }


def fnum(v):
    try:
        return float(str(v).strip().replace(" ", "").replace(",", "."))
    except Exception:
        return None


def target_row(row, idx):
    # Prefer semantic fields but keep a robust whole-row fallback for legacy exports.
    vals = " | ".join(row)
    nvals = norm(vals)
    name = row[idx["name"]] if idx["name"] is not None and idx["name"] < len(row) else ""
    code = row[idx["code"]] if idx["code"] is not None and idx["code"] < len(row) else ""
    ncode = norm(code)
    return "lacanau" in norm(name) or "lacanau" in nvals or ncode in {"fl49", "frfl49"} or ncode.endswith("fl49")


def transformer_for(code):
    from pyproj import Transformer
    c = norm(str(code))
    # Sandre: 26 = Lambert-93, 5 = Lambert II étendu.
    if c in {"26", "lambert93", "l93", "epsg2154", "2154"}:
        return Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True), "EPSG:2154"
    if c in {"5", "lambert2etendu", "lambertii", "epsg27572", "27572"}:
        return Transformer.from_crs("EPSG:27572", "EPSG:4326", always_xy=True), "EPSG:27572"
    return None, str(code)


def main():
    download()
    with zipfile.ZipFile(ZIP_PATH) as zf:
        table_name, delim, rows = detect_table(zf)
        info_names = [n for n in zf.namelist() if n.lower().endswith(".info")]
        info_text = decode(zf.read(info_names[0])) if info_names else ""

    header = rows[0]
    idx = header_index(header)
    if idx["x"] is None or idx["y"] is None or idx["depth"] is None:
        raise RuntimeError(f"Could not identify X/Y/depth columns: {idx}")

    matched = [r for r in rows[1:] if target_row(r, idx)]
    if not matched:
        # Diagnostics: show possible water-body codes/names containing 'lac' around the target region.
        sample = [r for r in rows[1:] if "lac" in norm(" | ".join(r))][:50]
        raise RuntimeError("No Lacanau rows found. Sample rows containing 'lac':\n" + "\n".join(map(str, sample)))

    raw_path = OUT / "lacanau_soundings_raw.csv"
    with raw_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(matched)

    pts = []
    crs_counts = Counter()
    bad = Counter()
    for r in matched:
        try:
            x, y, d = fnum(r[idx["x"]]), fnum(r[idx["y"]]), fnum(r[idx["depth"]])
            if x is None or y is None or d is None:
                bad["missing_numeric"] += 1
                continue
            if d < 0:
                bad["negative_depth"] += 1
                continue
            crs_code = r[idx["crs"]] if idx["crs"] is not None and idx["crs"] < len(r) else "26"
            tr, crs_label = transformer_for(crs_code)
            crs_counts[crs_label] += 1
            if tr is None:
                bad["unknown_crs"] += 1
                continue
            lon, lat = tr.transform(x, y)
            if not (-1.25 < lon < -1.0 and 44.85 < lat < 45.1):
                bad["outside_lacanau_bbox"] += 1
                continue
            date = r[idx["date"]].strip() if idx["date"] is not None and idx["date"] < len(r) else ""
            name = r[idx["name"]].strip() if idx["name"] is not None and idx["name"] < len(r) else "Lac de Lacanau"
            code = r[idx["code"]].strip() if idx["code"] is not None and idx["code"] < len(r) else ""
            pts.append({"x": x, "y": y, "lon": lon, "lat": lat, "depth": d, "date": date, "name": name, "code": code, "crs": crs_label})
        except Exception:
            bad["parse_exception"] += 1

    if not pts:
        raise RuntimeError(f"Matched {len(matched)} Lacanau rows but no valid georeferenced points. CRS counts={crs_counts}, bad={bad}")

    # Keep raw values, but collapse repeat pings at identical projected coordinates for the app.
    groups = defaultdict(list)
    meta = {}
    for p in pts:
        key = (round(p["x"], 3), round(p["y"], 3), p["crs"])
        groups[key].append(p["depth"])
        meta[key] = p

    features = []
    for key, depths in groups.items():
        p = meta[key]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(p["lon"], 7), round(p["lat"], 7)]},
            "properties": {
                "depth_m": round(statistics.median(depths), 3),
                "n": len(depths),
                "date": p["date"],
                "source_crs": p["crs"],
            },
        })
    geo = {
        "type": "FeatureCollection",
        "name": "Lac de Lacanau official raw bathymetry soundings (deduplicated by XY)",
        "source": URL,
        "license": "Licence Ouverte / Open Licence 2.0",
        "features": features,
    }
    (OUT / "lacanau_soundings.geojson").write_text(json.dumps(geo, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    depths = [p["depth"] for p in pts]
    lats = [p["lat"] for p in pts]
    lons = [p["lon"] for p in pts]
    dates = sorted({p["date"] for p in pts if p["date"]})
    codes = Counter(p["code"] for p in pts)
    names = Counter(p["name"] for p in pts)
    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "official_source": URL,
        "archive_member": table_name,
        "delimiter_repr": repr(delim),
        "archive_rows_excluding_header": len(rows) - 1,
        "matched_lacanau_rows": len(matched),
        "valid_lacanau_soundings": len(pts),
        "unique_xy_soundings": len(features),
        "depth_m": {"min": min(depths), "max": max(depths), "median": statistics.median(depths)},
        "wgs84_bbox": {"west": min(lons), "south": min(lats), "east": max(lons), "north": max(lats)},
        "dates": dates,
        "codes": dict(codes),
        "names": dict(names),
        "source_crs_counts": dict(crs_counts),
        "rejected": dict(bad),
        "header": header,
        "column_mapping": idx,
        "archive_info": info_text[:12000],
        "notes": [
            "Depth values are preserved from the official raw dataset; negative values are rejected.",
            "Duplicate projected XY positions are median-aggregated only in GeoJSON.",
            "0.1 m storage precision must not be interpreted as 0.1 m survey accuracy.",
        ],
    }
    (OUT / "lacanau_soundings_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
