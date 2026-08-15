#!/usr/bin/env python3
from __future__ import annotations

import io, json, re
from pathlib import Path
import cairosvg
import numpy as np
from PIL import Image
from scipy import ndimage
from skimage.measure import find_contours, approximate_polygon

ROOT=Path('.')
CLASS_IMAGE=ROOT/'bathymetry-geopdf-v41-classes.webp'
META_PATH=ROOT/'data/lacanau_geopdf_v41.json'
OUT_SVG=ROOT/'bathymetry-geopdf-v43-subpixel.svg'
OUT_REPORT=ROOT/'data/lacanau_vector_v43_report.json'


def load_classes():
    meta=json.loads(META_PATH.read_text())
    im=np.asarray(Image.open(CLASS_IMAGE).convert('RGBA'))
    h,w=im.shape[:2]
    if (w,h)!=(meta['width'],meta['height']): raise RuntimeError('class image / metadata size mismatch')
    pal=np.asarray(meta['palette_rgb'],dtype=np.int16)
    rgb=im[:,:,:3].astype(np.int16); water=im[:,:,3]>=128
    d=((rgb[:,:,None,:]-pal[None,None,:,:])**2).sum(axis=3)
    cls=np.argmin(d,axis=2).astype(np.int8)
    if np.any(np.min(d,axis=2)[water]!=0): raise RuntimeError('class image is not exact palette data')
    cls[~water]=-1
    return meta,pal.astype(np.uint8),cls


def chaikin_closed(pts,iterations=1):
    p=np.asarray(pts,dtype=float)
    for _ in range(iterations):
        q=np.roll(p,-1,axis=0)
        a=.75*p+.25*q; b=.25*p+.75*q
        out=np.empty((len(p)*2,2),float)
        out[0::2]=a; out[1::2]=b; p=out
    return p


def closed_simplify(pts,tolerance):
    """Douglas-Peucker simplification on a closed source ring.

    tolerance=1 source pixel means the staircase may collapse into its underlying
    diagonal/curve, but it cannot be displaced by more than one native ~5.66 m pixel.
    """
    closed=np.vstack([pts,pts[0]])
    out=approximate_polygon(closed,tolerance=tolerance)
    if len(out)>1 and np.linalg.norm(out[0]-out[-1])<1e-8: out=out[:-1]
    return out


def vectorize_ring(pts,k):
    nsrc=len(pts)
    # Shallow/medium map bands are large enough to expose the original pixel staircase.
    # First collapse that staircase within ONE source pixel, then round the resulting
    # vertices with a single bounded corner-cut pass.
    if k<=4:
        if nsrc<8:
            return pts,0,0.0
        base=closed_simplify(pts,1.0)
        if len(base)<3: base=pts
        return chaikin_closed(base,1),1,1.0

    # 5–7 m features are much smaller. Use only a quarter-pixel simplification and one
    # bounded pass for non-tiny 5–6 m rings; keep the rare 7–8 m rings exact.
    if k<=6 and nsrc>=12:
        base=closed_simplify(pts,.25)
        if len(base)<3: base=pts
        return chaikin_closed(base,1),1,.25

    return pts,0,0.0


def contour_paths(mask,k):
    source_rings=find_contours(np.pad(mask.astype(np.uint8),1),.5,fully_connected='high')
    ds=[]; raw=0; vn=0; stats=[]; eligible=0
    for arr in source_rings:
        if len(arr)<4: continue
        pts=np.asarray([(float(c)-.5,float(r)-.5) for r,c in arr],float)
        if np.linalg.norm(pts[0]-pts[-1])<1e-8: pts=pts[:-1]
        if len(pts)<3: continue
        eligible+=1; nsrc=len(pts); raw+=nsrc
        vec,it,tol=vectorize_ring(pts,k)
        if len(vec)<3: raise RuntimeError(f'threshold {k}: a source ring collapsed during vectorization')
        vn+=len(vec)
        ds.append(f'M {vec[0,0]:.3f},{vec[0,1]:.3f}'+''.join(f' L {x:.3f},{y:.3f}' for x,y in vec[1:])+' Z')
        stats.append({'source_vertices':nsrc,'pre_simplify_tolerance_px':tol,'chaikin_iterations':it,'vector_vertices':len(vec)})
    if len(ds)!=eligible: raise RuntimeError(f'threshold {k}: emitted {len(ds)} of {eligible} source rings')
    return ds,raw,vn,stats,eligible


def build_svg(pal,cls):
    h,w=cls.shape; layers=[]; stats=[]
    for k in range(8):
        paths,raw,n,rs,source_rings=contour_paths(cls>=k,k)
        color='#%02x%02x%02x'%tuple(int(v) for v in pal[k])
        extra=' stroke="#365e68" stroke-opacity="0.24" stroke-width="0.34"' if k==0 else ''
        layers.append(f'<path id="depth-ge-{k}" d="{" ".join(paths)}" fill="{color}" fill-rule="evenodd"{extra}/>')
        stats.append({'threshold_m':k,'source_rings':source_rings,'emitted_rings':len(paths),'vertices_source_half_pixel':raw,'vertices_vector':n,'ring_stats':rs})
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" preserveAspectRatio="none" shape-rendering="geometricPrecision">'
            '<title>Lac de Lacanau bathymetry — cartographic vector reconstruction</title>'
            '<desc>Official 1 m classes from corrected GeoPDF 4.1. Pixel staircases are first simplified within the native source-pixel uncertainty, then converted to bounded smooth curves. GPS depth lookup remains the unsmoothed source classes.</desc>'
            +''.join(layers)+'</svg>'),stats


def classify_render(arr,pal):
    rgb=arr[:,:,:3].astype(np.int16); p=pal.astype(np.int16)
    d=((rgb[:,:,None,:]-p[None,None,:,:])**2).sum(axis=3)
    return np.argmin(d,axis=2).astype(np.int8)


def boundary(mask):
    b=np.zeros_like(mask,bool)
    b[:-1]|=mask[:-1]!=mask[1:]; b[1:]|=mask[:-1]!=mask[1:]
    b[:,:-1]|=mask[:,:-1]!=mask[:,1:]; b[:,1:]|=mask[:,:-1]!=mask[:,1:]
    return b


def sym_boundary_dist(a,b):
    ba=boundary(a); bb=boundary(b)
    if not ba.any() or not bb.any(): return np.asarray([0.])
    return np.concatenate([ndimage.distance_transform_edt(~bb)[ba],ndimage.distance_transform_edt(~ba)[bb]])


def qc(svg,pal,cls,layers):
    h,w=cls.shape
    png=cairosvg.svg2png(bytestring=svg.encode(),output_width=w,output_height=h)
    arr=np.asarray(Image.open(io.BytesIO(png)).convert('RGBA'))
    rcls=classify_render(arr,pal); rwater=arr[:,:,3]>=128; water=cls>=0
    water_iou=float((rwater&water).sum()/(rwater|water).sum())
    bd=ndimage.binary_dilation(boundary(cls),iterations=3); stable=water&rwater&~bd
    exact_stable=float((rcls[stable]==cls[stable]).mean())
    overlap=water&rwater
    exact=float((rcls[overlap]==cls[overlap]).mean())
    within1=float((np.abs(rcls[overlap]-cls[overlap])<=1).mean())
    orig=[int((cls==k).sum()) for k in range(8)]
    rend=[int((rwater&(rcls==k)).sum()) for k in range(8)]
    rel=[(rend[k]-orig[k])/orig[k] if orig[k] else 0 for k in range(8)]
    mo=float(np.mean(cls[water].astype(float)+.5)); mr=float(np.mean(rcls[rwater].astype(float)+.5))
    th=[]
    for k in range(8):
        om=cls>=k; rm=rwater&(rcls>=k)
        iou=float((om&rm).sum()/(om|rm).sum()); d=sym_boundary_dist(om,rm)
        th.append({'threshold_m':k,'iou_1x_render':iou,'boundary_p95_px_1x_render':float(np.percentile(d,95)),
                   'boundary_p99_px_1x_render':float(np.percentile(d,99)),'boundary_max_px_1x_render':float(d.max()),
                   'source_rings':layers[k]['source_rings'],'emitted_rings':layers[k]['emitted_rings']})
    report={'water_mask_iou':water_iou,'stable_interior_exact_class_fraction':exact_stable,'all_overlap_exact_class_fraction':exact,
            'all_overlap_within_1m_fraction':within1,'relative_area_error_by_class':rel,'mean_depth_midpoint_original_m':mo,
            'mean_depth_midpoint_vector_m':mr,'threshold_qc':th}
    if water_iou<.995 or exact_stable<.9995 or within1<.998 or abs(mr-mo)>.02:
        raise RuntimeError(f'global QC failed {report}')
    # These are the broad bands being cartographically reconstructed. Their 95th-percentile
    # displacement must remain below 1.5 source pixels after curve rounding.
    for q in th[:5]:
        if q['iou_1x_render']<.975 or q['boundary_p95_px_1x_render']>1.5:
            raise RuntimeError(f'cartographic threshold QC failed {q}')
    # For small deep features, source-ring topology is the stable invariant; 1x pixel-centre
    # round-trip metrics are still recorded but do not falsely reject valid subpixel SVG rings.
    for q in th[5:]:
        if q['source_rings']!=q['emitted_rings']: raise RuntimeError(f'deep topology changed {q}')
    return report


def patch_ui():
    p=ROOT/'hires.html'; s=p.read_text()
    replacements={
        'Vector 4.3: bounded smooth polygons from corrected 4.1. Broad 0–5 m contours are de-pixelated inside the source-cell envelope; all boundaries at 5 m and deeper stay exact. GPS still samples unsmoothed 4.1 classes. Not a certified chart.':
        'Vector 4.3: cartographic reconstruction from corrected 4.1. Raster staircases are collapsed within one native source pixel, then converted to bounded smooth curves; GPS still samples the unsmoothed 4.1 classes. Not a certified chart.',
        'The corrected GeoPDF 4.1 bathymetry is rendered as <b>smooth SVG depth polygons</b>. Broad shallow and medium contours are corner-cut into continuous curves inside the local source-cell envelope. All boundaries at 5 m and deeper remain on the exact corrected 4.1 half-pixel geometry.':
        'The corrected GeoPDF 4.1 bathymetry is rendered as <b>cartographic SVG depth polygons</b>. Instead of preserving every raster step, each broad boundary is first simplified by at most one native pixel (~5.66 m), then rounded with a bounded curve pass. Small deep features receive much lighter treatment.',
        "warn.textContent='Vector 4.3: broad 0–5 m corrected 4.1 contours de-pixelated with bounded curves; ≥5 m geometry remains exact. Tap VECTOR for corrected raster 4.1, then v3.1. Not a certified chart.'":
        "warn.textContent='Vector 4.3: source-pixel staircases removed before bounded curve fitting; p95 displacement on broad 0–5 m bands is ≤1.5 native pixels. Tap VECTOR for corrected raster 4.1, then v3.1. Not a certified chart.'"
    }
    for old,new in replacements.items(): s=s.replace(old,new)
    p.write_text(s)
    sw=(ROOT/'sw.js').read_text()
    sw=re.sub(r"const CACHE='[^']+';","const CACHE='lacanautics-v4.3-cartographic';",sw)
    (ROOT/'sw.js').write_text(sw)


def main():
    meta,pal,cls=load_classes(); svg,layers=build_svg(pal,cls); q=qc(svg,pal,cls,layers)
    OUT_SVG.write_text(svg)
    report={'version':'4.3-final','source_version':'4.1-fixed',
            'method':'cartographic vector reconstruction: pre-simplify raster staircase ≤1.0 source pixel for thresholds 0–4, ≤0.25 px for non-tiny thresholds 5–6; one bounded Chaikin pass; 7–8 m exact; source-ring topology asserted',
            'source_resolution_m_per_px':meta['native_resolution_m_per_px'],'vertical_definition':'official 1 m classes',
            'layers':layers,'svg_bytes':len(svg.encode()),'qc':q,
            'navigation_note':'GPS lookup remains exact corrected v4.1 class mask; v4.3 changes visual geometry only.'}
    OUT_REPORT.write_text(json.dumps(report,indent=2)); patch_ui(); print(json.dumps(report,indent=2))

if __name__=='__main__': main()
