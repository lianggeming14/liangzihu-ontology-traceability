"""Attempt packaged native rendering, then retain explicitly labelled preview QA."""
from pathlib import Path
import json
import subprocess
import sys
from pdf2image import convert_from_path

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/backend-integration-20261019'
RUNTIME=Path('C:/Users/robot/.cache/codex-runtimes/codex-primary-runtime/dependencies')
RENDER=Path('C:/Users/robot/.codex/plugins/cache/openai-primary-runtime/documents/26.909.11814/skills/documents/render_docx.py')
for filename,folder in [('梁子湖本体数据库后端操作说明书_v0.4.docx','manual-qa'),('原梁子湖项目数据库分析与本体库比较报告.docx','report-qa')]:
    qa=OUT/folder
    result=subprocess.run([sys.executable,str(RENDER),str(ROOT/'交付文档'/filename),'--output_dir',str(qa/'native'),'--emit_pdf','--verbose'],capture_output=True,text=True,encoding='utf-8',timeout=45)
    (qa/'native-render.json').write_text(json.dumps({'command':'packaged render_docx.py','success':result.returncode==0,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr,'word_com_probe':'failed HRESULT 80070520; no document opened','fallback_is_native':False},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    target=qa/'preview-pages';target.mkdir(parents=True,exist_ok=True)
    paths=convert_from_path(str(qa/'layout-preview.pdf'),dpi=150,fmt='png',thread_count=4,output_folder=str(target),output_file='preview',paths_only=True,poppler_path=str(RUNTIME/'native/poppler/Library/bin'))
    for index,path in enumerate(paths,1):Path(path).replace(target/f'page-{index}.png')
    print(json.dumps({'document':filename,'native_verified':result.returncode==0,'preview_pages':len(paths)},ensure_ascii=False))
