#!/usr/bin/env python3
from __future__ import annotations
import json, ssl, urllib.request
from pathlib import Path
import fitz

URL='https://adour-garonne.eaufrance.fr/upload/DOC/FICHES/LACS/BATHYMETRIE/FRFL49_Bathym.pdf'
OUT=Path('data/frfl49_official_pdf_report.json')
PDF=Path('/tmp/FRFL49_Bathym.pdf')

def main():
    ctx=ssl._create_unverified_context()
    req=urllib.request.Request(URL,headers={'User-Agent':'Lacanautics/3.2'})
    with urllib.request.urlopen(req,timeout=90,context=ctx) as r:
        raw=r.read(); ctype=r.headers.get('Content-Type')
    PDF.write_bytes(raw)
    doc=fitz.open(PDF)
    rep={'url':URL,'bytes':len(raw),'content_type':ctype,'metadata':doc.metadata,'pages':[],'embedded_files':[]}
    try:
        for i in range(doc.embfile_count()):
            rep['embedded_files'].append(doc.embfile_info(i))
    except Exception as e: rep['embedded_error']=repr(e)
    for pi,p in enumerate(doc):
        drawings=p.get_drawings(extended=True)
        images=p.get_images(full=True)
        text=p.get_text('text')
        links=p.get_links()
        # summarize drawing objects / fill colors and complexity
        fill_counts={}; stroke_counts={}; items=0
        for d in drawings:
            items+=len(d.get('items',[]))
            fill=str(d.get('fill'))
            color=str(d.get('color'))
            if d.get('fill') is not None: fill_counts[fill]=fill_counts.get(fill,0)+1
            if d.get('color') is not None: stroke_counts[color]=stroke_counts.get(color,0)+1
        image_details=[]
        for img in images:
            xref=img[0]
            try:
                info=doc.extract_image(xref)
                image_details.append({'xref':xref,'width':info.get('width'),'height':info.get('height'),'ext':info.get('ext'),'bytes':len(info.get('image',b''))})
            except Exception as e:image_details.append({'xref':xref,'error':repr(e)})
        rep['pages'].append({'page':pi+1,'rect':[p.rect.x0,p.rect.y0,p.rect.x1,p.rect.y1],
            'rotation':p.rotation,'text_chars':len(text),'text_excerpt':text[:8000],
            'drawing_paths':len(drawings),'drawing_items':items,'top_fills':sorted(fill_counts.items(),key=lambda kv:-kv[1])[:20],
            'top_strokes':sorted(stroke_counts.items(),key=lambda kv:-kv[1])[:20],
            'images':image_details,'links':links[:30]})
        # Save a structural SVG for manual inspection if page is vector-heavy.
        try:
            svg=p.get_svg_image(matrix=fitz.Matrix(1,1),text_as_path=False)
            Path(f'data/frfl49_page_{pi+1}.svg').write_text(svg,encoding='utf-8')
        except Exception as e:
            rep['pages'][-1]['svg_error']=repr(e)
    OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(rep,ensure_ascii=False,indent=2,default=str))
if __name__=='__main__':main()
