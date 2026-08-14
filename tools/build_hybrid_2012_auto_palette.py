#!/usr/bin/env python3
"""Run the hybrid 2012 builder with automatic legend-swatch detection."""
import numpy as np
from scipy import ndimage
import build_hybrid_2012 as base


def auto_palette(rgb):
    h,w,_=rgb.shape
    # The depth legend is in the lower-left white panel. Detect only blue/cyan filled components.
    y0=int(round(h*0.56)); y1=int(round(h*0.94)); x0=0; x1=int(round(w*0.18))
    sub=rgb[y0:y1,x0:x1].astype(np.int16)
    r,g,b=sub[:,:,0],sub[:,:,1],sub[:,:,2]
    mask=(b-r>18)&(g-r>3)&(b>85)
    # Remove one-pixel compression noise, then label solid swatches.
    mask=ndimage.binary_opening(mask,structure=np.ones((2,2),bool))
    lab,n=ndimage.label(mask)
    objs=ndimage.find_objects(lab)
    cand=[]
    for i,sl in enumerate(objs,1):
        if sl is None:continue
        ys,xs=sl; hh=ys.stop-ys.start; ww=xs.stop-xs.start
        area=int((lab[sl]==i).sum())
        cy=(ys.start+ys.stop-1)/2+y0; cx=(xs.start+xs.stop-1)/2+x0
        # At 2048px width the swatches are roughly 65x30 px. Keep generous bounds for resized copies.
        if not (18<=ww<=130 and 10<=hh<=70 and area>=180):continue
        if cx>w*0.13:continue
        pix=rgb[y0+ys.start:y0+ys.stop,x0+xs.start:x0+xs.stop][lab[sl]==i]
        med=np.median(pix,axis=0)
        cand.append({'label':i,'cx':float(cx),'cy':float(cy),'w':ww,'h':hh,'area':area,'rgb':med})
    # The eight swatches share almost the same x coordinate. Prefer the dominant x cluster.
    if len(cand)>=8:
        xs=np.array([c['cx'] for c in cand]); medx=float(np.median(xs))
        cand=sorted(cand,key=lambda c:(abs(c['cx']-medx),-c['area']))[:max(8,min(12,len(cand)))]
    cand=sorted(cand,key=lambda c:c['cy'])
    # If extra blue components survived, find the best sequence of 8 with regular vertical spacing.
    if len(cand)>8:
        best=None
        for start in range(len(cand)-7):
            seq=cand[start:start+8]; yy=np.array([c['cy'] for c in seq]); gaps=np.diff(yy)
            score=float(np.std(gaps)/(np.mean(gaps)+1e-9))+0.003*float(np.std([c['cx'] for c in seq]))
            if best is None or score<best[0]:best=(score,seq)
        cand=best[1]
    if len(cand)!=8:
        raise RuntimeError('Expected 8 legend swatches; detected '+str([{
            'cx':round(c['cx'],1),'cy':round(c['cy'],1),'w':c['w'],'h':c['h'],'area':c['area'],'rgb':np.rint(c['rgb']).astype(int).tolist()
        } for c in cand]))
    palette=np.asarray([c['rgb'] for c in cand],dtype=np.float32)
    print('AUTO LEGEND SWATCHES:')
    for depth,c in enumerate(cand):
        print(depth,'-',depth+1,'m', 'xy=',round(c['cx'],1),round(c['cy'],1),'size=',c['w'],c['h'],'rgb=',np.rint(c['rgb']).astype(int).tolist())
    return palette

base.load_palette=auto_palette
base.main()
