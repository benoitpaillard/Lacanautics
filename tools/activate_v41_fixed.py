#!/usr/bin/env python3
from pathlib import Path

# Activation rerun after corrected v4.1 assets have landed on main.
p=Path('hires.html'); s=p.read_text(encoding='utf-8')

def rep(old,new):
    global s
    if old not in s: raise SystemExit('Missing expected snippet: '+old[:160])
    s=s.replace(old,new,1)

rep('<title>Lacanautics Survey v3.1</title>','<title>Lacanautics GeoPDF v4.1 fixed</title>')
rep('@media(max-height:650px){.legend,.warn{display:none}}','#sampleCanvas,#classMap{display:none}@media(max-height:650px){.legend,.warn{display:none}}')
rep('<div id="stage"><div id="world"><img id="map" src="bathymetry-2012-v3.webp?v=31" alt="Lac de Lacanau 2012 bathymetry"><svg id="track">',
    '<div id="stage"><div id="world"><img id="map" src="bathymetry-geopdf-v41-native.webp?v=411" alt="Corrected native GeoPDF bathymetry"><svg id="track">')
rep('</div></div>\n<div id="top">','</div></div>\n<img id="classMap" src="bathymetry-geopdf-v41-classes.webp?v=411" alt="" aria-hidden="true"><canvas id="sampleCanvas"></canvas>\n<div id="top">')
rep('<div id="badge" class="badge panel">SURVEY 2012 · NGF corrected</div>','<div id="badge" class="badge panel">GEOPDF 4.1 FIXED · native</div>')
rep('<button id="layer" class="mini"><strong>2012</strong><small>MAP</small></button>','<button id="layer" class="mini"><strong>4.1</strong><small>FIXED</small></button>')
rep('Survey reference: 13.21 m NGF. Lake-level correction is explicit and editable; the latest official value loaded by the app is dated, not live. Not a certified chart.',
    'Corrected GeoPDF 4.1: native strips are vertically oriented per the PDF matrix and stitched with their 1-pixel overlaps removed. Exact GeoPDF georeferencing; 1 m bands @ 13.21 m NGF. Tap 4.1 to compare with v3.1. Not a certified chart.')
rep('<div id="splash" class="splash"><div class="card"><h1>Lacanautics Survey v3.1</h1><p>The map follows the original Aquabio 2012 bathymetric bands. It now converts each band to an absolute bed-elevation interval and adjusts water depth for the selected lake level.</p><p>The latest official level found is loaded with its observation date, and you can change it manually by centimetres.</p><button id="start">Open map + start GPS</button><small>The displayed corrected depth remains an interval, not a fabricated decimal sounding.</small></div></div>',
    '<div id="splash" class="splash"><div class="card"><h1>Lacanautics GeoPDF v4.1 fixed</h1><p>This rebuild fixes the broken strip assembly: each embedded ArcMap strip is vertically flipped exactly as the PDF placement matrix requires, and the five 1-pixel strip overlaps are stitched instead of duplicated.</p><p>The <b>4.1 / 3.1</b> button lets you compare the corrected native GeoPDF directly with the previous Survey v3.1 map.</p><button id="start">Open map + start GPS</button><small>Horizontal source sampling ≈5.66 m/pixel. Vertical definition remains the official 1 m bands.</small></div></div>')

rep("const $=s=>document.querySelector(s),world=$('#world'),stage=$('#stage'),map=$('#map'),me=$('#me'),acc=$('#acc'),line=$('#line'),coord=$('#coord'),meta=$('#meta'),dv=$('#d'),dl=$('#depthLabel'),followBtn=$('#follow'),layerBtn=$('#layer'),levelBtn=$('#level'),badge=$('#badge'),warn=$('#warn'),legend=$('#legend'),overlay=$('#levelOverlay'),levelInput=$('#levelInput'),levelInfo=$('#levelInfo');",
    "const $=s=>document.querySelector(s),world=$('#world'),stage=$('#stage'),map=$('#map'),classMap=$('#classMap'),canvas=$('#sampleCanvas'),me=$('#me'),acc=$('#acc'),line=$('#line'),coord=$('#coord'),meta=$('#meta'),dv=$('#d'),dl=$('#depthLabel'),followBtn=$('#follow'),layerBtn=$('#layer'),levelBtn=$('#level'),badge=$('#badge'),warn=$('#warn'),legend=$('#legend'),overlay=$('#levelOverlay'),levelInput=$('#levelInput'),levelInfo=$('#levelInfo');")
rep("let W=1000,H=1670,B=null,scale=1,tx=0,ty=0,follow=true,last=null,watch=null,points=[],survey=null,model=null,mode='survey',pointers=new Map(),gesture=null,ready=false,levelCfg=null,lastSurveyBand=null;",
    "let W=971,H=1427,B=null,scale=1,tx=0,ty=0,follow=true,last=null,watch=null,points=[],survey=null,v41=null,mode='v41',pointers=new Map(),gesture=null,ready=false,levelCfg=null,lastSurveyBand=null,classCtx=null;")
rep("const REF=13.21,surveyURL='data/lacanau_2012_bands_v3.json?v=31',modelURL='data/lacanau_depth_grid_v2.json?v=31',levelURL='data/lacanau_lake_level.json?v=31';",
    "const REF=13.21,surveyURL='data/lacanau_2012_bands_v3.json?v=411',v41URL='data/lacanau_geopdf_v41.json?v=411',levelURL='data/lacanau_lake_level.json?v=411';")

old_config="function configure(){B=survey.bbox;const lat0=(B.south+B.north)/2*Math.PI/180,widthM=(B.east-B.west)*111320*Math.cos(lat0),heightM=(B.north-B.south)*111320;H=Math.round(W*heightM/widthM);world.style.width=W+'px';world.style.height=H+'px';$('#track').setAttribute('viewBox',`0 0 ${W} ${H}`);document.querySelectorAll('.poi').forEach(e=>{const p=ll(+e.dataset.lat,+e.dataset.lon);e.style.left=p.x+'px';e.style.top=p.y+'px'});ready=true;coord.textContent='GPS not started';meta.textContent='Aquabio 2012 · NGF-aware depth bands';fit()}"
new_config="function configure(){if(mode==='v41'){B=v41.bbox;W=v41.width;H=v41.height;map.src='bathymetry-geopdf-v41-native.webp?v=411';badge.textContent='GEOPDF 4.1 FIXED · native';warn.textContent='Corrected GeoPDF 4.1: strip orientation + 1-pixel overlap stitching fixed; exact embedded georeferencing; 1 m depth bands @ 13.21 m NGF. Tap 4.1 to compare v3.1. Not a certified chart.';layerBtn.innerHTML='<strong>4.1</strong><small>FIXED</small>';meta.textContent='Corrected native GeoPDF · ~5.66 m/px'}else{B=survey.bbox;W=1000;const lat0=(B.south+B.north)/2*Math.PI/180,widthM=(B.east-B.west)*111320*Math.cos(lat0),heightM=(B.north-B.south)*111320;H=Math.round(W*heightM/widthM);map.src='bathymetry-2012-v3.webp?v=411';badge.textContent='SURVEY v3.1 · previous';warn.textContent='Survey v3.1 comparison view: Peche33/Aquabio 2012 raster reconstruction with NGF correction. Tap 3.1 to return to corrected GeoPDF 4.1.';layerBtn.innerHTML='<strong>3.1</strong><small>VIEW</small>';meta.textContent='Survey v3.1 comparison'}world.style.width=W+'px';world.style.height=H+'px';$('#track').setAttribute('viewBox',`0 0 ${W} ${H}`);points=[];line.setAttribute('points','');document.querySelectorAll('.poi').forEach(e=>{const p=ll(+e.dataset.lat,+e.dataset.lon);e.style.left=p.x+'px';e.style.top=p.y+'px'});ready=true;coord.textContent='GPS not started';fit()}"
rep(old_config,new_config)

old_promise="Promise.all([fetch(surveyURL,{cache:'no-store'}).then(r=>r.json()),fetch(levelURL,{cache:'no-store'}).then(r=>r.ok?r.json():null).catch(()=>null)]).then(([s,l])=>{survey=s;levelCfg=l;if(!localStorage.getItem('lacanauticsLakeLevel')&&l?.latest_official_level_ngf_m)lakeLevel=Number(l.latest_official_level_ngf_m);saveLevel(lakeLevel);configure()}).catch(e=>{coord.textContent='Survey v3.1 still deploying';meta.textContent='Reload shortly · '+e.message});"
new_promise="Promise.all([fetch(surveyURL,{cache:'no-store'}).then(r=>r.json()),fetch(v41URL,{cache:'no-store'}).then(r=>r.json()),fetch(levelURL,{cache:'no-store'}).then(r=>r.ok?r.json():null).catch(()=>null),new Promise((resolve,reject)=>{if(classMap.complete&&classMap.naturalWidth)resolve();else{classMap.onload=resolve;classMap.onerror=()=>reject(Error('4.1 class image failed'))}})]).then(([s,v,l])=>{survey=s;v41=v;levelCfg=l;canvas.width=v.width;canvas.height=v.height;classCtx=canvas.getContext('2d',{willReadFrequently:true});classCtx.imageSmoothingEnabled=false;classCtx.drawImage(classMap,0,0,v.width,v.height);if(!localStorage.getItem('lacanauticsLakeLevel')&&l?.latest_official_level_ngf_m)lakeLevel=Number(l.latest_official_level_ngf_m);saveLevel(lakeLevel);configure()}).catch(e=>{coord.textContent='GeoPDF 4.1 still deploying';meta.textContent='Reload shortly · '+e.message});"
rep(old_promise,new_promise)

marker="function surveySample(lat,lon){"
if marker not in s: raise SystemExit('surveySample marker missing')
v41sample="function v41Sample(lat,lon){if(!v41||!classCtx)return null;const b=v41.bbox;if(lon<b.west||lon>b.east||lat<b.south||lat>b.north)return null;const x=Math.max(0,Math.min(v41.width-1,Math.round((lon-b.west)/(b.east-b.west)*(v41.width-1)))),y=Math.max(0,Math.min(v41.height-1,Math.round((b.north-lat)/(b.north-b.south)*(v41.height-1))));const p=classCtx.getImageData(x,y,1,1).data;if(p[3]<128)return null;let best=-1,bd=1e9;for(let k=0;k<v41.palette_rgb.length;k++){const c=v41.palette_rgb[k],d=(p[0]-c[0])**2+(p[1]-c[1])**2+(p[2]-c[2])**2;if(d<bd){bd=d;best=k}}return best>=0?{band:best}:null}\n"
s=s.replace(marker,v41sample+marker,1)

old_update="function updateDepth(lat,lon){if(mode==='survey'){const z=surveySample(lat,lon);lastSurveyBand=z?.band??null;if(z){const q=bandInfo(z.band);dv.textContent=`${fmt(q.currentLo)}–${fmt(q.currentHi)} m`;dl.textContent=`2012: ${z.band}–${z.band+1} m · bed ${fmt(q.bedLo)}–${fmt(q.bedHi)} NGF`}else{dv.textContent='—';dl.textContent='land / no survey class'}}else{lastSurveyBand=null;const z=modelSample(lat,lon);if(z){dv.textContent=z.depth.toFixed(1)+' m';dl.textContent=`2008 model · ${confNames[z.conf]||'unknown'}`}else{dv.textContent='—';dl.textContent='outside model'}}updateLevelInfo()}"
new_update="function updateDepth(lat,lon){const z=mode==='v41'?v41Sample(lat,lon):surveySample(lat,lon);lastSurveyBand=z?.band??null;if(z){const q=bandInfo(z.band);dv.textContent=`${fmt(q.currentLo)}–${fmt(q.currentHi)} m`;dl.textContent=`${mode==='v41'?'4.1 GeoPDF':'3.1 survey'}: ${z.band}–${z.band+1} m · bed ${fmt(q.bedLo)}–${fmt(q.bedHi)} NGF`}else{dv.textContent='—';dl.textContent='land / no survey class'}updateLevelInfo()}"
rep(old_update,new_update)
rep("function fail(e){coord.textContent='GPS unavailable';meta.textContent=!isSecureContext?'Open the HTTPS GitHub Pages URL':e.code===1?'Allow precise location for this site':e.message||'Check location settings'}function start(){if(!ready){meta.textContent='Wait for Survey v3.1 to load';return}",
    "function fail(e){coord.textContent='GPS unavailable';meta.textContent=!isSecureContext?'Open the HTTPS GitHub Pages URL':e.code===1?'Allow precise location for this site':e.message||'Check location settings'}function start(){if(!ready){meta.textContent='Wait for map to load';return}")

start=s.index('async function toggleLayer()')
end=s.index("$('#plus').onclick",start)
new_toggle="function toggleLayer(){mode=mode==='v41'?'v31':'v41';configure();if(last){const p=ll(last.coords.latitude,last.coords.longitude);me.style.left=p.x+'px';me.style.top=p.y+'px';updateDepth(last.coords.latitude,last.coords.longitude)}}\n"
s=s[:start]+new_toggle+s[end:]

s=s.replace("${mode==='survey'?'corrected depth '+dv.textContent:'model depth '+dv.textContent}","${mode==='v41'?'4.1 depth ':'3.1 depth '}${dv.textContent}")
p.write_text(s,encoding='utf-8')

idx=Path('index.html').read_text(encoding='utf-8')
idx=idx.replace('Lacanautics Survey v3.1','Lacanautics GeoPDF v4.1 fixed').replace('Survey v3.1','GeoPDF v4.1 fixed')
import re
idx=re.sub(r'hires\.html\?v=\d+','hires.html?v=411',idx)
Path('index.html').write_text(idx,encoding='utf-8')

sw=Path('sw.js').read_text(encoding='utf-8')
sw=re.sub(r"const CACHE='[^']+';","const CACHE='lacanautics-v4.1-fixed';",sw)
sw=re.sub(r"const CORE=\[[^;]+;","const CORE=['./','./index.html','./hires.html','./manifest.webmanifest','./bathymetry-geopdf-v41-native.webp','./bathymetry-geopdf-v41-classes.webp','./data/lacanau_geopdf_v41.json','./bathymetry-2012-v3.webp','./data/lacanau_2012_bands_v3.json','./data/lacanau_lake_level.json'];",sw)
Path('sw.js').write_text(sw,encoding='utf-8')

man=Path('manifest.webmanifest').read_text(encoding='utf-8')
man=man.replace('Aquabio 2012 bathymetric depth bands with live GPS for Lac de Lacanau','Corrected native GeoPDF 2012 bathymetry with v3.1 comparison and live GPS for Lac de Lacanau')
Path('manifest.webmanifest').write_text(man,encoding='utf-8')
print('Activated corrected v4.1 with v3.1 comparison toggle')
