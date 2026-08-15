#!/usr/bin/env python3
from pathlib import Path

root = Path('.')
hires = root / 'hires.html'
index = root / 'index.html'
sw = root / 'sw.js'
manifest = root / 'manifest.webmanifest'

if not hires.exists():
    raise SystemExit('hires.html not found')

html = hires.read_text(encoding='utf-8')

# Load the maximum-accuracy GPS wrapper explicitly before the main application script.
main_marker = "<script>\n(()=>{'use strict';"
if main_marker not in html:
    raise SystemExit('main application script marker not found')
if 'src="./gps-max.js' not in html:
    html = html.replace(main_marker, '<script src="./gps-max.js?v=2"></script>\n' + main_marker, 1)

# The app page itself owns service-worker registration. Bump its URL so browsers
# re-check the simplified worker immediately after this migration.
html = html.replace("navigator.serviceWorker.register('./sw.js')", "navigator.serviceWorker.register('./sw.js?v=singlepage1')")

index.write_text(html, encoding='utf-8')
hires.unlink()

# Conventional single-page service worker: no HTML injection and no redirects.
sw.write_text("""const CACHE='lacanautics-v4.5-singlepage1';
const CORE=['./','./index.html','./manifest.webmanifest','./gps-max.js','./bathymetry-geopdf-v45-taubin.svg','./bathymetry-geopdf-v41-classes.webp','./data/lacanau_geopdf_v41.json','./bathymetry-2012-v3.webp','./data/lacanau_2012_bands_v3.json','./data/lacanau_lake_level.json'];

self.addEventListener('install',event=>{
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(CORE)));
});

self.addEventListener('activate',event=>{
  event.waitUntil(Promise.all([
    caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key)))),
    self.clients.claim()
  ]));
});

async function networkFirst(request){
  try{
    const response=await fetch(request,{cache:'no-store'});
    if(response.ok){
      const copy=response.clone();
      caches.open(CACHE).then(cache=>cache.put(request,copy));
    }
    return response;
  }catch(error){
    return (await caches.match(request)) || Response.error();
  }
}

self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET')return;
  const url=new URL(event.request.url);

  if(event.request.mode==='navigate'){
    event.respondWith(
      fetch(event.request,{cache:'no-store'})
        .then(response=>{
          if(response.ok){
            const copy=response.clone();
            caches.open(CACHE).then(cache=>cache.put('./index.html',copy));
          }
          return response;
        })
        .catch(()=>caches.match('./index.html'))
    );
    return;
  }

  const fresh=/\\.(?:json|svg|webp|js)$/.test(url.pathname);
  if(fresh){
    event.respondWith(networkFirst(event.request));
    return;
  }

  event.respondWith(
    caches.match(event.request).then(cached=>cached||fetch(event.request).then(response=>{
      if(response.ok){
        const copy=response.clone();
        caches.open(CACHE).then(cache=>cache.put(event.request,copy));
      }
      return response;
    }))
  );
});
""", encoding='utf-8')

# Keep the manifest accurate now that there is a single app page.
text = manifest.read_text(encoding='utf-8')
text = text.replace('live GPS and raster/v3.1 comparison', 'live high-accuracy GPS and harmonized v3.1 comparison')
manifest.write_text(text, encoding='utf-8')

# Basic migration invariants.
result = index.read_text(encoding='utf-8')
assert 'Lacanautics Vector v4.5' in result
assert 'src="./gps-max.js?v=2"' in result
assert "register('./sw.js?v=singlepage1')" in result
assert 'location.replace(' not in result
assert not hires.exists()
assert 'injectGpsLayer' not in sw.read_text(encoding='utf-8')
assert 'hires.html' not in sw.read_text(encoding='utf-8')
print('Promoted Lacanautics to a single index.html application.')
