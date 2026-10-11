"""Review, commit and push project deliverables using normal Git authentication."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
REMOTE='https://github.com/lianggeming14/liangzihu-ontology-traceability.git'

def find_git():
    candidates=[shutil.which('git'),r'C:/Users/robot/.conda/envs/direct/Library/bin/git.exe']
    for value in candidates:
        if value and Path(value).is_file(): return value
    raise RuntimeError('Git 未安装或不在 PATH 中')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--message',default='Sync project deliverables')
    args=parser.parse_args()
    git=find_git()
    env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never')
    def run(*arguments,check=True):
        result=subprocess.run([git,'-c','safe.directory='+ROOT.as_posix(),'-c','credential.interactive=never',*arguments],cwd=ROOT,env=env,text=True,encoding='utf-8',capture_output=True)
        if check and result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'Git operation failed')
        return result
    if not (ROOT/'.git').exists(): run('init','-b','main')
    origin=run('remote','get-url','origin',check=False)
    if origin.returncode: run('remote','add','origin',REMOTE)
    elif origin.stdout.strip()!=REMOTE: raise RuntimeError('origin 与授权仓库不一致，已停止')
    # Fetch first. Nothing is auto-pushed until the remote baseline is known.
    run('fetch','origin','main')
    head=run('rev-parse','--verify','HEAD',check=False)
    if head.returncode:
        # Bootstrap after a browser import; preserve all working-tree bytes.
        run('reset','--mixed','origin/main')
        # Preserve remote-only bootstrap files instead of staging accidental deletions.
        for relative in run('ls-files','-z').stdout.split(chr(0)):
            if not relative: continue
            target=(ROOT/relative).resolve()
            if not target.is_relative_to(ROOT.resolve()): raise RuntimeError('远端路径超出项目目录')
            if not target.exists(): run('restore','--source=origin/main','--worktree','--',relative)
    else:
        branch=run('branch','--show-current').stdout.strip()
        if branch!='main': raise RuntimeError('当前分支不是 main；请先完成分支评审和合并')
        if run('merge-base','--is-ancestor','origin/main','HEAD',check=False).returncode:
            if run('status','--porcelain').stdout.strip():
                raise RuntimeError('远端有新提交且本地有未提交修改，需先人工/代理合并，工作区已保留')
            run('merge','--ff-only','origin/main')
    run('add','-A')
    checked=subprocess.run([sys.executable,str(ROOT/'tools'/'build_github_snapshot.py'),'--check-only'],cwd=ROOT,env=env)
    if checked.returncode: raise RuntimeError('提交前文件检查未通过；未创建提交、未推送')
    if run('diff','--cached','--quiet',check=False).returncode:
        run('-c','user.name=lianggeming14','-c','user.email=lianggeming14@users.noreply.github.com','commit','-m',args.message)
    run('push','-u','origin','main')
    local=run('rev-parse','HEAD').stdout.strip()
    remote=run('ls-remote','origin','refs/heads/main').stdout.split()[0]
    if local!=remote: raise RuntimeError('远端提交已变化，需要重新核对，不报告同步成功')
    print('已核对远端同步：'+REMOTE.removesuffix('.git'))
    print('提交：'+local)

if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('同步未完成；本地文件保留。'+str(exc),file=sys.stderr)
        raise SystemExit(1)
