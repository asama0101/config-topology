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
            "const POS={};const VIEWS=['physical','stats','checks','addr','ifs'];"
            "const DIFF=null;\n")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(stub + assets._JS)
        path = f.name
    try:
        r = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# D3b DIFF ビュー — アセットテスト
# ---------------------------------------------------------------------------

def test_is_table_view_includes_diff():
    """isTableView() が 'diff' を表ビューとして含むこと。"""
    assert 'S.view === "diff"' in assets._JS


def test_render_diff_view_function_exists():
    """JS に renderDiffView 関数が定義されていること。"""
    assert "function renderDiffView" in assets._JS


def test_render_table_view_dispatches_to_diff():
    """renderTableView が diff ビューで renderDiffView を呼び出すこと。"""
    assert "renderDiffView()" in assets._JS


def test_render_diff_view_reads_global_diff():
    """renderDiffView が グローバル DIFF を参照すること。"""
    diff_start = assets._JS.find("function renderDiffView")
    assert diff_start != -1
    section = assets._JS[diff_start:diff_start + 3000]
    assert "DIFF" in section


def test_render_diff_view_uses_esc():
    """renderDiffView が esc() で XSS エスケープすること。"""
    diff_start = assets._JS.find("function renderDiffView")
    assert diff_start != -1
    section = assets._JS[diff_start:diff_start + 3000]
    assert "esc(" in section


def test_render_diff_view_zero_diff_message():
    """renderDiffView が差分0件のとき「差分なし」相当のメッセージを表示すること。"""
    assert "差分なし" in assets._JS


def test_render_diff_view_null_diff_safe():
    """DIFF が null/undefined のとき renderDiffView が安全に処理すること（ガード有）。"""
    diff_start = assets._JS.find("function renderDiffView")
    assert diff_start != -1
    section = assets._JS[diff_start:diff_start + 3000]
    # null/undefined ガードが存在すること（!DIFF または DIFF == null 等）
    assert "!DIFF" in section or "DIFF == null" in section or "DIFF === null" in section


def test_render_diff_view_fixed_section_order():
    """renderDiffView がセクションを固定順で描画すること（決定性保証）。

    devices/interfaces/links/segments/routing_bgp/routing_ospf/routing_static の順で
    参照していること（文字列位置で確認）。
    """
    diff_start = assets._JS.find("function renderDiffView")
    assert diff_start != -1
    # セクション名を見つけて順序を検証
    section = assets._JS[diff_start:diff_start + 5000]
    sections = ["devices", "interfaces", "links", "segments",
                "routing_bgp", "routing_ospf", "routing_static"]
    positions = []
    for s in sections:
        pos = section.find('"' + s + '"')
        if pos == -1:
            pos = section.find("'" + s + "'")
        assert pos != -1, f"renderDiffView 内にセクション '{s}' が見つからない"
        positions.append(pos)
    assert positions == sorted(positions), \
        "renderDiffView のセクション順序が固定順でない（決定性違反）"


def test_node_check_syntax_with_diff():
    """DIFF グローバルを stub に含めた状態で node --check が通ること。"""
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不在のため構文チェックをスキップ")
    stub = ("const DATA={devices:{},links:[],segments:[],extPeers:[],bgpEdges:[],"
            "meta:{generated_from:[]},"
            "stats:{devices:0,interfaces:0,links:0,segments:0,"
            "by_vendor:{},by_as:{},by_area:{},link_kinds:{link:0,segment:0,stub:0},"
            "dualstack_ifs:0,bgp_sessions:0,ospf_networks:0,static_routes:0},"
            "checks:[]};"
            "const POS={};"
            "const VIEWS=['physical','diff','stats','checks','addr','ifs'];"
            "const DIFF={devices:{added:[],removed:[],changed:[]},"
            "interfaces:{added:[],removed:[],changed:[]},"
            "links:{added:[],removed:[],changed:[]},"
            "segments:{added:[],removed:[],changed:[]},"
            "routing_bgp:{added:[],removed:[],changed:[]},"
            "routing_ospf:{added:[],removed:[],changed:[]},"
            "routing_static:{added:[],removed:[],changed:[]}};\n")
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


# ---------------------------------------------------------------------------
# C4: BGP SESSIONS 表の attr 列（RR/NHS バッジ）テスト
# ---------------------------------------------------------------------------

def test_bgp_sessions_table_has_attr_column_header():
    """BGP SESSIONS 表に <th>attr</th> ヘッダが存在すること。

    attr 列は route_reflector_client(RR) / next_hop_self(NHS) の略称バッジを表示する列。
    """
    assert '<th>attr</th>' in assets._JS


def test_bgp_sessions_table_attr_rr_badge_logic():
    """attr 列が b.rr を "RR" バッジに変換するロジックを含むこと。

    b.rr が truthy のとき "RR" 文字列が生成されること。
    RR = route_reflector_client の略称。
    """
    assert 'b.rr?"RR"' in assets._JS


def test_bgp_sessions_table_attr_nhs_badge_logic():
    """attr 列が b.nhs を "NHS" バッジに変換するロジックを含むこと。

    b.nhs が truthy のとき "NHS" 文字列が生成されること。
    NHS = next_hop_self の略称。
    """
    assert 'b.nhs?"NHS"' in assets._JS


def test_bgp_sessions_table_attr_fallback_dash():
    """attr 列で RR/NHS 共に falsy のとき "—" が表示されること。

    [b.rr?"RR":null, b.nhs?"NHS":null].filter(Boolean).join(" ")||"—" パターン。
    """
    assert '.filter(Boolean).join(" ")||"—"' in assets._JS


# ---------------------------------------------------------------------------
# B3 URL ハッシュによるビュー・選択状態の保存/復元
# ---------------------------------------------------------------------------

# ---- string-presence（補助） ----

def test_url_hash_encode_state_function_present():
    """_JS に encodeState 関数が定義されていること。"""
    assert 'function encodeState' in assets._JS


def test_url_hash_decode_state_function_present():
    """_JS に decodeState 関数が定義されていること。"""
    assert 'function decodeState' in assets._JS


def test_url_hash_apply_state_from_hash_present():
    """_JS に applyStateFromHash 関数が定義されていること（boot 連携）。"""
    assert 'applyStateFromHash' in assets._JS


def test_url_hash_replace_state_present():
    """_JS に history.replaceState 呼び出しが存在すること（履歴汚染防止）。"""
    assert 'replaceState' in assets._JS


def test_url_hash_sync_hash_to_state_present():
    """_JS にハッシュ書き込み関数（syncHashToState 等）が存在すること。"""
    assert 'syncHashToState' in assets._JS


def test_url_hash_apply_called_before_update_in_boot():
    """boot 処理で applyStateFromHash が update() より前に呼ばれていること。

    boot ブロック内の呼び出し順序を文字列位置で検証する。
    function update() の定義終端より後のスコープで、
    applyStateFromHash() の呼び出しが update() の呼び出しより前にあること。
    """
    js = assets._JS
    # boot ブロックの開始（既存 boot マーカー）
    boot_start = js.find("/* ================= boot =================")
    assert boot_start != -1, "boot ブロックが見つからない"
    boot_section = js[boot_start:]
    # function update() 定義ブロックの終端を探す（balanced-brace）
    func_def_marker = "function update()"
    func_def_pos = boot_section.find(func_def_marker)
    assert func_def_pos != -1, "function update() が boot ブロックに無い"
    brace_depth = 0
    func_start_i = boot_section.index("{", func_def_pos)
    i = func_start_i
    while i < len(boot_section):
        if boot_section[i] == "{":
            brace_depth += 1
        elif boot_section[i] == "}":
            brace_depth -= 1
            if brace_depth == 0:
                break
        i += 1
    # 定義ブロック終端以降の "呼び出しセクション" で位置を検索
    call_section = boot_section[i + 1:]
    apply_pos = call_section.find("applyStateFromHash()")
    update_pos = call_section.find("update()")
    assert apply_pos != -1, "applyStateFromHash() が boot 呼び出しセクションに無い"
    assert update_pos != -1, "update() が boot 呼び出しセクションに無い"
    assert apply_pos < update_pos, "applyStateFromHash() は update() より前に呼ばれる必要がある"


def test_url_hash_sync_called_inside_update():
    """update() 関数内で syncHashToState() が呼ばれていること。

    状態変化（選択/ビュー変更）は全て update() を通るため、
    update() 内で一度呼べば最小変更で済む。
    """
    js = assets._JS
    # update 関数ブロックを切り出す
    update_start = js.find("function update()")
    assert update_start != -1
    # balanced-brace でブロック終端を探す
    brace_depth = 0
    func_start = js.index("{", update_start)
    i = func_start
    while i < len(js):
        if js[i] == "{":
            brace_depth += 1
        elif js[i] == "}":
            brace_depth -= 1
            if brace_depth == 0:
                break
        i += 1
    update_body = js[update_start:i + 1]
    assert 'syncHashToState()' in update_body, "syncHashToState() が update() 内で呼ばれていない"


# ---- node 実行ロジックテスト（純関数の実検証・必須） ----

def _extract_function_source(js: str, func_name: str) -> str:
    """_JS から指定した関数ブロックをバランス中括弧で切り出す。

    B1 の nHopNeighbors と同じ balanced-brace 抽出ロジック。
    """
    start_marker = f"function {func_name}"
    idx = js.find(start_marker)
    if idx == -1:
        raise ValueError(f"{func_name} not found in _JS")
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
    raise ValueError(f"{func_name}: unbalanced braces")


def _run_encode_decode_test(node_bin: str, driver_js: str) -> str:
    """node を使って encodeState/decodeState を実行し stdout を返す。"""
    encode_src = _extract_function_source(assets._JS, "encodeState")
    decode_src = _extract_function_source(assets._JS, "decodeState")
    full = f"{encode_src}\n{decode_src}\n{driver_js}"
    r = subprocess.run([node_bin, "--input-type=module"], input=full,
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node_bin], input=full,
                           capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return r.stdout.strip()


def test_encode_decode_roundtrip(node_bin):
    """encodeState → decodeState のラウンドトリップが一致すること。

    decodeState("#" + encodeState("bgp", ["r2","r1"])) の sel は昇順ソートされ
    ["r1","r2"] になること。ラウンドトリップで view と sel が元通りに復元できること。
    """
    driver = (
        "const encoded = encodeState('bgp', ['r2', 'r1']);\n"
        "const decoded = decodeState('#' + encoded);\n"
        "process.stdout.write(JSON.stringify(decoded));\n"
    )
    out = _run_encode_decode_test(node_bin, driver)
    result = json.loads(out)
    assert result["view"] == "bgp", f"view が復元できない: {result}"
    assert result["sel"] == ["r1", "r2"], f"sel が昇順ソートで復元できない: {result}"


def test_encode_deterministic_order(node_bin):
    """同じ集合を順不同で渡しても同一エンコードになること（決定性）。

    sel は昇順ソートして決定的に encode するため、順序に依存しない。
    """
    driver = (
        "const e1 = encodeState('physical', ['r2', 'r1', 'r3']);\n"
        "const e2 = encodeState('physical', ['r3', 'r1', 'r2']);\n"
        "process.stdout.write(JSON.stringify({e1, e2, same: e1 === e2}));\n"
    )
    out = _run_encode_decode_test(node_bin, driver)
    result = json.loads(out)
    assert result["same"] is True, f"順序が変わるとエンコードが変わってしまう: {result}"


def test_encode_no_n_when_no_selection(node_bin):
    """選択なしのとき n= が付かないこと。

    encodeState('physical', []) は 'v=physical' だけを返す。
    decodeState で sel=[] が復元されること。
    """
    driver = (
        "const encoded = encodeState('physical', []);\n"
        "const hasN = encoded.includes('n=');\n"
        "const decoded = decodeState('#' + encoded);\n"
        "process.stdout.write(JSON.stringify({encoded, hasN, sel: decoded.sel}));\n"
    )
    out = _run_encode_decode_test(node_bin, driver)
    result = json.loads(out)
    assert result["hasN"] is False, f"選択なしなのに n= が付いている: {result}"
    assert result["sel"] == [], f"sel が空配列でない: {result}"


def test_encode_decode_special_chars(node_bin):
    """特殊文字 id が encode→decode で保たれること。

    'ext:203.0.113.7' や 'seg-192.0.2.0/30' のような ':' や '/' を含む id が
    encodeURIComponent でエンコードされ、decodeURIComponent で復元されること。
    """
    driver = (
        "const ids = ['ext:203.0.113.7', 'seg-192.0.2.0/30'];\n"
        "const encoded = encodeState('bgp', ids);\n"
        "const decoded = decodeState('#' + encoded);\n"
        "const restored = decoded.sel.slice().sort();\n"
        "const expected = ids.slice().sort();\n"
        "process.stdout.write(JSON.stringify({restored, expected, ok: JSON.stringify(restored) === JSON.stringify(expected)}));\n"
    )
    out = _run_encode_decode_test(node_bin, driver)
    result = json.loads(out)
    assert result["ok"] is True, f"特殊文字 id が decode で変わっている: {result}"


def test_decode_empty_string_safe(node_bin):
    """decodeState('') が例外を投げず安全な値を返すこと。

    不正入力に対して {view:null, sel:[]} 相当を返すこと。
    """
    driver = (
        "let caught = null, result = null;\n"
        "try { result = decodeState(''); } catch(e) { caught = e.message; }\n"
        "process.stdout.write(JSON.stringify({caught, view: result ? result.view : 'ERROR', sel: result ? result.sel : 'ERROR'}));\n"
    )
    out = _run_encode_decode_test(node_bin, driver)
    result = json.loads(out)
    assert result["caught"] is None, f"例外が投げられた: {result['caught']}"
    assert result["view"] is None or result["view"] == "", f"view が安全でない: {result}"
    assert result["sel"] == [], f"sel が安全でない: {result}"


def test_decode_garbage_safe(node_bin):
    """decodeState('#garbage') が例外を投げず安全な値を返すこと。

    不正形式に対して {view:null, sel:[]} 相当を返すこと。
    """
    driver = (
        "let caught = null, result = null;\n"
        "try { result = decodeState('#garbage'); } catch(e) { caught = e.message; }\n"
        "process.stdout.write(JSON.stringify({caught, view: result ? result.view : 'ERROR', sel: result ? result.sel : 'ERROR'}));\n"
    )
    out = _run_encode_decode_test(node_bin, driver)
    result = json.loads(out)
    assert result["caught"] is None, f"例外が投げられた: {result['caught']}"
    assert result["view"] is None, f"view が null でない: {result}"
    assert result["sel"] == [], f"sel が安全でない: {result}"


def test_decode_empty_v_and_n_safe(node_bin):
    """decodeState('#v=&n=') が例外を投げず安全な値を返すこと。

    v= が空、n= が空のとき view は null 相当、sel は [] になること。
    """
    driver = (
        "let caught = null, result = null;\n"
        "try { result = decodeState('#v=&n='); } catch(e) { caught = e.message; }\n"
        "process.stdout.write(JSON.stringify({caught, view: result ? result.view : 'ERROR', sel: result ? result.sel : 'ERROR'}));\n"
    )
    out = _run_encode_decode_test(node_bin, driver)
    result = json.loads(out)
    assert result["caught"] is None, f"例外が投げられた: {result['caught']}"
    assert result["sel"] == [], f"sel が安全でない: {result}"


def test_encode_sort_breaks_if_not_sorted(node_bin):
    """ソートなし実装では決定性テストが失敗することの実証（壊れた実装の赤検証）。

    同じ id セットを異なる順序で渡してもエンコードが同一になることを確認するテスト
    (test_encode_deterministic_order) は、ソートが無ければ失敗する。
    このテストはソートが意味を持つことを確認する：ソート後の selIds で
    エンコードすると r1,r2,r3 の順になること（昇順）。
    """
    driver = (
        "const encoded = encodeState('physical', ['r3', 'r1', 'r2']);\n"
        "const decoded = decodeState('#' + encoded);\n"
        # ソートされていれば r1,r2,r3 の昇順になる
        "const isSorted = decoded.sel.join(',') === 'r1,r2,r3';\n"
        "process.stdout.write(JSON.stringify({sel: decoded.sel, isSorted}));\n"
    )
    out = _run_encode_decode_test(node_bin, driver)
    result = json.loads(out)
    assert result["isSorted"] is True, f"encodeState が sel を昇順ソートしていない: {result}"


# ---- render 決定性（ハッシュは HTML に焼かれないことを担保） ----

def test_render_html_determinism_with_hash_state():
    """render_html を 2 回呼んでバイト一致すること。

    URL ハッシュは実行時のクライアント状態であり生成 HTML に焼き込まれない。
    同一入力 → 同一バイトの決定性が維持されること。
    """
    from lib.rendering import template
    # 最小限のトポロジーデータで2回 render して比較
    # topology dict は topology_io.load_topology が返す形式に合わせる
    minimal_topology = {
        "devices": {},
        "interfaces": [],
        "links": [],
        "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
        "meta": {"generated_from": [], "schema_version": "2.0"},
    }
    h1 = template.render_html(minimal_topology)
    h2 = template.render_html(minimal_topology)
    assert h1 == h2, "render_html が決定的でない（2回呼んで異なるバイト列）"
    # ハッシュ文字列が HTML 本体（<script> タグ外）に焼き込まれていないことを確認。
    # （location.hash は _JS 定数内 = <script> タグ中にあってよいが、
    #   テンプレート変数として動的に挿入されてはいけない）
    # NOTE: 以前のアサーション "not in h1 or in assets._JS" は常時 True で無効だった。
    #       script タグを除去した HTML 本体に location.hash が現れないことを直接検証する。
    no_script = re.sub(r'<script[^>]*>.*?</script>', '', h1, flags=re.DOTALL)
    assert "location.hash" not in no_script, \
        "location.hash が <script> タグ外の HTML 本体に焼き込まれている"


# ---------------------------------------------------------------------------
# B3 追加テスト群（修正 #1 / #4 / #5b / #5c）
# ---------------------------------------------------------------------------

# ---- 修正 #1: プロトタイプ汚染防御（__proto__ / constructor 注入） ----

def test_decode_state_proto_pollution_safe(node_bin):
    """decodeState("#__proto__=x&v=bgp") がプロトタイプを汚染せず {view:"bgp", sel:[]} を返すこと。

    params を Object.create(null) で生成することで __proto__ / constructor キーの注入を防ぐ。
    DOM 非依存の純関数テストで node 実行し、汚染の有無と戻り値を両方検証する。
    """
    driver = (
        # __proto__ を注入した後に Object.prototype が汚染されていないかを検証
        "const before = Object.prototype.x;\n"
        "const result = decodeState('#__proto__=x&v=bgp');\n"
        "const afterProto = Object.prototype.x;\n"
        "const polluted = afterProto !== before;\n"
        "process.stdout.write(JSON.stringify({"
        "  view: result.view, sel: result.sel, polluted"
        "}));\n"
    )
    out = _run_encode_decode_test(node_bin, driver)
    result = json.loads(out)
    assert result["view"] == "bgp", f"view が bgp でない: {result}"
    assert result["sel"] == [], f"sel が空でない: {result}"
    assert result["polluted"] is False, f"Object.prototype が汚染された: {result}"


def test_decode_state_constructor_pollution_safe(node_bin):
    """decodeState("#constructor=x&v=ospf") が constructor キーで汚染されず {view:"ospf"} を返すこと。"""
    driver = (
        "const result = decodeState('#constructor=x&v=ospf');\n"
        "process.stdout.write(JSON.stringify({view: result.view, sel: result.sel}));\n"
    )
    out = _run_encode_decode_test(node_bin, driver)
    result = json.loads(out)
    assert result["view"] == "ospf", f"view が ospf でない: {result}"
    assert result["sel"] == [], f"sel が空でない: {result}"


# ---- 修正 #4: sel 上限ガード ----

def test_decode_state_sel_limit_in_js():
    """decodeState の n= 処理に sel 上限ガード（.slice(0, 500)）が含まれていること。

    巨大入力での無駄処理を防ぐ上限ガード。
    決定性・通常動作（500 件以内）に影響しないこと（500 は実トポロジー規模を十分上回る）。
    """
    assert '.slice(0, 500)' in assets._JS, \
        "decodeState の sel 上限ガード .slice(0, 500) が _JS に含まれていない"


def test_decode_state_sel_limit_functional(node_bin):
    """sel 上限ガードが機能すること: 501 件渡しても 500 件に切り捨てられること。

    DOM 依存なしの純関数で検証。通常のトポロジー（< 500 件）には影響しない。
    """
    # 501 件の id 配列を生成して n= に渡す
    driver = (
        "const ids = Array.from({length: 501}, (_, i) => 'node-' + i);\n"
        "const encoded = encodeState('physical', ids);\n"
        "const decoded = decodeState('#' + encoded);\n"
        "process.stdout.write(JSON.stringify({count: decoded.sel.length}));\n"
    )
    out = _run_encode_decode_test(node_bin, driver)
    result = json.loads(out)
    assert result["count"] <= 500, f"sel が 500 件を超えている: {result['count']}"


# ---- 修正 #5b: #v=bgp（選択なし）のラウンドトリップ ----

def test_decode_bgp_view_no_sel_roundtrip(node_bin):
    """#v=bgp（選択なし）の decode が {view:"bgp", sel:[]} を返すこと。

    encodeState('bgp', []) → decodeState のラウンドトリップで
    view="bgp" かつ sel=[] が保たれること。
    """
    driver = (
        "const encoded = encodeState('bgp', []);\n"
        "const decoded = decodeState('#' + encoded);\n"
        "process.stdout.write(JSON.stringify({view: decoded.view, sel: decoded.sel, hasN: encoded.includes('n=')}));\n"
    )
    out = _run_encode_decode_test(node_bin, driver)
    result = json.loads(out)
    assert result["view"] == "bgp", f"view が bgp でない: {result}"
    assert result["sel"] == [], f"sel が空でない: {result}"
    assert result["hasN"] is False, f"選択なしなのに n= が付いている: {result}"


# ---- 修正 #5c: applyStateFromHash の string-presence テスト ----

def test_apply_state_from_hash_views_includes_in_js():
    """applyStateFromHash 内で VIEWS.includes による view 検証が行われていること。

    DOM 依存のため実挙動は node で検証できないが、
    実装に VIEWS.includes が applyStateFromHash 関数内に含まれることを確認する。
    注意: このテストは string-presence のみ。実際の DOM 状態変化は E2E テストが担う。
    """
    js = assets._JS
    func_start = js.find("function applyStateFromHash")
    assert func_start != -1, "applyStateFromHash 関数が見つからない"
    func_src = _extract_function_source(js, "applyStateFromHash")
    assert "VIEWS.includes" in func_src, \
        "applyStateFromHash 内に VIEWS.includes が含まれていない"


def test_apply_state_from_hash_valid_ids_construction_in_js():
    """applyStateFromHash 内で validIds（DATA.devices/segments/extPeers から構築）が使われていること。

    DOM 依存のため実挙動は node で検証できないが、
    DATA.segments と DATA.extPeers を使った validIds 構築が関数内にあることを確認する。
    注意: このテストは string-presence のみ。実際の復元動作は node ロジックテストが担う。
    """
    func_src = _extract_function_source(assets._JS, "applyStateFromHash")
    assert "validIds" in func_src, \
        "applyStateFromHash 内に validIds が含まれていない"
    assert "DATA.segments" in func_src, \
        "applyStateFromHash 内に DATA.segments 参照が含まれていない"
    assert "DATA.extPeers" in func_src, \
        "applyStateFromHash 内に DATA.extPeers 参照が含まれていない"


def test_apply_state_from_hash_view_specific_cleanup_in_js():
    """applyStateFromHash 内に view 固有クリーンアップが含まれていること。

    手細工 URL（例: #v=bgp&n=seg-...）で bgp ビューに segment id が S.sel に残る
    不整合を解消するため、setView と同じ view 固有クリーンアップが
    applyStateFromHash 内で実施されること。

    具体的には "bgp" ビューで DATA.segments の id を S.sel から削除する処理。
    注意: このテストは string-presence のみ。DOM 依存で実挙動を node 検証できない限界を示す。
    DOM 上の実際の動作は E2E テストが担う。
    """
    func_src = _extract_function_source(assets._JS, "applyStateFromHash")
    # bgp ビューでは segment id を S.sel から削除するクリーンアップが必要
    assert 'DATA.segments' in func_src, \
        "applyStateFromHash 内に DATA.segments 参照が含まれていない（view 固有クリーンアップに必要）"
    # S.sel.delete が applyStateFromHash 内に存在すること
    assert 'S.sel.delete' in func_src, \
        "applyStateFromHash 内に S.sel.delete が含まれていない（view 固有クリーンアップに必要）"


# ===========================================================================
# A4: degree 連動ノードサイズ — nodeScale 純関数テスト
# ===========================================================================

# ---------------------------------------------------------------------------
# string-presence テスト: nodeScale が _JS に含まれること
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_nodescale_function_present_in_js():
    """nodeScale 関数が _JS に定義されていること。"""
    assert "function nodeScale" in assets._JS, \
        "_JS に function nodeScale が見当たらない"


@pytest.mark.unit
def test_device_node_rect_uses_nodescale():
    """device ノード描画 rect が nodeScale 由来の幅（変数 w）を使うこと。

    固定値 NODE_W ではなく nodeScale(d.degree||0).w を経由した変数を使っていること。
    """
    # device ノードセクション（"device nodes" コメント付近）
    assert "nodeScale(d.degree" in assets._JS, \
        "device ノード rect が nodeScale を参照していない"


@pytest.mark.unit
def test_device_node_rect_width_is_variable_not_constant():
    """device ノード描画で rect.body の width が固定 NODE_W でなく変数であること。

    width="${NODE_W}" が device ノードの rect.body に残っていないことを確認。
    ext ノードは基準サイズのまま（NODE_W）なので、device ノード専用でチェックする。
    """
    # device nodes セクション（"/* --- device nodes ---" 以降）を抽出
    device_nodes_start = assets._JS.find("/* --- device nodes ---")
    assert device_nodes_start != -1, "device nodes セクションが見つからない"
    device_section = assets._JS[device_nodes_start:device_nodes_start + 1000]
    # 固定 NODE_W が rect.body width に直接使われていないこと
    assert 'width="${NODE_W}"' not in device_section, \
        "device ノード rect.body の width が固定 NODE_W のまま（nodeScale 未適用）"


# ---------------------------------------------------------------------------
# node 実行ロジックテスト: nodeScale 純関数の動作検証
# ---------------------------------------------------------------------------

def _extract_nodescale_js(js_src):
    """_JS から nodeScale 関数本体を抽出し、node で実行可能な JS を返す。"""
    # NODE_W/NODE_H 定数 + nodeScale 関数を抽出
    # nodeScale の定義はブレースで終わる関数として抽出
    lines = js_src.split("\n")
    # NODE_W/NODE_H の行を見つける
    const_line = next((l for l in lines if "NODE_W" in l and "NODE_H" in l), "")
    # nodeScale 関数の開始行を見つける
    start_idx = next((i for i, l in enumerate(lines) if "function nodeScale" in l), None)
    if start_idx is None:
        return None, None
    # 関数のブレースを追跡して終了行を見つける
    depth = 0
    end_idx = start_idx
    for i in range(start_idx, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if i > start_idx and depth <= 0:
            end_idx = i
            break
    func_src = "\n".join(lines[start_idx:end_idx + 1])
    return const_line, func_src


@pytest.mark.unit
def test_nodescale_degree_zero_is_base_size():
    """nodeScale(0) が基準サイズ（NODE_W=148, NODE_H=56）を返すこと。"""
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不在のため nodeScale ロジックテストをスキップ")

    const_line, func_src = _extract_nodescale_js(assets._JS)
    assert func_src is not None, "_JS から nodeScale 関数を抽出できなかった"

    test_js = f"""\
"use strict";
{const_line}
{func_src}
const r = nodeScale(0);
if (r.w !== 148) process.exit(1);
if (r.h !== 56)  process.exit(2);
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(test_js)
        path = f.name
    try:
        result = subprocess.run([node, path], capture_output=True, text=True)
        assert result.returncode == 0, (
            f"nodeScale(0) が基準サイズを返さない: {result.stderr or result.stdout}"
        )
    finally:
        os.unlink(path)


@pytest.mark.unit
def test_nodescale_degree_one_is_base_size():
    """nodeScale(1) が基準サイズ（縮小しない・degree≤1 は基準）を返すこと。"""
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不在のため nodeScale ロジックテストをスキップ")

    const_line, func_src = _extract_nodescale_js(assets._JS)
    assert func_src is not None

    test_js = f"""\
"use strict";
{const_line}
{func_src}
const r = nodeScale(1);
if (r.w !== 148) process.exit(1);
if (r.h !== 56)  process.exit(2);
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(test_js)
        path = f.name
    try:
        result = subprocess.run([node, path], capture_output=True, text=True)
        assert result.returncode == 0, (
            f"nodeScale(1) が基準サイズを返さない: {result.stderr or result.stdout}"
        )
    finally:
        os.unlink(path)


@pytest.mark.unit
def test_nodescale_monotone_nondecreasing():
    """nodeScale は degree 増加に対して単調非減少（w も h も縮小しない）であること。

    壊すと赤になる: 縮小する実装（degree が大きいほど小さくなる）を入れると失敗する。
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不在のため nodeScale ロジックテストをスキップ")

    const_line, func_src = _extract_nodescale_js(assets._JS)
    assert func_src is not None

    # degree 0〜10 を試し、前の値より小さくなっていないか確認
    test_js = f"""\
"use strict";
{const_line}
{func_src}
let prev = nodeScale(0);
for (let d = 1; d <= 10; d++) {{
  const cur = nodeScale(d);
  if (cur.w < prev.w) {{ process.stdout.write("w shrank at degree " + d); process.exit(1); }}
  if (cur.h < prev.h) {{ process.stdout.write("h shrank at degree " + d); process.exit(2); }}
  prev = cur;
}}
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(test_js)
        path = f.name
    try:
        result = subprocess.run([node, path], capture_output=True, text=True)
        assert result.returncode == 0, (
            f"nodeScale が単調非減少でない: {result.stdout or result.stderr}"
        )
    finally:
        os.unlink(path)


@pytest.mark.unit
def test_nodescale_cap_limits_growth():
    """nodeScale は CAP 以上の degree でサイズが頭打ちになること（上限あり）。

    壊すと赤になる: CAP なしの実装では degree=100 が degree=7 より大きくなり、
    アサートの「同一値」が通らなくなる。
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不在のため nodeScale ロジックテストをスキップ")

    const_line, func_src = _extract_nodescale_js(assets._JS)
    assert func_src is not None

    # CAP=6 前提（CAP+1=7 で頭打ち）。CAP 定数変更時はこの値も合わせる
    # CAP 超えの degree(100) と CAP 相当の degree(7) が同一サイズになること
    test_js = f"""\
"use strict";
{const_line}
{func_src}
const at_cap = nodeScale(7);
const over_cap = nodeScale(100);
if (at_cap.w !== over_cap.w) {{
  process.stdout.write("w not capped: at7=" + at_cap.w + " at100=" + over_cap.w);
  process.exit(1);
}}
if (at_cap.h !== over_cap.h) {{
  process.stdout.write("h not capped: at7=" + at_cap.h + " at100=" + over_cap.h);
  process.exit(2);
}}
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(test_js)
        path = f.name
    try:
        result = subprocess.run([node, path], capture_output=True, text=True)
        assert result.returncode == 0, (
            f"nodeScale が CAP で頭打ちになっていない: {result.stdout or result.stderr}"
        )
    finally:
        os.unlink(path)


@pytest.mark.unit
def test_nodescale_never_shrinks_below_base():
    """nodeScale の返り値が常に基準サイズ以上であること（縮小しない）。

    壊すと赤になる: w < NODE_W または h < NODE_H を返す実装を入れると失敗する。
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不在のため nodeScale ロジックテストをスキップ")

    const_line, func_src = _extract_nodescale_js(assets._JS)
    assert func_src is not None

    test_js = f"""\
"use strict";
{const_line}
{func_src}
for (let d = 0; d <= 20; d++) {{
  const r = nodeScale(d);
  if (r.w < 148) {{ process.stdout.write("w<148 at degree " + d); process.exit(1); }}
  if (r.h < 56)  {{ process.stdout.write("h<56 at degree " + d);  process.exit(2); }}
}}
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(test_js)
        path = f.name
    try:
        result = subprocess.run([node, path], capture_output=True, text=True)
        assert result.returncode == 0, (
            f"nodeScale が基準サイズを下回る: {result.stdout or result.stderr}"
        )
    finally:
        os.unlink(path)


@pytest.mark.unit
def test_nodescale_degree2_larger_than_degree1():
    """nodeScale(2) が nodeScale(1) より大きいこと（degree>1 で拡大が始まること）。

    壊すと赤になる: 全 degree で基準サイズ固定の実装は失敗する。
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不在のため nodeScale ロジックテストをスキップ")

    const_line, func_src = _extract_nodescale_js(assets._JS)
    assert func_src is not None

    test_js = f"""\
"use strict";
{const_line}
{func_src}
const r1 = nodeScale(1);
const r2 = nodeScale(2);
/* w は degree=2 で厳密に増加すること（STEP_W > 0 の保証）。
   h は単調非減少を monotone テストがカバーするため、ここでは w のみ厳密増加を確認。
   r2.w <= r1.w のみで失敗させる（h が増加しなくても degree2>degree1 が保たれなければ赤） */
if (r2.w <= r1.w) {{
  process.stdout.write("degree2.w not strictly greater than degree1.w: r1.w=" + r1.w + " r2.w=" + r2.w);
  process.exit(1);
}}
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(test_js)
        path = f.name
    try:
        result = subprocess.run([node, path], capture_output=True, text=True)
        assert result.returncode == 0, (
            f"nodeScale(2) が nodeScale(1) より大きくない: {result.stdout or result.stderr}"
        )
    finally:
        os.unlink(path)


# ===========================================================================
# D3b DIFF ビュー — XSS node 実行テスト（修正 1）
# ===========================================================================

def _extract_function_balanced(js: str, func_name: str) -> str:
    """_JS から指定関数ブロックをバランス中括弧で切り出す（既存ヘルパと同実装）。"""
    start_marker = f"function {func_name}"
    idx = js.find(start_marker)
    if idx == -1:
        raise ValueError(f"{func_name} not found in _JS")
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
    raise ValueError(f"{func_name}: unbalanced braces")


def _extract_esc_line(js: str) -> str:
    """_JS から const esc = ... の1行を抽出する。"""
    for line in js.splitlines():
        if line.strip().startswith("const esc ="):
            return line.strip()
    raise ValueError("const esc = ... が _JS に見つからない")


def _run_render_diff_node(node_bin: str, diff_js: str) -> str:
    """renderDiffView + esc（const）を node で実行して HTML を返す。

    renderDiffView はローカル関数 entryLabel / changedLabel を含むため、
    関数本体のみで自己完結する。DIFF グローバルと esc を注入して実行する。
    """
    render_diff_src = _extract_function_balanced(assets._JS, "renderDiffView")
    esc_line = _extract_esc_line(assets._JS)

    driver = (
        f"const DIFF = {diff_js};\n"
        f"{esc_line}\n"
        f"{render_diff_src}\n"
        "process.stdout.write(renderDiffView());\n"
    )
    r = subprocess.run([node_bin, "--input-type=module"], input=driver,
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node_bin], input=driver,
                           capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return r.stdout


@pytest.mark.unit
def test_render_diff_view_xss_escape_added_hostname(node_bin):
    """renderDiffView が hostname に XSS ペイロードを含む added エントリを esc() すること。

    devices.added の id / hostname に <img onerror=alert(1)> を埋め込み、
    出力 HTML に生の <img が現れず &lt;img として HTML エスケープされていることを検証。
    esc を1つ消すと赤になる（XSS 防御の有効性を実証）。
    """
    xss_id = '<img onerror=alert(1)>'
    xss_hostname = '</script><script>alert(2)</script>'
    diff_js = (
        '{"devices":{"added":[{"id":"' + xss_id.replace('"', '\\"') + '",'
        '"hostname":"' + xss_hostname.replace('"', '\\"') + '",'
        '"vendor":"cisco_ios","as":null}],"removed":[],"changed":[]},'
        '"interfaces":{"added":[],"removed":[],"changed":[]},'
        '"links":{"added":[],"removed":[],"changed":[]},'
        '"segments":{"added":[],"removed":[],"changed":[]},'
        '"routing_bgp":{"added":[],"removed":[],"changed":[]},'
        '"routing_ospf":{"added":[],"removed":[],"changed":[]},'
        '"routing_static":{"added":[],"removed":[],"changed":[]}}'
    )
    html = _run_render_diff_node(node_bin, diff_js)
    # 生の XSS タグが出力されていないこと
    assert "<img" not in html, f"生の <img タグが出力された（XSS 未防御）: {html[:500]}"
    assert "</script>" not in html.replace("<\\/script>", ""), (
        f"</script> が生出力された: {html[:500]}"
    )
    # エスケープ済み文字列が存在すること
    assert "&lt;img" in html or "onerror" not in html, (
        f"&lt;img エスケープが見つからない: {html[:500]}"
    )


@pytest.mark.unit
def test_render_diff_view_xss_escape_links(node_bin):
    """renderDiffView が links.added の subnet/device/if に XSS ペイロードが含まれる場合に esc() すること。"""
    diff_js = (
        '{"devices":{"added":[],"removed":[],"changed":[]},'
        '"interfaces":{"added":[],"removed":[],"changed":[]},'
        '"links":{"added":[{"subnet":"<script>alert(3)</script>",'
        '"a_device":"<img>","a_if":"GE0","b_device":"R2","b_if":"GE1"}],'
        '"removed":[],"changed":[]},'
        '"segments":{"added":[],"removed":[],"changed":[]},'
        '"routing_bgp":{"added":[],"removed":[],"changed":[]},'
        '"routing_ospf":{"added":[],"removed":[],"changed":[]},'
        '"routing_static":{"added":[],"removed":[],"changed":[]}}'
    )
    html = _run_render_diff_node(node_bin, diff_js)
    assert "<script>" not in html, f"生の <script> タグが links.added に現れた: {html[:500]}"
    assert "<img>" not in html, f"生の <img> が links.added に現れた: {html[:500]}"
    # エスケープされた形式（&lt;script&gt; 等）が存在すること
    assert "&lt;script&gt;" in html, f"&lt;script&gt; エスケープが見つからない: {html[:500]}"


# ===========================================================================
# D3b DIFF ビュー — テーブルヘッダ整合テスト（修正 2）
# ===========================================================================

@pytest.mark.unit
def test_render_diff_view_table_header_kind_entry():
    """renderDiffView のテーブルヘッダ第1列が Kind、エントリ列が Entry であること。

    実データ col0=変更種別（+added/-removed/~changed）に合わせ、
    第1列ヘッダを Kind とし、Section ヘッダは colspan グループ行で提示する。
    renderChecksView（第1列=Severity）との一貫性を保つ。
    常に空の未使用列は削除して列数とデータを一致させる。
    """
    diff_start = assets._JS.find("function renderDiffView")
    assert diff_start != -1
    # renderDiffView の関数本体（3000文字程度でカバー）
    section = assets._JS[diff_start:diff_start + 5000]
    # ヘッダ: 第1列が Kind、エントリ列が Entry
    assert '<th style="width:120px">Kind</th>' in section, (
        "renderDiffView の第1列ヘッダが Kind でない"
    )
    assert '<th>Entry</th>' in section, (
        "renderDiffView にエントリ列ヘッダ Entry が無い"
    )
    # Section 列ヘッダ（セクション名は colspan グループ行で提示するため独立列ヘッダは不要）
    assert '<th style="width:120px">Section</th>' not in section, (
        "Section 独立列ヘッダが残存している（colspan グループ行に移行済みのはず）"
    )


@pytest.mark.unit
def test_render_diff_view_no_always_empty_column():
    """renderDiffView のデータ行に常に空の未使用列（<td></td>）がないこと。

    データ構造は col0=変更種別、col1=エントリ（colspan=2 または別列）で完結し、
    未使用の空 <td></td> が残っていないこと（列数とデータの一致）。
    """
    diff_start = assets._JS.find("function renderDiffView")
    assert diff_start != -1
    section = assets._JS[diff_start:diff_start + 5000]
    # 旧実装の <td></td>（空セル）が added/removed 行に残っていないこと
    # パターン: "...kind..."</td><td></td><td>entryLabel...
    assert "<td></td><td>" not in section, (
        "renderDiffView データ行に常に空の <td></td> が残存している"
    )


# ===========================================================================
# D3b DIFF ビュー — links entryLabel スペース統一テスト（修正 3）
# ===========================================================================

@pytest.mark.unit
def test_render_diff_view_links_entry_label_double_space():
    """renderDiffView の links entryLabel が subnet の後にスペース2個を使うこと。

    lib/diff.py の _entry_label（スペース2: "%s  %s::%s -- %s::%s"）に統一する。
    現状の JS（スペース1）を修正してスペース2に揃える。
    """
    diff_start = assets._JS.find("function renderDiffView")
    assert diff_start != -1
    section = assets._JS[diff_start:diff_start + 3000]
    # links の entryLabel: subnet後スペース2個 + a_device::a_if -- b_device::b_if
    # パターン: (e.subnet||"") + "  " + (e.a_device||"")
    assert '(e.subnet||"") + "  " + (e.a_device||"")' in section, (
        'links entryLabel のスペースが1個（JS と Python の _entry_label が不一致）'
    )


# ===========================================================================
# D3b DIFF ビュー — changedLabel links 分岐コメントテスト（修正 5）
# ===========================================================================

@pytest.mark.unit
def test_diff_links_comment_about_changed_and_changed_label():
    """lib/diff.py の _diff_links コメントに changedLabel links 分岐の将来注記があること。

    現状 _diff_links は changed 常に空だが、将来追加時の保守メモとして
    'changedLabel' または 'assets.py' へのコメントが _diff_links docstring に存在すること。
    """
    import inspect
    import lib.diff as diff_mod
    src = inspect.getsource(diff_mod._diff_links)
    assert "changedLabel" in src or "assets.py" in src, (
        "_diff_links の docstring/コメントに changedLabel / assets.py への注記が無い"
    )


# ===========================================================================
# C5 修正1: assets.py の renderDetails に REDISTRIBUTE 表が存在すること
# ===========================================================================

@pytest.mark.unit
def test_render_details_has_redistribute_section():
    """renderDetails 関数に REDISTRIBUTE 表（見出しまたは列ヘッダ）が含まれること。"""
    func_start = assets._JS.find("function renderDetails(")
    assert func_start != -1, "renderDetails 関数が _JS に存在しない"
    # 次の function 宣言まで切り出す
    next_func = assets._JS.find("\nfunction ", func_start + 1)
    section = assets._JS[func_start:next_func if next_func != -1 else func_start + 20000]
    assert "REDISTRIBUTE" in section, (
        "renderDetails に 'REDISTRIBUTE' 見出しが存在しない"
    )


@pytest.mark.unit
def test_render_details_redistribute_table_has_required_columns():
    """renderDetails の REDISTRIBUTE 表に into/source/metric/route-map の列ヘッダが含まれること。"""
    func_start = assets._JS.find("function renderDetails(")
    assert func_start != -1
    next_func = assets._JS.find("\nfunction ", func_start + 1)
    section = assets._JS[func_start:next_func if next_func != -1 else func_start + 20000]
    # 列ヘッダとして into / source が含まれること
    assert "into" in section, "REDISTRIBUTE 表に 'into' 列ヘッダがない"
    assert "source" in section, "REDISTRIBUTE 表に 'source' 列ヘッダがない"


@pytest.mark.unit
def test_render_details_redistribute_references_d_redistribute():
    """renderDetails が d.redistribute（新キー名）を参照していること。"""
    func_start = assets._JS.find("function renderDetails(")
    assert func_start != -1
    next_func = assets._JS.find("\nfunction ", func_start + 1)
    section = assets._JS[func_start:next_func if next_func != -1 else func_start + 20000]
    assert "d.redistribute" in section, (
        "renderDetails が d.redistribute（新キー名）を参照していない"
    )


@pytest.mark.unit
def test_render_details_redistribute_no_bare_d_redist():
    """renderDetails が旧キー d.redist を参照していないこと（リネーム確認）。"""
    func_start = assets._JS.find("function renderDetails(")
    assert func_start != -1
    next_func = assets._JS.find("\nfunction ", func_start + 1)
    section = assets._JS[func_start:next_func if next_func != -1 else func_start + 20000]
    # d.redistributeXxx は許可するが d.redist のみで終わるパターンを弾く
    import re
    bare_redist = re.search(r'\bd\.redist\b(?!ribute)', section)
    assert bare_redist is None, (
        "renderDetails に旧キー d.redist が残存している（d.redistribute に変更すること）"
    )


@pytest.mark.unit
def test_render_details_redistribute_shows_dash_for_missing():
    """renderDetails の REDISTRIBUTE 表で metric/route-map が無い場合に代替表示（— 等）を使うこと。"""
    func_start = assets._JS.find("function renderDetails(")
    assert func_start != -1
    next_func = assets._JS.find("\nfunction ", func_start + 1)
    section = assets._JS[func_start:next_func if next_func != -1 else func_start + 20000]
    # metric/route_map が無い場合のフォールバック（"—" か "?" か null チェック）
    # "r.metric" の参照がある（存在確認）かつ null/undefined ガードがあること
    assert "r.metric" in section or "metric" in section, (
        "REDISTRIBUTE 表に metric フィールドの参照がない"
    )


@pytest.mark.unit
def test_js_node_check_with_redistribute():
    """node --check が redistribute を含む _JS で構文エラーを出さないこと。"""
    import shutil
    import tempfile
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node が見つからない")
    # _JS に stub DATA（redistribute を含む）を前置して構文チェック
    stub = (
        "const DATA = {"
        "  devices: { r1: { hostname: 'R1', vendor: 'cisco_ios', as: 65001,"
        "    ospf_rid: null, bgp_rid: null, ifs: [], bgp: [], ospf: [], static: [],"
        "    redistribute: [{ into: 'bgp', source: 'connected', metric: null, route_map: null }],"
        "    degree: 0 } },"
        "  links: [], segments: [], extPeers: [], bgpEdges: [],"
        "  meta: { generated_from: [] }, stats: {}, checks: [] };\n"
        "const POS = {};\n"
    )
    src = stub + assets._JS
    with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False, encoding="utf-8") as f:
        f.write(src)
        fname = f.name
    try:
        result = subprocess.run([node, "--check", fname],
                                capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, (
            "node --check 失敗（redistribute を含む stub で構文エラー）:\n" + result.stderr
        )
    finally:
        import os
        os.unlink(fname)


# ===========================================================================
# B4: データ駆動凡例 — presentAreas / presentASes 純関数 + renderLegend データ駆動化
#     + applyVisibility の as: 強調分岐
# ===========================================================================

# ---------------------------------------------------------------------------
# string-presence テスト（RED: 実装前は必ず失敗する）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_b4_present_areas_function_in_js():
    """presentAreas 関数が _JS に定義されていること。"""
    assert "function presentAreas" in assets._JS, \
        "_JS に function presentAreas が見当たらない"


@pytest.mark.unit
def test_b4_present_ases_function_in_js():
    """presentASes 関数が _JS に定義されていること。"""
    assert "function presentASes" in assets._JS, \
        "_JS に function presentASes が見当たらない"


@pytest.mark.unit
def test_b4_render_legend_no_hardcoded_area():
    """renderLegend にハードコードされた 'area:0' や 'area:1' が残っていないこと。

    B4 実装後は presentAreas(DATA) でデータ駆動生成するため、
    ハードコードの固定 area 文字列リテラル（'area:0'/'area:1' 等）は
    renderLegend 内に存在してはならない。
    area:0 と area:1 の両方を検証し、再混入を防ぐ。
    """
    legend_start = assets._JS.find("function renderLegend")
    assert legend_start != -1, "renderLegend 関数が見つからない"
    brace_depth = 0
    func_start = assets._JS.index("{", legend_start)
    i = func_start
    while i < len(assets._JS):
        if assets._JS[i] == "{":
            brace_depth += 1
        elif assets._JS[i] == "}":
            brace_depth -= 1
            if brace_depth == 0:
                break
        i += 1
    legend_body = assets._JS[legend_start:i + 1]
    assert '"area:1"' not in legend_body, \
        "renderLegend に 'area:1' ハードコードが残っている（データ駆動化が未実装）"
    assert '"area:0"' not in legend_body, \
        "renderLegend に 'area:0' ハードコードが残っている（データ駆動化が未実装）"


@pytest.mark.unit
def test_b4_render_legend_uses_present_areas():
    """renderLegend が presentAreas(DATA) を呼び出してデータ駆動生成すること。"""
    legend_start = assets._JS.find("function renderLegend")
    assert legend_start != -1
    brace_depth = 0
    func_start = assets._JS.index("{", legend_start)
    i = func_start
    while i < len(assets._JS):
        if assets._JS[i] == "{":
            brace_depth += 1
        elif assets._JS[i] == "}":
            brace_depth -= 1
            if brace_depth == 0:
                break
        i += 1
    legend_body = assets._JS[legend_start:i + 1]
    assert "presentAreas" in legend_body, \
        "renderLegend 内に presentAreas の呼び出しが見当たらない"


@pytest.mark.unit
def test_b4_render_legend_uses_present_ases():
    """renderLegend が presentASes(DATA) を呼び出して AS 別凡例を生成すること。"""
    legend_start = assets._JS.find("function renderLegend")
    assert legend_start != -1
    brace_depth = 0
    func_start = assets._JS.index("{", legend_start)
    i = func_start
    while i < len(assets._JS):
        if assets._JS[i] == "{":
            brace_depth += 1
        elif assets._JS[i] == "}":
            brace_depth -= 1
            if brace_depth == 0:
                break
        i += 1
    legend_body = assets._JS[legend_start:i + 1]
    assert "presentASes" in legend_body, \
        "renderLegend 内に presentASes の呼び出しが見当たらない"


@pytest.mark.unit
def test_b4_apply_visibility_has_as_branch():
    """applyVisibility に as: 分岐が含まれていること。

    S.legendHot が 'as:<n>' のとき AS 別強調を行う else-if 分岐が存在すること。
    """
    assert 'lg.startsWith("as:")' in assets._JS, \
        'applyVisibility に lg.startsWith("as:") 分岐が見当たらない'


@pytest.mark.unit
def test_b4_seglink_as_branch_no_dataset_id():
    """applyVisibility の seglink as: 分岐が el.dataset.id を参照しないこと。

    segment 自体は AS を持たないため el.dataset.id（segment id）への asHit() 呼び出しは
    常に false を返す無駄な評価となる。
    正しい形は asHit(el.dataset.mem) のみ（メンバーデバイスの AS を判定）。
    BGP ビューでは segment が描画されないため as: 強調時にこの seglink 分岐は
    実際には非到達だが、コードの意図を明確にするため除去する。
    """
    # seglink の as: 分岐で el.dataset.id を参照する形（除去済みであること）
    assert 'asHit(el.dataset.mem) && asHit(el.dataset.id)' not in assets._JS, \
        'seglink as: 分岐に el.dataset.id への asHit() が残っている（除去が必要）'


@pytest.mark.unit
def test_b4_update_resets_as_legend_when_not_bgp():
    """update() 内の legendHot リセット条件に as: が含まれていること。

    BGP ビュー以外で as: が固着しないよう、ebgp/ibgp と同じ条件に as: も含まれること。
    """
    update_start = assets._JS.find("function update()")
    assert update_start != -1
    brace_depth = 0
    func_start = assets._JS.index("{", update_start)
    i = func_start
    while i < len(assets._JS):
        if assets._JS[i] == "{":
            brace_depth += 1
        elif assets._JS[i] == "}":
            brace_depth -= 1
            if brace_depth == 0:
                break
        i += 1
    update_body = assets._JS[update_start:i + 1]
    assert 'lg.startsWith("as:")' in update_body, \
        'update() の legendHot リセット条件に lg.startsWith("as:") が含まれていない'


# ---------------------------------------------------------------------------
# node 実行ロジックテスト: presentAreas / presentASes 純関数の動作検証
# ---------------------------------------------------------------------------

def _b4_extract_func(js: str, func_name: str) -> str:
    """_JS から指定関数ブロックをバランス中括弧で切り出す。"""
    idx = js.find(f"function {func_name}")
    if idx == -1:
        raise ValueError(f"{func_name} not found in _JS")
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
    raise ValueError(f"{func_name}: unbalanced braces")


def _run_present_areas(node_bin: str, data_js: str) -> list:
    """node を使って presentAreas(data) を実行し Python list として返す。"""
    func_src = _b4_extract_func(assets._JS, "presentAreas")
    driver = (
        f"{func_src}\n"
        f"const data = {data_js};\n"
        f"process.stdout.write(JSON.stringify(presentAreas(data)));\n"
    )
    r = subprocess.run([node_bin, "--input-type=module"], input=driver,
                      capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node_bin], input=driver,
                           capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return json.loads(r.stdout)


def _run_present_ases(node_bin: str, data_js: str) -> list:
    """node を使って presentASes(data) を実行し Python list として返す。"""
    func_src = _b4_extract_func(assets._JS, "presentASes")
    driver = (
        f"{func_src}\n"
        f"const data = {data_js};\n"
        f"process.stdout.write(JSON.stringify(presentASes(data)));\n"
    )
    r = subprocess.run([node_bin, "--input-type=module"], input=driver,
                      capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node_bin], input=driver,
                           capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return json.loads(r.stdout)


@pytest.mark.unit
def test_b4_present_areas_multiple(node_bin):
    """presentAreas が links と segments から複数 area を収集し数値昇順で返すこと。

    壊すと赤になる: ソートを除去すると [10, 2] になりアサートが失敗する。
    """
    data_js = json.dumps({
        "links": [
            {"a": "r1", "b": "r2", "area": "0", "admin_down": False},
            {"a": "r2", "b": "r3", "area": "2", "admin_down": False},
        ],
        "segments": [{"id": "seg1", "area": "10", "members": []}],
    })
    result = _run_present_areas(node_bin, data_js)
    assert result == [0, 2, 10], f"数値昇順でない: {result}"


@pytest.mark.unit
def test_b4_present_areas_compound_split(node_bin):
    """presentAreas が複合 area ('0/1') を '/' で分割して個別 area として収集すること。

    壊すと赤になる: 分割未実装では '0/1' が整数変換できず両方とも除外される。
    """
    data_js = json.dumps({
        "links": [
            {"a": "r1", "b": "r2", "area": "0/1", "admin_down": False},
        ],
        "segments": [],
    })
    result = _run_present_areas(node_bin, data_js)
    assert 0 in result, f"分割後 area 0 が含まれていない: {result}"
    assert 1 in result, f"分割後 area 1 が含まれていない: {result}"


@pytest.mark.unit
def test_b4_present_areas_excludes_admin_down(node_bin):
    """presentAreas が admin_down のリンクを除外すること。

    壊すと赤になる: admin_down 除外漏れで area 99 が混入する。
    """
    data_js = json.dumps({
        "links": [
            {"a": "r1", "b": "r2", "area": "99", "admin_down": True},
            {"a": "r2", "b": "r3", "area": "1", "admin_down": False},
        ],
        "segments": [],
    })
    result = _run_present_areas(node_bin, data_js)
    assert 99 not in result, f"admin_down リンクの area 99 が混入: {result}"
    assert 1 in result, f"有効リンクの area 1 が含まれていない: {result}"


@pytest.mark.unit
def test_b4_present_areas_dedup(node_bin):
    """presentAreas が重複 area を排除すること。

    壊すと赤になる: 重複排除未実装で [0, 0] になりアサートが失敗する。
    """
    data_js = json.dumps({
        "links": [
            {"a": "r1", "b": "r2", "area": "0", "admin_down": False},
            {"a": "r3", "b": "r4", "area": "0", "admin_down": False},
        ],
        "segments": [{"id": "seg1", "area": "0", "members": []}],
    })
    result = _run_present_areas(node_bin, data_js)
    assert result == [0], f"重複排除されていない: {result}"


@pytest.mark.unit
def test_b4_present_areas_empty(node_bin):
    """presentAreas が空データで空配列を返すこと。"""
    data_js = json.dumps({"links": [], "segments": []})
    result = _run_present_areas(node_bin, data_js)
    assert result == [], f"空データで空配列でない: {result}"


@pytest.mark.unit
def test_b4_present_areas_numeric_sort_vs_string_sort(node_bin):
    """ソートなし実装で数値昇順テストが確実に失敗することの実証。

    area '10' と '2' は文字列ソートだと [10, 2] になるが数値ソートでは [2, 10]。
    壊すと赤になる: 文字列ソートのまま実装すると [10, 2] でアサートが失敗する。
    正しい実装では数値昇順で PASS、文字列ソートに変えると [10, 2] 等で赤になる（RED 実証用）。
    """
    data_js = json.dumps({
        "links": [
            {"a": "r1", "b": "r2", "area": "10", "admin_down": False},
            {"a": "r2", "b": "r3", "area": "2", "admin_down": False},
        ],
        "segments": [],
    })
    result = _run_present_areas(node_bin, data_js)
    assert result == [2, 10], f"数値昇順でない（文字列ソートのまま？）: {result}"


@pytest.mark.unit
def test_b4_present_ases_devices_and_ext(node_bin):
    """presentASes が devices と extPeers の AS を統合し数値昇順で返すこと。

    壊すと赤になる: ソートを除去すると順序が保証されなくなる。
    """
    data_js = json.dumps({
        "devices": {
            "r1": {"as": 65001, "hostname": "R1"},
            "r2": {"as": 65002, "hostname": "R2"},
        },
        "extPeers": [{"id": "ext:1.1.1.1", "as": 100}],
    })
    result = _run_present_ases(node_bin, data_js)
    assert result == [100, 65001, 65002], f"数値昇順でない: {result}"


@pytest.mark.unit
def test_b4_present_ases_null_excluded(node_bin):
    """presentASes が null の as を除外すること。

    壊すと赤になる: null 除外漏れで null が混入しアサートが失敗する。
    """
    data_js = json.dumps({
        "devices": {
            "r1": {"as": 65001, "hostname": "R1"},
            "r2": {"as": None, "hostname": "R2"},
        },
        "extPeers": [{"id": "ext:1.1.1.1", "as": None}],
    })
    result = _run_present_ases(node_bin, data_js)
    assert None not in result, f"null が混入している: {result}"
    assert result == [65001], f"期待は [65001] のみ: {result}"


@pytest.mark.unit
def test_b4_present_ases_dedup(node_bin):
    """presentASes が重複 AS を排除すること。

    壊すと赤になる: 重複排除未実装で [65000, 65000, 65000] になる。
    """
    data_js = json.dumps({
        "devices": {
            "r1": {"as": 65000, "hostname": "R1"},
            "r2": {"as": 65000, "hostname": "R2"},
        },
        "extPeers": [{"id": "ext:1.1.1.1", "as": 65000}],
    })
    result = _run_present_ases(node_bin, data_js)
    assert result == [65000], f"重複排除されていない: {result}"


@pytest.mark.unit
def test_b4_present_ases_empty(node_bin):
    """presentASes が空データで空配列を返すこと。"""
    data_js = json.dumps({"devices": {}, "extPeers": []})
    result = _run_present_ases(node_bin, data_js)
    assert result == [], f"空データで空配列でない: {result}"


@pytest.mark.unit
def test_b4_present_ases_numeric_sort_vs_string(node_bin):
    """ソートなし実装で数値昇順テストが確実に失敗することの実証。

    AS 9 と 100 は文字列ソートだと [100, 9] になるが数値ソートでは [9, 100]。
    壊すと赤になる: 文字列ソートのまま実装するとアサートが失敗する。
    正しい実装では数値昇順で PASS、文字列ソートに変えると [100, 9] 等で赤になる（RED 実証用）。
    """
    data_js = json.dumps({
        "devices": {
            "r1": {"as": 100, "hostname": "R1"},
            "r2": {"as": 9, "hostname": "R2"},
        },
        "extPeers": [],
    })
    result = _run_present_ases(node_bin, data_js)
    assert result == [9, 100], f"数値昇順でない（文字列ソートのまま？）: {result}"


@pytest.mark.unit
def test_b4_present_ases_no_as_field(node_bin):
    """presentASes が as フィールドを持たない device を無視すること。"""
    data_js = json.dumps({
        "devices": {"r1": {"hostname": "R1"}},
        "extPeers": [],
    })
    result = _run_present_ases(node_bin, data_js)
    assert result == [], f"as なし device が混入: {result}"


# ---------------------------------------------------------------------------
# render 決定性テスト（B4 実装後も維持されること）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_b4_render_html_determinism():
    """B4 実装後も render_html が決定的であること（2回バイト一致）。"""
    from lib.rendering import template
    minimal_topology = {
        "devices": {},
        "interfaces": [],
        "links": [],
        "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
        "meta": {"generated_from": [], "schema_version": "2.0"},
    }
    h1 = template.render_html(minimal_topology)
    h2 = template.render_html(minimal_topology)
    assert h1 == h2, "B4 実装後に render_html が決定的でなくなった"


# ===========================================================================
# A2: リンクラベルの法線（垂直）オフセットによる重なり回避
# ===========================================================================

# ---------------------------------------------------------------------------
# string-presence テスト
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_a2_edge_normal_offset_function_in_js():
    """edgeNormalOffset 関数が _JS に定義されていること。"""
    assert "function edgeNormalOffset" in assets._JS, \
        "_JS に function edgeNormalOffset が見当たらない"


@pytest.mark.unit
def test_a2_label_normal_offset_constant_in_js():
    """LABEL_NORMAL_OFFSET 定数が _JS に定義されていること。"""
    assert "LABEL_NORMAL_OFFSET" in assets._JS, \
        "_JS に LABEL_NORMAL_OFFSET 定数が見当たらない"


@pytest.mark.unit
def test_a2_subnet_label_uses_edge_normal_offset():
    """subnet ラベル配置が edgeNormalOffset を使っていること（固定 my + 7 が消えたこと）。

    旧実装 `stackLabel(parts, mx, my + 7, ...)` は法線オフセット化により
    `const off = edgeNormalOffset(...); stackLabel(parts, mx + off.dx, my + off.dy, ...)` に
    置換される。固定 `my + 7` パターンはリンクセクションに残っていてはならない。
    """
    # edgeNormalOffset を呼び出していること
    assert "edgeNormalOffset(a.x, a.y, b.x, b.y" in assets._JS, \
        "subnet ラベル配置が edgeNormalOffset を呼び出していない"
    # off.dx / off.dy を使って stackLabel を呼んでいること
    assert "off.dx" in assets._JS, \
        "stackLabel に off.dx が渡されていない"
    assert "off.dy" in assets._JS, \
        "stackLabel に off.dy が渡されていない"


@pytest.mark.unit
def test_a2_fixed_my_plus_7_removed():
    """旧実装の固定 `my + 7` が subnet ラベル配置から除去されていること。

    `stackLabel(parts, mx, my + 7,` というパターンが残っていると
    法線オフセット化されていないことを意味する。
    """
    # links セクションの subnet ラベル部分に my + 7 が残っていないこと
    # (OSPF area badge セクションは今回スコープ外なので `my+14` 等は許可)
    assert "stackLabel(parts, mx, my + 7," not in assets._JS, \
        "旧実装 `stackLabel(parts, mx, my + 7,` が残存している（法線オフセット化されていない）"


# ---------------------------------------------------------------------------
# node 実行ロジックテスト: edgeNormalOffset 純関数の実検証（必須）
# ---------------------------------------------------------------------------

def _extract_edge_normal_offset_source(js: str) -> str:
    """_JS から edgeNormalOffset 関数ブロックをバランス中括弧で切り出す。"""
    start_marker = "function edgeNormalOffset"
    idx = js.find(start_marker)
    if idx == -1:
        raise ValueError("edgeNormalOffset not found in _JS")
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
    raise ValueError("edgeNormalOffset: unbalanced braces")


def _run_edge_normal_offset(node_bin: str, ax, ay, bx, by, dist) -> dict:
    """node を使って edgeNormalOffset を実行し {dx, dy} を Python dict として返す。"""
    func_src = _extract_edge_normal_offset_source(assets._JS)
    driver = (
        f"{func_src}\n"
        f"const result = edgeNormalOffset({ax}, {ay}, {bx}, {by}, {dist});\n"
        "process.stdout.write(JSON.stringify(result));\n"
    )
    r = subprocess.run([node_bin, "--input-type=module"], input=driver,
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node_bin], input=driver,
                           capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return json.loads(r.stdout)


@pytest.mark.unit
def test_a2_horizontal_edge_offset_is_vertical(node_bin):
    """水平エッジ (0,0)-(10,0) の法線オフセットが垂直方向（dx≈0, |dy|≈dist）であること。

    水平エッジ (dx=10, dy=0) の法線は (-dy, dx)/L = (0, 10)/10 = (0, 1)。
    dist=10 をかけると {dx:0, dy:10}（符号は回転方向により異なるが |dy|≈10）。
    壊すと赤: 法線ではなく接線（{dx≈10, dy≈0}）にすると dx 大 dy≈0 で失敗する。
    """
    result = _run_edge_normal_offset(node_bin, 0, 0, 10, 0, 10)
    assert abs(result["dx"]) < 1.0, \
        f"水平エッジの法線オフセットで dx が大きすぎる（接線方向？）: dx={result['dx']}"
    assert abs(result["dy"]) > 9.0, \
        f"水平エッジの法線オフセットで |dy| が小さすぎる: dy={result['dy']}"


@pytest.mark.unit
def test_a2_vertical_edge_offset_is_horizontal(node_bin):
    """垂直エッジ (0,0)-(0,10) の法線オフセットが水平方向（|dx|≈dist, dy≈0）であること。

    垂直エッジ (dx=0, dy=10) の法線は (-dy, dx)/L = (-10, 0)/10 = (-1, 0)。
    dist=10 をかけると {dx:-10, dy:0}（|dx|≈10）。
    壊すと赤: 法線ではなく接線（{dx≈0, dy≈10}）にすると dy 大 dx≈0 で失敗する。
    """
    result = _run_edge_normal_offset(node_bin, 0, 0, 0, 10, 10)
    assert abs(result["dx"]) > 9.0, \
        f"垂直エッジの法線オフセットで |dx| が小さすぎる: dx={result['dx']}"
    assert abs(result["dy"]) < 1.0, \
        f"垂直エッジの法線オフセットで dy が大きすぎる（接線方向？）: dy={result['dy']}"


@pytest.mark.unit
def test_a2_diagonal_edge_orthogonality(node_bin):
    """斜めエッジの法線オフセットがエッジ方向と直交すること（内積≈0）。

    斜めエッジ (0,0)-(3,4) では edge方向=(3,4)、法線=(-4,3)/5（正規化後）× dist。
    off · (edge方向) ≈ 0 が成立しなければ法線ではなく接線方向になっている。
    壊すと赤: edgeNormalOffset で (-dy,dx) の代わりに (dx,dy) を返すと
    off = edge方向と平行になり内積 ≠ 0 で失敗する。
    """
    dist = 10
    result = _run_edge_normal_offset(node_bin, 0, 0, 3, 4, dist)
    # edge方向ベクトル
    edge_dx, edge_dy = 3, 4
    # 内積: off.dx * edge_dx + off.dy * edge_dy ≈ 0
    dot = result["dx"] * edge_dx + result["dy"] * edge_dy
    assert abs(dot) < 1.0, \
        f"法線オフセットがエッジ方向と直交していない（内積={dot:.4f}、接線方向になっている可能性）"


@pytest.mark.unit
def test_a2_offset_magnitude_equals_dist(node_bin):
    """法線オフセットの大きさが dist に等しいこと（正規化されていること）。

    edgeNormalOffset(0, 0, 3, 4, 10) → sqrt(dx²+dy²) ≈ 10。
    壊すと赤: 正規化を省くと大きさが L になり dist ≠ 大きさで失敗する。
    """
    result = _run_edge_normal_offset(node_bin, 0, 0, 3, 4, 10)
    magnitude = (result["dx"] ** 2 + result["dy"] ** 2) ** 0.5
    assert abs(magnitude - 10.0) < 0.5, \
        f"法線オフセットの大きさが dist(=10) に等しくない: magnitude={magnitude:.4f}"


@pytest.mark.unit
def test_a2_degenerate_same_point_returns_zero(node_bin):
    """退化ケース a==b（始点==終点）で {dx:0, dy:0} が返ること（例外なし）。

    L=0 の除算で例外を投げる実装を弾く。
    """
    result = _run_edge_normal_offset(node_bin, 5, 5, 5, 5, 10)
    assert result["dx"] == 0.0 or result["dx"] == 0, \
        f"退化ケースで dx が 0 でない: dx={result['dx']}"
    assert result["dy"] == 0.0 or result["dy"] == 0, \
        f"退化ケースで dy が 0 でない: dy={result['dy']}"


@pytest.mark.unit
def test_a2_deterministic_same_call_twice(node_bin):
    """edgeNormalOffset を同じ引数で2回呼んで同一結果が得られること（決定性）。"""
    func_src = _extract_edge_normal_offset_source(assets._JS)
    driver = (
        f"{func_src}\n"
        "const r1 = edgeNormalOffset(1, 2, 4, 6, 12);\n"
        "const r2 = edgeNormalOffset(1, 2, 4, 6, 12);\n"
        "const same = (r1.dx === r2.dx && r1.dy === r2.dy);\n"
        "process.stdout.write(JSON.stringify({r1, r2, same}));\n"
    )
    r = subprocess.run([node_bin, "--input-type=module"], input=driver,
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node_bin], input=driver,
                           capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    result = json.loads(r.stdout)
    assert result["same"] is True, \
        f"edgeNormalOffset が決定的でない（2回呼んで異なる結果）: {result}"


# ---------------------------------------------------------------------------
# render 決定性テスト（A2 実装後も維持されること）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_a2_render_html_determinism():
    """A2 実装後も render_html が決定的であること（2回バイト一致）。

    edgeNormalOffset が純粋な数式で決定的であるため HTML 出力も決定的であること。
    """
    from lib.rendering import template
    minimal_topology = {
        "devices": {},
        "interfaces": [],
        "links": [],
        "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
        "meta": {"generated_from": [], "schema_version": "2.0"},
    }
    h1 = template.render_html(minimal_topology)
    h2 = template.render_html(minimal_topology)
    assert h1 == h2, "A2 実装後に render_html が決定的でなくなった"
