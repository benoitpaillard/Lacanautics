#!/usr/bin/env python3
from __future__ import annotations
import json, re, ssl, urllib.request
from pathlib import Path
import fitz

URL='https://adour-garonne.eaufrance.fr/upload/DOC/FICHES/LACS/BATHYMETRIE/FRFL49_Bathym.pdf'
OUT=Path('data/frfl49_official_pdf_report.json')
PDF=Path('/tmp/FRFL49_Bathym.pdf')
GEO_TOKENS=['/LGIDict','/GPTS','/LPTS','/VP','/Measure','/GCS','/DCS','/Projection','/WKT','/EPSG','/Geo']

def main():
    ctx=ssl._create_unverified_context()
    req=urllib.request.Request(URL,headers={'User-Agent':'Lacanautics/3.3'})
    with urllib.request.urlopen(req,timeout=90,context=ctx) as r:
        raw=r.read(); ctype=r.headers.get('Content-Type')
    PDF.write_bytes(raw)
    doc=fitz.open(PDF)
    raw_ascii=raw.decode('latin-1','ignore')
    raw_hits={tok:(tok in raw_ascii) for tok in GEO_TOKENS}
    xref_hits=[]
    for xref in range(1,doc.xref_length()):
        try:o=doc.xref_object(xref,compressed=False)
        except Exception:continue
        found=[tok for tok in GEO_TOKENS if tok in o]
        if found:xref_hits.append({'xref':xref,'tokens':found,'object':o[:12000]})
    rep={'url':URL,'bytes':len(raw),'content_type':ctype,'metadata':doc.metadata,'pdf_xref_count':doc.xref_length(),
         'geospatial_probe':{'raw_token_presence':raw_hits,'xref_hits':xref_hits},'pages':[],'embedded_files':[]}
    try:
        for i in range(doc.embfile_count()):rep['embedded_files'].append(doc.embfile_info(i))
    except Exception as e:rep['embedded_error']=repr(e)
    for pi,p in enumerate(doc):
        drawings=p.get_drawings(extended=True);images=p.get_images(full=True);text=p.get_text('text');links=p.get_links()
        fill_counts={};stroke_counts={};items=0;class_drawings=[]
        depth_rgb=[(182,237,240),(145,205,237),(107,174,232),(61,144,227),(32,114,214),(32,76,189),(25,44,168),(9,9,145)]
        for di,d in enumerate(drawings):
            items+=len(d.get('items',[]));fill=str(d.get('fill'));color=str(d.get('color'))
            if d.get('fill') is not None:fill_counts[fill]=fill_counts.get(fill,0)+1
            if d.get('color') is not None:stroke_counts[color]=stroke_counts.get(color,0)+1
            if d.get('fill') is not None:
                rgb=tuple(round(float(v)*255) for v in d['fill'])
                if rgb in depth_rgb:
                    class_drawings.append({'depth_class':depth_rgb.index(rgb),'rgb':rgb,'drawing_index':di,
                       'rect':[d['rect'].x0,d['rect'].y0,d['rect'].x1,d['rect'].y1] if d.get('rect') else None,
                       'items':len(d.get('items',[])),'closePath':d.get('closePath'),'even_odd':d.get('even_odd'),'layer':d.get('layer')})
        image_details=[]
        for img in images:
            xref=img[0]
            try:
                info=doc.extract_image(xref);image_details.append({'xref':xref,'width':info.get('width'),'height':info.get('height'),'ext':info.get('ext'),'bytes':len(info.get('image',b''))})
            except Exception as e:image_details.append({'xref':xref,'error':repr(e)})
        rep['pages'].append({'page':pi+1,'rect':[p.rect.x0,p.rect.y0,p.rect.x1,p.rect.y1],'rotation':p.rotation,
            'text_chars':len(text),'text_excerpt':text[:8000],'drawing_paths':len(drawings),'drawing_items':items,
            'depth_class_drawings':class_drawings,
            'top_fills':sorted(fill_counts.items(),key=lambda kv:-kv[1])[:20],
            'top_strokes':sorted(stroke_counts.items(),key=lambda kv:-kv[1])[:20],'images':image_details,'links':links[:30]})
        try:
            svg=p.get_svg_image(matrix=fitz.Matrix(1,1),text_as_path=False)
            Path(f'data/frfl49_page_{pi+1}.svg').write_text(svg,encoding='utf-8')
        except Exception as e:rep['pages'][-1]['svg_error']=repr(e)
    OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(rep,ensure_ascii=False,indent=2,default=str))
if __name__=='__main__':main()
