#!/usr/bin/env python3
from pathlib import Path

p = Path('index.html')
s = p.read_text(encoding='utf-8')

if '#tiles{' not in s:
    s = s.replace(
        '#map{position:absolute;inset:0;width:100%;height:100%;object-fit:fill;pointer-events:none}',
        '#map{position:absolute;inset:0;width:100%;height:100%;object-fit:fill;pointer-events:none}'
        '#tiles{position:absolute;inset:0;display:none;pointer-events:none;overflow:hidden}'
        '.maptile{position:absolute;display:block;pointer-events:none;user-select:none;-webkit-user-drag:none}'
    )

if '<div id="tiles"></div>' not in s:
    s = s.replace('<svg id="track">', '<div id="tiles"></div><svg id="track">', 1)

s = s.replace("map=$('#map'),classMap=", "map=$('#map'),tiles=$('#tiles'),classMap=")

marker = "const FAST_RASTER=matchMedia('(pointer:coarse)').matches||navigator.maxTouchPoints>0||innerWidth<900;"
if "const TILE_ROOT='tiles/mobile-v1'" not in s:
    s = s.replace(
        marker,
        marker + "\nconst TILE_ROOT='tiles/mobile-v1',TILE_PX=1024,TILE_LEVELS=[2,4,8];\n"
        "let tileLevel=0,tileMode='',tileEls=new Map();"
    )

tile_funcs = r'''function resetTiles(){tiles.replaceChildren();tileEls.clear();tileLevel=0;tileMode=''}
function bestTileLevel(){const need=scale*Math.min(window.devicePixelRatio||1,1.5);return need<=2?2:need<=4?4:8}
function updateTiles(){
  if(!FAST_RASTER||!ready){tiles.style.display='none';return}
  const level=bestTileLevel();
  if(tileMode!==mode||tileLevel!==level){tiles.replaceChildren();tileEls.clear();tileMode=mode;tileLevel=level}
  tiles.style.display='block';
  const margin=TILE_PX/level;
  const left=Math.max(0,-tx/scale-margin),top=Math.max(0,-ty/scale-margin);
  const right=Math.min(W,(innerWidth-tx)/scale+margin),bottom=Math.min(H,(innerHeight-ty)/scale+margin);
  const cols=Math.ceil(W*level/TILE_PX),rows=Math.ceil(H*level/TILE_PX);
  const x0=Math.max(0,Math.min(cols-1,Math.floor(left*level/TILE_PX)));
  const y0=Math.max(0,Math.min(rows-1,Math.floor(top*level/TILE_PX)));
  const x1=Math.max(0,Math.min(cols-1,Math.floor(Math.max(0,right-1e-6)*level/TILE_PX)));
  const y1=Math.max(0,Math.min(rows-1,Math.floor(Math.max(0,bottom-1e-6)*level/TILE_PX)));
  const keep=new Set();
  for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){
    const key=`${x}_${y}`;keep.add(key);
    if(tileEls.has(key))continue;
    const img=new Image();img.className='maptile';img.decoding='async';img.draggable=false;
    const px=x*TILE_PX,py=y*TILE_PX;
    const pw=Math.min(TILE_PX,W*level-px),ph=Math.min(TILE_PX,H*level-py);
    img.style.left=(px/level)+'px';img.style.top=(py/level)+'px';
    img.style.width=(pw/level)+'px';img.style.height=(ph/level)+'px';
    img.src=`${TILE_ROOT}/${mode}/${level}/${x}_${y}.png?v=1`;
    tiles.appendChild(img);tileEls.set(key,img);
  }
  for(const [key,img] of tileEls)if(!keep.has(key)){img.remove();tileEls.delete(key)}
}'''

if 'function updateTiles(){' not in s:
    s = s.replace('function configure(){', tile_funcs + '\nfunction configure(){', 1)

s = s.replace(
    "meta.textContent=FAST_RASTER?'Fast mobile raster · source ~5.66 m/px':'Sub-pixel SVG zones · source ~5.66 m/px'",
    "meta.textContent=FAST_RASTER?'Adaptive PNG tiles · source ~5.66 m/px':'Sub-pixel SVG zones · source ~5.66 m/px'"
)
s = s.replace(
    "meta.textContent=FAST_RASTER?'Survey v3.1 · fast mobile raster':'Survey v3.1 · 10 m grid · matched vector lines'",
    "meta.textContent=FAST_RASTER?'Survey v3.1 · adaptive PNG tiles':'Survey v3.1 · 10 m grid · matched vector lines'"
)
s = s.replace(
    "world.style.width=W+'px';world.style.height=H+'px';$('#track').setAttribute('viewBox'",
    "resetTiles();world.style.width=W+'px';world.style.height=H+'px';$('#track').setAttribute('viewBox'"
)
s = s.replace(
    "world.style.transform=`translate3d(${tx}px,${ty}px,0) scale(${scale})`})}",
    "world.style.transform=`translate3d(${tx}px,${ty}px,0) scale(${scale})`;updateTiles()})}"
)
s = s.replace("register('./sw.js?v=singlepage3-mobilefast')", "register('./sw.js?v=singlepage4-mobiletiles')")
p.write_text(s, encoding='utf-8')

p = Path('sw.js')
s = p.read_text(encoding='utf-8')
s = s.replace('lacanautics-v4.5-singlepage3-mobilefast', 'lacanautics-v4.5-singlepage4-mobiletiles')
p.write_text(s, encoding='utf-8')

# Migration checks.
html = Path('index.html').read_text(encoding='utf-8')
sw = Path('sw.js').read_text(encoding='utf-8')
assert '#tiles{' in html
assert '<div id="tiles"></div>' in html
assert "const TILE_ROOT='tiles/mobile-v1'" in html
assert 'function updateTiles(){' in html
assert 'Adaptive PNG tiles' in html
assert 'sw.js?v=singlepage4-mobiletiles' in html
assert 'lacanautics-v4.5-singlepage4-mobiletiles' in sw
print('Adaptive mobile PNG tile renderer activated.')
