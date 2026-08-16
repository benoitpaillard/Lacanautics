#!/usr/bin/env python3
from pathlib import Path

p = Path('index.html')
s = p.read_text(encoding='utf-8')

old = "let transformRAF=0;function apply(){if(transformRAF)return;transformRAF=requestAnimationFrame(()=>{transformRAF=0;world.style.transform=`translate3d(${tx}px,${ty}px,0) scale(${scale})`;updateTiles()})}"
new = "function clampView(){const vw=innerWidth,vh=innerHeight,mw=W*scale,mh=H*scale;if(mw<=vw)tx=(vw-mw)/2;else tx=Math.min(0,Math.max(vw-mw,tx));if(mh<=vh)ty=(vh-mh)/2;else ty=Math.min(0,Math.max(vh-mh,ty))}let transformRAF=0;function apply(){if(transformRAF)return;transformRAF=requestAnimationFrame(()=>{transformRAF=0;clampView();world.style.transform=`translate3d(${tx}px,${ty}px,0) scale(${scale})`;updateTiles()})}"

if old not in s:
    if 'function clampView(){' in s:
        print('Pan clamp already active')
    else:
        raise RuntimeError('apply() transform block not found')
else:
    s = s.replace(old, new, 1)

s = s.replace("register('./sw.js?v=singlepage7-homedepth')", "register('./sw.js?v=singlepage8-panclamp')")
p.write_text(s, encoding='utf-8')

p = Path('sw.js')
sw = p.read_text(encoding='utf-8')
sw = sw.replace('lacanautics-v4.5-singlepage7-homedepth', 'lacanautics-v4.5-singlepage8-panclamp')
p.write_text(sw, encoding='utf-8')

html = Path('index.html').read_text(encoding='utf-8')
sw = Path('sw.js').read_text(encoding='utf-8')
assert 'function clampView(){' in html
assert 'mw<=vw' in html and 'mh<=vh' in html
assert 'Math.max(vw-mw,tx)' in html and 'Math.max(vh-mh,ty)' in html
assert 'clampView();world.style.transform=' in html
assert "sw.js?v=singlepage8-panclamp" in html
assert 'lacanautics-v4.5-singlepage8-panclamp' in sw
print('Map panning is clamped to the map extent.')
