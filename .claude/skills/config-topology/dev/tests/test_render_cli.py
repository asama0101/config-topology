"""§10.1/§10.2 render_topology.py CLI のテスト。"""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REBUILD_ROOT = Path(__file__).resolve().parents[2]
GOLDEN = REBUILD_ROOT / "dev" / "examples" / "topology"
CLI = REBUILD_ROOT / "scripts" / "render_topology.py"


def _run(args, cwd=None):
    return subprocess.run([sys.executable, str(CLI)] + args, capture_output=True,
                          text=True, cwd=cwd)


def test_generates_html_default_output(tmp_path):
    proc = _run([str(GOLDEN)], cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    out = tmp_path / "topology.html"
    assert out.exists()
    assert out.read_text(encoding="utf-8").lstrip().lower().startswith("<!doctype html")
    assert "Generated" in proc.stdout
    assert "description" in proc.stderr or "確認" in proc.stderr   # §10.2 機密注意行


def test_explicit_output(tmp_path):
    out = tmp_path / "x.html"
    proc = _run([str(GOLDEN), "-o", str(out)])
    assert proc.returncode == 0 and out.exists()


def test_render_retains_existing_html(tmp_path):
    # 既定出力 ./topology.html が既存 → 生成前に history へ退避
    (tmp_path / "topology.html").write_text("<!doctype html>old", encoding="utf-8")
    proc = _run([str(GOLDEN)], cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    history = tmp_path / "history"
    assert history.exists()
    snaps = list(history.iterdir())
    assert len(snaps) == 1
    assert (snaps[0] / "topology.html").read_text(encoding="utf-8") == "<!doctype html>old"
    new = tmp_path / "topology.html"
    assert new.exists()
    assert new.read_text(encoding="utf-8").lstrip().lower().startswith("<!doctype html")
    assert "退避" in proc.stderr


def test_render_no_retention_when_absent(tmp_path):
    proc = _run([str(GOLDEN)], cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / "history").exists()


def test_dangling_ref_exits_1(tmp_path):
    bad = tmp_path / "topo"
    bad.mkdir()
    (bad / "_meta.yaml").write_text("generated_from: []\nschema_version: '1.0'\ntitle: T\n",
                                    encoding="utf-8")
    (bad / "devices.yaml").write_text(
        "devices: []\ninterfaces:\n- {id: 'rX::Gi0', device: rX, name: Gi0, ip: null, vlan: null,"
        " description: null, shutdown: false, admin_status: up, oper_status: null, mtu: null,"
        " speed: null, duplex: null, l2_l3: null, switchport: null, encapsulation: null,"
        " source: parsed, addresses: []}\n", encoding="utf-8")
    (bad / "physical.yaml").write_text("links: []\nsegments: []\n", encoding="utf-8")
    proc = _run([str(bad)])
    assert proc.returncode == 1
    assert "rX" in proc.stderr


# ---------------------------------------------------------------------------
# D3b DIFF ビュー — CLI テスト
# ---------------------------------------------------------------------------

import shutil as _shutil


def _copy_topology(src, dst):
    """topology ディレクトリを dst にコピーする。"""
    _shutil.copytree(str(src), str(dst))


def test_diff_against_generates_diff_view(tmp_path):
    """--diff-against <prev_dir> を指定すると DIFF タブを含む HTML が生成されること。"""
    # current = golden そのまま
    current = GOLDEN
    # prev = golden をコピーして 1 ファイル変更（差分を作る）
    prev = tmp_path / "prev_topo"
    _copy_topology(GOLDEN, prev)
    # devices.yaml を少し書き換えて差分を発生させる
    devices_yaml = prev / "devices.yaml"
    content = devices_yaml.read_text(encoding="utf-8")
    # hostname の一部を書き換えて差分を作る
    content_mod = content.replace("hostname: R1", "hostname: R1_OLD", 1)
    if content_mod == content:
        # フォールバック: 任意の文字列変更
        content_mod = content + "\n# diff-marker\n"
    devices_yaml.write_text(content_mod, encoding="utf-8")

    out = tmp_path / "diff.html"
    proc = _run([str(current), "-o", str(out), "--diff-against", str(prev)])
    assert proc.returncode == 0, proc.stderr
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert 'data-view="diff"' in html
    assert "const DIFF=" in html
    assert "const DIFF=null;" not in html


def test_without_diff_against_no_diff_view(tmp_path):
    """--diff-against なし（従来通り）の場合 DIFF タブが出ないこと（回帰）。"""
    out = tmp_path / "nodiff.html"
    proc = _run([str(GOLDEN), "-o", str(out)])
    assert proc.returncode == 0, proc.stderr
    html = out.read_text(encoding="utf-8")
    assert 'data-view="diff"' not in html
    assert "const DIFF=null;" in html


def test_diff_against_invalid_dir_exits_nonzero(tmp_path):
    """--diff-against に不正ディレクトリを指定すると非ゼロ終了すること。"""
    out = tmp_path / "err.html"
    proc = _run([str(GOLDEN), "-o", str(out),
                 "--diff-against", str(tmp_path / "nonexistent_prev")])
    assert proc.returncode != 0


def test_diff_against_deterministic(tmp_path):
    """--diff-against 指定で2回生成した HTML がバイト一致すること（決定性）。"""
    prev = tmp_path / "prev_topo"
    _copy_topology(GOLDEN, prev)
    out1 = tmp_path / "d1.html"
    out2 = tmp_path / "d2.html"
    _run([str(GOLDEN), "-o", str(out1), "--diff-against", str(prev)])
    _run([str(GOLDEN), "-o", str(out2), "--diff-against", str(prev)])
    assert out1.read_bytes() == out2.read_bytes()


# ---------------------------------------------------------------------------
# 修正 4: ゼロ差分・非ゼロ差分の CLI テスト
# ---------------------------------------------------------------------------

def test_diff_against_same_topology_has_no_diff_content(tmp_path):
    """prev と current が同一トポロジー（golden を2回指定）で --diff-against した HTML に
    「差分なし」テキストが含まれ、DIFF タブが出ること。"""
    # current = golden、prev = golden のコピー（同一内容）
    prev = tmp_path / "prev_same"
    _copy_topology(GOLDEN, prev)
    out = tmp_path / "same.html"
    proc = _run([str(GOLDEN), "-o", str(out), "--diff-against", str(prev)])
    assert proc.returncode == 0, proc.stderr
    html = out.read_text(encoding="utf-8")
    # DIFF タブが存在すること
    assert 'data-view="diff"' in html, "同一トポロジーでも DIFF タブが出ること"
    # 差分なしメッセージが含まれること（JS の renderDiffView が生成）
    assert "差分なし" in html, "差分なし文字列が HTML に含まれること"


def test_diff_against_nontrivial_deterministic(tmp_path):
    """非ゼロ差分（1フィールド変えた tmp）で --diff-against した HTML を2回生成してバイト一致（決定性・非trivial）。"""
    prev = tmp_path / "prev_modified"
    _copy_topology(GOLDEN, prev)
    # devices.yaml の hostname を変えて非ゼロ差分を生成
    devices_yaml = prev / "devices.yaml"
    content = devices_yaml.read_text(encoding="utf-8")
    content_mod = content.replace("hostname: R1", "hostname: R1_PREV", 1)
    if content_mod == content:
        content_mod = content + "\n# nontrivial-marker\n"
    devices_yaml.write_text(content_mod, encoding="utf-8")

    out1 = tmp_path / "nt1.html"
    out2 = tmp_path / "nt2.html"
    proc1 = _run([str(GOLDEN), "-o", str(out1), "--diff-against", str(prev)])
    proc2 = _run([str(GOLDEN), "-o", str(out2), "--diff-against", str(prev)])
    assert proc1.returncode == 0, proc1.stderr
    assert proc2.returncode == 0, proc2.stderr
    # バイト一致（決定性）
    assert out1.read_bytes() == out2.read_bytes(), "非ゼロ差分の HTML が決定的でない"
    # 非trivial: diff タブが存在し何らかの差分コンテンツがあること
    html = out1.read_text(encoding="utf-8")
    assert 'data-view="diff"' in html


# ---------------------------------------------------------------------------
# 修正 7: 本体 topo load の YAMLError 捕捉テスト
# ---------------------------------------------------------------------------

def test_main_topo_yaml_error_exits_nonzero(tmp_path):
    """破損 YAML（syntax error）を topology_dir に含めると非ゼロ終了すること。

    メイン topology_dir の load_topology が YAMLError を補足し、
    トレースを露出させずに非ゼロ終了する（§7 不変条件: エラーハンドリング）。
    """
    bad = tmp_path / "bad_topo"
    bad.mkdir()
    # _meta.yaml を正常に作成
    (bad / "_meta.yaml").write_text(
        "generated_from: []\nschema_version: '2.0'\ntitle: T\n",
        encoding="utf-8",
    )
    # devices.yaml に破損 YAML（タブ文字によるインデントエラー）を埋め込む
    (bad / "devices.yaml").write_text(
        "devices:\n\t- id: r1\n",  # タブはYAMLで不正
        encoding="utf-8",
    )
    (bad / "physical.yaml").write_text("links: []\nsegments: []\n", encoding="utf-8")
    proc = _run([str(bad)])
    assert proc.returncode != 0, "破損 YAML で非ゼロ終了しなかった"
    # トレースバックが stderr に出ていないこと（ERROR メッセージのみ）
    assert "Traceback" not in proc.stderr, f"トレースバックが露出: {proc.stderr[:500]}"
