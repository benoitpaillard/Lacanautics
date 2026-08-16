#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path('.')

# ---------------- index.html ----------------
p = ROOT / 'index.html'
s = p.read_text(encoding='utf-8')

s = s.replace('<title>Lacanautics Vector v4.5</title>', '<title>Lacanautics · Lacanau Bathymetry</title>')

# Source badge/link styling.
css_anchor = ".badge{position:fixed;z-index:9;left:10px;top:110px;padding:8px 10px;font-size:10px;font-weight:800}"
css_new = css_anchor + ".sourceBadge{color:var(--ink);appearance:none;text-align:left;cursor:pointer}.sourceBadge:after{content:' ⓘ';color:#8bd7ff}.sourceLink{display:block;text-align:center;text-decoration:none;border:1px solid #284c5625;border-radius:13px;background:#07151b;color:#9adfff;min-height:48px;padding:14px 10px;margin:8px 0;font-weight:850}.sourceLink.secondary{background:#071012;color:#a9bac0}"
if '.sourceBadge{' not in s:
    if css_anchor not in s:
        raise RuntimeError('badge CSS anchor not found')
    s = s.replace(css_anchor, css_new, 1)

# Badge becomes tappable source-info control.
s = s.replace(
    '<div id="badge" class="badge panel">VECTOR 4.5 · Taubin-smoothed</div>',
    '<button id="badge" class="badge panel sourceBadge" type="button">Adour-Garonne · GeoPDF</button>',
    1,
)

# Layer switch shows source rather than internal version.
s = s.replace(
    '<button id="layer" class="mini"><strong>VECTOR</strong><small>4.5</small></button>',
    '<button id="layer" class="mini" aria-label="Switch bathymetry source"><strong>ADOUR-G.</strong><small>GeoPDF</small></button>',
    1,
)

# Add source information sheet after lake-level sheet.
source_overlay = '''<div id="sourceOverlay" class="overlay"><div class="sheet"><h2 id="sourceTitle">Adour-Garonne GeoPDF</h2><p id="sourceText"></p><div id="sourceDetails" class="readout"></div><a id="sourceLink" class="sourceLink" href="#" target="_blank" rel="noopener noreferrer">Open bathymetry source ↗</a><div class="readout"><b>Common shoreline</b><br>Both bathymetry sources are clipped to IGN BD TOPO permanent, non-marsh hydrography so intermittent lake fringes and marshes are treated as land.</div><a class="sourceLink secondary" href="https://documentation.geoservices.ign.fr/?BDTopo=&amp;id_classe=0&amp;id_theme=97" target="_blank" rel="noopener noreferrer">IGN shoreline documentation ↗</a><button id="closeSource" class="close">Done</button></div></div>'''
if 'id="sourceOverlay"' not in s:
    needle = '<div id="splash" class="splash">'
    if needle not in s:
        raise RuntimeError('splash anchor not found')
    s = s.replace(needle, source_overlay + '\n' + needle, 1)

# Simplify splash terminology.
s = s.replace('<h1>Lacanautics Vector v4.5</h1>', '<h1>Lacanautics</h1>')
s = s.replace(
    '<p>The corrected GeoPDF 4.1 bathymetry is rendered as <b>compact Taubin-smoothed iso-contours</b>. Depth numbers are intentionally omitted for clarity. <b>Tap or click anywhere on the lake to read its depth band.</b></p><p>Tap the <b>VECTOR</b> button to switch directly between Vector 4.5 and Survey v3.1 for comparison.</p>',
    '<p>Choose between the <b>Adour-Garonne GeoPDF</b> bathymetry and the <b>Aquabio 2012 survey</b>. Both use the corrected IGN permanent-water shoreline. <b>Tap or click anywhere on the lake to read its depth band.</b></p><p>Tap the source button on the right to switch maps. Tap the source name at upper left for provenance and the original source link.</p>',
)
s = s.replace(
    '<small>Source sampling ≈5.66 m/pixel. Taubin smoothing uses λ=0.50, μ=−0.53 on the 1–5 m contours; shoreline and 6–8 m zones retain v4.4 geometry. GPS depth lookup is unchanged. Vertical definition remains the official 1 m bands.</small>',
    '<small>Adour-Garonne GeoPDF: ≈5.66 m/pixel source sampling with smoothed display contours. Aquabio 2012: published 1 m depth classes digitized to a 10 m lookup grid. Versions remain available in the source information sheet for traceability.</small>',
)

# Add source sheet DOM references.
s = s.replace(
    "levelInput=$('#levelInput'),levelInfo=$('#levelInfo');",
    "levelInput=$('#levelInput'),levelInfo=$('#levelInfo'),sourceOverlay=$('#sourceOverlay'),sourceTitle=$('#sourceTitle'),sourceText=$('#sourceText'),sourceDetails=$('#sourceDetails'),sourceLink=$('#sourceLink');",
    1,
)

# Source metadata constants.
const_anchor = "const REF=13.21,surveyURL='data/lacanau_2012_bands_v3.json?v=411',v41URL='data/lacanau_geopdf_v41.json?v=411',levelURL='data/lacanau_lake_level.json?v=411',shorelineURL='data/lacanau_open_water_mask.geojson?v=1';"
const_new = const_anchor + "\nconst SOURCE_INFO={vector:{name:'Adour-Garonne GeoPDF',button:'ADOUR-G.',sub:'GeoPDF',version:'Lacanautics display v4.5',url:'https://adour-garonne.eaufrance.fr/upload/DOC/FICHES/LACS/BATHYMETRIE/FRFL49_Bathym.pdf',text:'Agence de l’Eau Adour-Garonne FRFL49 bathymetry GeoPDF. Official 1 m depth classes, georeferenced from the embedded GeoPDF coordinates.',details:'Source sampling ≈5.66 m/pixel · Lacanautics: Taubin-smoothed 1–5 m display contours · depth lookup uses the corrected source classes.'},v31:{name:'Aquabio 2012 survey',button:'AQUABIO',sub:'2012',version:'Lacanautics display v3.1',url:'https://www.peche33.com/2023/08/bathymetrie-plans-deau-gironde-2022/',text:'Aquabio / Agence de l’Eau Adour-Garonne published 2012 Lac de Lacanau bathymetry, preserved as official 1 m depth classes.',details:'Published bathymetry map · Lacanautics digitization: 10 m class grid · no contour smoothing · public source copy hosted by Fédération de pêche de Gironde.'}};"
if 'const SOURCE_INFO=' not in s:
    if const_anchor not in s:
        raise RuntimeError('source constant anchor not found')
    s = s.replace(const_anchor, const_new, 1)

# Source sheet updater before configure().
if 'function updateSourceInfo()' not in s:
    needle = 'function configure(){'
    fn = "function updateSourceInfo(){const x=SOURCE_INFO[mode];badge.textContent=x.name;layerBtn.innerHTML=`<strong>${x.button}</strong><small>${x.sub}</small>`;sourceTitle.textContent=x.name;sourceText.textContent=x.text;sourceDetails.innerHTML=`<b>${x.version}</b><br>${x.details}`;sourceLink.href=x.url}\n"
    if needle not in s:
        raise RuntimeError('configure anchor not found')
    s = s.replace(needle, fn + needle, 1)

# Replace configure source/version-facing text but preserve technical behavior.
s = s.replace(
    "badge.textContent='VECTOR 4.5 · Taubin-smoothed';warn.textContent='Vector 4.5: Taubin-smoothed 1–5 m isobaths suppress short scallops without shrinkage; shoreline and 6–8 m zones retain v4.4 geometry. Depth classes remain 2012/v4.1, but land/water is clipped to IGN permanent hydrography so intermittent lake fringes and marshes are land. Not a certified chart.';layerBtn.innerHTML='<strong>VECTOR</strong><small>4.5</small>';meta.textContent=FAST_RASTER?'Adaptive PNG tiles · source ~5.66 m/px':'Sub-pixel SVG zones · source ~5.66 m/px'",
    "warn.textContent='Adour-Garonne GeoPDF: official 1 m depth classes, displayed with smoothed 1–5 m contours. Land/water is clipped to IGN permanent hydrography so intermittent lake fringes and marshes are land. Not a certified chart.';meta.textContent=FAST_RASTER?'Adour-Garonne GeoPDF · adaptive PNG · ~5.66 m/px':'Adour-Garonne GeoPDF · SVG · ~5.66 m/px'",
    1,
)
s = s.replace(
    "badge.textContent='SURVEY v3.1 · harmonized';warn.textContent='Survey v3.1: original 10 m depth classes vectorized at cell edges, using the same line widths, opacity, round joins/caps and 0–8 m colors as Vector 4.5. Tap 3.1 to return to Vector 4.5.';layerBtn.innerHTML='<strong>3.1</strong><small>VIEW</small>';meta.textContent=FAST_RASTER?'Survey v3.1 · adaptive PNG tiles':'Survey v3.1 · 10 m grid · matched vector lines'",
    "warn.textContent='Aquabio 2012: published 1 m depth classes digitized to a 10 m grid and vectorized at cell edges without contour smoothing. Land/water uses the same IGN permanent-water mask. Not a certified chart.';meta.textContent=FAST_RASTER?'Aquabio 2012 · 10 m grid · adaptive PNG':'Aquabio 2012 · 10 m grid · SVG'",
    1,
)
# Ensure source label/sheet refreshes on every configure.
s = s.replace("resetTiles();world.style.width=W+'px';", "updateSourceInfo();resetTiles();world.style.width=W+'px';", 1)

# Human-readable depth provenance.
s = s.replace("${mode==='vector'?'4.5 Taubin vector':'3.1 survey'}:", "${mode==='vector'?'Adour-Garonne GeoPDF':'Aquabio 2012'}:")

# Human-readable share provenance.
s = s.replace("${mode==='vector'?'4.5 vector depth ':'3.1 depth '}${dv.textContent}", "${SOURCE_INFO[mode].name} depth ${dv.textContent}")

# Source sheet controls alongside existing overlays.
control_anchor = "levelBtn.onclick=()=>{updateLevelInfo();overlay.style.display='flex'};$('#depthPanel').onclick=()=>{updateLevelInfo();overlay.style.display='flex'};"
control_new = control_anchor + "badge.onclick=()=>{updateSourceInfo();sourceOverlay.style.display='flex'};$('#closeSource').onclick=()=>sourceOverlay.style.display='none';sourceOverlay.onclick=e=>{if(e.target===sourceOverlay)sourceOverlay.style.display='none'};"
if 'badge.onclick=()=>{updateSourceInfo()' not in s:
    if control_anchor not in s:
        raise RuntimeError('UI control anchor not found')
    s = s.replace(control_anchor, control_new, 1)

# Cache-bust the shell after user-visible source naming changes.
s = s.replace("register('./sw.js?v=singlepage9-shoreline')", "register('./sw.js?v=singlepage10-sourcenames')")
p.write_text(s, encoding='utf-8')

# ---------------- sw.js ----------------
p = ROOT / 'sw.js'
sw = p.read_text(encoding='utf-8')
sw = sw.replace('lacanautics-v4.5-singlepage9-shoreline', 'lacanautics-v4.5-singlepage10-sourcenames')
p.write_text(sw, encoding='utf-8')

# ---------------- permanent validator ----------------
p = ROOT / '.github/workflows/validate-web.yml'
v = p.read_text(encoding='utf-8')
v = v.replace("register('./sw.js?v=singlepage9-shoreline')", "register('./sw.js?v=singlepage10-sourcenames')")
v = v.replace('lacanautics-v4.5-singlepage9-shoreline', 'lacanautics-v4.5-singlepage10-sourcenames')
v = v.replace("bathymetry-geopdf-v45-mobile.webp?v=m2' in html", "bathymetry-geopdf-v45-mobile.webp?v=m2' in html")
# Remove old user-facing version-string requirements if present.
v = v.replace("          assert 'VECTOR 4.5' in html\n", '')
v = v.replace("          assert 'SURVEY v3.1 · harmonized' in html\n", '')
v = v.replace("          assert 'matched vector lines' in html\n", '')
# Add source-name/info requirements near existing probe checks.
probe_check = "          assert 'tapState' in html\n"
source_checks = "          assert 'tapState' in html\n          assert 'Adour-Garonne GeoPDF' in html\n          assert 'Aquabio 2012 survey' in html\n          assert 'id=\"sourceOverlay\"' in html\n          assert 'const SOURCE_INFO=' in html\n          assert 'function updateSourceInfo()' in html\n          assert 'FRFL49_Bathym.pdf' in html\n          assert 'bathymetrie-plans-deau-gironde-2022' in html\n"
if "assert 'const SOURCE_INFO=' in html" not in v:
    if probe_check not in v:
        raise RuntimeError('validator probe anchor not found')
    v = v.replace(probe_check, source_checks, 1)
# Add simple grep requirements near source-independent controls.
line = "          grep -q 'function probeAtScreen' index.html\n"
more = line + "          grep -q 'Adour-Garonne GeoPDF' index.html\n          grep -q 'Aquabio 2012 survey' index.html\n          grep -q 'id=\"sourceOverlay\"' index.html\n          grep -q 'function updateSourceInfo()' index.html\n"
if "grep -q 'id=\"sourceOverlay\"' index.html" not in v:
    if line not in v:
        raise RuntimeError('validator grep anchor not found')
    v = v.replace(line, more, 1)
p.write_text(v, encoding='utf-8')

# ---------------- sanity ----------------
html = (ROOT / 'index.html').read_text(encoding='utf-8')
sw = (ROOT / 'sw.js').read_text(encoding='utf-8')
val = (ROOT / '.github/workflows/validate-web.yml').read_text(encoding='utf-8')
assert '<title>Lacanautics · Lacanau Bathymetry</title>' in html
assert 'Adour-Garonne GeoPDF' in html and 'Aquabio 2012 survey' in html
assert 'id="sourceOverlay"' in html and 'function updateSourceInfo()' in html
assert 'FRFL49_Bathym.pdf' in html
assert 'bathymetrie-plans-deau-gironde-2022' in html
assert 'singlepage10-sourcenames' in html and 'singlepage10-sourcenames' in sw
assert 'singlepage10-sourcenames' in val
print('Source names and tappable provenance sheet activated.')
