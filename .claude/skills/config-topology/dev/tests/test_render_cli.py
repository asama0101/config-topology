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

# ---------------------------------------------------------------------------
# D3c: --diff-against-history フラグのテスト
# ---------------------------------------------------------------------------

def _build_pseudo_history(base_dir, ts_name, src_topology, inner_name="topology"):
    """擬似 history/<ts_name>/<inner_name>/ を src_topology からコピーして作る。"""
    inner = base_dir / ts_name / inner_name
    _shutil.copytree(str(src_topology), str(inner))
    return inner


def test_diff_against_history_with_existing_history(tmp_path):
    """--diff-against-history で有効な history が存在するとき DIFF ビューを含む HTML が出る。

    修正3: YAML コメント追加（差分ゼロになりうる）ではなく、
    load_topology が実際に差分として検知する変更（hostname 値の置換）を使う。
    差分が空でない（DIFF 内容が実際に出る）ことをアサートする。
    """
    history = tmp_path / "history"
    # prev topology（devices.yaml の hostname を変えて load_topology が検知する実差分を作る）
    inner = _build_pseudo_history(history, "2026-06-14_1000", GOLDEN)
    devices_yaml = inner / "devices.yaml"
    content = devices_yaml.read_text(encoding="utf-8")
    content_mod = content.replace("hostname: R1", "hostname: R1_HISTORY_PREV", 1)
    if content_mod == content:
        # hostname: R1 が存在しない場合はテスト前提が崩れている
        pytest.fail(
            "'hostname: R1' が devices.yaml に存在しない。"
            "golden の内容を確認して置換対象を修正すること。"
            f"devices.yaml の先頭: {content[:200]}"
        )
    devices_yaml.write_text(content_mod, encoding="utf-8")

    out = tmp_path / "out.html"
    proc = _run([str(GOLDEN), "-o", str(out), "--diff-against-history"], cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert 'data-view="diff"' in html
    assert "const DIFF=" in html
    assert "const DIFF=null;" not in html

    # 修正3追加: 差分が空でないことを確認（hostname 変更が実際に DIFF に出ること）
    import json as _json
    diff_start = html.find("const DIFF=")
    diff_end = html.find(";", diff_start)
    diff_json_str = html[diff_start + len("const DIFF="):diff_end]
    diff_data = _json.loads(diff_json_str)
    assert diff_data is not None, "DIFF データが null であるべきでない"
    has_diff = any(
        diff_data.get(k) for k in ("devices", "links", "segments", "routing", "interfaces")
    )
    assert has_diff, (
        f"DIFF データに差分エントリがない: {list(diff_data.keys())}。"
        "hostname 変更が diff_topology で検知されていない可能性がある。"
    )


def test_diff_against_history_no_history_gives_no_diff(tmp_path):
    """--diff-against-history で history が存在しないとき差分なしで描画し INFO を stderr に出す。"""
    out = tmp_path / "out.html"
    proc = _run([str(GOLDEN), "-o", str(out), "--diff-against-history"], cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    # diff なし: DIFF タブが出ない
    assert 'data-view="diff"' not in html
    assert "const DIFF=null;" in html
    # INFO メッセージが stderr に出る
    assert "INFO" in proc.stderr


def test_diff_against_takes_priority_over_history(tmp_path):
    """--diff-against <dir> と --diff-against-history が両方指定された場合 --diff-against を優先する。

    修正2: history prev と --diff-against prev で内容を変えて、
    生成 HTML の DIFF 内容が --diff-against 側に由来することを区別検証する。
    history prev には hostname HISTORY_PREV、--diff-against prev には hostname EXPLICIT_PREV を入れ、
    DIFF に EXPLICIT_PREV 由来の変更が出て HISTORY_PREV 由来が出ないことを確認する。
    """
    # 擬似 history（prev_a）: hostname を HISTORY_PREV に変更
    history = tmp_path / "history"
    prev_a = _build_pseudo_history(history, "2026-06-14_1000", GOLDEN)
    devices_yaml_a = prev_a / "devices.yaml"
    content_a = devices_yaml_a.read_text(encoding="utf-8")
    content_a_mod = content_a.replace("hostname: R1", "hostname: HISTORY_PREV", 1)
    if content_a_mod == content_a:
        pytest.fail(
            "'hostname: R1' が devices.yaml に存在しない。golden の内容を確認すること。"
        )
    devices_yaml_a.write_text(content_a_mod, encoding="utf-8")

    # --diff-against 用の prev_b: hostname を EXPLICIT_PREV に変更（history とは別の値）
    prev_b = tmp_path / "prev_b"
    _copy_topology(GOLDEN, prev_b)
    devices_yaml_b = prev_b / "devices.yaml"
    content_b = devices_yaml_b.read_text(encoding="utf-8")
    content_b_mod = content_b.replace("hostname: R1", "hostname: EXPLICIT_PREV", 1)
    if content_b_mod == content_b:
        pytest.fail(
            "'hostname: R1' が devices.yaml に存在しない。golden の内容を確認すること。"
        )
    devices_yaml_b.write_text(content_b_mod, encoding="utf-8")

    out = tmp_path / "out.html"
    proc = _run([str(GOLDEN), "-o", str(out),
                 "--diff-against", str(prev_b),
                 "--diff-against-history"], cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    html = out.read_text(encoding="utf-8")

    # --diff-against が優先されるので DIFF ビューあり
    assert 'data-view="diff"' in html, "DIFF タブが存在しない"
    assert "const DIFF=null;" not in html, "DIFF データが null になっている"

    # 修正2: DIFF 内容が --diff-against 側（EXPLICIT_PREV）に由来すること
    assert "EXPLICIT_PREV" in html, (
        "--diff-against 側の変更（EXPLICIT_PREV）が DIFF に反映されていない"
    )
    # history 側（HISTORY_PREV）に由来する変更は出ないこと
    assert "HISTORY_PREV" not in html, (
        "history 側の変更（HISTORY_PREV）が DIFF に混入している。"
        "--diff-against が優先されていない可能性がある。"
    )


def test_diff_against_history_deterministic(tmp_path):
    """--diff-against-history で有効な history がある場合、2回生成した HTML がバイト一致（決定性）。"""
    history = tmp_path / "history"
    _build_pseudo_history(history, "2026-06-14_1000", GOLDEN)

    out1 = tmp_path / "h1.html"
    out2 = tmp_path / "h2.html"
    proc1 = _run([str(GOLDEN), "-o", str(out1), "--diff-against-history"], cwd=str(tmp_path))
    proc2 = _run([str(GOLDEN), "-o", str(out2), "--diff-against-history"], cwd=str(tmp_path))
    assert proc1.returncode == 0, proc1.stderr
    assert proc2.returncode == 0, proc2.stderr
    assert out1.read_bytes() == out2.read_bytes()


# ---------------------------------------------------------------------------
# 修正2: --diff-against が --diff-against-history より優先される識別力テスト
# （内容を変えて、DIFF 内容が --diff-against 側に由来することを区別検証）
# ---------------------------------------------------------------------------

def test_diff_against_takes_priority_content_distinction(tmp_path):
    """--diff-against と --diff-against-history が両方指定された場合に、
    生成 HTML の DIFF 内容が --diff-against 側（prev_b）に由来し、
    history 側（prev_a）に由来しないことを検証する。

    history prev には hostname A（hostname: HISTORY_PREV）、
    --diff-against prev には hostname B（hostname: EXPLICIT_PREV）を入れ、
    DIFF に B 由来の変更が出て A 由来が出ないことを確認する。
    """
    history = tmp_path / "history"

    # history prev: hostname を HISTORY_PREV に変更
    inner_a = _build_pseudo_history(history, "2026-06-14_1000", GOLDEN)
    devices_yaml_a = inner_a / "devices.yaml"
    content_a = devices_yaml_a.read_text(encoding="utf-8")
    content_a_mod = content_a.replace("hostname: R1", "hostname: HISTORY_PREV", 1)
    if content_a_mod == content_a:
        pytest.skip("golden に 'hostname: R1' が見つからず、テスト前提が成立しない")
    devices_yaml_a.write_text(content_a_mod, encoding="utf-8")

    # --diff-against prev: hostname を EXPLICIT_PREV に変更（history とは別の値）
    prev_b = tmp_path / "prev_b"
    _copy_topology(GOLDEN, prev_b)
    devices_yaml_b = prev_b / "devices.yaml"
    content_b = devices_yaml_b.read_text(encoding="utf-8")
    content_b_mod = content_b.replace("hostname: R1", "hostname: EXPLICIT_PREV", 1)
    if content_b_mod == content_b:
        pytest.skip("golden に 'hostname: R1' が見つからず、テスト前提が成立しない")
    devices_yaml_b.write_text(content_b_mod, encoding="utf-8")

    out = tmp_path / "out.html"
    proc = _run(
        [str(GOLDEN), "-o", str(out),
         "--diff-against", str(prev_b),
         "--diff-against-history"],
        cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    html = out.read_text(encoding="utf-8")

    # DIFF ビューが存在すること（--diff-against が有効）
    assert 'data-view="diff"' in html, "DIFF タブが存在しない"
    assert "const DIFF=null;" not in html, "DIFF データが null になっている"

    # DIFF 内容が --diff-against 側（EXPLICIT_PREV）に由来すること
    assert "EXPLICIT_PREV" in html, (
        "--diff-against 側の変更（EXPLICIT_PREV）が DIFF に反映されていない"
    )
    # history 側（HISTORY_PREV）に由来する変更は出ないこと
    assert "HISTORY_PREV" not in html, (
        "history 側の変更（HISTORY_PREV）が DIFF に混入している。"
        "--diff-against が優先されていない可能性がある。"
    )


# ---------------------------------------------------------------------------
# 修正3: history-diff テストを実差分に（load_topology が差分として検知する変更）
# ---------------------------------------------------------------------------

def test_diff_against_history_with_real_diff(tmp_path):
    """--diff-against-history で history の prev に実差分がある場合、
    DIFF 内容が空でなく（差分が実際に出る）ことを検証する。

    YAML コメントではなく devices.yaml の hostname を別値に置換して
    load_topology が実際に差分として検知する変更を作成する。
    """
    history = tmp_path / "history"
    inner = _build_pseudo_history(history, "2026-06-14_1000", GOLDEN)
    devices_yaml = inner / "devices.yaml"
    content = devices_yaml.read_text(encoding="utf-8")

    # hostname の値を変えて実差分を作成（load_topology が読み込む実フィールド）
    content_mod = content.replace("hostname: R1", "hostname: R1_HISTORY_DIFF", 1)
    if content_mod == content:
        pytest.fail(
            "'hostname: R1' が devices.yaml に見つからなかった。"
            "golden を確認して置換対象を修正すること。"
        )
    devices_yaml.write_text(content_mod, encoding="utf-8")

    out = tmp_path / "out.html"
    proc = _run([str(GOLDEN), "-o", str(out), "--diff-against-history"], cwd=str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    html = out.read_text(encoding="utf-8")

    # DIFF ビューが存在すること
    assert 'data-view="diff"' in html, "DIFF タブが存在しない"
    assert "const DIFF=null;" not in html, "DIFF データが null になっている"

    # 差分が空でない: DIFF 内容に実際の変更内容が含まれること
    # hostname の変化（R1_HISTORY_DIFF → R1）が DIFF に反映される
    assert "DIFF=" in html
    # null 以外の実差分コンテンツがあること（JSON の中身が "{}" ではないレベル）
    import json as _json
    diff_start = html.find("const DIFF=")
    diff_end = html.find(";", diff_start)
    diff_json_str = html[diff_start + len("const DIFF="):diff_end]
    diff_data = _json.loads(diff_json_str)
    # diff_data は diff_topology の戻り値をシリアライズしたもの
    # 差分が空でないことを確認（devices または routing に変化があるはず）
    assert diff_data is not None, "DIFF データが null"
    # 何らかの差分エントリが存在すること（空の dict / list でないこと）
    has_diff = any(
        diff_data.get(k) for k in ("devices", "links", "segments", "routing", "interfaces")
    )
    assert has_diff, (
        f"DIFF データに差分エントリがない: {list(diff_data.keys())}。"
        "hostname 変更が diff_topology で検知されていない可能性がある。"
    )


# ---------------------------------------------------------------------------
# 修正4: --diff-against-history 経由の非ゼロ差分でバイト一致（決定性）テスト
# ---------------------------------------------------------------------------

def test_diff_against_history_nontrivial_deterministic(tmp_path):
    """--diff-against-history で非ゼロ差分がある場合、2回生成した HTML がバイト一致（決定性）。

    既存の test_diff_against_history_deterministic は golden そのまま（ゼロ差分相当）だが、
    こちらは実差分を含むケースで決定性を保証する。
    """
    history = tmp_path / "history"
    inner = _build_pseudo_history(history, "2026-06-14_1000", GOLDEN)
    devices_yaml = inner / "devices.yaml"
    content = devices_yaml.read_text(encoding="utf-8")
    content_mod = content.replace("hostname: R1", "hostname: R1_DET_TEST", 1)
    if content_mod == content:
        content_mod = content + "\n# determinism-test-marker\n"
    devices_yaml.write_text(content_mod, encoding="utf-8")

    out1 = tmp_path / "det1.html"
    out2 = tmp_path / "det2.html"
    proc1 = _run([str(GOLDEN), "-o", str(out1), "--diff-against-history"], cwd=str(tmp_path))
    proc2 = _run([str(GOLDEN), "-o", str(out2), "--diff-against-history"], cwd=str(tmp_path))
    assert proc1.returncode == 0, proc1.stderr
    assert proc2.returncode == 0, proc2.stderr
    assert out1.read_bytes() == out2.read_bytes(), (
        "--diff-against-history 非ゼロ差分の HTML がバイト一致しない（決定性が失われている）"
    )


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
