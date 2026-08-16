#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests
from pyproj import Transformer
from shapely.geometry import Point, mapping, shape
from shapely.ops import transform, unary_union

ROOT = Path('.')
OUT = ROOT / 'data/lacanau_open_water_mask.geojson'
REPORT = ROOT / 'data/lacanau_open_water_mask_report.json'
BBOX = (-1.155, 44.925, -1.075, 45.010)  # west,south,east,north
SEED = Point(-1.116, 44.982)
WFS = 'https://data.geopf.fr/wfs/ows'
TYPENAME = 'BDTOPO_V3:surface_hydrographique'


def fetch_bdtopo():
    params = {
        'SERVICE': 'WFS', 'REQUEST': 'GetFeature', 'VERSION': '2.0.0',
        'TYPENAMES': TYPENAME,
        'SRSNAME': 'urn:ogc:def:crs:OGC:1.3:CRS84',
        'BBOX': f'{BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]},urn:ogc:def:crs:OGC:1.3:CRS84',
        'OUTPUTFORMAT': 'application/json', 'COUNT': '1000',
    }
    r = requests.get(WFS, params=params, timeout=60)
    r.raise_for_status()
    data = r.json()
    if not data.get('features'):
        raise RuntimeError('IGN BD TOPO WFS returned no hydrographic surfaces')
    return data, r.url


def prop(p, *names):
    for n in names:
        if p.get(n) not in (None, ''):
            return p[n]
    return None


def main():
    data, url = fetch_bdtopo()
    features = []
    for f in data['features']:
        try:
            g = shape(f['geometry']).buffer(0)
        except Exception:
            continue
        p = f.get('properties', {})
        features.append((g, p))

    # Use only permanent, non-marsh surface water. IGN explicitly models intermittent
    # lake fringes and marshes separately; those are land for this navigation map.
    eligible = []
    counts = Counter()
    intermittent_lacanau = []
    marshes = []
    for g, p in features:
        nature = str(prop(p, 'nature', 'NATURE') or '')
        persistence = str(prop(p, 'persistance', 'PERSISTANC') or '')
        name = str(prop(p, 'cpx_toponyme_de_plan_d_eau', 'NOM_P_EAU', 'nom_p_eau') or '')
        counts[(nature, persistence)] += 1
        if persistence.lower() == 'permanent' and nature.lower() != 'marais':
            eligible.append(g)
        if persistence.lower() == 'intermittent' and 'lacanau' in name.lower():
            intermittent_lacanau.append(g)
        if nature.lower() == 'marais':
            marshes.append(g)

    u = unary_union(eligible).buffer(0)
    parts = [u] if u.geom_type == 'Polygon' else list(u.geoms)
    selected = [g for g in parts if g.buffer(1e-8).contains(SEED)]
    if not selected:
        selected = [max(parts, key=lambda x: x.area)]
    main_water = unary_union(selected).buffer(0)

    # Simplify in Lambert-93 by 1.5 m: below both bathymetry source grids while
    # keeping the committed mask compact and deterministic.
    to_l93 = Transformer.from_crs('EPSG:4326', 'EPSG:2154', always_xy=True).transform
    to_wgs = Transformer.from_crs('EPSG:2154', 'EPSG:4326', always_xy=True).transform
    l93 = transform(to_l93, main_water)
    simplified = l93.simplify(1.5, preserve_topology=True)
    out_geom = transform(to_wgs, simplified)

    feature = {
        'type': 'Feature',
        'properties': {
            'name': 'Lac de Lacanau permanent open water',
            'authority': 'IGN BD TOPO V3',
            'rule': 'persistance=Permanent; nature!=Marais; component containing main-lake seed',
            'simplification_m': 1.5,
        },
        'geometry': mapping(out_geom),
    }
    OUT.write_text(json.dumps(feature, separators=(',', ':'), ensure_ascii=False) + '\n', encoding='utf-8')

    intermittent_area = transform(to_l93, unary_union(intermittent_lacanau)).area if intermittent_lacanau else 0.0
    marsh_area = transform(to_l93, unary_union(marshes)).area if marshes else 0.0
    report = {
        'version': '1.0-permanent-water-shoreline',
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'authority': 'IGN BD TOPO V3 surface_hydrographique',
        'source_wfs_url': url,
        'source_bbox_wgs84': BBOX,
        'selection_rule': 'Keep permanent non-marsh hydrography and the connected component containing the main lake seed; reject intermittent lake fringes and marshes.',
        'seed_lon_lat': [SEED.x, SEED.y],
        'source_feature_count': len(features),
        'nature_persistence_counts': [
            {'nature': k[0], 'persistance': k[1], 'count': v}
            for k, v in sorted(counts.items())
        ],
        'main_open_water_area_m2': float(l93.area),
        'main_open_water_area_km2': float(l93.area / 1e6),
        'intermittent_lacanau_fringe_area_in_query_m2': float(intermittent_area),
        'marsh_area_in_query_m2': float(marsh_area),
        'simplification_m': 1.5,
        'simplified_area_change_fraction': float((simplified.area - l93.area) / l93.area),
        'cross_checks': [
            'IGN BD TOPO distinguishes permanent water from intermittent lake fringe and Marais.',
            'SIAEBVELG/GestEau wetland studies describe extensive wetland mosaics on the east side of the Médoc lakes.',
            'The 2012 Aquabio bathymetry remains the depth source only; it no longer defines the present-day shoreline.',
        ],
    }
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
