#!/usr/bin/env python3
from pathlib import Path
import json
import re

ROOT=Path('.')

# 1) Remove the rendered depth-number labels from the production SVG now.
p=ROOT/'bathymetry-geopdf-v45-taubin.svg'
s=p.read_text(encoding='utf-8')
s2,n=re.subn(r'<g id="depth-labels"[^>]*>.*?</g>','',s,flags=re.S)
if n==0 and '<text ' in s2:
    raise RuntimeError('depth label group not found')
p.write_text(s2,encoding='utf-8')

report=ROOT/'data/lacanau_vector_v45_taubin_report.json'
r=json.loads(report.read_text(encoding='utf-8'))
r['depth_label_count']=0
r['navigation_note']='GPS and tap/click depth lookup remain exact corrected v4.1 classes; rendered isobath numbers are intentionally omitted.'
report.write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8')

# 2) Make future v4.5 rebuilds label-free as well.
p=ROOT/'tools/build_vector_v45_taubin.py'
s=p.read_text(encoding='utf-8')
old="        '<g id=\"depth-labels\" pointer-events=\"none\">' + ''.join(labels) + '</g>'\n"
if old in s:
    s=s.replace(old,'')
# Force the report to state zero labels even though the old label-position loop remains harmless.
needle="    svg = (\n"
if 'label_count = 0\n    svg = (' not in s:
    s=s.replace(needle,"    label_count = 0\n"+needle,1)
p.write_text(s,encoding='utf-8')

# 3) Add a tap/click depth probe to the app.
p=ROOT/'index.html'
s=p.read_text(encoding='utf-8')

if '.probe{' not in s:
    s=s.replace(
        '.me{position:absolute;display:none;transform:translate(-50%,-50%);width:24px;height:24px;border-radius:50%;background:var(--blue);border:4px solid #fff;box-shadow:0 2px 8px #0006,0 0 0 4px #087fc033;pointer-events:none}',
        '.me{position:absolute;display:none;transform:translate(-50%,-50%);width:24px;height:24px;border-radius:50%;background:var(--blue);border:4px solid #fff;box-shadow:0 2px 8px #0006,0 0 0 4px #087fc033;pointer-events:none}.probe{position:absolute;display:none;transform:translate(-50%,-50%);width:18px;height:18px;border:2px solid #ffd54a;border-radius:50%;box-shadow:0 0 0 2px #0008,0 0 8px #000;pointer-events:none}.probe:before,.probe:after{content:\'\';position:absolute;background:#ffd54a;left:50%;top:50%;transform:translate(-50%,-50%)}.probe:before{width:24px;height:2px}.probe:after{width:2px;height:24px}'
    )

if 'id="probe"' not in s:
    s=s.replace('<div id="me" class="me"></div>','<div id="me" class="me"></div><div id="probe" class="probe"></div>',1)

s=s.replace("me=$('#me'),acc=", "me=$('#me'),probe=$('#probe'),acc=")
s=s.replace(
    "lastSurveyBand=null,classCtx=null;",
    "lastSurveyBand=null,classCtx=null,probeActive=false,lastProbe=null,tapState=null;"
)

s=s.replace(
    "<p>The corrected GeoPDF 4.1 bathymetry is rendered as <b>compact Taubin-smoothed SVG iso-contours</b>. The proven v4.4 contours are non-shrinking low-pass filtered only where the scalloping is visible, then simplified and nested by clipping. The 1–7 m isobaths are drawn and labelled on top.</p>",
    "<p>The corrected GeoPDF 4.1 bathymetry is rendered as <b>compact Taubin-smoothed iso-contours</b>. Depth numbers are intentionally omitted for clarity. <b>Tap or click anywhere on the lake to read its depth band.</b></p>"
)

# Make the level-info sheet identify whether its current band came from GPS or a tap.
s=s.replace("gps=`<b>At GPS</b><br>2012 band:", "gps=`<b>${probeActive?'At tapped point':'At GPS'}</b><br>2012 band:")

# Preserve a tapped reading when lake level changes.
s=s.replace(
    "updateLevelInfo();if(last)updateDepth(last.coords.latitude,last.coords.longitude)}",
    "updateLevelInfo();if(probeActive&&lastProbe)showProbe(lastProbe.lat,lastProbe.lon);else if(last)updateDepth(last.coords.latitude,last.coords.longitude)}",
    1
)

probe_funcs=r'''function showProbe(lat,lon){
  if(!ready)return;
  const p=ll(lat,lon);
  if(p.x<0||p.x>W||p.y<0||p.y>H)return;
  lastProbe={lat,lon};probeActive=true;follow=false;followBtn.classList.remove('active');
  Object.assign(probe.style,{display:'block',left:p.x+'px',top:p.y+'px'});
  const z=mode==='v31'?surveySample(lat,lon):v41Sample(lat,lon);
  lastSurveyBand=z?.band??null;
  if(z){
    const q=bandInfo(z.band),mid=(q.currentLo+q.currentHi)/2;
    dv.textContent=`${fmt(q.currentLo)}–${fmt(q.currentHi)} m`;
    dl.textContent=`Tap ≈${fmt(mid)} m midpoint · source band ${z.band}–${z.band+1} m`;
  }else{
    dv.textContent='—';dl.textContent='Tapped point: land / no surveyed depth';
  }
  updateLevelInfo();
}
function probeAtScreen(sx,sy){
  const x=(sx-tx)/scale,y=(sy-ty)/scale;
  if(x<0||x>W||y<0||y>H)return;
  const lon=B.west+x/W*(B.east-B.west),lat=B.north-y/H*(B.north-B.south);
  showProbe(lat,lon);
}
function clearProbe(){
  probeActive=false;lastProbe=null;probe.style.display='none';
  if(last)updateDepth(last.coords.latitude,last.coords.longitude);
}'''
if 'function showProbe(lat,lon)' not in s:
    s=s.replace('function gps(pos){',probe_funcs+'\nfunction gps(pos){',1)

# GPS should not overwrite an actively inspected tapped depth.
s=s.replace(
    "}updateDepth(c.latitude,c.longitude);coord.textContent=",
    "}if(!probeActive)updateDepth(c.latitude,c.longitude);coord.textContent=",
    1
)

# Reproject the probe when switching between the two maps.
s=s.replace(
    "function toggleLayer(){mode=mode==='vector'?'v31':'vector';configure();if(last){const p=ll(last.coords.latitude,last.coords.longitude);me.style.left=p.x+'px';me.style.top=p.y+'px';updateDepth(last.coords.latitude,last.coords.longitude)}}",
    "function toggleLayer(){mode=mode==='vector'?'v31':'vector';configure();if(probeActive&&lastProbe)showProbe(lastProbe.lat,lastProbe.lon);else if(last){const p=ll(last.coords.latitude,last.coords.longitude);me.style.left=p.x+'px';me.style.top=p.y+'px';updateDepth(last.coords.latitude,last.coords.longitude)}}"
)

# Following/locating returns the depth panel to GPS mode.
s=s.replace(
    "followBtn.onclick=()=>{follow=!follow;followBtn.classList.toggle('active',follow);if(follow&&last){",
    "followBtn.onclick=()=>{follow=!follow;followBtn.classList.toggle('active',follow);if(follow){clearProbe()}if(follow&&last){"
)
s=s.replace("$('#loc').onclick=()=>{follow=true;", "$('#loc').onclick=()=>{clearProbe();follow=true;")
s=s.replace("$('#start').onclick=()=>{$('#splash').style.display='none';follow=true;", "$('#start').onclick=()=>{$('#splash').style.display='none';clearProbe();follow=true;")

old_pointer="const pp=e=>({x:e.clientX,y:e.clientY});stage.onpointerdown=e=>{stage.setPointerCapture(e.pointerId);pointers.set(e.pointerId,pp(e));if(pointers.size===1)gesture={p:[...pointers.values()][0],tx,ty};else{const a=[...pointers.values()];gesture={d:Math.hypot(a[1].x-a[0].x,a[1].y-a[0].y),s:scale,tx,ty,cx:(a[0].x+a[1].x)/2,cy:(a[0].y+a[1].y)/2}}};stage.onpointermove=e=>{if(!pointers.has(e.pointerId))return;pointers.set(e.pointerId,pp(e));follow=false;followBtn.classList.remove('active');if(pointers.size===1&&gesture?.p){const p=[...pointers.values()][0];tx=gesture.tx+p.x-gesture.p.x;ty=gesture.ty+p.y-gesture.p.y;apply()}else if(pointers.size===2&&gesture?.d){const a=[...pointers.values()],dd=Math.hypot(a[1].x-a[0].x,a[1].y-a[0].y),cx=(a[0].x+a[1].x)/2,cy=(a[0].y+a[1].y)/2,ns=Math.max(.25,Math.min(14,gesture.s*dd/gesture.d)),wx=(gesture.cx-gesture.tx)/gesture.s,wy=(gesture.cy-gesture.ty)/gesture.s;scale=ns;tx=cx-wx*ns;ty=cy-wy*ns;apply()}};stage.onpointerup=stage.onpointercancel=e=>{pointers.delete(e.pointerId);gesture=null};"
new_pointer="const pp=e=>({x:e.clientX,y:e.clientY});stage.onpointerdown=e=>{stage.setPointerCapture(e.pointerId);pointers.set(e.pointerId,pp(e));if(pointers.size===1){gesture={p:[...pointers.values()][0],tx,ty};tapState={id:e.pointerId,x:e.clientX,y:e.clientY,t:performance.now(),moved:false}}else{if(tapState)tapState.moved=true;const a=[...pointers.values()];gesture={d:Math.hypot(a[1].x-a[0].x,a[1].y-a[0].y),s:scale,tx,ty,cx:(a[0].x+a[1].x)/2,cy:(a[0].y+a[1].y)/2}}};stage.onpointermove=e=>{if(!pointers.has(e.pointerId))return;pointers.set(e.pointerId,pp(e));if(tapState&&tapState.id===e.pointerId&&Math.hypot(e.clientX-tapState.x,e.clientY-tapState.y)>8)tapState.moved=true;if(pointers.size>1||tapState?.moved){follow=false;followBtn.classList.remove('active')}if(pointers.size===1&&gesture?.p){const p=[...pointers.values()][0];tx=gesture.tx+p.x-gesture.p.x;ty=gesture.ty+p.y-gesture.p.y;apply()}else if(pointers.size===2&&gesture?.d){const a=[...pointers.values()],dd=Math.hypot(a[1].x-a[0].x,a[1].y-a[0].y),cx=(a[0].x+a[1].x)/2,cy=(a[0].y+a[1].y)/2,ns=Math.max(.25,Math.min(14,gesture.s*dd/gesture.d)),wx=(gesture.cx-gesture.tx)/gesture.s,wy=(gesture.cy-gesture.ty)/gesture.s;scale=ns;tx=cx-wx*ns;ty=cy-wy*ns;apply()}};stage.onpointerup=e=>{const isTap=tapState&&tapState.id===e.pointerId&&!tapState.moved&&performance.now()-tapState.t<700&&pointers.size===1;if(isTap)probeAtScreen(e.clientX,e.clientY);pointers.delete(e.pointerId);tapState=null;gesture=null};stage.onpointercancel=e=>{pointers.delete(e.pointerId);tapState=null;gesture=null};"
if old_pointer not in s:
    if 'stage.onpointerdown' in s and 'probeAtScreen' not in s[s.find('stage.onpointerdown'):]:
        raise RuntimeError('pointer handler shape changed')
else:
    s=s.replace(old_pointer,new_pointer)

s=s.replace("register('./sw.js?v=singlepage5-oledblack')","register('./sw.js?v=singlepage6-depthprobe')")
p.write_text(s,encoding='utf-8')

p=ROOT/'sw.js'
s=p.read_text(encoding='utf-8').replace('lacanautics-v4.5-singlepage5-oledblack','lacanautics-v4.5-singlepage6-depthprobe')
p.write_text(s,encoding='utf-8')

# Sanity checks.
html=(ROOT/'index.html').read_text(encoding='utf-8')
svg=(ROOT/'bathymetry-geopdf-v45-taubin.svg').read_text(encoding='utf-8')
assert '<text ' not in svg
assert 'id="depth-labels"' not in svg
assert 'function showProbe(lat,lon)' in html
assert 'function probeAtScreen(sx,sy)' in html
assert 'Tap ≈' in html
assert 'tapState' in html
assert 'singlepage6-depthprobe' in html
print('Removed map depth figures and added tap/click depth probe.')
