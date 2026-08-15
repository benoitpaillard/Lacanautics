(()=>{'use strict';
if(!navigator.geolocation)return;

const originalWatch=navigator.geolocation.watchPosition.bind(navigator.geolocation);
const originalGet=navigator.geolocation.getCurrentPosition?.bind(navigator.geolocation);
const TARGET_ACCURACY_M=8;
const ACCEPT_ACCURACY_M=20;
const FALLBACK_AFTER_MS=12000;

function wrapSuccess(success){
  const started=Date.now();
  let bestAccuracy=Infinity;
  let bestPosition=null;
  let delivered=false;

  return pos=>{
    const accuracy=Number(pos?.coords?.accuracy);
    if(Number.isFinite(accuracy)&&accuracy<bestAccuracy){
      bestAccuracy=accuracy;
      bestPosition=pos;
    }

    const good=Number.isFinite(accuracy)&&accuracy<=ACCEPT_ACCURACY_M;
    const timedOut=!delivered&&Date.now()-started>=FALLBACK_AFTER_MS;

    if(good){
      delivered=true;
      success(pos);
      return;
    }

    if(timedOut&&bestPosition){
      delivered=true;
      success(bestPosition);
      return;
    }

    const coord=document.getElementById('coord');
    const meta=document.getElementById('meta');
    if(coord&&Number.isFinite(accuracy))coord.textContent=`Refining GPS… ±${Math.round(accuracy)} m`;
    if(meta){
      const best=Number.isFinite(bestAccuracy)?`best ±${Math.round(bestAccuracy)} m`:'waiting for GPS';
      meta.textContent=`Maximum accuracy requested · target ≤${TARGET_ACCURACY_M} m · ${best}`;
    }
  };
}

navigator.geolocation.watchPosition=(success,error,options={})=>originalWatch(
  wrapSuccess(success),
  error,
  {...options,enableHighAccuracy:true,maximumAge:0,timeout:30000}
);

if(originalGet){
  navigator.geolocation.getCurrentPosition=(success,error,options={})=>originalGet(
    wrapSuccess(success),
    error,
    {...options,enableHighAccuracy:true,maximumAge:0,timeout:30000}
  );
}
})();
