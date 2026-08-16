const CACHE='lacanautics-v4.5-singlepage9-shoreline';
const CORE=['./','./index.html','./manifest.webmanifest','./gps-max.js','./bathymetry-geopdf-v45-taubin.svg','./bathymetry-geopdf-v45-mobile.webp','./bathymetry-geopdf-v41-classes.webp','./data/lacanau_geopdf_v41.json','./bathymetry-2012-v31.svg','./bathymetry-2012-v31-mobile.webp','./data/lacanau_2012_bands_v3.json','./data/lacanau_lake_level.json','./data/lacanau_open_water_mask.geojson'];

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

  const fresh=/\.(?:json|geojson|svg|webp|js)$/.test(url.pathname);
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
