"""アセット（CSS/BODY/JS）の自己完結性・適応の構造テスト。"""
import re
import shutil
import subprocess
import tempfile
import os

import pytest

from lib.rendering import assets

pytestmark = pytest.mark.unit


def test_no_external_references():
    blob = assets._CSS + "\n" + assets._BODY + "\n" + assets._JS
    assert "http://" not in blob and "https://" not in blob
    assert "<script src" not in blob.lower()
    assert "@import" not in blob


def test_js_has_no_dummy_data_literal():
    assert not re.search(r"const\s+DATA\s*=\s*\{", assets._JS)
    assert not re.search(r"const\s+POS\s*=\s*\{", assets._JS)


def test_js_references_addrs():
    assert "addrs" in assets._JS         # 全アドレス検索/表への適応


def test_node_check_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不在のため構文チェックをスキップ")
    stub = ("const DATA={devices:{},links:[],segments:[],extPeers:[],bgpEdges:[],"
            "meta:{generated_from:[]}};const POS={};const VIEWS=['physical','addr','ifs'];\n")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(stub + assets._JS)
        path = f.name
    try:
        r = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    finally:
        os.unlink(path)
