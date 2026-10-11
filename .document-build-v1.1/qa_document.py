import json,re,hashlib
from pathlib import Path
from zipfile import ZipFile
from lxml import etree
from PIL import Image,ImageOps,ImageDraw,ImageFont
BASE=Path(__file__).resolve().parent;D=json.loads((BASE/'plan-content.json').read_text(encoding='utf-8'));P=json.loads((BASE/'pagination.json').read_text(encoding='utf-8'))
DOC=BASE.parent/'交付文档'/'梁子湖智慧农业本体库与溯源系统总体方案_v1.1.docx'
with ZipFile(DOC) as z: xml=etree.fromstring(z.read('word/document.xml'))
ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
actual=''.join(xml.xpath('//w:t/text()',namespaces=ns))
def norm(s):return re.sub(r'\s+','',s)
actualn=norm(actual);missing=[]
for ci,ch in enumerate(D['chapters']):
 for bi,b in enumerate(ch['blocks']):
  items=[]
  if b['type'] in ['p','h2','h3','code']:items=[b['text']]
  elif b['type']=='bullets':items=b['items']
  elif b['type']=='table':items=b['headers']+[v for row in b['rows'] for v in row]
  elif b['type']=='figure':items=[b['caption']]
  elif b['type']=='reference':items=[b['title'],b['note']]
  for s in items:
   if norm(s) not in actualn:missing.append({'chapter':ci+1,'block':bi,'text':s[:80]})
# All paragraphs were explicitly wrapped; compare item geometry to safe page body.
geometry=[]
for n,page in enumerate(P['layout'],1):
 for item in page:
  if item.get('height',0)+item['top']>728.5:geometry.append({'page':n,'kind':item['kind'],'bottom':item['top']+item.get('height',0)})
font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',22)
for group in range((P['pages']+8)//9):
 sheet=Image.new('RGB',(1260,1836),'#d9dfe5');draw=ImageDraw.Draw(sheet)
 for j in range(9):
  n=group*9+j+1
  if n>P['pages']:break
  im=Image.open(BASE/'preview-pages'/('page-'+str(n)+'.png'));im.thumbnail((410,578))
  x=(j%3)*420;y=(j//3)*612
  sheet.paste(im,(x+(420-im.width)//2,y+28));draw.text((x+10,y+2),'第 '+str(n)+' 页',font=font,fill='black')
 sheet.save(BASE/('contact-'+str(group+1)+'.png'))
report={'pages_planned':P['pages'],'explicit_page_breaks':len(xml.xpath('//w:br[@w:type="page"]',namespaces=ns)),'missing_content':missing,'geometry_issues':geometry,'sha256':hashlib.sha256(DOC.read_bytes()).hexdigest(),'native_word_render_verified':False,'preview_backend':'ReportLab matched explicit DOCX lines and page boundaries','docx_bytes':DOC.stat().st_size}
(BASE/'final-qa.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
