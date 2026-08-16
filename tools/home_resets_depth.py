#!/usr/bin/env python3
from pathlib import Path

p=Path('index.html')
s=p.read_text(encoding='utf-8')
old="$('#plus').onclick=()=>zoom(innerWidth/2,innerHeight/2,1.35);$('#minus').onclick=()=>zoom(innerWidth/2,innerHeight/2,.74);$('#fit').onclick=fit;"
new="$('#plus').onclick=()=>zoom(innerWidth/2,innerHeight/2,1.35);$('#minus').onclick=()=>zoom(innerWidth/2,innerHeight/2,.74);$('#fit').onclick=()=>{clearProbe();fit()};"
if old not in s:
    if "$('#fit').onclick=()=>{clearProbe();fit()}" in s:
        print('Home depth reset already active')
    else:
        raise RuntimeError('fit button handler not found')
else:
    s=s.replace(old,new,1)

s=s.replace("register('./sw.js?v=singlepage6-depthprobe')","register('./sw.js?v=singlepage7-homedepth')")
p.write_text(s,encoding='utf-8')

p=Path('sw.js')
sw=p.read_text(encoding='utf-8')
sw=sw.replace('lacanautics-v4.5-singlepage6-depthprobe','lacanautics-v4.5-singlepage7-homedepth')
p.write_text(sw,encoding='utf-8')

html=Path('index.html').read_text(encoding='utf-8')
sw=Path('sw.js').read_text(encoding='utf-8')
assert "$('#fit').onclick=()=>{clearProbe();fit()}" in html
assert "sw.js?v=singlepage7-homedepth" in html
assert 'lacanautics-v4.5-singlepage7-homedepth' in sw
print('Home now resets tapped depth to latest GPS depth before fitting the lake.')
