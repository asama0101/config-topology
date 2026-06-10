"""
tests/test_assets_split.py — assets.py 分割リファクタの検証テスト

テスト観点:
1. lib.rendering.assets から _CSS/_JS が import できる
2. lib.rendering.template からも _CSS/_JS が再 export として import できる
3. assets._CSS is template._CSS（同一オブジェクト）
4. assets._JS is template._JS（同一オブジェクト）
5. lib.rendering の import で circular import が発生しない
6. render() 出力が基準ハッシュと byte 単位で一致する（分割後の退行ゼロ確認）
"""
from __future__ import annotations

import hashlib
import importlib
import os
import sys

import pytest


EXPECTED_LEN = 134797
EXPECTED_SHA = "a63fc53673a266d7d4fc03ca2df6cfb963953f4010db31c1fa595147853d812e"
# __file__ を使って絶対パスで解決（pytest の cwd に依存しない）
EXAMPLES_TOPOLOGY = os.path.join(os.path.dirname(__file__), "..", "examples", "topology")


# ---------------------------------------------------------------------------
# 1. assets モジュールから _CSS/_JS が import できる
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_assets_import_css():
    """lib.rendering.assets._CSS が import 可能で非空文字列。"""
    from lib.rendering.assets import _CSS  # noqa: PLC0415
    assert isinstance(_CSS, str)
    assert len(_CSS) > 0


@pytest.mark.unit
def test_assets_import_js():
    """lib.rendering.assets._JS が import 可能で非空文字列。"""
    from lib.rendering.assets import _JS  # noqa: PLC0415
    assert isinstance(_JS, str)
    assert len(_JS) > 0


# ---------------------------------------------------------------------------
# 2. template モジュールから再 export として import できる
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_template_reexport_css():
    """lib.rendering.template._CSS が引き続き import 可能。"""
    from lib.rendering.template import _CSS  # noqa: PLC0415
    assert isinstance(_CSS, str)
    assert len(_CSS) > 0


@pytest.mark.unit
def test_template_reexport_js():
    """lib.rendering.template._JS が引き続き import 可能。"""
    from lib.rendering.template import _JS  # noqa: PLC0415
    assert isinstance(_JS, str)
    assert len(_JS) > 0


# ---------------------------------------------------------------------------
# 3 & 4. 同一オブジェクト確認（is）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_css_same_object():
    """template._CSS is assets._CSS（再 export で同一インスタンス）。"""
    from lib.rendering import assets  # noqa: PLC0415
    from lib.rendering import template  # noqa: PLC0415
    assert template._CSS is assets._CSS


@pytest.mark.unit
def test_js_same_object():
    """template._JS is assets._JS（再 export で同一インスタンス）。"""
    from lib.rendering import assets  # noqa: PLC0415
    from lib.rendering import template  # noqa: PLC0415
    assert template._JS is assets._JS


# ---------------------------------------------------------------------------
# 5. circular import が発生しない
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_no_circular_import():
    """lib.rendering の import が循環 import エラーなく成功する。"""
    # sys.modules から削除して強制再ロード
    mods_to_remove = [k for k in sys.modules if k.startswith("lib.rendering")]
    for mod in mods_to_remove:
        sys.modules.pop(mod, None)

    try:
        importlib.import_module("lib.rendering")
        importlib.import_module("lib.rendering.assets")
        importlib.import_module("lib.rendering.template")
    except ImportError as exc:
        pytest.fail(f"circular import または import エラーが発生: {exc}")


# ---------------------------------------------------------------------------
# 6. render() 出力が基準ハッシュと完全一致（byte 一致）
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_render_output_hash_unchanged():
    """分割後の render() 出力が事前計測のハッシュと byte 単位で一致する。"""
    from lib.rendering import render  # noqa: PLC0415
    from lib.topology_io import load_topology  # noqa: PLC0415

    topo = load_topology(EXAMPLES_TOPOLOGY)
    html = render(topo)

    actual_len = len(html)
    actual_sha = hashlib.sha256(html.encode("utf-8")).hexdigest()

    assert actual_len == EXPECTED_LEN, (
        f"HTML length mismatch: expected {EXPECTED_LEN}, got {actual_len}"
    )
    assert actual_sha == EXPECTED_SHA, (
        f"HTML SHA256 mismatch:\n  expected: {EXPECTED_SHA}\n  actual:   {actual_sha}"
    )
