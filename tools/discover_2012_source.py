#!/usr/bin/env python3
from __future__ import annotations
import io, json, urllib.parse, urllib.request
from pathlib import Path
from PIL import Image

OUT=Path('data'); OUT.mkdir(exist_ok=True)
BASE='https://www.peche33.com'
KNOWN=f'{BASE}/wp-content/uploads/2023/08/lacanau-2012-1024x724.webp'
CANDIDATES=[
 f'{BASE}/wp-content/uploads/2023/08/lacanau-2012.webp',
 f'{BASE}/wp-content/uploads/2023/08/lacanau-2012.jpg',
 f'{BASE}/wp-content/uploads/2023/08/lacanau-2012.jpeg',
 f'{BASE}/wp-content/uploads/2023/08/lacanau-2012.png',
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

def main():
    report={'candidates':[],'wordpress_media':[]}
    for u in CANDIDATES:
        info=image_info(u); report['candidates'].append(info); print(info)
    for term in ['lacanau 2012','lacanau','bathymetrie lacanau']:
        url=f'{BASE}/wp-json/wp/v2/media?search='+urllib.parse.quote(term)+'&per_page=100'
        try:
            st,h,b=get(url); items=json.loads(b.decode('utf-8'))
            for m in items:
                title=(m.get('title') or {}).get('rendered',''); source=m.get('source_url')
                if 'lacanau' in (title+' '+str(source)).lower():
                    md=m.get('media_details') or {}; sizes=md.get('sizes') or {}
                    report['wordpress_media'].append({'id':m.get('id'),'title':title,'source_url':source,
                      'width':intval(md.get('width')),'height':intval(md.get('height')),
                      'sizes':{k:{'source_url':v.get('source_url'),'width':intval(v.get('width')),'height':intval(v.get('height'))} for k,v in sizes.items()}})
        except Exception as e:report.setdefault('wordpress_errors',[]).append({'term':term,'error':repr(e)})
    good=[x for x in report['candidates'] if intval(x.get('width'))>0]
    good += [{'url':m.get('source_url'),'width':intval(m.get('width')),'height':intval(m.get('height'))} for m in report['wordpress_media'] if m.get('source_url')]
    if not good:raise RuntimeError('No 2012 image source available')
    best=max(good,key=lambda x:intval(x.get('width'))*intval(x.get('height')))
    st,h,b=get(best['url']); im=Image.open(io.BytesIO(b)).convert('RGB')
    out=OUT/'lacanau_2012_best.png'; im.save(out,optimize=True)
    report['best']={'url':best['url'],'width':int(im.width),'height':int(im.height),'saved':str(out)}
    (OUT/'lacanau_2012_source_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
