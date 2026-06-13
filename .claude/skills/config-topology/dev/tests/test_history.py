# rebuild/dev/tests/test_history.py
"""§10.3 history 退避（旧成果物の自動退避）のテスト。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # rebuild/
from lib.history import (  # noqa: E402
    current_timestamp,
    latest_history_topology,
    retain_for_build,
    retain_for_render,
    unique_history_dir,
)

pytestmark = pytest.mark.integration


def test_current_timestamp_format():
    ts = current_timestamp()
    # YYYY-MM-DD_HHMM の固定幅（例: 2026-06-14_1530）
    assert len(ts) == len("2026-06-14_1530")
    assert ts[4] == "-" and ts[7] == "-" and ts[10] == "_"
    assert ts.replace("-", "").replace("_", "").isdigit()


def test_unique_history_dir_no_collision(tmp_path):
    got = unique_history_dir(tmp_path, "2026-06-14_1530")
    assert got == tmp_path / "2026-06-14_1530"


def test_unique_history_dir_collision_suffix(tmp_path):
    (tmp_path / "2026-06-14_1530").mkdir()
    (tmp_path / "2026-06-14_1530_2").mkdir()
    got = unique_history_dir(tmp_path, "2026-06-14_1530")
    assert got == tmp_path / "2026-06-14_1530_3"


def _seed_topo_dir(d):
    d.mkdir(parents=True)
    (d / "devices.yaml").write_text("devices: []\n", encoding="utf-8")


def test_retain_build_moves_existing_yaml(tmp_path):
    out = tmp_path / "topology"
    _seed_topo_dir(out)
    history = tmp_path / "history"
    dest = retain_for_build(out, None, "2026-06-14_1530", history_root=history)
    assert dest == history / "2026-06-14_1530"
    assert (dest / "topology" / "devices.yaml").exists()
    assert not out.exists()                       # 元ディレクトリは移動済み


def test_retain_build_none_when_empty(tmp_path):
    out = tmp_path / "topology"                    # 存在しない
    history = tmp_path / "history"
    dest = retain_for_build(out, None, "2026-06-14_1530", history_root=history)
    assert dest is None
    assert not history.exists()                    # 退避不要なら history も作らない


def test_retain_build_pairs_html_into_same_dir(tmp_path):
    out = tmp_path / "topology"
    _seed_topo_dir(out)
    html = tmp_path / "topology.html"
    html.write_text("<!doctype html>", encoding="utf-8")
    history = tmp_path / "history"
    dest = retain_for_build(out, html, "2026-06-14_1530", history_root=history)
    assert (dest / "topology" / "devices.yaml").exists()
    assert (dest / "topology.html").exists()       # 同一退避ディレクトリへペア退避
    assert not html.exists()


def test_retain_build_html_only_when_pair_given(tmp_path):
    # html_pair=None（非既定パス相当）のとき既存 HTML を巻き込まない
    out = tmp_path / "topology"
    _seed_topo_dir(out)
    html = tmp_path / "topology.html"
    html.write_text("<!doctype html>", encoding="utf-8")
    history = tmp_path / "history"
    dest = retain_for_build(out, None, "2026-06-14_1530", history_root=history)
    assert (dest / "topology").exists()
    assert html.exists()                           # HTML は退避されず残る


def test_retain_build_html_not_moved_when_no_yaml(tmp_path):
    # output_dir に YAML が無い + html_pair 実在 → ペア前提が崩れるので退避しない
    out = tmp_path / "topology"           # 作成しない（YAML なし）
    html = tmp_path / "topology.html"
    html.write_text("<!doctype html>", encoding="utf-8")
    history = tmp_path / "history"
    dest = retain_for_build(out, html, "2026-06-14_1530", history_root=history)
    assert dest is None
    assert html.exists()                  # HTML は退避されず残る
    assert not history.exists()           # history も作られない


def test_retain_build_collision_suffix(tmp_path):
    out = tmp_path / "topology"
    _seed_topo_dir(out)
    history = tmp_path / "history"
    (history / "2026-06-14_1530").mkdir(parents=True)   # 既存退避ディレクトリ
    dest = retain_for_build(out, None, "2026-06-14_1530", history_root=history)
    assert dest == history / "2026-06-14_1530_2"


def test_retain_render_moves_existing_html(tmp_path):
    html = tmp_path / "topology.html"
    html.write_text("<!doctype html>old", encoding="utf-8")
    history = tmp_path / "history"
    dest = retain_for_render(html, "2026-06-14_1530", history_root=history)
    assert dest == history / "2026-06-14_1530"
    assert (dest / "topology.html").read_text(encoding="utf-8") == "<!doctype html>old"
    assert not html.exists()


def test_retain_render_none_when_absent(tmp_path):
    html = tmp_path / "topology.html"              # 存在しない
    history = tmp_path / "history"
    dest = retain_for_render(html, "2026-06-14_1530", history_root=history)
    assert dest is None
    assert not history.exists()


# ---------------------------------------------------------------------------
# D3c: latest_history_topology のテスト
# ---------------------------------------------------------------------------

def _seed_history_topology(history_root, ts_name, inner_name="topology"):
    """history_root/<ts_name>/<inner_name>/_meta.yaml を作成し inner dir の Path を返す。"""
    inner = history_root / ts_name / inner_name
    inner.mkdir(parents=True)
    (inner / "_meta.yaml").write_text(
        "generated_from: []\nschema_version: '2.0'\ntitle: T\n", encoding="utf-8"
    )
    return inner


class TestLatestHistoryTopology:
    """latest_history_topology の仕様テスト。"""

    def test_returns_none_when_history_root_absent(self, tmp_path):
        """history_root 自体が存在しない場合は None を返す。"""
        result = latest_history_topology(tmp_path / "nonexistent_history")
        assert result is None

    def test_returns_none_when_history_root_empty(self, tmp_path):
        """history_root が空ディレクトリのとき None を返す。"""
        history = tmp_path / "history"
        history.mkdir()
        result = latest_history_topology(history)
        assert result is None

    def test_returns_inner_dir_for_single_entry(self, tmp_path):
        """単一 <ts>/topology/_meta.yaml があれば inner dir の Path を返す。"""
        history = tmp_path / "history"
        inner = _seed_history_topology(history, "2026-06-14_1200")
        result = latest_history_topology(history)
        assert result == inner

    def test_returns_path_containing_meta_yaml(self, tmp_path):
        """返り値の Path 内に _meta.yaml が存在すること。"""
        history = tmp_path / "history"
        _seed_history_topology(history, "2026-06-14_1200")
        result = latest_history_topology(history)
        assert result is not None
        assert (result / "_meta.yaml").exists()

    def test_returns_latest_when_multiple_entries(self, tmp_path):
        """複数 <ts>/ がある場合は最新（降順 max）の inner dir を返す。"""
        history = tmp_path / "history"
        _seed_history_topology(history, "2026-06-13_0900")   # 古い
        _seed_history_topology(history, "2026-06-14_1200")   # 新しい（最新）
        result = latest_history_topology(history)
        assert result == history / "2026-06-14_1200" / "topology"

    def test_does_not_return_older_entry(self, tmp_path):
        """最新を返し、古い方のパスを返さないこと。"""
        history = tmp_path / "history"
        _seed_history_topology(history, "2026-06-13_0900")   # 古い
        _seed_history_topology(history, "2026-06-14_1200")   # 新しい
        result = latest_history_topology(history)
        assert result != history / "2026-06-13_0900" / "topology"

    def test_collision_suffix_is_selected_over_base(self, tmp_path):
        """_2/_3 連番 <ts> は base より後にソートされ、最新の衝突が選ばれる。"""
        history = tmp_path / "history"
        _seed_history_topology(history, "2026-06-14_1200")    # base
        _seed_history_topology(history, "2026-06-14_1200_2")  # 連番（衝突）→ 新しい
        result = latest_history_topology(history)
        # 降順 lexical で "2026-06-14_1200_2" > "2026-06-14_1200"
        assert result == history / "2026-06-14_1200_2" / "topology"

    def test_skips_ts_dir_without_meta_yaml(self, tmp_path):
        """_meta.yaml を持たない <ts>/（render-only 退避 = topology.html のみ）をスキップする。"""
        history = tmp_path / "history"
        # render-only 退避: topology.html のみ
        render_only = history / "2026-06-14_1300"
        render_only.mkdir(parents=True)
        (render_only / "topology.html").write_text("<!doctype html>", encoding="utf-8")
        # _meta.yaml を持つ古い build 退避
        _seed_history_topology(history, "2026-06-14_1200")
        result = latest_history_topology(history)
        assert result == history / "2026-06-14_1200" / "topology"

    def test_returns_none_when_all_ts_dirs_lack_meta_yaml(self, tmp_path):
        """全 <ts>/ に _meta.yaml を持つ inner dir が無いとき None を返す。"""
        history = tmp_path / "history"
        # HTML のみのディレクトリ×2
        for ts in ["2026-06-14_1200", "2026-06-14_1300"]:
            d = history / ts
            d.mkdir(parents=True)
            (d / "topology.html").write_text("<!doctype html>", encoding="utf-8")
        result = latest_history_topology(history)
        assert result is None

    def test_inner_dir_name_matches_original_topology_name(self, tmp_path):
        """inner dir 名は topology に限らず任意の名前でも正しく返る（inner_name=my_topo）。"""
        history = tmp_path / "history"
        inner = _seed_history_topology(history, "2026-06-14_1200", inner_name="my_topo")
        result = latest_history_topology(history)
        assert result == inner

    def test_deterministic_same_fs_same_result(self, tmp_path):
        """同一 FS 状態に対して2回呼んでも同じ結果（決定性）。"""
        history = tmp_path / "history"
        _seed_history_topology(history, "2026-06-13_0900")
        _seed_history_topology(history, "2026-06-14_1200")
        r1 = latest_history_topology(history)
        r2 = latest_history_topology(history)
        assert r1 == r2

    # -------------------------------------------------------------------
    # 修正1: 連番 _N の数値ソートテスト
    # -------------------------------------------------------------------

    def test_numeric_suffix_sort_prefers_10_over_9(self, tmp_path):
        """同一 base（タイムスタンプ）に _9 と _10 が衝突した場合、数値的に大きい _10（最新）が選ばれる。

        lexical ソートでは "2026-06-14_1200_9" > "2026-06-14_1200_10"（文字列比較で '9' > '1'）
        になり _9 が選ばれてしまう。数値ソートでは _10 が選ばれなければならない。
        """
        history = tmp_path / "history"
        # base, _9, _10 を全部作成
        _seed_history_topology(history, "2026-06-14_1200")      # base（最古）
        _seed_history_topology(history, "2026-06-14_1200_9")    # 9番目（中間）
        _seed_history_topology(history, "2026-06-14_1200_10")   # 10番目（最新）
        result = latest_history_topology(history)
        # 数値ソートなら _10 が最大 → 選ばれる
        assert result == history / "2026-06-14_1200_10" / "topology", (
            f"_10 が選ばれるべきだが {result} が返った。"
            "lexical ソートでは _9 > _10 になるため、数値ソートが必要。"
        )

    def test_lexical_sort_would_fail_numeric_suffix(self, tmp_path):
        """対照テスト: lexical ソートの実装では _9 が _10 より優先されてしまうことを示す。

        このテストは現行実装(lexical)が「間違った結果」を返すことを明示し、
        数値ソートへの修正が必要であることを実証する。
        """
        history = tmp_path / "history"
        _seed_history_topology(history, "2026-06-14_1200")
        _seed_history_topology(history, "2026-06-14_1200_9")
        _seed_history_topology(history, "2026-06-14_1200_10")

        # lexical 順では "2026-06-14_1200_9" > "2026-06-14_1200_10" になる
        names = ["2026-06-14_1200", "2026-06-14_1200_9", "2026-06-14_1200_10"]
        lexical_max = sorted(names, reverse=True)[0]
        # lexical では _9 が最大になることを確認（対照実証）
        assert lexical_max == "2026-06-14_1200_9", (
            "lexical ソートでは _9 が _10 より大きく見えることを確認"
        )
        # 一方、数値ソートでは _10 が最大でなければならない
        # latest_history_topology の正しい実装は _10 を返す（前テストで検証済み）

    # -------------------------------------------------------------------
    # 修正4: _meta.yaml を持たないサブディレクトリのみを含む <ts> のスキップテスト
    # -------------------------------------------------------------------

    def test_skips_ts_dir_with_only_subdir_without_meta_yaml(self, tmp_path):
        """<ts>/ 直下にサブディレクトリはあるが _meta.yaml を持たない場合、その <ts> をスキップする。

        ファイル直置きのみでなく「サブディレクトリだが _meta.yaml なし」のケース。
        """
        history = tmp_path / "history"
        # 新しい <ts>: サブディレクトリはあるが _meta.yaml を持たない
        no_meta_ts = history / "2026-06-14_1300"
        no_meta_ts.mkdir(parents=True)
        # サブディレクトリを作るが _meta.yaml は置かない
        subdir_without_meta = no_meta_ts / "no_meta_inner"
        subdir_without_meta.mkdir()
        (subdir_without_meta / "devices.yaml").write_text("devices: []\n", encoding="utf-8")
        # _meta.yaml を持たない別のサブディレクトリも追加
        another_no_meta = no_meta_ts / "also_no_meta"
        another_no_meta.mkdir()
        (another_no_meta / "routing.yaml").write_text("bgp: {}\n", encoding="utf-8")

        # 古い <ts>: 正常な _meta.yaml あり
        _seed_history_topology(history, "2026-06-14_1200")

        result = latest_history_topology(history)
        # _meta.yaml なしの新しい <ts> はスキップされ、古い正常 <ts> が選ばれる
        assert result == history / "2026-06-14_1200" / "topology", (
            f"_meta.yaml を持たない <ts> をスキップし旧エントリを返すべきだが {result} が返った"
        )

    # -------------------------------------------------------------------
    # 修正4: --diff-against-history 経由の非ゼロ差分で render を2回実行しバイト一致（決定性）
    # （render側テストは test_render_cli.py に追加、ここでは history 関数単体の決定性を補強）
    # -------------------------------------------------------------------

    def test_numeric_sort_deterministic_multiple_calls(self, tmp_path):
        """数値サフィックスを含む複数 <ts> がある状態で複数回呼んでも同一結果（決定性）。"""
        history = tmp_path / "history"
        _seed_history_topology(history, "2026-06-14_1200")
        _seed_history_topology(history, "2026-06-14_1200_9")
        _seed_history_topology(history, "2026-06-14_1200_10")
        _seed_history_topology(history, "2026-06-13_0900")
        r1 = latest_history_topology(history)
        r2 = latest_history_topology(history)
        assert r1 == r2, "数値サフィックスソート後も決定性を維持すること"
