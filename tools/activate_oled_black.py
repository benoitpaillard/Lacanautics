#!/usr/bin/env python3
from pathlib import Path

p=Path('index.html')
s=p.read_text(encoding='utf-8')

repls={
    '<meta name="theme-color" content="#eef0e8">':'<meta name="theme-color" content="#000000">',
    ':root{--land:#eef0e8;--ink:#17343d;--muted:#63767c;--panel:rgba(255,255,255,.95);--blue:#087fc0;--track:#ff3155}':':root{--land:#000000;--ink:#e7f3f6;--muted:#9fb1b7;--panel:rgba(4,8,10,.94);--blue:#159bd7;--track:#ff3155}',
    'background:#dff4f6;border-radius:13px':'background:#06171d;border-radius:13px',
    'color:#075a78;line-height:1.05':'color:#9adfff;line-height:1.05',
    'color:#63767c;display:block':'color:#9fb1b7;display:block',
    'color:#63767c;margin-top:3px':'color:#9fb1b7;margin-top:3px',
    'background:#fffffff2;font-size:20px':'background:#05090bf2;font-size:20px',
    'color:#65777c;margin-top:2px':'color:#9fb1b7;margin-top:2px',
    'color:#566b72}.legend':'color:#a9bac0}.legend',
    'color:#63767c;line-height:1.25':'color:#a9bac0;line-height:1.25',
    'background:#fffffff2;font-weight:850':'background:#05090bf2;font-weight:850',
    'background:#dff1ff;color:#0674af':'background:#092536;color:#8bd7ff',
    'background:#17343d66':'background:#000000cc',
    'background:#fff;border-radius:22px 22px 0 0':'background:#05090b;border-radius:22px 22px 0 0',
    'color:#60747a;font-size:12px':'color:#9fb1b7;font-size:12px',
    'background:#eef7fb;min-height:50px':'background:#07151b;min-height:50px',
    'color:#075a78}.levelrow':'color:#9adfff}.levelrow',
    'background:#f3f6f3;border-radius:13px':'background:#071012;border-radius:13px',
    'color:#17343d}.close':'color:#e7f3f6}.close',
    'background:#17343d;color:#fff':'background:#0b2530;color:#fff',
    'background:#eef0e8fa;display:flex':'background:#000000fa;display:flex',
    'max-width:430px;background:#fff;border-radius:20px':'max-width:430px;background:#05090b;border-radius:20px',
    'color:#5c7076}.card':'color:#a9bac0}.card',
    'color:#78878b;line-height:1.35':'color:#91a3a9;line-height:1.35',
    'border-top:1px solid #dfe7e5':'border-top:1px solid #233238',
}
for old,new in repls.items():
    s=s.replace(old,new)

# Catch the remaining common light surfaces without affecting bathymetry palette values.
s=s.replace('background:#fff;', 'background:#05090b;')
s=s.replace('background:#eef0e8;', 'background:#000000;')
s=s.replace('background:#eef7fb;', 'background:#07151b;')
s=s.replace('background:#f3f6f3;', 'background:#071012;')

# Cache-bust the app shell/service worker after the theme change.
s=s.replace("register('./sw.js?v=singlepage4-mobiletiles')", "register('./sw.js?v=singlepage5-oledblack')")
p.write_text(s,encoding='utf-8')

p=Path('sw.js')
sw=p.read_text(encoding='utf-8')
sw=sw.replace('lacanautics-v4.5-singlepage4-mobiletiles','lacanautics-v4.5-singlepage5-oledblack')
p.write_text(sw,encoding='utf-8')

# Sanity checks
html=Path('index.html').read_text(encoding='utf-8')
assert '--land:#000000' in html
assert '<meta name="theme-color" content="#000000">' in html
assert "sw.js?v=singlepage5-oledblack" in html
assert 'bathymetry-geopdf-v45-taubin.svg' in html
assert 'bathymetry-2012-v31.svg' in html
assert 'tiles/mobile-v1' in html
assert 'lacanautics-v4.5-singlepage5-oledblack' in Path('sw.js').read_text(encoding='utf-8')
print('OLED black theme activated')
