#!/usr/bin/env python3
from __future__ import annotations
import io, json, re, urllib.parse, urllib.request
from pathlib import Path
from PIL import Image

OUT=Path('data'); OUT.mkdir(exist_ok=True)
BASE='https://www.peche33.com'
ORIGINAL=f'{BASE}/wp-content/uploads/2023/08/lacanau-2012.webp'
KNOWN=f'{BASE}/wp-content/uploads/2023/08/lacanau-2012-1024x724.webp'
CANDIDATES=[
 ORIGINAL,
 f'{BASE}/wp-content/uploads/2023/08/lacanau-2012-scaled.webp',
 KNOWN,
]

def get(url,timeout=30):
    req=urllib.request.Request(url,headers={'User-Agent':'Lacanautics/2.2 (+https://github.com/benoitpaillard/Lacanautics)'})
    with urllib.request.urlopen(req,timeout=timeout) as r:return r.status,r.headers,r.read()

def image_info(url):
    try:
        st,h,b=get(url); im=Image.open(io.BytesIO(b))
        return {'url':url,'status':st,'bytes':len(b),'width':int(im.width),'height':int(im.height),'format':im.format,'content_type':h.get('Content-Type')}
    except Exception as e:return {'url':url,'error':repr(e)}

def intval(v):
    try:return int(v)
    except Exception:return 0

def exact_2012(title,source):
    s=(str(title)+' '+str(source)).lower()
    # Reject other Lacanau photos/events. Only the canonical bathymetry attachment is eligible.
    return 'lacanau-2012' in s and ('2023/08' in s or str(title).strip().lower()=='lacanau-2012')

def main():
    report={'candidates':[],'wordpress_media':[]}
    for u in CANDIDATES:
        info=image_info(u); report['candidates'].append(info); print(info)
    url=f'{BASE}/wp-json/wp/v2/media?search='+urllib.parse.quote('lacanau 2012')+'&per_page=100'
    try:
        st,h,b=get(url); items=json.loads(b.decode('utf-8'))
        for m in items:
            title=(m.get('title') or {}).get('rendered',''); source=m.get('source_url')
            if not exact_2012(title,source):continue
            md=m.get('media_details') or {}; sizes=md.get('sizes') or {}
            report['wordpress_media'].append({'id':m.get('id'),'title':title,'source_url':source,
              'width':intval(md.get('width')),'height':intval(md.get('height')),
              'sizes':{k:{'source_url':v.get('source_url'),'width':intval(v.get('width')),'height':intval(v.get('height'))} for k,v in sizes.items()}})
    except Exception as e:report.setdefault('wordpress_errors',[]).append({'error':repr(e)})
    good=[x for x in report['candidates'] if intval(x.get('width'))>0]
    good += [{'url':m.get('source_url'),'width':intval(m.get('width')),'height':intval(m.get('height'))} for m in report['wordpress_media'] if m.get('source_url')]
    if not good:raise RuntimeError('No exact Lacanau-2012 image source available')
    best=max(good,key=lambda x:intval(x.get('width'))*intval(x.get('height')))
    # Sanity: the bathymetry publication has aspect ~1.414. Reject portrait/event imagery.
    ratio=intval(best.get('width'))/max(1,intval(best.get('height')))
    if not (1.35<ratio<1.48):raise RuntimeError(f'Unexpected bathymetry aspect ratio {ratio:.3f}: {best}')
    st,h,b=get(best['url']); im=Image.open(io.BytesIO(b)).convert('RGB')
    out=OUT/'lacanau_2012_best.png'; im.save(out,optimize=True)
    report['best']={'url':best['url'],'width':int(im.width),'height':int(im.height),'saved':str(out)}
    (OUT/'lacanau_2012_source_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
