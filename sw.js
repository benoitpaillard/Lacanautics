const CACHE='lacanautics-v4.5-taubin-gpsmax1';
const CORE=['./','./index.html','./manifest.webmanifest','./gps-max.js','./bathymetry-geopdf-v45-taubin.svg','./bathymetry-geopdf-v41-native.webp','./bathymetry-geopdf-v41-classes.webp','./data/lacanau_geopdf_v41.json','./bathymetry-2012-v3.webp','./data/lacanau_2012_bands_v3.json','./data/lacanau_lake_level.json'];

self.addEventListener('install',e=>{
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c=>c.addAll(CORE)));
});

self.addEventListener('activate',e=>{
  e.waitUntil(Promise.all([
    caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))),
    self.clients.claim()
  ]));
});

async function injectGpsLayer(resp){
  if(!resp)return resp;
  const text=await resp.text();
  const patched=text.includes('gps-max.js')?text:text.replace('</body>','<script src="./gps-max.js?v=1"></script></body>');
  const headers=new Headers(resp.headers);
  headers.delete('content-length');
  return new Response(patched,{status:resp.status,statusText:resp.statusText,headers});
}

self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  const u=new URL(e.request.url);
  const isHires=u.pathname.endsWith('/hires.html');
  const fresh=isHires||u.pathname.endsWith('.html')||u.pathname.endsWith('.json')||u.pathname.endsWith('.svg')||u.pathname.endsWith('.webp')||u.pathname.endsWith('/Lacanautics/')||u.pathname.endsWith('/Lacanautics');

  if(isHires){
    e.respondWith(
      fetch(e.request,{cache:'no-store'})
        .then(resp=>injectGpsLayer(resp))
        .then(resp=>{if(resp.ok){const copy=resp.clone();caches.open(CACHE).then(c=>c.put(e.request,copy))}return resp})
        .catch(async()=>{
          const cached=await caches.match(e.request)||await caches.match('./hires.html');
          return cached?injectGpsLayer(cached):caches.match('./index.html');
        })
    );
    return;
  }

  if(fresh){
    e.respondWith(fetch(e.request,{cache:'no-store'}).then(resp=>{if(resp.ok){const copy=resp.clone();caches.open(CACHE).then(c=>c.put(e.request,copy))}return resp}).catch(()=>caches.match(e.request).then(r=>r||caches.match('./index.html'))));
  }else{
    e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request).then(resp=>{if(resp.ok){const copy=resp.clone();caches.open(CACHE).then(c=>c.put(e.request,copy))}return resp})));
  }
});
