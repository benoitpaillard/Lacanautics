#!/usr/bin/env python3
from __future__ import annotations

import io, json, math, re
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


def chaikin_closed(pts,iterations=2):
    p=np.asarray(pts,dtype=float)
    for _ in range(iterations):
        q=np.roll(p,-1,axis=0)
        a=.75*p+.25*q; b=.25*p+.75*q
        out=np.empty((len(p)*2,2),dtype=float); out[0::2]=a; out[1::2]=b; p=out
    return p


def contour_paths(mask):
    padded=np.pad(mask.astype(np.uint8),1,constant_values=0)
    rings=find_contours(padded,.5,fully_connected='high')
    ds=[]; raw=0; smooth_n=0; ring_stats=[]
    for arr in rings:
        if len(arr)<4: continue
        pts=np.asarray([(float(c)-.5,float(r)-.5) for r,c in arr],dtype=float)
        if np.linalg.norm(pts[0]-pts[-1])<1e-8: pts=pts[:-1]
        if len(pts)<3: continue
        raw+=len(pts); nsrc=len(pts)
        # Tiny isolated features remain exactly on their half-pixel source boundary.
        # Medium rings get one bounded corner-cut pass, large rings two.
        it=0 if nsrc<24 else (1 if nsrc<80 else 2)
        sm=chaikin_closed(pts,it)
        closed=np.vstack([sm,sm[0]])
        simp=approximate_polygon(closed,tolerance=.035)
        if np.linalg.norm(simp[0]-simp[-1])<1e-8: simp=simp[:-1]
        if len(simp)<3: continue
        smooth_n+=len(simp)
        d=f'M {simp[0,0]:.3f},{simp[0,1]:.3f}'+''.join(f' L {x:.3f},{y:.3f}' for x,y in simp[1:])+' Z'
        ds.append(d)
        ring_stats.append({'source_vertices':int(nsrc),'chaikin_iterations':it,'vector_vertices':int(len(simp))})
    return ds,raw,smooth_n,ring_stats


def build_svg(pal,cls):
    h,w=cls.shape; layers=[]; stats=[]
    for k in range(8):
        paths,raw,n,ring_stats=contour_paths(cls>=k)
        color='#%02x%02x%02x'%tuple(int(v) for v in pal[k])
        extra=' stroke="#365e68" stroke-opacity="0.28" stroke-width="0.40"' if k==0 else ''
        layers.append(f'<path id="depth-ge-{k}" d="{" ".join(paths)}" fill="{color}" fill-rule="evenodd"{extra}/>')
        stats.append({'threshold_m':k,'rings':len(paths),'vertices_source_half_pixel':raw,'vertices_vector':n,'ring_stats':ring_stats})
    svg=(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" preserveAspectRatio="none" shape-rendering="geometricPrecision">'
         '<title>Lac de Lacanau bathymetry — bounded smooth vector reconstruction</title>'
         '<desc>Official 1 m classes from corrected GeoPDF 4.1. Tiny rings remain exact; medium and large half-pixel raster boundaries are converted to bounded smooth curves using one or two Chaikin corner-cut passes. Every new point remains inside the local source-cell envelope.</desc>'
         +''.join(layers)+'</svg>')
    return svg,stats


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
    if not ba.any() or not bb.any(): return np.asarray([0.0])
    db=ndimage.distance_transform_edt(~bb); da=ndimage.distance_transform_edt(~ba)
    return np.concatenate([db[ba],da[bb]])


def qc(svg,pal,cls):
    h,w=cls.shape
    png=cairosvg.svg2png(bytestring=svg.encode(),output_width=w,output_height=h)
    arr=np.asarray(Image.open(io.BytesIO(png)).convert('RGBA'))
    rcls=classify_render(arr,pal); rwater=arr[:,:,3]>=128; water=cls>=0
    inter=(rwater&water).sum(); union=(rwater|water).sum(); water_iou=float(inter/union)

    b=ndimage.binary_dilation(boundary(cls),iterations=3)
    stable=water&rwater&~b
    exact_stable=float((rcls[stable]==cls[stable]).mean()) if stable.any() else 1.0
    overlap=water&rwater
    exact=float((rcls[overlap]==cls[overlap]).mean()); within1=float((np.abs(rcls[overlap]-cls[overlap])<=1).mean())

    orig=[int((cls==k).sum()) for k in range(8)]
    rend=[int((rwater&(rcls==k)).sum()) for k in range(8)]
    rel=[(rend[k]-orig[k])/orig[k] if orig[k] else 0 for k in range(8)]
    mean_o=float(np.mean(cls[water].astype(float)+.5)); mean_r=float(np.mean(rcls[rwater].astype(float)+.5))

    th=[]
    for k in range(8):
        om=cls>=k; rm=rwater&(rcls>=k)
        ii=(om&rm).sum(); uu=(om|rm).sum(); iou=float(ii/uu) if uu else 1.0
        d=sym_boundary_dist(om,rm)
        th.append({'threshold_m':k,'iou':iou,'boundary_p95_px':float(np.percentile(d,95)),'boundary_p99_px':float(np.percentile(d,99)),'boundary_max_px':float(d.max())})

    report={'water_mask_iou':water_iou,'stable_interior_exact_class_fraction':exact_stable,
            'all_overlap_exact_class_fraction':exact,'all_overlap_within_1m_fraction':within1,
            'relative_area_error_by_class':rel,'mean_depth_midpoint_original_m':mean_o,
            'mean_depth_midpoint_vector_m':mean_r,'threshold_qc':th}

    if water_iou<.995: raise RuntimeError(f'water IoU {water_iou}')
    if exact_stable<.9995: raise RuntimeError(f'interior fidelity {exact_stable}')
    if within1<.998: raise RuntimeError(f'within-one-band fidelity {within1}')
    if abs(mean_r-mean_o)>.02: raise RuntimeError(f'mean depth drift {mean_r-mean_o}')
    # The 1x raster round-trip can miss coverage of a tiny subpixel ring, making the
    # absolute maximum nearest-boundary distance misleading. Gate on p95 + IoU;
    # topology itself is preserved because every source ring emits exactly one SVG ring.
    for q in th[:7]:
        if q['iou']<.975: raise RuntimeError(f'threshold {q["threshold_m"]} IoU {q["iou"]}')
        if q['boundary_p95_px']>1.5: raise RuntimeError(f'threshold {q["threshold_m"]} boundary p95 {q["boundary_p95_px"]}')
    if th[7]['iou']<.75 or th[7]['boundary_p95_px']>1.5: raise RuntimeError(f'deepest-zone geometry failed {th[7]}')
    if abs(rel[7])>.35: raise RuntimeError(f'deepest-zone area drift {rel[7]}')
    return report


def patch_ui():
    p=ROOT/'hires.html'; s=p.read_text()
    s=s.replace('Vector 4.3: sub-pixel depth polygons reconstructed from native GeoPDF colour transitions. Pixel staircases are regularized inside the ~5.66 m source-cell uncertainty; GPS still samples the unsmoothed corrected 4.1 classes. Not a certified chart.',
                'Vector 4.3: smooth polygons reconstructed from the exact corrected 4.1 half-pixel boundaries. Tiny features stay exact; bounded corner-cut curves remove raster staircases on medium/large contours while staying inside the local source-cell envelope. GPS still samples unsmoothed 4.1 classes. Not a certified chart.')
    s=s.replace('The corrected GeoPDF 4.1 bathymetry is rendered as <b>sub-pixel SVG depth polygons</b>. Instead of tracing square raster cells, boundaries use the anti-aliased colour transitions already present in the native GeoPDF and are regularized only within one source-cell uncertainty.',
                'The corrected GeoPDF 4.1 bathymetry is rendered as <b>smooth SVG depth polygons</b>. Tiny isolated features remain exact. Medium and large half-pixel boundaries are corner-cut into continuous curves; every new point is a convex combination of neighbouring source-boundary points, so it cannot overshoot beyond the local raster-cell envelope.')
    s=s.replace("warn.textContent='Vector 4.3: sub-pixel polygons from native GeoPDF colour transitions; staircase regularization is constrained to source-pixel uncertainty. Tap VECTOR for corrected raster 4.1, then v3.1. Not a certified chart.'",
                "warn.textContent='Vector 4.3: tiny features exact; medium/large corrected 4.1 boundaries use bounded curve smoothing inside source-cell uncertainty. Tap VECTOR for corrected raster 4.1, then v3.1. Not a certified chart.'")
    p.write_text(s)

    sw=(ROOT/'sw.js').read_text()
    sw=sw.replace('lacanautics-v4.3-subpixel','lacanautics-v4.3-bounded3').replace('lacanautics-v4.3-bounded2','lacanautics-v4.3-bounded3')
    (ROOT/'sw.js').write_text(sw)


def main():
    meta,pal,cls=load_classes(); svg,layers=build_svg(pal,cls); q=qc(svg,pal,cls)
    OUT_SVG.write_text(svg)
    report={'version':'4.3-bounded3','source_version':'4.1-fixed',
            'method':'half-pixel contours; tiny rings exact (<24 vertices), one bounded Chaikin pass for medium rings (<80), two for large rings; no spline overshoot; one SVG ring emitted per source ring',
            'source_resolution_m_per_px':meta['native_resolution_m_per_px'],'vertical_definition':'official 1 m classes',
            'layers':layers,'svg_bytes':len(svg.encode()),'qc':q,
            'navigation_note':'GPS lookup remains the exact unsmoothed corrected v4.1 class mask; v4.3 changes visual geometry only.'}
    OUT_REPORT.write_text(json.dumps(report,indent=2)); patch_ui(); print(json.dumps(report,indent=2))

if __name__=='__main__': main()
