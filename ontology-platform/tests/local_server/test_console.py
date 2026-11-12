"""Actual console JavaScript with deterministic delayed responses."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


def test_selected_release_and_async_response_boundaries():
    node=os.environ.get("LZO_LOCAL_NODE_EXE") or shutil.which("node")
    if not node:
        pytest.skip("Node.js runtime is required for the actual console regression")
    root=Path(__file__).resolve().parents[2]
    result=subprocess.run([node,str(Path(__file__).with_name("console_version_regression.cjs")),str(root/"local_server/web/console.js")],
                          cwd=root,capture_output=True,text=True,encoding="utf8",timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
