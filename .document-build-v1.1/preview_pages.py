import importlib.util,os
from pathlib import Path
BASE=Path(__file__).resolve().parent
skill=Path(r'C:/Users/robot/.codex/plugins/cache/openai-primary-runtime/documents/26.909.11814/skills/documents')
os.environ['PATH']=r'C:/Users/robot/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin'+os.pathsep+os.environ.get('PATH','')
spec=importlib.util.spec_from_file_location('render_docx',skill/'render_docx.py');render=importlib.util.module_from_spec(spec);spec.loader.exec_module(render)
preview=BASE/'fixed-layout-preview.pdf'
render.convert_to_pdf=lambda *args,**kwargs:(str(preview),'Fixed line and page preview; native Word renderer unavailable')
paths=render.rasterize(str(BASE.parent/'交付文档'/'梁子湖智慧农业本体库与溯源系统总体方案_v1.1.docx'),str(BASE/'preview-pages'),100,False,False)
print('Fixed-pagination preview pages:',len(paths))
