"""アセット（CSS/BODY/JS）の自己完結性・適応の構造テスト。"""
import json
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


def test_status_bgp_counts_unique_sessions():
    # ステータスバー bgp は各 bgpEdge の afs 数の総和＝ユニーク BGP セッション数を示す。
    # dual-stack（同一リンク/ペアの v4+v6）は 1 エッジ・afs=["v4","v6"] で 2 と数える。
    # v4-only は各 afs=["v4"] なので総和=エッジ数（双方向2エントリを1セッションに正規化）。
    # ※元の機器別 bgp[] 合算ロジックは双方向セッションを二重計上していた（本修正で是正）。
    assert '$("#st-bgp").textContent = DATA.bgpEdges.reduce((n,e)=>n+e.afs.length,0)' in assets._JS
    # 回帰ガード: 機器ごとの bgp[] を合算する旧ロジックが復活していないこと。
    assert 'reduce((n,d)=>n+d.bgp.length' not in assets._JS


def test_addr_table_af_uses_string_comparison():
    # addrs[].af は文字列 "v4"/"v6"。数値比較(=== 4/=== 6)は常に false になりバグる。
    assert 'a.af === 4' not in assets._JS
    assert 'a.af === 6' not in assets._JS
    assert 'a.af === "v4"' in assets._JS
    assert 'a.af === "v6"' in assets._JS


def test_addr_table_excludes_link_local():
    # addrs[] を消費する2ループ（表 secondary 行・重複IP検出）の双方で link-local を除外する。
    # DATA.addrs[].scope は "link-local" | undefined（models.Address.to_dict）。
    # 各ループ固有のコメントで個別に裏取り（ヘルパ化や片側統合でも意図ズレを検知）。
    assert 'a.scope === "link-local"' in assets._JS                      # ガード自体が存在
    assert 'link-local(fe80::) は ADDRESSES 表に出さない' in assets._JS   # 表 secondary 行ループ
    assert 'link-local は重複IP判定の対象外' in assets._JS                # 重複IP検出ループ


def test_node_check_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不在のため構文チェックをスキップ")
    stub = ("const DATA={devices:{},links:[],segments:[],extPeers:[],bgpEdges:[],"
            "meta:{generated_from:[]},"
            "stats:{devices:0,interfaces:0,links:0,segments:0,"
            "by_vendor:{},by_as:{},by_area:{},link_kinds:{link:0,segment:0,stub:0},"
            "dualstack_ifs:0,bgp_sessions:0,ospf_networks:0,static_routes:0},"
            "checks:[]};"
            "const POS={};const VIEWS=['physical','stats','checks','addr','ifs'];\n")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(stub + assets._JS)
        path = f.name
    try:
        r = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    finally:
        os.unlink(path)


def test_ifv6list_helper_present():
    assert 'function ifV6List' in assets._JS


def test_interfaces_and_card_show_all_v6():
    # INTERFACES 表の行データとデバイス詳細カードが、それぞれ ifV6List を参照する。
    # （定義行を数に含めず、2つの呼び出し箇所を文脈付きで個別に裏取りする）
    assert 'v6list: ifV6List(i)' in assets._JS      # INTERFACES 表の行データ
    assert 'const v6=ifV6List(i)' in assets._JS     # デバイス詳細カード（1回呼んで GUA/LL に分配）


def test_device_card_ipv4_ipv6_columns():
    # Device Detail カードは IPv4 と IPv6 を別列に分け、link-local は IPv6 列に淡色併記
    # （専用 LL 列は持たない）。フルスクリーン INTERFACES 表の IPv6 列と同じ扱い。
    assert '<th>IPv4</th><th>IPv6</th><th>Desc</th>' in assets._JS   # IPv4/IPv6 分離・直後が Desc
    assert 'title="link-local">LL' not in assets._JS                 # 専用 LL 列ヘッダは無い
    assert 'v6.map(x=>x.ll?' in assets._JS                           # IPv6 セルが全 v6 を ll 条件で淡色併記


def test_link_end_label_includes_link_local():
    # リンク端ラベルが端点 IF の link-local を ifV6List 経由で抽出し、faint 行として描く。
    assert 'ifV6List(itf).filter(x=>x.ll)' in assets._JS   # リンク端ラベル固有の抽出
    assert 'faint:true' in assets._JS                       # faint 行として渡す
    assert '.iflabel.ll' in assets._CSS                     # SVG ラベル淡色


# ---------------------------------------------------------------------------
# 修正 1: OSPF バッジ title 属性のエスケープ正確性テスト
# ---------------------------------------------------------------------------

def test_ospf_badge_builds_from_raw_not_esc_parts():
    """ospfBadge が生値の配列 raw[] から組み立て、title と本文を別々に esc() すること。

    旧実装は esc() 済みの parts 要素を再 join して title に渡すため、
    network_type に特殊文字が入ると二重エスケープまたは属性破壊のリスクがあった。
    修正後は const raw = [] から生値を収集し、
      title="OSPF: ${esc("OSPF: " + raw.join(" | "))}" の形式で一括エスケープすること。
    """
    # raw 配列から生値を収集するパターン
    assert 'const raw = [];' in assets._JS
    # title は raw.join(" | ") の生値を esc() で一括エスケープ
    assert 'esc("OSPF: " + raw.join(" | "))' in assets._JS
    # 本文は raw.join(" ") を esc() で一括エスケープ
    assert 'esc(raw.join(" "))' in assets._JS
    # cost は != null チェック（0でも表示）
    assert 'r.ospf.cost != null' in assets._JS
    # 旧実装の esc(String(r.ospf.cost)) が parts[] に push される形式は消えていること
    assert 'parts.push(`cost ${esc(String(r.ospf.cost))}`' not in assets._JS


# ---------------------------------------------------------------------------
# D2 設計検証パネル — JS アセットテスト
# ---------------------------------------------------------------------------

def test_render_checks_view_function_exists():
    """JS に renderChecksView 関数が定義されていること。"""
    assert "function renderChecksView" in assets._JS


def test_is_table_view_includes_checks():
    """isTableView() が 'checks' を table view として扱うこと。"""
    assert '"checks"' in assets._JS
    # isTableView で checks が含まれていること
    assert 'S.view === "checks"' in assets._JS


def test_render_checks_view_uses_data_checks():
    """renderChecksView が DATA.checks を参照すること。"""
    assert "DATA.checks" in assets._JS


def test_render_checks_view_has_empty_message():
    """0 件のとき肯定メッセージを表示するコードが含まれること。"""
    assert "問題は検出されませんでした" in assets._JS


def test_render_checks_view_uses_esc():
    """renderChecksView が esc() を使用して XSS 対策していること。"""
    # renderChecksView 内で esc() が呼ばれていること（関数定義から探す）
    checks_start = assets._JS.find("function renderChecksView")
    assert checks_start != -1
    # 関数本体内で esc が使われていること
    checks_section = assets._JS[checks_start:checks_start + 2000]
    assert "esc(" in checks_section


def test_render_table_view_dispatches_to_checks():
    """renderTableView が checks ビューに対して renderChecksView を呼び出すこと。"""
    assert "renderChecksView()" in assets._JS


# ---------------------------------------------------------------------------
# C1 [render テスト]: BGP SESSIONS 表の src 列
# ---------------------------------------------------------------------------

def test_bgp_sessions_table_has_src_column_header():
    """BGP SESSIONS 表に <th>src</th> ヘッダが存在すること。

    §8.5: デバイス詳細カードの BGP SESSIONS テーブルには
    neighbor / peer AS / type / af に加えて src 列を持つ。
    """
    assert '<th>src</th>' in assets._JS


def test_bgp_sessions_table_renders_esc_b_src():
    """BGP SESSIONS 表のデータ行が esc(b.src) を経由して src を描画すること。

    b.src が truthy のとき esc(b.src) で XSS エスケープして表示すること。
    """
    assert 'esc(b.src)' in assets._JS


def test_bgp_sessions_table_src_fallback_dash():
    """b.src が falsy（None/undefined/空文字）のとき "—" を表示すること。"""
    # b.src ? esc(b.src) : "—" パターン
    assert 'b.src?esc(b.src):"—"' in assets._JS


# ---------------------------------------------------------------------------
# B1 隣接フォーカスモード — string-presence テスト（補助）
# ---------------------------------------------------------------------------

def test_focus_mode_state_in_js():
    """S.focusMode と S.focusHops が state に定義されていること。"""
    assert 'S.focusMode' in assets._JS
    assert 'S.focusHops' in assets._JS


def test_focus_btn_in_body():
    """_BODY に id="btn-focus" ボタンが存在し、class="tbtn gonly" が付与されていること。

    gonly クラスは図ビュー専用（表ビューに切り替わると hidden になる）。
    実装の属性順（class="tbtn gonly" id="btn-focus"）に合わせて検証する。
    """
    assert 'id="btn-focus"' in assets._BODY
    assert 'class="tbtn gonly" id="btn-focus"' in assets._BODY  # 図ビュー専用クラスが付与されていること


def test_nhop_neighbors_function_in_js():
    """_JS に nHopNeighbors 関数が定義されていること。"""
    assert 'function nHopNeighbors' in assets._JS


def test_focus_set_in_apply_visibility():
    """applyVisibility 内で focusSet と focusActive が使われていること。"""
    assert 'focusSet' in assets._JS
    assert 'focusActive' in assets._JS  # 二重ガード集約変数が存在すること


def test_focus_mode_dim_condition_for_nodes():
    """ノードの dim 条件に focusMode ガードが含まれること。

    focusActive 変数（= S.focusMode && S.sel.size）を使った名前付き条件で検証する。
    同一条件の二重記述を 1 変数に集約（maint HIGH 修正後の形式）。
    """
    assert 'focusActive && !focusSet.has(id)' in assets._JS


def test_focus_mode_dim_condition_for_lines():
    """ラインの dim 条件に focusMode ガードが含まれること。

    focusActive 変数（= S.focusMode && S.sel.size）を使った名前付き条件で検証する。
    """
    assert 'focusActive && !ends.every(id=>focusSet.has(id))' in assets._JS


# ---------------------------------------------------------------------------
# B1 隣接フォーカスモード — node 実行ロジックテスト（nHopNeighbors 純関数の実検証）
# ---------------------------------------------------------------------------

def _extract_nhop_neighbors_source(js: str) -> str:
    """_JS から nHopNeighbors 関数ブロックをバランス中括弧で切り出す。"""
    start_marker = "function nHopNeighbors"
    idx = js.find(start_marker)
    if idx == -1:
        raise ValueError("nHopNeighbors not found in _JS")
    # 関数の { } のバランスを数えて切り出す
    brace_depth = 0
    func_start = js.index("{", idx)
    i = func_start
    while i < len(js):
        if js[i] == "{":
            brace_depth += 1
        elif js[i] == "}":
            brace_depth -= 1
            if brace_depth == 0:
                return js[idx:i + 1]
        i += 1
    raise ValueError("nHopNeighbors: unbalanced braces")


def _run_nhop_test(node_bin: str, adj_js: str, seeds_js: str, hops: int) -> set:
    """node を使って nHopNeighbors を実行し、結果の Set を Python set として返す。"""
    func_src = _extract_nhop_neighbors_source(assets._JS)
    driver = (
        f"{func_src}\n"
        f"const adj = {adj_js};\n"
        f"const seeds = {seeds_js};\n"
        f"const result = nHopNeighbors(adj, seeds, {hops});\n"
        f"process.stdout.write(JSON.stringify([...result]));\n"
    )
    r = subprocess.run([node_bin, "--input-type=module"], input=driver,
                      capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        # ESM が使えない環境はフォールバック（通常の script）
        r = subprocess.run([node_bin], input=driver,
                           capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return set(json.loads(r.stdout))


@pytest.fixture(scope="module")
def node_bin():
    """node バイナリのパスを返す。存在しなければ skip。"""
    b = shutil.which("node")
    if not b:
        pytest.skip("node 不在のためロジックテストをスキップ")
    return b


def test_nhop_1hop_direct_neighbors(node_bin):
    """1-hop: seed の直接隣接のみ（seed 自身を含む）が返ること。

    グラフ: A-B-C-D（線形）、seed=A → {A, B} だけ。
    C や D は含まれない。
    """
    adj = '{"A":["B"],"B":["A","C"],"C":["B","D"],"D":["C"]}'
    result = _run_nhop_test(node_bin, adj, '["A"]', 1)
    assert result == {"A", "B"}


def test_nhop_2hop_two_steps(node_bin):
    """2-hop: seed から 2 段先まで含むこと。

    グラフ: A-B-C-D（線形）、seed=A → {A, B, C}。D は含まれない。
    """
    adj = '{"A":["B"],"B":["A","C"],"C":["B","D"],"D":["C"]}'
    result = _run_nhop_test(node_bin, adj, '["A"]', 2)
    assert result == {"A", "B", "C"}


def test_nhop_seed_always_included(node_bin):
    """seed 自身は必ず結果に含まれること（隣接がない場合でも）。

    adj が空リストの seed は隣接が存在しないため、結果は {"A"} のみ。
    単なる `"A" in result` ではなく厳密な集合一致で「余計なものが入らない」こと
    も合わせて検証する（部分一致テストはバグを見逃す）。
    """
    adj = '{"A":[]}'
    result = _run_nhop_test(node_bin, adj, '["A"]', 1)
    assert result == {"A"}  # "A" in result より厳密: 余計なノードが混入しないことも保証


def test_nhop_disconnected_node_excluded(node_bin):
    """非連結ノードは結果に含まれないこと。

    グラフ: A-B、別クラスタ C-D、seed=A → {A, B} のみ。
    """
    adj = '{"A":["B"],"B":["A"],"C":["D"],"D":["C"]}'
    result = _run_nhop_test(node_bin, adj, '["A"]', 1)
    assert result == {"A", "B"}
    assert "C" not in result
    assert "D" not in result


def test_nhop_multiple_seeds(node_bin):
    """複数 seed の和集合が得られること。

    グラフ: A-B-C-D（線形）、seeds=[A, D] with 1-hop → {A, B, C, D}。
    A の 1-hop = {A, B}、D の 1-hop = {C, D}、和集合 = {A, B, C, D}。
    """
    adj = '{"A":["B"],"B":["A","C"],"C":["B","D"],"D":["C"]}'
    result = _run_nhop_test(node_bin, adj, '["A","D"]', 1)
    assert result == {"A", "B", "C", "D"}


def test_nhop_hops_zero_returns_only_seeds(node_bin):
    """hops=0 の場合は seed のみが返ること。

    hops を無視して隣接を展開する壊れた BFS では B が混入するため、
    「B が含まれない」ことも明示的に検証し、そのような実装を確実に弾く。
    """
    adj = '{"A":["B"],"B":["A","C"],"C":["B"]}'
    result = _run_nhop_test(node_bin, adj, '["A"]', 0)
    assert result == {"A"}
    assert "B" not in result  # hops=0 で隣接が入らないこと（hops を無視する壊れた BFS を弾く）


def test_nhop_seed_not_in_adj_still_included(node_bin):
    """adj に存在しない id を seeds に含めた場合、その seed 自身は結果に入ること。

    UNKNOWN_NODE は adj に存在しないため隣接が取得できない。
    結果は {"UNKNOWN_NODE"} のみ（adj 上の他ノード A・B は混入しない）。
    厳密な集合一致で検証し、「seed が入ること」と「余計なノードが入らないこと」
    を同時に保証する。
    """
    adj = '{"A":["B"],"B":["A"]}'
    result = _run_nhop_test(node_bin, adj, '["UNKNOWN_NODE"]', 1)
    assert result == {"UNKNOWN_NODE"}  # seed 自身のみ: 他ノード(A/B)が混入しないことも検証
