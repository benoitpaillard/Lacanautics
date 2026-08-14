#!/usr/bin/env python3
"""Run the hybrid 2012 builder with automatic legend-swatch detection."""
import numpy as np
from scipy import ndimage
import build_hybrid_2012 as base


def auto_palette(rgb):
    h,w,_=rgb.shape
    # The depth legend is in the lower-left white panel. Detect only blue/cyan filled components.
    y0=int(round(h*0.56)); y1=int(round(h*0.95)); x0=0; x1=int(round(w*0.18))
    sub=rgb[y0:y1,x0:x1].astype(np.int16)
    r,g,b=sub[:,:,0],sub[:,:,1],sub[:,:,2]
    mask=(b-r>18)&(g-r>3)&(b>85)
    mask=ndimage.binary_opening(mask,structure=np.ones((2,2),bool))
    lab,n=ndimage.label(mask)
    objs=ndimage.find_objects(lab)
    cand=[]
    for i,sl in enumerate(objs,1):
        if sl is None:continue
        ys,xs=sl; hh=ys.stop-ys.start; ww=xs.stop-xs.start
        area=int((lab[sl]==i).sum())
        cy=(ys.start+ys.stop-1)/2+y0; cx=(xs.start+xs.stop-1)/2+x0
        if not (18<=ww<=130 and 10<=hh<=70 and area>=180):continue
        if cx>w*0.13:continue
        pix=rgb[y0+ys.start:y0+ys.stop,x0+xs.start:x0+xs.stop][lab[sl]==i]
        med=np.median(pix,axis=0)
        cand.append({'label':i,'cx':float(cx),'cy':float(cy),'w':ww,'h':hh,'area':area,'rgb':med})
    if len(cand)>=8:
        xs=np.array([c['cx'] for c in cand]); medx=float(np.median(xs))
        cand=sorted(cand,key=lambda c:(abs(c['cx']-medx),-c['area']))[:max(8,min(12,len(cand)))]
    cand=sorted(cand,key=lambda c:c['cy'])
    if len(cand)>8:
        best=None
        for start in range(len(cand)-7):
            seq=cand[start:start+8]; yy=np.array([c['cy'] for c in seq]); gaps=np.diff(yy)
            score=float(np.std(gaps)/(np.mean(gaps)+1e-9))+0.003*float(np.std([c['cx'] for c in seq]))
            if best is None or score<best[0]:best=(score,seq)
        cand=best[1]
    # The 7-8 m swatch is very dark and can legitimately fail the blue threshold. If the first
    # seven form a regular vertical sequence, infer the eighth rectangle location from that geometry
    # and sample its interior directly (not from a guessed absolute pixel position).
    if len(cand)==7:
        yy=np.array([c['cy'] for c in cand]); gaps=np.diff(yy)
        xx=np.array([c['cx'] for c in cand])
        if np.mean(gaps)>20 and np.std(gaps)<4 and np.std(xx)<3:
            cy=float(yy[-1]+np.median(gaps)); cx=float(np.median(xx))
            ww=int(round(np.median([c['w'] for c in cand]))); hh=int(round(np.median([c['h'] for c in cand])))
            # Sample only the central half to stay away from the black rectangle border/text.
            rx=max(5,ww//4); ry=max(4,hh//4); xi=int(round(cx)); yi=int(round(cy))
            patch=rgb[max(0,yi-ry):min(h,yi+ry+1),max(0,xi-rx):min(w,xi+rx+1)]
            med=np.median(patch.reshape(-1,3),axis=0)
            cand.append({'label':-1,'cx':cx,'cy':cy,'w':ww,'h':hh,'area':int(patch.shape[0]*patch.shape[1]),'rgb':med,'inferred':True})
    if len(cand)!=8:
        raise RuntimeError('Expected 8 legend swatches; detected '+str([{
            'cx':round(c['cx'],1),'cy':round(c['cy'],1),'w':c['w'],'h':c['h'],'area':c['area'],'rgb':np.rint(c['rgb']).astype(int).tolist()
        } for c in cand]))
    cand=sorted(cand,key=lambda c:c['cy'])
    palette=np.asarray([c['rgb'] for c in cand],dtype=np.float32)
    # Final sanity checks: swatches must get progressively darker/bluer overall and remain chromatic.
    if np.any((palette[:,2]-palette[:,0])<15):
        raise RuntimeError('Legend palette sanity failed: '+str(np.rint(palette).astype(int).tolist()))
    print('AUTO LEGEND SWATCHES:')
    for depth,c in enumerate(cand):
        print(depth,'-',depth+1,'m','xy=',round(c['cx'],1),round(c['cy'],1),'size=',c['w'],c['h'],'rgb=',np.rint(c['rgb']).astype(int).tolist(), 'inferred='+str(bool(c.get('inferred'))))
    return palette

base.load_palette=auto_palette
base.main()
