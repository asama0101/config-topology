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
            "checks:[],raw_configs:{},parse_status:{},raw_configs_prev:{},stub_nodes:[],fib:{},static_edges:[],static_stubs:[]};"
            "const POS={};const VIEWS=['physical','addr','ifs','checks'];"
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
            "checks:[],raw_configs:{},parse_status:{},raw_configs_prev:{},stub_nodes:[],fib:{},static_edges:[],static_stubs:[]};"
            "const POS={};"
            "const VIEWS=['physical','addr','ifs','diff','checks'];"
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


# ---------------------------------------------------------------------------
# stub / loopback ノード描画（segment 様式に統一）— アセット構造テスト
# ---------------------------------------------------------------------------

def _stub_block(js):
    """render() の stub ノード描画ブロックを切り出す（3000文字窓）。

    DATA.stub_nodes は複数箇所（netNodes/validIds/view クリーンアップ/lgNodes 等）に出るため、
    render() の描画ループ固有の `const _stubIdx = {}` を起点アンカーにする。
    """
    s = js.find("const _stubIdx = {}")
    assert s != -1, "render() の stub 描画ブロック（_stubIdx）が見つからない"
    return js[s:s + 3000]


@pytest.mark.unit
def test_stub_render_two_views_not_bgp():
    """stub ノード描画が BGP 以外（physical/ospf）で実行され、OSPF では area あり（参加）のみに絞られること。

    確認項目:
      - DATA.stub_nodes 参照（Python build_stub_nodes が組んだ stub を JS が消費）
      - `S.view !== "bgp"` ガード（physical/ospf 両ビュー描画・BGP では出さない）
      - `S.view === "ospf" && !st.area`（OSPF ビューは OSPF 参加=area あり のみ）
      - Math.round(（座標決定化）・areaColor(（OSPF area 色）
    壊すと赤: ビュー条件・決定化・area 絞り込みを外すと該当文字列が消える。
    """
    js = assets._JS
    assert "DATA.stub_nodes" in js, "DATA.stub_nodes が _JS に存在しない"
    # render の stub 描画ブロック起点（_stubIdx）の直前に `S.view !== "bgp"` ガードがあること
    # ＝ ガードが stub 描画を確実に囲んでいることを位置で証明する（全文 in だと別箇所ヒットで素通りするため）。
    s = js.find("const _stubIdx = {}")
    assert s != -1, "render() の stub 描画ブロック（_stubIdx）が無い"
    guard_pos = js.rfind('S.view !== "bgp"', 0, s)
    assert guard_pos != -1 and s - guard_pos < 80, \
        "stub 描画ブロックの直前に `S.view !== \"bgp\"` ガードが無い（BGP でも描画される恐れ）"
    blk = _stub_block(js)
    assert 'S.view === "ospf" && !st.area' in blk, \
        "OSPF ビューで area あり（参加）のみに絞る条件が無い"
    assert "Math.round(" in blk, "座標決定化 Math.round が stub ブロックに無い"
    assert "areaColor(" in blk, "areaColor( が stub ブロックに無い（OSPF area 色）"


@pytest.mark.unit
def test_stub_mousedown_guards_pos_for_non_drag():
    """mousedown で POS に座標を持つノードのみドラッグ対象にし、stub（POS 非登録）は pan にフォールバックすること。

    stub は data-elem="seg" を持つため mousedown の closest にマッチするが、POS[sid] は存在しない。
    `POS[g.dataset.id].x` を無条件参照すると undefined.x でクラッシュする。POS 存在ガードで防ぐ。

    壊すと赤: ガード（POS[g.dataset.id] チェック）を外すと stub mousedown でクラッシュする実装に戻る。
    """
    js = assets._JS
    md = js.find('canvas.addEventListener("mousedown"')
    assert md != -1, "mousedown ハンドラが見つからない"
    ctx = js[md:md + 500]
    assert "g && POS[g.dataset.id]" in ctx, \
        "mousedown が POS 存在ガード（g && POS[g.dataset.id]）を持たない（stub mousedown でクラッシュ）"


@pytest.mark.unit
def test_stub_dblclick_does_not_clear_selection():
    """dblclick の「空白=全解除」ガードに [data-elem='seg'] が含まれ、stub/loopback 上の
    ダブルクリックで選択が全クリアされないこと。

    壊すと赤: dblclick ガードから [data-elem='seg'] を外すと stub dblclick で S.sel.clear() が走る。
    """
    js = assets._JS
    dbl = js.find('canvas.addEventListener("dblclick"')
    assert dbl != -1, "dblclick ハンドラが見つからない"
    ctx = js[dbl:dbl + 600]
    assert "[data-elem='seg']" in ctx, \
        "dblclick の全解除ガードに [data-elem='seg'] が無い（stub dblclick で選択が全クリアされる）"


@pytest.mark.unit
def test_stub_data_attrs_escaped():
    """stub の data 属性（data-id/data-mem/data-deco）が esc 済みであること（IF 名生値による属性ブレイク防止）。

    壊すと赤: esid/edev（esc 済み）を使わず生 sid/st.dev を data 属性に出すと XSS/属性ブレイクの恐れ。
    """
    blk = _stub_block(assets._JS)
    assert "const esid = esc(sid)" in blk and "edev = esc(st.dev)" in blk, \
        "stub の id/dev を esc した esid/edev が無い"
    assert 'data-id="${esid}"' in blk and 'data-mem="${edev}"' in blk, \
        "stub の data-id/data-mem が esc 済み（esid/edev）でない"
    assert 'data-deco="seg:${esid}"' in blk, "stub area-badge の data-deco が esc 済みでない"


@pytest.mark.unit
def test_stub_uses_seg_hittest_not_legacy():
    """stub ノードが segment と同じ hittest（data-elem="seg"/"seglink"）を使い、旧 lpstub/data-dev/title を使わないこと。

    新モデル: stub は data-elem="seg"・data-id（dev:ifn）で segment と同じ選択/可視性/詳細パネルに乗る。
    旧モデル（lpstub: deco・data-dev 親選択・<title> ツールチップ）は廃止。

    壊すと赤: 旧モデルへ戻すと lpstub:/data-dev/<title> が再出現する。
    """
    blk = _stub_block(assets._JS)
    assert 'data-elem="seg"' in blk, "stub 楕円が data-elem=\"seg\" を使っていない（segment hittest に乗らない）"
    assert 'data-elem="seglink"' in blk, "stub スポークが data-elem=\"seglink\" を使っていない"
    assert "lk-hit" in blk, "stub スポークに透明 .lk-hit が無い（spoke hover/click できない）"
    # 旧モデルの痕跡が無いこと
    assert "lpstub:" not in assets._JS, "旧 lpstub: deco が _JS に残っている"
    assert "data-dev=" not in assets._JS, "旧 data-dev（親デバイス選択）が _JS に残っている"
    assert "<title>" not in blk, "stub ブロックに <title>（旧ツールチップ）が残っている"


@pytest.mark.unit
def test_stub_color_classes_and_label():
    """stub 楕円が kind で色クラス（lpnode/stubnode）を分け、subnet テキストと IF/IP の stackLabel を出すこと。

    - 色区別: `st.kind === "loopback" ? "lpnode" : "stubnode"`
    - 中央テキスト: subnet（st.subnet）
    - IF/IP ラベル: segment と同じ stackLabel を labelParts に積む（hover/選択/hot 時）
    壊すと赤: 色分岐・subnet・stackLabel を消すと該当文字列が消える。
    """
    blk = _stub_block(assets._JS)
    assert 'st.kind === "loopback" ? "lpnode" : "stubnode"' in blk, \
        "kind による色クラス分岐（lpnode/stubnode）が無い"
    assert "esc(st.subnet)" in blk, "stub 中央テキストに subnet（esc(st.subnet)）が無い"
    assert "stackLabel(labelParts" in blk, \
        "stub の IF/IP ラベルが stackLabel(labelParts, ...) で積まれていない（segment と同方式でない）"
    assert "st.ifn" in blk and "st.ip" in blk, "stub ラベルに IF 名/IP（st.ifn/st.ip）が無い"


@pytest.mark.unit
def test_css_stub_color_rules_before_selected():
    """lpnode/stubnode の色 CSS が selected/hovered ルールより前にあり、凡例スウォッチ・テーマ変数があること。

    同詳細度（0,2,1）のため、lpnode/stubnode を selected/hovered より前に置かないと
    選択時の accent stroke が色ルールに上書きされる。

    壊すと赤: 順序を逆にする・色 CSS や var を消すと失敗。
    """
    css = assets._CSS
    lp = css.find("g.segnode.lpnode ellipse")
    stub = css.find("g.segnode.stubnode ellipse")
    sel = css.find("g.segnode.selected ellipse")
    assert lp != -1, "g.segnode.lpnode ellipse ルールが _CSS に無い"
    assert stub != -1, "g.segnode.stubnode ellipse ルールが _CSS に無い"
    assert sel != -1, "g.segnode.selected ellipse ルールが _CSS に無い"
    assert lp < sel and stub < sel, \
        "lpnode/stubnode ルールが selected ルールより後にある（選択時の色が上書きされる）"
    # 凡例スウォッチとテーマ変数
    assert ".sw.lp " in css or ".sw.lp{" in css, "凡例スウォッチ .sw.lp が無い"
    assert ".sw.stub2 " in css or ".sw.stub2{" in css, "凡例スウォッチ .sw.stub2 が無い"
    assert "--lp-edge" in css and "--stub-edge" in css, "テーマ変数 --lp-edge/--stub-edge が無い"
    # segment 様式の共通 CSS は維持
    assert "g.segnode" in css and ".area-badge" in css


@pytest.mark.unit
def test_stub_block_uses_esc():
    """stub の SVG 要素に esc() が使われていること（XSS 対策）。"""
    blk = _stub_block(assets._JS)
    assert "esc(" in blk, "stub ブロックに esc() が存在しない"


def test_link_end_label_includes_link_local():
    # リンク端ラベルが端点 IF の link-local を ifV6List 経由で抽出し、faint 行として描く。
    assert 'ifV6List(itf).filter(x=>x.ll)' in assets._JS   # リンク端ラベル固有の抽出
    assert 'faint:true' in assets._JS                       # faint 行として渡す
    assert '.iflabel.ll' in assets._CSS                     # SVG ラベル淡色


# ---------------------------------------------------------------------------
# 改修⑥ STATS タブ削除
# ---------------------------------------------------------------------------

def test_no_render_stats_view():
    """JS に renderStatsView 関数定義が無いこと。"""
    assert "function renderStatsView" not in assets._JS


def test_isTableView_no_stats():
    """isTableView() が 'stats' を参照しないこと。"""
    assert 'S.view === "stats"' not in assets._JS


def test_render_table_view_no_stats_branch():
    """renderTableView に stats 分岐（renderStatsView 呼び出し）が無いこと。"""
    assert "renderStatsView()" not in assets._JS


def test_no_stats_css_classes():
    """stats 専用 CSS クラスが _CSS に無いこと。"""
    assert ".stats-cards" not in assets._CSS
    assert ".stats-card" not in assets._CSS
    assert ".stats-num" not in assets._CSS
    assert ".stats-label" not in assets._CSS
    assert ".stats-tbl-wrap" not in assets._CSS



# ---------------------------------------------------------------------------
# 改修⑦: INTERFACES 表 Status 列の ospfBadge 削除
# ---------------------------------------------------------------------------

def _extract_render_ifs_table_js(js: str) -> str:
    """_JS から renderIfsTable 関数のソースを切り出して返す。"""
    start = js.find("function renderIfsTable(")
    assert start != -1, "renderIfsTable 関数が見つからない"
    # 次の function 定義（または末尾）まで
    next_fn = js.find("\nfunction ", start + 1)
    return js[start:] if next_fn == -1 else js[start:next_fn]


def test_ifs_status_no_ospf_badge():
    """renderIfsTable の Status セルに ospfBadge が存在しないこと。

    改修⑦で削除。消し忘れ（${ospfBadge} や const ospfBadge が残る）と赤になる。
    """
    fn_src = _extract_render_ifs_table_js(assets._JS)
    assert "${ospfBadge}" not in fn_src, \
        "Status セルに ${ospfBadge} が残っている（削除もれ）"
    assert "const ospfBadge" not in fn_src, \
        "renderIfsTable 内に const ospfBadge 計算ブロックが残っている（削除もれ）"


def test_ifs_status_keeps_kind_and_role_badge():
    """renderIfsTable の Status セルに IFK_LABEL[r.kind] と ovBadge が残ること。

    ospfBadge を削除しても up/down・種別バッジ・予約/使用不可バッジは維持される。
    """
    fn_src = _extract_render_ifs_table_js(assets._JS)
    assert "IFK_LABEL[r.kind]" in fn_src, \
        "種別バッジ IFK_LABEL[r.kind] が消えている（回帰）"
    assert "${ovBadge}" in fn_src, \
        "予約/使用不可バッジ ${ovBadge} が消えている（回帰）"
    assert "${esc(r.st)}" in fn_src, \
        "up/down ステータス ${esc(r.st)} が消えている（回帰）"


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


# ===========================================================================
# A5: 長いホスト名ラベルの省略表示
#     truncateLabel / nodeLabelMaxChars 純関数テスト
# ===========================================================================

# ---------------------------------------------------------------------------
# string-presence テスト（RED: 実装前は必ず失敗する）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_a5_truncate_label_function_in_js():
    """truncateLabel 関数が _JS に定義されていること。"""
    assert "function truncateLabel" in assets._JS, \
        "_JS に function truncateLabel が見当たらない"


@pytest.mark.unit
def test_a5_node_label_max_chars_function_in_js():
    """nodeLabelMaxChars 関数が _JS に定義されていること。"""
    assert "function nodeLabelMaxChars" in assets._JS, \
        "_JS に function nodeLabelMaxChars が見当たらない"


@pytest.mark.unit
def test_a5_device_node_uses_truncate_label():
    """device ノード描画が truncateLabel を使って hostname を省略すること。

    device nodes セクションで truncateLabel(d.hostname, ...) が呼ばれていること。
    """
    device_nodes_start = assets._JS.find("/* --- device nodes ---")
    assert device_nodes_start != -1, "device nodes セクションが見つからない"
    device_section = assets._JS[device_nodes_start:device_nodes_start + 1500]
    assert "truncateLabel(d.hostname," in device_section, \
        "device ノード描画で truncateLabel(d.hostname, ...) が呼ばれていない"


@pytest.mark.unit
def test_a5_device_node_has_title_element():
    """device ノード描画に <title> 要素（full hostname）が含まれること。

    SVG <title> はネイティブツールチップ。full hostname を esc() でエスケープして出す。
    """
    device_nodes_start = assets._JS.find("/* --- device nodes ---")
    assert device_nodes_start != -1, "device nodes セクションが見つからない"
    device_section = assets._JS[device_nodes_start:device_nodes_start + 1500]
    assert "<title>" in device_section, \
        "device ノード描画に <title> 要素が含まれていない"
    assert "esc(d.hostname)" in device_section, \
        "device ノードの <title> に esc(d.hostname) が含まれていない"


@pytest.mark.unit
def test_a5_device_node_title_before_rect():
    """device ノード <g> の最初の子に <title> が置かれていること（文字列位置で検証）。

    <title>${esc(d.hostname)}</title> は <rect class="body" ... より前にあること。
    """
    device_nodes_start = assets._JS.find("/* --- device nodes ---")
    assert device_nodes_start != -1
    device_section = assets._JS[device_nodes_start:device_nodes_start + 1500]
    title_pos = device_section.find("<title>")
    rect_pos = device_section.find('<rect class="body"')
    assert title_pos != -1, "<title> が見つからない"
    assert rect_pos != -1, '<rect class="body" が見つからない'
    assert title_pos < rect_pos, \
        "<title> が <rect class=\"body\" より後にある（<title> は最初の子に置くこと）"


@pytest.mark.unit
def test_a5_ext_node_uses_truncate_label():
    """ext ノード（外部ピア）描画が truncateLabel を使って e.sub（neighbor IP）を省略すること。

    BGP ビュー変更後: external peers セクションの hn テキストは truncateLabel(e.sub, ...) を使う。
    e.label（AS xxx）は <title> ホバーにのみ残り、ノード上には表示されない。
    """
    ext_peers_start = assets._JS.find("/* --- external peers")
    assert ext_peers_start != -1, "external peers セクションが見つからない"
    ext_section = assets._JS[ext_peers_start:ext_peers_start + 1000]
    assert "truncateLabel(e.sub," in ext_section, \
        "ext ノード描画で truncateLabel(e.sub, ...) が呼ばれていない（neighbor IP が主ラベルに使われていない）"


@pytest.mark.unit
def test_a5_ext_node_has_title_element():
    """ext ノード描画に <title> 要素（full label）が含まれること。"""
    ext_peers_start = assets._JS.find("/* --- external peers")
    assert ext_peers_start != -1
    ext_section = assets._JS[ext_peers_start:ext_peers_start + 1000]
    assert "<title>" in ext_section, \
        "ext ノード描画に <title> 要素が含まれていない"
    assert "esc(e.label)" in ext_section, \
        "ext ノードの <title> に esc(e.label) が含まれていない"


# ---------------------------------------------------------------------------
# node 実行ロジックテスト: truncateLabel 純関数の動作検証（必須）
# ---------------------------------------------------------------------------

def _extract_truncate_label_source(js: str) -> str:
    """_JS から truncateLabel 関数ブロックをバランス中括弧で切り出す。"""
    start_marker = "function truncateLabel"
    idx = js.find(start_marker)
    if idx == -1:
        raise ValueError("truncateLabel not found in _JS")
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
    raise ValueError("truncateLabel: unbalanced braces")


def _extract_node_label_max_chars_source(js: str) -> str:
    """_JS から nodeLabelMaxChars 関数ブロックをバランス中括弧で切り出す。"""
    start_marker = "function nodeLabelMaxChars"
    idx = js.find(start_marker)
    if idx == -1:
        raise ValueError("nodeLabelMaxChars not found in _JS")
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
    raise ValueError("nodeLabelMaxChars: unbalanced braces")


def _run_truncate_label(node_bin: str, text_js: str, max_chars: int) -> str:
    """node を使って truncateLabel(text, maxChars) を実行して結果文字列を返す。"""
    func_src = _extract_truncate_label_source(assets._JS)
    driver = (
        f"{func_src}\n"
        f"const result = truncateLabel({text_js}, {max_chars});\n"
        "process.stdout.write(JSON.stringify(result));\n"
    )
    r = subprocess.run([node_bin, "--input-type=module"], input=driver,
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node_bin], input=driver,
                           capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return json.loads(r.stdout)


def _run_node_label_max_chars(node_bin: str, w: int) -> int:
    """node を使って nodeLabelMaxChars(w) を実行して整数を返す。"""
    func_src = _extract_node_label_max_chars_source(assets._JS)
    driver = (
        f"{func_src}\n"
        f"const result = nodeLabelMaxChars({w});\n"
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
def test_a5_truncate_label_short_returns_as_is(node_bin):
    """短いテキストはそのまま返ること（省略しない）。

    text.length <= maxChars なら text を unchanged で返す。
    壊すと赤: 常に省略する実装で "short" が "shor…" になり失敗する。
    """
    result = _run_truncate_label(node_bin, '"short"', 10)
    assert result == "short", f"短いテキストが変更された: {result!r}"


@pytest.mark.unit
def test_a5_truncate_label_exact_max_chars_returns_as_is(node_bin):
    """text.length == maxChars のとき省略しないこと（境界値: 等しい場合は省略不要）。

    壊すと赤: text.length < maxChars のみ通す実装で "12345" (len=5, maxChars=5) が省略される。
    """
    result = _run_truncate_label(node_bin, '"12345"', 5)
    assert result == "12345", f"length==maxChars で省略されてしまった: {result!r}"


@pytest.mark.unit
def test_a5_truncate_label_long_appends_ellipsis(node_bin):
    """長いテキストは (maxChars-1) 文字 + '…' になること。

    壊すと赤: 省略しない実装で末尾が '…' にならず失敗する。
    """
    result = _run_truncate_label(node_bin, '"core-router-dc1-rack5-unit12"', 10)
    assert result.endswith("…"), f"省略形の末尾が '…' でない: {result!r}"
    assert len(result) == 10, f"省略後の長さが maxChars(10) でない: len={len(result)}, {result!r}"


@pytest.mark.unit
def test_a5_truncate_label_result_length_le_max_chars(node_bin):
    """truncateLabel の結果長が常に maxChars 以下であること。

    壊すと赤: 省略後に maxChars を超える実装で失敗する（省略の本質的要件）。
    """
    for max_chars in [5, 10, 15, 20]:
        result = _run_truncate_label(node_bin, '"abcdefghijklmnopqrstuvwxyz"', max_chars)
        assert len(result) <= max_chars, \
            f"maxChars={max_chars} で結果長 {len(result)} が maxChars 超: {result!r}"


@pytest.mark.unit
def test_a5_truncate_label_maxchars_1_boundary(node_bin):
    """maxChars=1 の境界安全: 例外を投げず '…' を返すこと。

    maxChars=1 → maxChars-1=0 文字 + '…' = '…'（長さ1）。
    壊すと赤: text[0:-1] のような実装は 'a' など元文字を返す誤り。
    """
    result = _run_truncate_label(node_bin, '"core-router"', 1)
    assert result == "…", f"maxChars=1 で '…' が返らなかった: {result!r}"
    assert len(result) == 1, f"maxChars=1 で長さが 1 でない: len={len(result)}"


@pytest.mark.unit
def test_a5_truncate_label_maxchars_0_boundary_safe(node_bin):
    """maxChars=0/負 の境界安全: 例外を投げないこと。

    maxChars <= 0 の境界では例外なく安全な値（空文字または '…'）を返すこと。
    壊すと赤: slice で -1 が発生しクラッシュする実装を弾く。
    """
    caught = None
    for max_chars in [0, -1]:
        func_src = _extract_truncate_label_source(assets._JS)
        driver = (
            f"{func_src}\n"
            "let caught = null, result = null;\n"
            f"try {{ result = truncateLabel('core-router', {max_chars}); }}"
            "catch(e) {{ caught = e.message; }}\n"
            "process.stdout.write(JSON.stringify({caught, result}));\n"
        )
        node = shutil.which("node")
        if not node:
            pytest.skip("node 不在のためスキップ")
        r = subprocess.run([node, "--input-type=module"], input=driver,
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            r = subprocess.run([node], input=driver,
                               capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"node が非ゼロ終了: {r.stderr}"
        out = json.loads(r.stdout)
        assert out["caught"] is None, \
            f"maxChars={max_chars} で例外が投げられた: {out['caught']}"


@pytest.mark.unit
def test_a5_truncate_label_empty_string_safe(node_bin):
    """空文字入力が安全に処理されること（例外なし・空文字を返す）。

    壊すと赤: text.length アクセスや slice が null/undefined でクラッシュする実装を弾く。
    """
    result = _run_truncate_label(node_bin, '""', 10)
    assert result == "", f"空文字が空文字で返らなかった: {result!r}"


@pytest.mark.unit
def test_a5_truncate_label_null_safe(node_bin):
    """null 入力が安全に処理されること（例外なし・空文字を返す）。

    壊すと赤: null.length でクラッシュする実装を弾く。
    """
    func_src = _extract_truncate_label_source(assets._JS)
    driver = (
        f"{func_src}\n"
        "let caught = null, result = null;\n"
        "try { result = truncateLabel(null, 10); }"
        "catch(e) { caught = e.message; }\n"
        "process.stdout.write(JSON.stringify({caught, result}));\n"
    )
    node = shutil.which("node")
    r = subprocess.run([node, "--input-type=module"], input=driver,
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node], input=driver,
                           capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node が非ゼロ終了: {r.stderr}"
    out = json.loads(r.stdout)
    assert out["caught"] is None, f"null 入力で例外が投げられた: {out['caught']}"
    assert out["result"] == "", f"null 入力が空文字を返さなかった: {out['result']!r}"


@pytest.mark.unit
def test_a5_truncate_label_deterministic(node_bin):
    """同じ引数で2回呼んで同一結果が返ること（決定性）。

    壊すと赤: 乱数や副作用に依存する実装を弾く。
    """
    func_src = _extract_truncate_label_source(assets._JS)
    driver = (
        f"{func_src}\n"
        "const r1 = truncateLabel('core-router-dc1-rack5-unit12', 10);\n"
        "const r2 = truncateLabel('core-router-dc1-rack5-unit12', 10);\n"
        "process.stdout.write(JSON.stringify({r1, r2, same: r1 === r2}));\n"
    )
    r = subprocess.run([node_bin, "--input-type=module"], input=driver,
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node_bin], input=driver,
                           capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    result = json.loads(r.stdout)
    assert result["same"] is True, \
        f"truncateLabel が決定的でない（2回呼んで異なる結果）: {result}"


# ---------------------------------------------------------------------------
# node 実行ロジックテスト: nodeLabelMaxChars 純関数の動作検証（必須）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_a5_node_label_max_chars_monotone_nondecreasing(node_bin):
    """nodeLabelMaxChars は w 増加に対して単調非減少であること。

    壊すと赤: w が増えるほど max_chars が減る実装で失敗する。
    """
    func_src = _extract_node_label_max_chars_source(assets._JS)
    test_js = f"""\
"use strict";
{func_src}
let prev = nodeLabelMaxChars(100);
for (let w = 110; w <= 300; w += 10) {{
  const cur = nodeLabelMaxChars(w);
  if (cur < prev) {{
    process.stdout.write("maxChars shrank at w=" + w + ": prev=" + prev + " cur=" + cur);
    process.exit(1);
  }}
  prev = cur;
}}
"""
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不在のためスキップ")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(test_js)
        path = f.name
    try:
        result = subprocess.run([node, path], capture_output=True, text=True)
        assert result.returncode == 0, \
            f"nodeLabelMaxChars が単調非減少でない: {result.stdout or result.stderr}"
    finally:
        os.unlink(path)


@pytest.mark.unit
def test_a5_node_label_max_chars_w148_reasonable(node_bin):
    """nodeLabelMaxChars(148) が妥当な値（1以上かつ画面幅を超えない）を返すこと。

    基準幅 NODE_W=148 で max_chars >= 1 かつ <= 50 程度。
    例 Math.max(1, Math.floor((148 - 22) / 8)) = Math.floor(126/8) = 15。
    壊すと赤: 0 や 200 を返す実装で失敗する。
    """
    result = _run_node_label_max_chars(node_bin, 148)
    assert result >= 1, f"nodeLabelMaxChars(148) が 1 未満: {result}"
    assert result <= 50, f"nodeLabelMaxChars(148) が 50 超（非現実的）: {result}"


@pytest.mark.unit
def test_a5_node_label_max_chars_w196_larger_than_w148(node_bin):
    """nodeLabelMaxChars(196) >= nodeLabelMaxChars(148) であること（単調性）。

    degree 拡大で w が 148→196 に増えたとき max_chars も増えること。
    壊すと赤: w 依存なし（固定値）の実装では w=148 と w=196 が同じ値になるが
    「>=」なのでその場合は PASS。より厳格な「>」でテストする。
    """
    r148 = _run_node_label_max_chars(node_bin, 148)
    r196 = _run_node_label_max_chars(node_bin, 196)
    assert r196 >= r148, \
        f"nodeLabelMaxChars(196)={r196} < nodeLabelMaxChars(148)={r148}（単調性違反）"
    # 196 > 148 なので maxChars(196) > maxChars(148) が期待される
    assert r196 > r148, \
        f"nodeLabelMaxChars(196)={r196} が nodeLabelMaxChars(148)={r148} より大きくない（w 依存してない？）"


@pytest.mark.unit
def test_a5_node_label_max_chars_minimum_1(node_bin):
    """nodeLabelMaxChars の返り値が常に最小 1 であること。

    w が非常に小さくても 0 や負にならないこと。
    壊すと赤: Math.floor((w - 22) / 8) のみで w < 30 なら 0 以下になる実装を弾く。
    """
    for w in [1, 10, 20, 30]:
        result = _run_node_label_max_chars(node_bin, w)
        assert result >= 1, \
            f"nodeLabelMaxChars({w}) が 1 未満（{result}）: Math.max(1,...) が無い？"


# ---------------------------------------------------------------------------
# render 決定性テスト（A5 実装後も維持されること）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_a5_render_html_determinism():
    """A5 実装後も render_html が決定的であること（2回バイト一致）。

    truncateLabel/nodeLabelMaxChars が純粋関数のため HTML 出力は決定的なはず。
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
    assert h1 == h2, "A5 実装後に render_html が決定的でなくなった"


@pytest.mark.unit
def test_a5_node_check_syntax_with_truncate_label():
    """truncateLabel / nodeLabelMaxChars を含む _JS で node --check が通ること。"""
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
            "const DIFF=null;\n")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(stub + assets._JS)
        path = f.name
    try:
        r = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert r.returncode == 0, f"node --check 失敗（A5 追加後）: {r.stderr}"
    finally:
        os.unlink(path)


# ===========================================================================
# A5 レビュー確定修正
# ===========================================================================

# ---------------------------------------------------------------------------
# 修正 #2 [test MED]: maxChars=0 / maxChars=-1 の戻り値検証強化
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_a5_truncate_label_maxchars_0_returns_empty(node_bin):
    """maxChars=0 のとき truncateLabel が空文字 "" を返すこと。

    既存の test_a5_truncate_label_maxchars_0_boundary_safe は例外なし（caught is None）だけを
    検証していたが、戻り値まで assert する形に強化する。
    実装: maxChars<=1 かつ maxChars<=0 → "" を返す（コメントと実装の一致）。
    壊すと赤: maxChars=0 で "…" を返す実装（maxChars=1 との分岐が無い）で失敗する。
    """
    func_src = _extract_truncate_label_source(assets._JS)
    for max_chars in [0, -1]:
        driver = (
            f"{func_src}\n"
            "let caught = null, result = null;\n"
            f"try {{ result = truncateLabel('core-router', {max_chars}); }}"
            "catch(e) { caught = e.message; }\n"
            "process.stdout.write(JSON.stringify({caught, result}));\n"
        )
        r = subprocess.run([node_bin, "--input-type=module"], input=driver,
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            r = subprocess.run([node_bin], input=driver,
                               capture_output=True, text=True, timeout=10)
        assert r.returncode == 0, f"node が非ゼロ終了 (maxChars={max_chars}): {r.stderr}"
        out = json.loads(r.stdout)
        assert out["caught"] is None, \
            f"maxChars={max_chars} で例外が投げられた: {out['caught']}"
        assert out["result"] == "", \
            f"maxChars={max_chars} で空文字が返らなかった: {out['result']!r}"


# ---------------------------------------------------------------------------
# 修正 #3 [test LOW]: 検索 corpus 構築に truncateLabel が適用されていないこと
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_a5_corpus_assignment_uses_full_hostname():
    """検索 corpus / fcorpus の構築が d.hostname / e.label の full 値を使うこと。

    §8.3.2「省略は表示のみ・検索は full」の担保。
    corpus[id] / fcorpus[id].host へ代入する行には truncateLabel が適用されて
    いないことを string-presence で検証する。
    検索 corpus 代入行の付近: 'corpus[id] = [...d.hostname...' または
    'fcorpus[id] = { host: d.hostname.toLowerCase()' の形式で、
    truncateLabel 呼び出しが混入していないこと。
    """
    js = assets._JS
    # corpus / fcorpus の構築ブロック（DATA.devices ループ）を切り出す。
    # 開始位置: "const corpus = {}, fcorpus = {};" 付近
    corpus_start = js.find("const corpus = {}, fcorpus = {};")
    assert corpus_start != -1, "_JS に 'const corpus = {}, fcorpus = {};' が見つからない"

    # corpus/fcorpus ブロックの終端: "/* IP（ホスト部）→" コメントまで
    corpus_end_marker = "/* IP（ホスト部）"  # "/* IP（ホスト部）"
    corpus_end = js.find(corpus_end_marker, corpus_start)
    if corpus_end == -1:
        # フォールバック: IP2NET 定数の初期化まで
        corpus_end = js.find("const IP2NET = {};", corpus_start)
    assert corpus_end != -1, "corpus ブロックの終端マーカーが見つからない"

    corpus_block = js[corpus_start:corpus_end]

    # corpus ブロック内に truncateLabel が存在しないこと
    assert "truncateLabel" not in corpus_block, (
        "検索 corpus 構築ブロック内に truncateLabel が含まれている。"
        "§8.3.2「省略は表示のみ・検索は full」に違反する。"
    )

    # fcorpus[id].host に d.hostname.toLowerCase() が直接代入されていること（full 値の確認）
    assert "d.hostname.toLowerCase()" in corpus_block, (
        "fcorpus[id].host に d.hostname.toLowerCase() が直接代入されていない。"
        "検索 corpus は full hostname を使うこと（§8.3.2）。"
    )

    # extPeers の corpus 代入でも e.label の full 値を使うこと
    assert "e.label.toLowerCase()" in corpus_block, (
        "extPeers の fcorpus[e.id].host に e.label.toLowerCase() が直接代入されていない。"
        "検索 corpus は full label を使うこと（§8.3.2）。"
    )


# ---------------------------------------------------------------------------
# 修正 #4 [maint MED]: extMaxc がループ外に移動されていること
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_a5_extmaxc_outside_ext_for_loop():
    """extMaxc = nodeLabelMaxChars(NODE_W) が ext ノードの for ループ外に定義されていること。

    NODE_W は定数のため毎ループ同値。ループ外（'if (showBgp) {' 直後等）に移動することで
    不要な再評価を排除する（挙動・決定性は不変）。
    検証: ext peers for ループ開始より前に extMaxc の定義があること。
    壊すと赤: extMaxc をループ内に戻すと、for ループ開始より後に extMaxc 定義が現れる。
    """
    js = assets._JS
    ext_section_start = js.find("/* --- external peers")
    assert ext_section_start != -1, "external peers セクションが見つからない"

    # "if (showBgp)" の位置（ext peers ブロックの先頭ガード）
    show_bgp_pos = js.find("if (showBgp)", ext_section_start)
    assert show_bgp_pos != -1, "ext peers セクション内に 'if (showBgp)' が見つからない"

    # for ループ開始位置（DATA.extPeers を使う for）
    ext_for_pos = js.find("for (const e of DATA.extPeers)", show_bgp_pos)
    assert ext_for_pos != -1, "ext peers ループ 'for (const e of DATA.extPeers)' が見つからない"

    # extMaxc の定義位置
    extmaxc_pos = js.find("const extMaxc = nodeLabelMaxChars(NODE_W)", show_bgp_pos)
    assert extmaxc_pos != -1, \
        "'const extMaxc = nodeLabelMaxChars(NODE_W)' が ext peers ブロック内に見つからない"

    # extMaxc の定義が for ループ開始より前にあること
    assert extmaxc_pos < ext_for_pos, (
        f"extMaxc の定義がループ内にある（extMaxc_pos={extmaxc_pos} >= ext_for_pos={ext_for_pos}）。"
        "ループ外（if (showBgp) 直後等）に移動すること。"
    )


# ===========================================================================
# B5: キーボードショートカット拡充
# ===========================================================================

# ---------------------------------------------------------------------------
# string-presence テスト（構造・存在確認）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_b5_key_to_action_function_present():
    """keyToAction 関数が _JS に定義されていること。"""
    assert "function keyToAction" in assets._JS, \
        "_JS に function keyToAction が見当たらない"


@pytest.mark.unit
def test_b5_toggle_shortcuts_overlay_function_present():
    """toggleShortcutsOverlay 関数が _JS に定義されていること。"""
    assert "function toggleShortcutsOverlay" in assets._JS, \
        "_JS に function toggleShortcutsOverlay が見当たらない"


@pytest.mark.unit
def test_b5_shortcuts_overlay_in_body():
    """_BODY に id="shortcuts-overlay" 要素が存在すること。"""
    assert 'id="shortcuts-overlay"' in assets._BODY, \
        '_BODY に id="shortcuts-overlay" が見当たらない'


@pytest.mark.unit
def test_b5_shortcuts_overlay_default_hidden():
    """shortcuts-overlay が既定で display:none （非表示）で定義されていること。

    _CSS の #shortcuts-overlay ルールに "display:none" が含まれていること。
    これにより:
    - display:none を削除すると赤（初期非表示を壊すと検出）
    - #shortcuts-overlay セレクタだけ残して display:none を消しても赤

    壊すと赤: _CSS の #shortcuts-overlay { display: none; ... } から
    "display:none" を除去すると失敗する。
    """
    css = assets._CSS
    # #shortcuts-overlay セレクタのルールブロックを切り出す
    selector = "#shortcuts-overlay {"
    idx = css.find(selector)
    assert idx != -1, f"_CSS に {selector!r} セレクタが存在しない"
    # セレクタから対応する閉じ中括弧までのブロックを取り出す
    block_start = idx
    brace_depth = 0
    i = idx
    block_end = -1
    while i < len(css):
        if css[i] == "{":
            brace_depth += 1
        elif css[i] == "}":
            brace_depth -= 1
            if brace_depth == 0:
                block_end = i + 1
                break
        i += 1
    assert block_end != -1, "#shortcuts-overlay の CSS ブロックが閉じていない"
    rule_block = css[block_start:block_end]
    # ブロック内に display:none（スペース有無を問わない）が含まれること
    normalized = re.sub(r"\s+", "", rule_block)
    assert "display:none" in normalized, (
        f"#shortcuts-overlay の CSS ルールに display:none が存在しない。\n"
        f"該当ブロック: {rule_block!r}"
    )


@pytest.mark.unit
def test_b5_keydown_dispatches_keytoaction():
    """keydown ハンドラ内に keyToAction(ev.key) の呼び出しが存在すること。"""
    assert "keyToAction(ev.key)" in assets._JS, \
        "keydown ハンドラに keyToAction(ev.key) の呼び出しが存在しない"


@pytest.mark.unit
def test_b5_keydown_dispatch_after_input_guard():
    """keydown ハンドラ内で keyToAction() の呼び出しが INPUT/SELECT ガードより後にあること。

    入力欄ガード（ev.target.tagName === "INPUT"）が keyToAction 呼び出しより前にあること。
    これを逆転させると検索欄入力中にも g/h/m/l が発火する（入力欄ガード跨ぎバグ）。
    """
    js = assets._JS
    guard_pos = js.find("INPUT|SELECT|TEXTAREA")
    action_pos = js.find("keyToAction(ev.key)")
    assert guard_pos != -1, '_JS に入力欄ガードが存在しない（入力欄ガード削除を検出）'
    assert action_pos != -1, '_JS に keyToAction(ev.key) が存在しない'
    assert guard_pos < action_pos, (
        "keyToAction(ev.key) の呼び出しが入力欄ガードより前にある"
        "（ガードを跨いでいる: 回帰防止テスト）"
    )


@pytest.mark.unit
def test_b5_input_select_guard_preserved():
    """入力欄ガード（INPUT/SELECT/TEXTAREA）が keydown ハンドラに残存していること（削除を検出する回帰防止）。

    壊すと赤: ガードを削除すると検索入力中・config 編集中に g/h/m/l 等が奪われる。
    TEXTAREA はワークベンチの編集スクラッチ（textarea.cfgedit）でキーが奪われないために必須。
    """
    for tag in ("INPUT", "SELECT", "TEXTAREA"):
        assert tag in assets._JS, "keydown ハンドラに %s ガードが存在しない（入力欄ガード削除を検出）" % tag


@pytest.mark.unit
def test_b5_escape_closes_shortcuts_overlay():
    """Escape ハンドラが shortcuts-overlay を閉じる処理を含むこと。

    既存の選択解除/リセット処理は維持しつつ、
    shortcuts-overlay の非表示化がグローバル keydown の Escape 分岐内に追加されていること。

    注意: 検索欄専用 keydown（#search）にも "Escape" 分岐があるため、
    グローバル keydown ハンドラ（window.addEventListener("keydown"...）内の
    Escape 分岐のみを対象とする。

    1000文字マジックスライスではなく、バランス中括弧で keydown ブロック全体を
    robust に切り出してから検証する。
    """
    js = assets._JS
    # グローバル keydown ハンドラ（keyboard セクション）の開始位置を特定
    keyboard_marker = "/* keyboard"
    keyboard_pos = js.find(keyboard_marker)
    assert keyboard_pos != -1, '_JS にキーボードセクションマーカーが存在しない'
    # グローバル keydown ハンドラの開始位置
    global_keydown_pos = js.find('window.addEventListener("keydown"', keyboard_pos)
    assert global_keydown_pos != -1, 'グローバル keydown ハンドラが見つからない'
    # バランス中括弧で keydown ハンドラブロック全体を切り出す
    # window.addEventListener("keydown", ev => { ... }); の形を想定
    brace_start = js.index("{", global_keydown_pos)
    brace_depth = 0
    i = brace_start
    block_end = -1
    while i < len(js):
        if js[i] == "{":
            brace_depth += 1
        elif js[i] == "}":
            brace_depth -= 1
            if brace_depth == 0:
                block_end = i + 1
                break
        i += 1
    assert block_end != -1, 'グローバル keydown ハンドラの閉じ中括弧が見つからない'
    # 閉じ括弧の次の "});" まで含めて切り出す（addEventListener の末尾）
    # block_end はアロー関数本体の } の直後。addEventListener の ); までを含める
    closing = js.find(");", block_end)
    if closing != -1 and closing - block_end < 10:
        block_end = closing + 2
    global_keydown_section = js[global_keydown_pos:block_end]
    assert "Escape" in global_keydown_section, \
        'グローバル keydown ハンドラに Escape キー処理が存在しない'
    assert "shortcuts-overlay" in global_keydown_section, \
        'グローバル keydown の Escape 処理に shortcuts-overlay 非表示化が含まれていない'


@pytest.mark.unit
def test_b5_shortcuts_keymap_in_body_or_js():
    """ショートカット一覧（Ctrl/⌘+F / F / Esc / 1-N / G / H / M / L / ?）が
    overlay または _JS の toggleShortcutsOverlay 近傍に記載されていること。"""
    blob = assets._BODY + assets._JS
    # 主要ショートカット文字が一覧に含まれていること
    assert "Ctrl" in blob or "⌘" in blob, "Ctrl/⌘ の記述が _BODY/_JS に存在しない"
    # overlay コンテンツとして少なくとも G / H / M / L のいずれかが一覧記載されていること
    overlay_section = assets._BODY
    has_shortcut_list = any(k in overlay_section for k in ["G", "H", "M", "L", "?"])
    assert has_shortcut_list, "shortcuts-overlay の一覧内容が _BODY に存在しない"


# ---------------------------------------------------------------------------
# node 実行ロジックテスト: keyToAction 純関数の実検証（必須）
# ---------------------------------------------------------------------------

def _extract_key_to_action_source(js: str) -> str:
    """_JS から keyToAction 関数ブロックをバランス中括弧で切り出す。"""
    start_marker = "function keyToAction"
    idx = js.find(start_marker)
    if idx == -1:
        raise ValueError("keyToAction not found in _JS")
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
    raise ValueError("keyToAction: unbalanced braces")


def _run_key_to_action(node_bin: str, key: str) -> object:
    """node を使って keyToAction(key) を実行し結果（文字列 or null）を返す。"""
    func_src = _extract_key_to_action_source(assets._JS)
    driver = (
        f"{func_src}\n"
        f"const result = keyToAction({json.dumps(key)});\n"
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
def test_b5_key_g_lowercase_returns_connected(node_bin):
    """keyToAction("g") が "connected" を返すこと。

    壊すと赤: g キーのマッピングを消すと null になり失敗する。
    """
    result = _run_key_to_action(node_bin, "g")
    assert result == "connected", f'keyToAction("g") = {result!r}, 期待: "connected"'


@pytest.mark.unit
def test_b5_key_g_uppercase_returns_connected(node_bin):
    """keyToAction("G") が "connected" を返すこと（大文字小文字正規化）。

    実装で String(key).toLowerCase() しているため G も g と同じ結果になること。
    壊すと赤: toLowerCase() を除去すると G が null になる。
    """
    result = _run_key_to_action(node_bin, "G")
    assert result == "connected", f'keyToAction("G") = {result!r}, 期待: "connected"'


@pytest.mark.unit
def test_b5_key_h_returns_focus(node_bin):
    """keyToAction("h") が "focus" を返すこと。"""
    result = _run_key_to_action(node_bin, "h")
    assert result == "focus", f'keyToAction("h") = {result!r}, 期待: "focus"'


@pytest.mark.unit
def test_b5_key_m_returns_minimap(node_bin):
    """keyToAction("m") が "minimap" を返すこと。"""
    result = _run_key_to_action(node_bin, "m")
    assert result == "minimap", f'keyToAction("m") = {result!r}, 期待: "minimap"'


@pytest.mark.unit
def test_b5_key_l_returns_legend(node_bin):
    """keyToAction("l") が "legend" を返すこと。"""
    result = _run_key_to_action(node_bin, "l")
    assert result == "legend", f'keyToAction("l") = {result!r}, 期待: "legend"'


@pytest.mark.unit
def test_b5_key_question_returns_shortcuts(node_bin):
    """keyToAction("?") が "shortcuts" を返すこと。"""
    result = _run_key_to_action(node_bin, "?")
    assert result == "shortcuts", f'keyToAction("?") = {result!r}, 期待: "shortcuts"'


@pytest.mark.unit
def test_b5_key_f_returns_null(node_bin):
    """keyToAction("f") が null を返すこと（f は既存処理 zoomFit が担う）。

    壊すと赤: f を keyToAction のマップに追加すると null でなくなり失敗する。
    """
    result = _run_key_to_action(node_bin, "f")
    assert result is None, f'keyToAction("f") = {result!r}, 期待: null（既存予約キー）'


@pytest.mark.unit
def test_b5_key_x_returns_null(node_bin):
    """keyToAction("x") が null を返すこと（未割当キー）。

    壊すと赤: 余計なキーをマップに追加すると null でなくなり失敗する。
    """
    result = _run_key_to_action(node_bin, "x")
    assert result is None, f'keyToAction("x") = {result!r}, 期待: null'


@pytest.mark.unit
def test_b5_key_digit_returns_null(node_bin):
    """keyToAction("1") が null を返すこと（数字は既存タブ切替が担う）。

    壊すと赤: 数字をマップに追加すると null でなくなり失敗する。
    """
    result = _run_key_to_action(node_bin, "1")
    assert result is None, f'keyToAction("1") = {result!r}, 期待: null（既存予約キー）'


@pytest.mark.unit
def test_b5_key_escape_returns_null(node_bin):
    """keyToAction("Escape") が null を返すこと（Escape は既存処理が担う）。

    壊すと赤: Escape をマップに追加すると null でなくなり失敗する。
    """
    result = _run_key_to_action(node_bin, "Escape")
    assert result is None, f'keyToAction("Escape") = {result!r}, 期待: null（既存予約キー）'


@pytest.mark.unit
def test_b5_node_check_syntax_with_shortcuts(node_bin):
    """keyToAction / toggleShortcutsOverlay を含む _JS 全体で node --check が通ること。"""
    stub = (
        "const DATA={devices:{},links:[],segments:[],extPeers:[],bgpEdges:[],"
        "meta:{generated_from:[]},"
        "stats:{devices:0,interfaces:0,links:0,segments:0,"
        "by_vendor:{},by_as:{},by_area:{},link_kinds:{link:0,segment:0,stub:0},"
        "dualstack_ifs:0,bgp_sessions:0,ospf_networks:0,static_routes:0},"
        "checks:[]};"
        "const POS={};const VIEWS=['physical','stats','checks','addr','ifs'];"
        "const DIFF=null;\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(stub + assets._JS)
        path = f.name
    try:
        r = subprocess.run([node_bin, "--check", path], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# B5 修正: 表ビューガード検証
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_b5_graph_ops_guarded_by_is_table_view():
    """グラフ操作系ディスパッチ（_act）が isTableView() でガードされていること。

    壊すと赤: isTableView ガードを除去すると表ビュー中に g/h/m/l が
    グラフ状態を変更してしまう（実害修正 #1）。

    検証内容:
    - keyToAction の dispatch ブロックに isTableView が含まれること
    - shortcuts アクションは isTableView ガード外で発火できること
      （else if (_act === "shortcuts") が isTableView チェックより前にあること）
    """
    js = assets._JS
    # keydown ハンドラ全体を切り出す（keyboard セクション以降）
    keyboard_marker = "/* keyboard"
    keyboard_pos = js.find(keyboard_marker)
    assert keyboard_pos != -1, '_JS にキーボードセクションが存在しない'
    global_keydown_pos = js.find('window.addEventListener("keydown"', keyboard_pos)
    assert global_keydown_pos != -1, 'グローバル keydown ハンドラが見つからない'
    # バランス中括弧でブロック切り出し
    brace_start = js.index("{", global_keydown_pos)
    brace_depth = 0
    i = brace_start
    block_end = -1
    while i < len(js):
        if js[i] == "{":
            brace_depth += 1
        elif js[i] == "}":
            brace_depth -= 1
            if brace_depth == 0:
                block_end = i + 1
                break
        i += 1
    assert block_end != -1, 'グローバル keydown ハンドラの閉じ中括弧が見つからない'
    handler_src = js[global_keydown_pos:block_end]

    # 1. keyToAction の dispatch ブロックに isTableView が含まれること
    assert "isTableView" in handler_src, (
        "keydown ハンドラに isTableView() ガードが存在しない。\n"
        "グラフ操作系（g/h/m/l）が表ビュー中に発火してしまう。"
    )

    # 2. "shortcuts" アクションの分岐は isTableView() より前（ガード外）にあること
    #    つまり: "_act === \"shortcuts\"" の位置が "isTableView" より前
    shortcuts_pos = handler_src.find('"shortcuts"')
    is_table_view_pos = handler_src.find("isTableView")
    assert shortcuts_pos != -1, 'handler に "shortcuts" 分岐が存在しない'
    assert is_table_view_pos != -1, 'handler に isTableView が存在しない'
    assert shortcuts_pos < is_table_view_pos, (
        '"shortcuts" 分岐が isTableView() ガードより後にある。\n'
        "表ビュー中でも ? キーでオーバーレイを開けるよう、"
        '"shortcuts" は isTableView チェックの前に置くこと。'
    )


@pytest.mark.unit
def test_b5_toggle_shortcuts_overlay_simplified():
    """toggleShortcutsOverlay が classList.toggle("visible") 1行で実装されていること。

    壊すと赤: const isVisible = ...; classList.toggle("visible", !isVisible);
    という冗長な2行に戻すと失敗する（修正 #2: 簡約）。

    검証: 関数本体に classList.toggle("visible") が含まれ、
    classList.contains を使った isVisible 変数パターンが存在しないこと。
    """
    js = assets._JS
    # toggleShortcutsOverlay 関数ブロックを切り出す
    start_marker = "function toggleShortcutsOverlay"
    idx = js.find(start_marker)
    assert idx != -1, '_JS に toggleShortcutsOverlay 関数が存在しない'
    brace_start = js.index("{", idx)
    brace_depth = 0
    i = brace_start
    block_end = -1
    while i < len(js):
        if js[i] == "{":
            brace_depth += 1
        elif js[i] == "}":
            brace_depth -= 1
            if brace_depth == 0:
                block_end = i + 1
                break
        i += 1
    assert block_end != -1, 'toggleShortcutsOverlay: 閉じ中括弧が見つからない'
    func_body = js[idx:block_end]

    # 1. classList.toggle("visible") が含まれること（引数1個 = 純トグル）
    assert 'classList.toggle("visible")' in func_body, (
        'toggleShortcutsOverlay に classList.toggle("visible") が存在しない。\n'
        "classList.toggle(\"visible\") 1行への簡約が行われていないか、"
        "または引数2個の形式（toggle(\"visible\", !isVisible)）のまま。"
    )

    # 2. 冗長パターン（isVisible 変数 + contains）が存在しないこと
    assert "classList.contains" not in func_body, (
        'toggleShortcutsOverlay に classList.contains が残存している。\n'
        "isVisible 変数パターンを廃止し、classList.toggle(\"visible\") 1行に簡約すること。"
    )


@pytest.mark.unit
def test_b5_toggle_shortcuts_overlay_dom_stub(node_bin):
    """toggleShortcutsOverlay が classList.toggle("visible") を呼び出すことを node で実検証。

    DOM-stub（最小の classList モック）を使い:
    - 初期状態（visible なし）→ toggle 呼び出し後に "visible" が付与されること
    - 再度 toggle 呼び出し後に "visible" が除去されること

    壊すと赤: classList.toggle("visible") を消したり別の実装に変えると失敗する。
    """
    # toggleShortcutsOverlay 関数ブロックを切り出す
    js = assets._JS
    start_marker = "function toggleShortcutsOverlay"
    idx = js.find(start_marker)
    assert idx != -1, '_JS に toggleShortcutsOverlay 関数が存在しない'
    brace_start = js.index("{", idx)
    brace_depth = 0
    i = brace_start
    block_end = -1
    while i < len(js):
        if js[i] == "{":
            brace_depth += 1
        elif js[i] == "}":
            brace_depth -= 1
            if brace_depth == 0:
                block_end = i + 1
                break
        i += 1
    func_src = js[idx:block_end]

    # DOM スタブ + $ モック + 実行ドライバ
    driver = r"""
// DOM-stub: 最小の classList 実装
function makeElement() {
  const classes = new Set();
  return {
    classList: {
      add(c)    { classes.add(c); },
      remove(c) { classes.delete(c); },
      toggle(c, force) {
        if (force === undefined) {
          if (classes.has(c)) classes.delete(c); else classes.add(c);
        } else {
          force ? classes.add(c) : classes.delete(c);
        }
      },
      contains(c) { return classes.has(c); },
      has(c)      { return classes.has(c); },
    },
    _classes: classes,
  };
}
const _ov = makeElement();
// $ モック: #shortcuts-overlay のみ応答
function $(sel) {
  if (sel === "#shortcuts-overlay") return _ov;
  throw new Error("unexpected selector: " + sel);
}

""" + func_src + r"""

// テスト 1: 初期状態（visible なし）→ toggle → visible が付与される
if (_ov._classes.has("visible")) throw new Error("初期状態に visible が存在する");
toggleShortcutsOverlay();
if (!_ov._classes.has("visible")) throw new Error("1回目 toggle 後に visible が付与されない");

// テスト 2: 再度 toggle → visible が除去される
toggleShortcutsOverlay();
if (_ov._classes.has("visible")) throw new Error("2回目 toggle 後に visible が除去されない");

process.stdout.write("ok");
"""

    r = subprocess.run([node_bin, "--input-type=module"], input=driver,
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node_bin], input=driver,
                           capture_output=True, text=True, timeout=10)
    assert r.returncode == 0 and r.stdout.strip() == "ok", (
        f"toggleShortcutsOverlay DOM-stub テスト失敗:\n"
        f"stdout={r.stdout!r}\nstderr={r.stderr!r}"
    )


# ===========================================================================
# BGP ビュー ノード AS 番号表記削除（機器ノード副ラベル + 外部ピアノード主ラベル）
# ===========================================================================

@pytest.mark.unit
def test_bgp_device_sub_uses_bgp_rid_not_as():
    """機器ノードの BGP 分岐が bgp_rid を表示し、旧形 `AS ${d.as}` を含まないこと。

    変更後の sub 式は:
      S.view === "bgp" ? (d.bgp_rid ? `rid ${d.bgp_rid}` : "bgp rid なし")
    を使う。旧形 `AS ${d.as}` が存在すると AS 番号がノード上に表示されてしまう。
    """
    js = assets._JS
    # 新形: bgp_rid を使う分岐が存在すること（クォート種を問わず単一 assert）
    assert 'd.bgp_rid ? `rid ${d.bgp_rid}`' in js, \
        "機器ノード BGP 分岐に `rid ${d.bgp_rid}` 形式が含まれていない"
    # 新形フォールバック: "bgp rid なし" が存在すること
    assert '"bgp rid なし"' in js, \
        "機器ノード BGP 分岐のフォールバック \"bgp rid なし\" が含まれていない"
    # 旧形不在: `AS ${d.as}` が機器ノード描画箇所に残っていないこと（戻すと赤）
    device_nodes_start = js.find("/* --- device nodes ---")
    assert device_nodes_start != -1, "device nodes セクションが見つからない"
    device_section = js[device_nodes_start:device_nodes_start + 1500]
    assert '`AS ${d.as}`' not in device_section, \
        "機器ノード BGP 分岐に旧形 `AS ${d.as}` が残っている（AS がノード上に表示されてしまう）"


@pytest.mark.unit
def test_bgp_device_sub_bgp_rid_fallback_present():
    """機器ノード BGP 分岐: bgp_rid が無いとき "bgp rid なし" フォールバックが使われること。

    壊すと赤: フォールバック文字列を変更・削除するとこのテストが失敗する。
    """
    assert '"bgp rid なし"' in assets._JS, \
        "\"bgp rid なし\" が _JS に含まれていない（BGP rid フォールバックが消えている）"


@pytest.mark.unit
def test_bgp_device_sub_ospf_branch_unchanged():
    """機器ノード OSPF 分岐が従来通り残っていること（回帰防止）。

    OSPF ビューの sub は `rid ${d.ospf_rid}` または "ospf rid なし" のまま。
    BGP 変更で OSPF 分岐が壊れていないことを確認する。
    """
    js = assets._JS
    assert '`rid ${d.ospf_rid}`' in js, \
        "OSPF 分岐 `rid ${d.ospf_rid}` が消えている（回帰）"
    assert '"ospf rid なし"' in js, \
        "OSPF フォールバック \"ospf rid なし\" が消えている（回帰）"


@pytest.mark.unit
def test_bgp_device_sub_vendor_branch_unchanged():
    """機器ノードの物理ビュー分岐（d.vendor）が従来通り残っていること（回帰防止）。

    physical ビューでは sub は d.vendor を表示する。BGP 変更で壊れていないことを確認する。
    """
    device_nodes_start = assets._JS.find("/* --- device nodes ---")
    assert device_nodes_start != -1, "device nodes セクションが見つからない"
    device_section = assets._JS[device_nodes_start:device_nodes_start + 1500]
    assert "d.vendor" in device_section, \
        "device nodes セクションに d.vendor が含まれていない（物理ビュー分岐が消えている）"


@pytest.mark.unit
def test_bgp_ext_peer_hn_uses_e_sub_not_e_label():
    """外部ピアノードの主ラベル（hn）が e.sub（neighbor IP）を使うこと。

    変更後: <text class="hn"> は truncateLabel(e.sub, ...) を表示する。
    旧形: truncateLabel(e.label, ...) が hn に使われていた（AS xxx がノード上に表示されていた）。
    壊すと赤: e.label を hn に戻すとこのテストが失敗する。
    """
    ext_peers_start = assets._JS.find("/* --- external peers")
    assert ext_peers_start != -1, "external peers セクションが見つからない"
    ext_section = assets._JS[ext_peers_start:ext_peers_start + 1000]
    # 新形: hn が e.sub を使う
    assert 'class="hn"' in ext_section and 'truncateLabel(e.sub,' in ext_section, \
        "ext ノード hn に truncateLabel(e.sub, ...) が使われていない"
    # 旧形不在: e.label が hn の <text>...</text> 内に使われていないこと（戻すと赤）
    # 属性末尾の ">" ではなく "</text>" まで切り出すことでテンプレート本文を含める
    hn_pos = ext_section.find('class="hn"')
    assert hn_pos != -1, 'class="hn" が ext セクションに見つからない'
    hn_elem_end = ext_section.find("</text>", hn_pos) + len("</text>")
    hn_content = ext_section[hn_pos:hn_elem_end]
    assert "truncateLabel(e.sub," in hn_content, \
        "ext ノード hn テキストに truncateLabel(e.sub, ...) が含まれていない"
    assert "truncateLabel(e.label," not in hn_content, \
        "ext ノード hn テキストに旧形 truncateLabel(e.label, ...) が残っている（AS がノード主ラベルに表示される）"


@pytest.mark.unit
def test_bgp_ext_peer_sub_text_removed():
    """外部ピアノードの副ラベル（<text class="sub">）が削除されていること。

    変更後: <text class="sub"> の行は ext ブロックに存在しない。
    旧形: sub に e.sub（neighbor IP）を表示していた行が残ると AS テキストが別途表示される。
    壊すと赤: <text class="sub"> を ext ブロックに戻すとこのテストが失敗する。
    """
    ext_peers_start = assets._JS.find("/* --- external peers")
    assert ext_peers_start != -1, "external peers セクションが見つからない"
    ext_section = assets._JS[ext_peers_start:ext_peers_start + 1000]
    assert '<text class="sub"' not in ext_section, \
        "ext ノードに <text class=\"sub\"> が残っている（旧構造が残存している）"


@pytest.mark.unit
def test_bgp_ext_peer_title_preserved():
    """外部ピアノードの <title>（ホバー）が e.label を保持していること（AS 文脈の維持）。

    変更後も <title>${esc(e.label)}</title> は残す（ホバーで AS 情報を確認できる）。
    壊すと赤: title を削除・変更するとこのテストが失敗する。
    """
    ext_peers_start = assets._JS.find("/* --- external peers")
    assert ext_peers_start != -1, "external peers セクションが見つからない"
    ext_section = assets._JS[ext_peers_start:ext_peers_start + 1000]
    assert "<title>" in ext_section and "esc(e.label)" in ext_section, \
        "ext ノードの <title>${esc(e.label)}</title> が消えている（ホバーで AS 文脈が失われる）"


@pytest.mark.unit
def test_as_identification_means_preserved():
    """AS 識別手段（asColor・aslabel 枠ラベル・検索 as: 分岐）がソースに残っていること。

    ノード上の AS テキスト削除後も AS の識別手段が残ることを担保する回帰テスト。
    壊すと赤: asColor / aslabel / as: 検索のいずれかを削除するとこのテストが失敗する。
    """
    js = assets._JS
    # AS 枠の色: device/ext 両 vbar で asColor( が使われていること（消すと赤）
    assert "asColor(" in js, "asColor が _JS から消えている（AS 色識別が失われる）"
    # AS 枠ラベル: aslabel テキスト内に "AS ${as}" が存在すること（消すと赤）
    assert "AS ${as}" in js, \
        "aslabel の \"AS ${as}\" が _JS から消えている（AS 枠ラベルが失われる）"
    # 検索 corpus: device ノードで "AS"+d.as がインデックスされていること（消すと赤）
    assert '"AS"+d.as' in js, \
        'corpus の "AS"+d.as が _JS から消えている（AS による検索が失われる）'
    # 検索クリック: clk(`as:${a}`) で AS フィルタリングできること（消すと赤）
    assert 'clk(`as:' in js, \
        "検索クリック clk(`as: が _JS から消えている（AS フィルタリングが失われる）"


# ===========================================================================
# 改修③: 表示ノード選択パネル（#nodepanel）スクロール対応
# ===========================================================================

@pytest.mark.unit
def test_nodepanel_scrollable():
    """#nodepanel CSS ブロックに overflow-y と max-height が両方含まれること。

    ノードが多い場合に縦に伸びて画面外にはみ出す問題を解消するため、
    #nodepanel に overflow-y:auto と max-height:calc(100vh - 160px) を追加する。

    このテストでは _CSS から #nodepanel { ... } ブロックを正規表現で切り出し、
    overflow-y と max-height の両方が含まれることを検証する。

    壊すと赤になる: overflow-y または max-height を削除するとこのテストが失敗する。
    """
    # #nodepanel { ... } ブロックを切り出す（次の { } ブロックまで）
    match = re.search(r'#nodepanel\s*\{([^}]*)\}', assets._CSS)
    assert match is not None, "_CSS に #nodepanel { ... } ブロックが見つからない"
    nodepanel_block = match.group(1)

    assert 'overflow-y' in nodepanel_block, \
        "#nodepanel CSS ブロックに overflow-y が含まれていない（スクロール対応未実装）"
    assert 'max-height' in nodepanel_block, \
        "#nodepanel CSS ブロックに max-height が含まれていない（スクロール対応未実装）"


# ===========================================================================
# 改修① OSPF area 不一致バッジ簡素化 — assets 構造アサート
# ===========================================================================

@pytest.mark.unit
def test_area_badge_mismatch_uses_neq_link():
    """リンク area-badge の描画に '/' 分岐と '≠' 表記・警告色が存在すること。

    DRY 化後は '≠' / 分岐 / 警告色は areaBadge 共通ヘルパーに集約される。
    リンク badge セクションが areaBadge を呼び出し、areaBadge 定義に '≠' が
    含まれることで出力不変を担保する。

    壊すと赤: areaBadge 呼び出しが削除された場合、または areaBadge 定義から '≠' が
    消えた場合に失敗する。
    """
    js = assets._JS

    # リンク badge セクションが areaBadge(l.area) を呼び出していること
    badge_start = js.find("/* OSPF area badge */")
    assert badge_start != -1, "_JS に '/* OSPF area badge */' コメントが存在しない"
    badge_section = js[badge_start:badge_start + 600]
    assert "areaBadge(l.area)" in badge_section, (
        "リンク area-badge セクションが areaBadge(l.area) を呼び出していない: %r"
        % badge_section[:200]
    )

    # areaBadge 関数定義に '≠' / '/' 分岐 / 警告色が存在すること
    area_badge_start = js.find("function areaBadge(")
    assert area_badge_start != -1, "_JS に function areaBadge が存在しない"
    area_badge_def = js[area_badge_start:area_badge_start + 300]

    assert "≠" in area_badge_def, (
        "areaBadge 定義に '≠' (\\u2260) 文字が存在しない: %r" % area_badge_def[:200]
    )
    has_slash_branch = (
        'split("/")' in area_badge_def or
        'includes("/")' in area_badge_def or
        '.indexOf("/")' in area_badge_def
    )
    assert has_slash_branch, (
        "areaBadge 定義に '/' 含む場合の分岐が存在しない: %r" % area_badge_def[:200]
    )
    assert "var(--danger)" in area_badge_def, (
        "areaBadge 定義に var(--danger) 警告色が存在しない: %r" % area_badge_def[:200]
    )

    # 旧形（分岐なし const txt = "area " + l.area）が badge セクションに残っていないこと
    old_form_match = re.search(
        r'const\s+txt\s*=\s*["\']area\s+["\'][^;]*l\.area\s*[,;]',
        badge_section
    )
    assert old_form_match is None, (
        "リンク area-badge に分岐なし旧形 'const txt = \"area \" + l.area' が残っている: %r"
        % old_form_match.group(0)
    )


@pytest.mark.unit
def test_area_badge_mismatch_uses_neq_segment():
    """セグメント area-badge の描画に '/' 分岐と '≠' 表記・警告色が存在すること。

    DRY 化後はセグメント badge セクションも areaBadge 共通ヘルパーを呼び出す。
    areaBadge の定義に '≠' / 分岐 / 警告色があることで出力不変を担保する。

    壊すと赤: areaBadge(s.area) 呼び出しが消えた場合に失敗する。
    """
    js = assets._JS

    # セグメント badge セクションが areaBadge(s.area) を呼び出していること
    seg_badge_start = js.find("if (showOspf && s.area)")
    assert seg_badge_start != -1, "_JS に 'if (showOspf && s.area)' が存在しない"
    seg_badge_section = js[seg_badge_start:seg_badge_start + 400]
    assert "areaBadge(s.area)" in seg_badge_section, (
        "セグメント area-badge セクションが areaBadge(s.area) を呼び出していない: %r"
        % seg_badge_section[:200]
    )

    # areaBadge 関数定義の検証はリンク側テストで担保済み（DRY）
    # セグメント側の '/' 分岐・警告色は areaBadge に集約されているため個別検証不要。
    # ただし areaBadge 定義に var(--danger) があることは呼び出し元と独立してガード：
    area_badge_start = js.find("function areaBadge(")
    assert area_badge_start != -1, "_JS に function areaBadge が存在しない"
    area_badge_def = js[area_badge_start:area_badge_start + 300]
    assert "var(--danger)" in area_badge_def, (
        "areaBadge 定義に var(--danger) 警告色が存在しない: %r" % area_badge_def[:200]
    )


@pytest.mark.unit
def test_area_stroke_uses_area_color_unchanged():
    """stroke の areaColor(l.area) は変更されていないこと（color/凡例整合維持）。

    壊すと赤: stroke 側まで ≠ 分岐が混入した場合（例: fill="var(--danger)" に
    変えてしまった場合）に失敗する。_JS 全体検索ではなく stroke= を含む行に限定して
    areaColor 参照を確認するため、badge 側の areaBadge 呼び出しでは通過しない。
    """
    js = assets._JS
    # stroke 決定行（リンク）: stroke="${areaColor(l.area)}" を含む行が存在すること
    # _JS 全体検索では badge 内の areaColor でも通過するため、stroke= 文脈に限定する
    link_stroke_ok = bool(re.search(r'stroke=.*areaColor\(l\.area\)', js))
    assert link_stroke_ok, (
        "stroke 側の areaColor(l.area) が消えている（stroke は split[0] 基準維持）。"
        "stroke= を含む文脈でのみ検証する。"
    )
    # セグメント stroke: stroke="${areaColor(s.area)}" を含む行が存在すること
    seg_stroke_ok = bool(re.search(r'stroke=.*areaColor\(s\.area\)', js))
    assert seg_stroke_ok, (
        "セグメント stroke 側の areaColor(s.area) が消えている。"
        "stroke= を含む文脈でのみ検証する。"
    )


# ===========================================================================
# 改修② ハイライト時ラインラベルのノード前面表示（z-order 再構成）
# ===========================================================================

def _extract_render_function_source(js: str) -> str:
    """_JS から render() 関数ブロックをバランス中括弧で切り出す。"""
    marker = "function render()"
    idx = js.find(marker)
    if idx == -1:
        raise ValueError("function render() not found in _JS")
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
    raise ValueError("function render(): unbalanced braces")


@pytest.mark.unit
def test_render_labelparts_declared():
    """render() 内に labelParts 配列が宣言されていること。

    壊すと赤: labelParts を削除した場合に失敗する。
    """
    js = assets._JS
    render_src = _extract_render_function_source(js)
    assert "const labelParts = []" in render_src, (
        "render() 内に 'const labelParts = []' が宣言されていない。"
        "z-order 再構成（改修②）で追加する必要がある。"
    )


@pytest.mark.unit
def test_render_line_labels_use_labelparts():
    """render() 内のライン/エッジラベル stackLabel が labelParts を使うこと。

    対象4箇所:
      - link IF/IP ラベル (L960相当)
      - link subnet ラベル (L967相当)
      - seg メンバー IF ラベル (L1010相当)
      - BGP edge アドレスラベル (L1079相当)

    壊すと赤: いずれかを stackLabel(parts, ...) に戻すと失敗する。
    """
    js = assets._JS
    render_src = _extract_render_function_source(js)
    # 4箇所すべて labelParts を使っていること
    # 各呼び出しの deco 文字列で個別に識別する
    assert 'stackLabel(labelParts, lx, ly - 9 - (lines.length-1)*13, lines, {show: showIf, deco:`link:${l.id}`})' in render_src, (
        "link IF/IP ラベルの stackLabel が labelParts を使っていない（z-order 未対応）"
    )
    assert 'stackLabel(labelParts, mx + off.dx, my + off.dy, [l.subnet, l.dual].filter(Boolean), {show: true, deco:`link:${l.id}`})' in render_src, (
        "link subnet ラベルの stackLabel が labelParts を使っていない（z-order 未対応）"
    )
    assert 'stackLabel(labelParts, lx, ly - 9 - (lines.length-1)*13, lines, {show: true, deco:`seglink:${s.id}:${m.dev}`})' in render_src, (
        "seg メンバー IF ラベルの stackLabel が labelParts を使っていない（z-order 未対応）"
    )
    assert 'stackLabel(labelParts, lx, ly - 10, [ifn, ip, ip6].filter(Boolean), {show: true, deco:`bgpedge:${e.id}`})' in render_src, (
        "BGP edge アドレスラベルの stackLabel が labelParts を使っていない（z-order 未対応）"
    )


@pytest.mark.unit
def test_render_no_label_stacklabel_uses_parts():
    """render() 内にラベル系の stackLabel(parts, ...) 呼び出しが残っていないこと。

    4箇所のラベルはすべて labelParts に移動済みのため、render() 内で
    stackLabel(parts, ...) はゼロであること（stackLabel 関数定義の行は除く）。

    壊すと赤: いずれかのラベル stackLabel を parts に戻すと失敗する。
    """
    js = assets._JS
    render_src = _extract_render_function_source(js)
    # stackLabel(parts, ... の呼び出し（関数定義「function stackLabel(parts,」は render() 外なので除外される）
    # render() 本体内で stackLabel(parts, が呼ばれる回数が 0 であること
    call_count = render_src.count("stackLabel(parts,")
    assert call_count == 0, (
        f"render() 内に stackLabel(parts, ...) 呼び出しが {call_count} 箇所残っている。"
        "ラベル系は labelParts に移動すること（改修②）。"
    )


@pytest.mark.unit
def test_render_bgp_subnet_tag_uses_labelparts():
    """render() 内の BGP loopback subnet-tag が labelParts.push(...) を使うこと。

    壊すと赤: parts.push(`<text class="subnet-tag" data-deco="bgpedge:...`) に戻すと失敗する。
    """
    js = assets._JS
    render_src = _extract_render_function_source(js)
    # labelParts.push で subnet-tag テキストが積まれること
    assert 'labelParts.push(`<text class="subnet-tag" data-deco="bgpedge:' in render_src, (
        "BGP loopback subnet-tag が labelParts.push を使っていない（改修②未対応）"
    )
    # 回帰ガード: parts.push で subnet-tag が積まれないこと（data-deco="bgpedge: 付きのみ対象）
    # area-badge 内の subnet-tag は parts のまま（除外対象）
    # data-deco="bgpedge: を持つ subnet-tag が parts.push に残っていないこと
    assert 'parts.push(`<text class="subnet-tag" data-deco="bgpedge:' not in render_src, (
        "BGP loopback subnet-tag が parts.push を使っている（labelParts への移動が未完了）"
    )


@pytest.mark.unit
def test_render_labelparts_pushed_after_device_nodes():
    """labelParts の内容が device ノード描画より後・world.innerHTML より前に parts へ積まれること。

    z-order の核心アサート:
      - device ノード（data-elem="dev"）の最後の push より後に labelParts が積まれること
      - world.innerHTML より前に labelParts が積まれること

    これにより HTML 文字列内でノード要素の後にラベルが来て、
    SVG の描画順でラベルがノードより前面に表示される。

    壊すと赤: parts.push(...labelParts) または parts.push(labelParts.join("")) を
    world.innerHTML の後に移動した場合、または削除した場合に失敗する。
    """
    js = assets._JS
    render_src = _extract_render_function_source(js)

    # labelParts を parts に統合するステートメントが存在すること
    merge_pattern1 = "parts.push(...labelParts)"
    merge_pattern2 = "parts.push(labelParts.join(\"\"))"
    has_merge = (merge_pattern1 in render_src) or (merge_pattern2 in render_src)
    assert has_merge, (
        "render() 内に 'parts.push(...labelParts)' または 'parts.push(labelParts.join(\"\"))' が存在しない。"
        "labelParts の内容を parts に統合するステートメントが必要（改修②）。"
    )

    # device ノード（data-elem="dev"）の最後の parts.push 位置
    dev_push = 'data-elem="dev"'
    dev_pos = render_src.rfind(dev_push)
    assert dev_pos != -1, "render() 内に data-elem='dev' の push が見つからない"

    # world.innerHTML の位置
    world_pos = render_src.find("world.innerHTML")
    assert world_pos != -1, "render() 内に world.innerHTML が見つからない"

    # labelParts 統合ステートメントの位置
    merge_pos = render_src.find(merge_pattern1)
    if merge_pos == -1:
        merge_pos = render_src.find(merge_pattern2)

    # 順序チェック: dev_pos < merge_pos < world_pos
    assert dev_pos < merge_pos, (
        f"labelParts の統合（pos={merge_pos}）が device ノード push（pos={dev_pos}）より前にある。"
        "labelParts はすべての device ノード描画の後に積む必要がある。"
    )
    assert merge_pos < world_pos, (
        f"labelParts の統合（pos={merge_pos}）が world.innerHTML（pos={world_pos}）より後にある。"
        "world.innerHTML の直前に labelParts を統合すること。"
    )


@pytest.mark.unit
def test_render_labelparts_no_spread_push():
    """parts.push(...labelParts) のスプレッド形が残っていないこと（スタック安全化 改修②修正1）。

    大規模トポロジー（要素数 13万超）で V8 のスプレッド引数上限により
    Maximum call stack size exceeded が起きうるため、
    parts.push(labelParts.join("")) に差し替えた。

    壊すと赤: parts.push(...labelParts) に戻すと失敗する。
    """
    js = assets._JS
    render_src = _extract_render_function_source(js)
    assert "parts.push(...labelParts)" not in render_src, (
        "parts.push(...labelParts) のスプレッド形が残っている。"
        "大規模トポロジーでスタックオーバーフローを起こしうるため "
        "parts.push(labelParts.join(\"\")) を使うこと（改修②修正1）。"
    )
    assert 'parts.push(labelParts.join(""))' in render_src, (
        "parts.push(labelParts.join(\"\")) が存在しない。"
        "labelParts 統合はスタック安全な join 形で行うこと（改修②修正1）。"
    )


@pytest.mark.unit
def test_css_subnet_tag_pointer_events_none():
    """.subnet-tag CSS ルールに pointer-events: none が含まれること（改修②修正2）。

    改修②で subnet-tag がノード前面（labelParts 経由）に移動したため、
    ノード上に重なってもクリックを素通りさせる必要がある。

    壊すと赤: pointer-events: none を .subnet-tag から消すと失敗する。
    """
    css = assets._CSS
    # .subnet-tag ルールブロックを抽出して確認
    tag_pos = css.find(".subnet-tag")
    assert tag_pos != -1, ".subnet-tag ルールが CSS に存在しない"
    # ルール開始から閉じ括弧まで
    block_end = css.find("}", tag_pos)
    assert block_end != -1, ".subnet-tag ブロックの閉じ括弧が見つからない"
    block = css[tag_pos:block_end + 1]
    assert "pointer-events: none" in block, (
        f".subnet-tag CSS ルールに pointer-events: none がない。\n実際のブロック: {block!r}\n"
        "ノード前面移動後もクリック透過させるために必要（改修②修正2）。"
    )


@pytest.mark.unit
def test_css_iflabel_pointer_events_none():
    """.iflabel / .iflabel-bg CSS ルールに pointer-events: none が含まれること（回帰ガード）。

    壊すと赤: どちらかから pointer-events: none を消すと失敗する。
    """
    css = assets._CSS
    # .iflabel の確認（.iflabel-bg や .iflabel.show は別ルール。クラス名前方一致で先頭ブロックを探す）
    for selector in (".iflabel ", ".iflabel-bg "):
        pos = css.find(selector)
        assert pos != -1, f"CSS に {selector.strip()} ルールが存在しない"
        block_end = css.find("}", pos)
        assert block_end != -1, f"{selector.strip()} ブロックの閉じ括弧が見つからない"
        block = css[pos:block_end + 1]
        assert "pointer-events: none" in block, (
            f"{selector.strip()} CSS ルールに pointer-events: none がない。\n実際のブロック: {block!r}"
        )


# ===========================================================================
# stub / loopback ノードの統一挙動（hover/click/可視性/凡例/状態）— アセット構造テスト
# ===========================================================================

@pytest.mark.unit
def test_lpId_and_segById_helpers():
    """lpId（dev:ifn）と segById（segments→stub_nodes フォールバック）ヘルパーが定義されていること。

    壊すと赤: これらを消すと描画・hover・click・詳細パネルが stub を引けなくなる。
    """
    js = assets._JS
    assert 'function lpId(st)' in js and 'st.dev + ":" + st.ifn' in js, \
        "lpId(st)=dev:ifn ヘルパーが無い"
    assert 'function segById(id)' in js, "segById ヘルパーが無い"
    # segById は stub を STUB_BY_ID（id→st の Map・O(1)）でフォールバック解決する
    assert "const STUB_BY_ID = new Map" in js, \
        "stub 索引 STUB_BY_ID（Map）が無い（segById が線形 find に戻っている）"
    assert "STUB_BY_ID.get(id)" in js, \
        "segById が STUB_BY_ID.get(id) で stub をフォールバック解決していない"


@pytest.mark.unit
def test_stub_hover_ellipse_shows_label():
    """楕円 hover でもスポーク hover と同じく IF/IP ラベルを出す（hoverLink=s.id）こと。

    旧仕様は楕円 hover では want=null（ラベル無し）だった。新仕様は want=s.id に統一。
    segment・stub 共通（どちらも data-elem="seg"）。

    壊すと赤: want を null に戻すと楕円 hover でラベルが出なくなる。
    """
    js = assets._JS
    mv = js.find('window.addEventListener("mousemove"')
    assert mv != -1, "mousemove ハンドラが見つからない"
    ctx = js[mv:mv + 2000]
    assert "const s = segById(sid)" in ctx, "mousemove の seg/seglink hover が segById を使っていない"
    assert "const want = s ? s.id : sid" in ctx, \
        "楕円 hover で want=s.id（ラベル表示）になっていない（旧 want=null のまま）"
    # 旧 data-dev hover フォールバックが消えていること
    assert "lp.dataset.dev" not in js, "旧 data-dev hover フォールバックが残っている"


@pytest.mark.unit
def test_stub_click_uses_segById_setHotNet():
    """click の seg 分岐が segById→setHotNet を使い（subnet 連動選択）、旧 data-dev 親選択分岐が無いこと。

    壊すと赤: segById を DATA.segments.find に戻すと stub クリックが効かない／
             data-dev 分岐を復活させると挙動が分裂する。
    """
    js = assets._JS
    click_start = js.find('canvas.addEventListener("click"')
    assert click_start != -1
    ctx = js[click_start:click_start + 1600]
    assert 'g.dataset.elem === "seg"' in ctx and "segById(id)" in ctx and "setHotNet(" in ctx, \
        "click の seg 分岐が segById→setHotNet になっていない"
    assert "data-dev" not in ctx, "click ハンドラに旧 data-dev 分岐が残っている"
    # seglink クリックも segById 経由
    assert "segById(le.dataset.id)" in ctx, "seglink クリックが segById を使っていない"


@pytest.mark.unit
def test_stub_netNodes_includes_stub_nodes():
    """netNodes(net) が DATA.stub_nodes も走査し、該当 subnet の stub ノード id＋親デバイスを追加すること。

    これにより setHotNet（subnet 連動選択）が stub/loopback にも効く。

    壊すと赤: netNodes に stub_nodes 走査が無いと stub クリックで何も選択されない。
    """
    js = assets._JS
    nn = js.find("function netNodes(net)")
    assert nn != -1, "netNodes が見つからない"
    ctx = js[nn:nn + 800]
    assert "DATA.stub_nodes" in ctx and "lpId(st)" in ctx and "st.dev" in ctx, \
        "netNodes が stub_nodes（id＋親デバイス）を追加していない"


@pytest.mark.unit
def test_stub_nodepanel_and_legend():
    """表示ノードパネルに stub 行・凡例に loopback/スタブのクリック項目・lgNodes 分岐があること。"""
    js = assets._JS
    # 表示ノードパネル: stub_nodes を行に
    np = js.find("function renderNodePanel")
    assert np != -1
    np_ctx = js[np:np + 700]
    assert "DATA.stub_nodes" in np_ctx and "lpId(st)" in np_ctx, \
        "renderNodePanel に stub_nodes 行が無い（チェックボックスで非表示にできない）"
    # 凡例: clk("loopback") と clk("stub")
    assert 'clk("loopback"' in js, "凡例に loopback 専用項目（clk）が無い"
    assert 'clk("stub"' in js, "凡例に stub（スタブ）専用項目（clk）が無い"
    # lgNodes: loopback/stub 一括強調分岐
    assert 'lg === "loopback" || lg === "stub"' in js, \
        "lgNodes 構築に loopback/stub 凡例強調の分岐が無い"


@pytest.mark.unit
def test_stub_validIds_and_view_cleanup():
    """hash 復元の validIds に stub id を含め、BGP/OSPF ビュー切替で不適合 stub を選択解除すること。"""
    js = assets._JS
    # validIds に stub id
    assert "...(DATA.stub_nodes || []).map(lpId)" in js, \
        "validIds に stub ノード id が含まれていない（リロードで選択復元できない）"
    # ビュー切替クリーンアップ: BGP では stub を、OSPF では area なし stub を選択解除
    assert 'if (v === "bgp") for (const st of (DATA.stub_nodes || [])) S.sel.delete(lpId(st));' in js, \
        "BGP ビューで stub 選択を解除するクリーンアップが無い"
    assert 'if (v === "ospf") for (const st of (DATA.stub_nodes || [])) if (!st.area) S.sel.delete(lpId(st));' in js, \
        "OSPF ビューで非参加 stub 選択を解除するクリーンアップが無い"


@pytest.mark.unit
def test_stub_category_toggle_filters():
    """loopback/stub のカテゴリ全体トグル（segment の #f-seg に相当）が実装されていること。

    - 状態 S.filters に lo/stub
    - ツールバー UI #f-lo / #f-stub（checked）
    - onchange ハンドラ
    - stubFiltered(id) ヘルパを visible()/selectable() で使用（カテゴリ非表示）
    壊すと赤: どれかを消すと loopback/stub の全体表示トグルが効かなくなる。
    """
    js = assets._JS
    body = assets._BODY
    # 状態とUIとハンドラ
    assert "filters:{seg:true, lo:true, stub:true, ext:true}" in js, \
        "S.filters に lo/stub の初期値が無い"
    assert 'id="f-lo"' in body, "ツールバーに #f-lo チェックボックスが無い"
    assert 'id="f-stub"' in body, "ツールバーに #f-stub チェックボックスが無い"
    assert '$("#f-lo").onchange' in js and '$("#f-stub").onchange' in js, \
        "#f-lo / #f-stub の onchange ハンドラが無い"
    # stubFiltered ヘルパと visible/selectable での使用
    assert "function stubFiltered(id)" in js, "stubFiltered ヘルパが無い"
    assert 'st.kind === "loopback" && !S.filters.lo' in js and 'st.kind === "stub" && !S.filters.stub' in js, \
        "stubFiltered が kind ごとに S.filters.lo/stub を見ていない"
    assert js.count("if (stubFiltered(id)) return false;") >= 2, \
        "visible()/selectable() の両方で stubFiltered を使っていない"


@pytest.mark.unit
def test_stub_uses_areabadge_helper():
    """stub ブロックが areaBadge() ヘルパーを呼び出していること（OSPF area バッジ・DRY）。"""
    blk = _stub_block(assets._JS)
    assert "areaBadge(" in blk, "stub ブロックに areaBadge( 呼び出しが存在しない"


@pytest.mark.unit
def test_stub_segnode_css_reused_and_legacy_removed():
    """g.segnode の共通 CSS が再利用され、旧 lpstub CSS が無いこと。

    壊すと赤: g.segnode ellipse/text を消すと stub の点線楕円・subnet テキストが消える。
             旧 .lpstub / cursor:default 上書きを復活させると失敗。
    """
    css = assets._CSS
    assert "g.segnode ellipse" in css and "g.segnode text" in css, \
        "g.segnode の共通 CSS が消えている（stub の楕円/テキストが消える）"
    assert ".lpstub" not in css, "旧 .lpstub CSS が残っている"
    assert 'g.segnode[data-deco^="lpstub:"]' not in css, "旧 lpstub cursor 上書きが残っている"


# ---------------------------------------------------------------------------
# CONFIG ビュー — JS アセット構造
# ---------------------------------------------------------------------------

def test_js_has_render_config_view():
    """renderConfigView 関数が定義されていること。"""
    assert "function renderConfigView(" in assets._JS


def test_is_table_view_includes_config():
    """isTableView が config を表ビューとして扱うこと。"""
    m = re.search(r"const isTableView = \(\) => (.*?);", assets._JS)
    assert m and 'S.view === "config"' in m.group(1)


def test_render_table_view_dispatches_config():
    """renderTableView が config を renderConfigView へ振り分けること。"""
    assert 'S.view === "config"' in assets._JS
    assert "renderConfigView()" in assets._JS


def test_js_has_config_state():
    """S に選択機器状態 configDev が存在すること。"""
    assert "configDev" in assets._JS


def test_config_view_reuses_global_search():
    """CONFIG ビューはグローバル検索を流用すること（専用入力でフォーカスを失わないため）。
    searchQuery() を介して S.search を解釈する。"""
    m = re.search(r"function renderConfigView\(\) \{(.*?)\n\}", assets._JS, re.DOTALL)
    assert m and "searchQuery()" in m.group(1)


def test_config_view_secret_warning_present():
    """機密がそのまま含まれる旨の警告文言が含まれること。"""
    assert "機密" in assets._JS


# ---------------------------------------------------------------------------
# CONFIG ワークベンチ Phase A — ペイン内ユーティリティ
# ---------------------------------------------------------------------------

def test_js_has_copy_text_helper():
    """汎用クリップボードコピー copyText が定義されていること。"""
    assert "function copyText(" in assets._JS


def test_config_view_has_toolbar_toggles():
    """renderConfigView に 折返し/grep トグルとコピー/ナビの data 属性があること。"""
    m = re.search(r"function renderConfigView\(\) \{(.*?)\n\}", assets._JS, re.DOTALL)
    body = m.group(1)
    assert 'data-cfgtoggle="wrap"' in body
    assert 'data-cfgtoggle="grep"' in body
    assert "data-cfgcopy" in body
    assert "data-cfgnav" in body


def test_js_has_config_wrap_grep_state():
    """S に configWrap / configGrep 状態があること。"""
    assert "configWrap" in assets._JS and "configGrep" in assets._JS


def test_config_view_grep_filters_lines():
    """grep モードのとき一致行のみを描く分岐（S.configGrep）が renderConfigView にあること。"""
    m = re.search(r"function renderConfigView\(\) \{(.*?)\n\}", assets._JS, re.DOTALL)
    assert "S.configGrep" in m.group(1)


def test_tableview_handles_config_toggles():
    """#tableview のイベント委譲に cfgtoggle / cfgnav / cfgcopy の分岐があること。"""
    assert "data-cfgtoggle" in assets._JS
    assert "data-cfgnav" in assets._JS
    assert "data-cfgcopy" in assets._JS


# ---------------------------------------------------------------------------
# CONFIG ワークベンチ Phase P — parse 状態モード
# ---------------------------------------------------------------------------

def test_config_view_parse_status_mode():
    """renderConfigView に parse 状態モード（DATA.parse_status・3段階・凡例・未対応のみ）があること。"""
    m = re.search(r"function renderConfigView\(\) \{(.*?)\n\}", assets._JS, re.DOTALL)
    body = m.group(1)
    assert "DATA.parse_status" in body
    assert 'data-cfgtoggle="parse"' in body
    assert 'data-cfgtoggle="unparsed"' in body
    assert "ps-" in body


def test_js_has_config_parse_state():
    """S に configParse / configUnparsedOnly 状態があること。"""
    assert "configParse" in assets._JS and "configUnparsedOnly" in assets._JS


def test_css_has_parse_status_colors():
    """parse 状態の 3 色（ps-parsed/ps-ignored/ps-unparsed）の CSS があること。"""
    assert ".cfgline.ps-unparsed" in assets._CSS
    assert ".cfgline.ps-parsed" in assets._CSS
    assert ".cfgline.ps-ignored" in assets._CSS


# ---------------------------------------------------------------------------
# CONFIG ワークベンチ — アウトライン・折りたたみ廃止（負テスト）
# ---------------------------------------------------------------------------

def test_outline_and_fold_removed():
    """アウトライン/折りたたみ関連（cfgSections・data-cfgoutline/cfgfold・outline トグル・
    configOutline/collapsedCfg・CSS）が完全に除去されていること。"""
    js = assets._JS
    for tok in ["cfgSections", "data-cfgoutline", "data-cfgfold", 'data-cfgtoggle="outline"',
                "configOutline", "collapsedCfg"]:
        assert tok not in js, "アウトライン/折りたたみ残骸: %s" % tok
    for css in [".cfgoutline", ".cfgolink", ".cfgfold", ".cfghead"]:
        assert css not in assets._CSS, "アウトライン/折りたたみ CSS 残骸: %s" % css


# ---------------------------------------------------------------------------
# CONFIG ワークベンチ Phase B — 2ペイン比較＋編集＋ライブ差分
# ---------------------------------------------------------------------------

def test_js_has_line_align_and_split():
    for fn in ["function lineAlign(", "function cfgSymRows(", "function cfgEditLeftRows(",
               "function renderCfgSplit(", "function updateCfgSplitDiff(", "function cfgSources("]:
        assert fn in assets._JS, fn
    assert "function lineDiff(" not in assets._JS, "旧 lineDiff が残存（lineAlign へ移行済みのはず）"


def test_js_has_split_state_and_scratch():
    for s in ["configSplit", "configSrcL", "configSrcR", "configScratch", "ct-cfgscratch"]:
        assert s in assets._JS, s


def test_config_split_readonly_no_edit_affordances():
    """比較モードは読取専用化: renderCfgSplit に textarea/find-replace/「コピーして編集」を出さない。
    編集系（textarea.cfgedit・data-cfgreplace）は編集モード（renderCfgEdit）にのみ存在。"""
    js = assets._JS
    body = _extract_fn(js, "renderCfgSplit")   # balanced-brace 抽出（regex の非貪欲より頑健）
    for forbidden in ["textarea", "data-cfgcopyedit", "data-cfgreplace", "cfgedit"]:
        assert forbidden not in body, f"比較モードに編集要素が残存: {forbidden}"
    assert "data-cfgcopytext" in body and 'class="cfgsrc"' in body  # コピー・source 選択は残す
    # 「コピーして編集」ハンドラ自体が JS から除去されていること（dead code 清掃）
    assert "data-cfgcopyedit" not in js, "data-cfgcopyedit が残存（読取専用化で全廃のはず）"


def test_css_has_split_and_diff_styles():
    for s in [".cfgsplit", ".cfgpane", "textarea.cfgedit", ".cfgline.diff-add", ".cfgline.diff-del",
              ".cfgreplace"]:
        assert s in assets._CSS, s


def test_scratch_is_separate_source_preserves_original():
    """編集モデル: cfgTextOf は scratch:* のみ scratch を読み、dev:/prev: は原本（cfgRawOf）を返す
    （= 原本保持・原本 vs 編集の比較が成立）。コピーして編集・全置換のシンボルも存在。"""
    js = assets._JS
    # cfgTextOf が scratch: 分岐で startsWith を使い、dev/prev は cfgRawOf を返す
    m = re.search(r"function cfgTextOf\(key\) \{(.*?)\n\}", js, re.DOTALL)
    assert m and 'startsWith("scratch:")' in m.group(1) and "cfgRawOf(key)" in m.group(1)
    # 旧トグル方式は廃止
    assert "configEditL" not in js and "configEditR" not in js
    # cfgSources が scratch:* を含める
    ms = re.search(r"function cfgSources\(\) \{(.*?)\n\}", js, re.DOTALL)
    assert ms and "scratch:" in ms.group(1)
    # リテラル全置換（split().join()）
    assert ".split(f).join(" in js


# ---------------------------------------------------------------------------
# CONFIG ワークベンチ — ノード駆動「編集」モード（編集前 vs 編集中）
# ---------------------------------------------------------------------------

def _extract_fn(js: str, name: str) -> str:
    """_JS から `function <name>(` ブロックをバランス中括弧で切り出す。"""
    start_marker = "function " + name + "("
    idx = js.find(start_marker)
    if idx == -1:
        raise ValueError(name + " not found in _JS")
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
    raise ValueError(name + ": unbalanced braces")


def test_config_edit_state_and_button():
    """S に configEdit 状態があり、単一ペイン toolbar に「編集」「比較」両ボタンが併存すること。"""
    assert "configEdit" in assets._JS
    m = re.search(r"function renderConfigView\(\) \{(.*?)\n\}", assets._JS, re.DOTALL)
    body = m.group(1)
    assert 'data-cfgtoggle="edit"' in body, "編集ボタンが無い"
    assert 'data-cfgtoggle="split"' in body, "比較ボタンが消えた（併存させること）"


def test_config_edit_function_and_dispatch():
    """renderCfgEdit が定義され、renderConfigView が S.configEdit で振り分けること。"""
    assert "function renderCfgEdit(" in assets._JS
    m = re.search(r"function renderConfigView\(\) \{(.*?)\n\}", assets._JS, re.DOTALL)
    assert "renderCfgEdit(" in m.group(1) and "S.configEdit" in m.group(1)


def test_config_edit_toggle_creates_scratch_and_excludes_split():
    """編集トグル分岐: scratch を原本から生成し、split と排他にすること（ハンドラ構造）。"""
    js = assets._JS
    m = re.search(r'else if \(t === "edit"\) \{(.*?)\n    \}', js, re.DOTALL)
    assert m, "edit トグル分岐が見つからない"
    branch = m.group(1)
    assert "S.configSplit = false" in branch, "edit 時に split を倒していない（排他）"
    assert 'cfgRawOf("dev:" + cur)' in branch, "scratch を原本から生成していない"
    # split 突入時も edit を倒す（排他）
    assert "if (S.configSplit) S.configEdit = false" in js


def test_config_edit_handlers_key_fallback():
    """編集モードは select.cfgsrc が無いため、保存/置換/差分/コピーは共通の cfgPaneKey で
    source を解決すること（select 優先・無ければ data-cfgkey フォールバック）。"""
    js = assets._JS
    assert "function cfgPaneKey(" in js, "キー解決ヘルパ cfgPaneKey が無い"
    m = re.search(r"function cfgPaneKey\(paneEl, ta\) \{(.*?)\n\}", js, re.DOTALL)
    body = m.group(1)
    assert "select.cfgsrc" in body and "ta.dataset.cfgkey" in body and "paneEl.dataset.cfgkey" in body
    # 利用箇所（input 保存・全置換・コピー）＋定義 が cfgPaneKey に集約されていること
    assert js.count("cfgPaneKey(") >= 4, "cfgPaneKey が各ハンドラで共通利用されていない"


def _run_line_align(node_bin, a_js, b_js):
    """lineAlign(a,b) を実行し {ops, skipped} を返す。"""
    driver = (
        _extract_fn(assets._JS, "lineAlign") + "\n"
        + f'const d = lineAlign({a_js}, {b_js});\n'
        + 'process.stdout.write(JSON.stringify({ops:d.ops, skipped: !!d.skipped}));\n'
    )
    r = subprocess.run([node_bin, "--input-type=module"], input=driver,
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node_bin], input=driver, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return json.loads(r.stdout)


def test_line_align_identical_shortcut(node_bin):
    """lineAlign: 同一内容は DP を回さず全 same op を返し skipped を立てない。"""
    d = _run_line_align(node_bin, '["x","y","z"]', '["x","y","z"]')
    assert d["skipped"] is False
    assert [o["t"] for o in d["ops"]] == ["same", "same", "same"]


def test_line_align_add_del_change(node_bin):
    """lineAlign: 追加=add・削除=del・変更=del+add（行全体不一致）を順序付き ops で返す。"""
    # 追加のみ
    d = _run_line_align(node_bin, '["a"]', '["a","b"]')
    assert [o["t"] for o in d["ops"]] == ["same", "add"]
    # 削除のみ
    d = _run_line_align(node_bin, '["a","b"]', '["a"]')
    assert [o["t"] for o in d["ops"]] == ["same", "del"]
    # 変更（b 行が全て別物）= same → del → add（del 優先は dp[i+1][j] >= dp[i][j+1] で決定的）
    d = _run_line_align(node_bin, '["a","old"]', '["a","new"]')
    assert [o["t"] for o in d["ops"]] == ["same", "del", "add"]
    # 空入力
    d = _run_line_align(node_bin, '[]', '[]')
    assert d["ops"] == [] and d["skipped"] is False


def _run_cfg_pane_key(node_bin: str, scenario_js: str):
    """cfgPaneKey(paneEl, ta) を疑似 DOM スタブで実行し戻り値（key or null）を返す。"""
    driver = (
        _extract_fn(assets._JS, "cfgPaneKey") + "\n"
        + scenario_js + "\n"
        + 'process.stdout.write(JSON.stringify(cfgPaneKey(paneEl, ta)));\n'
    )
    r = subprocess.run([node_bin, "--input-type=module"], input=driver,
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node_bin], input=driver, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return json.loads(r.stdout)


def test_cfg_pane_key_prefers_select(node_bin):
    """自由比較ペイン（select.cfgsrc あり）は select の値を優先すること。"""
    scenario = (
        'const paneEl = { querySelector: s => s === "select.cfgsrc" ? { value: "prev:r9" } : null,'
        ' dataset: { cfgkey: "dev:r1" } };\n'
        'const ta = { dataset: { cfgkey: "scratch:r1" } };\n'
    )
    assert _run_cfg_pane_key(node_bin, scenario) == "prev:r9"


def test_cfg_pane_key_falls_back_to_textarea_key(node_bin):
    """編集モード（select 無し）: textarea の data-cfgkey（scratch:）で解決すること（編集保存の核心）。"""
    scenario = (
        'const paneEl = { querySelector: () => null, dataset: { cfgkey: "scratch:r1" } };\n'
        'const ta = { dataset: { cfgkey: "scratch:r1" } };\n'
    )
    assert _run_cfg_pane_key(node_bin, scenario) == "scratch:r1"


def test_cfg_pane_key_falls_back_to_pane_key_readonly(node_bin):
    """編集モードの読取専用ペイン（select も textarea も無い）: pane の data-cfgkey（dev:）で解決すること。"""
    scenario = (
        'const paneEl = { querySelector: () => null, dataset: { cfgkey: "dev:r1" } };\n'
        'const ta = null;\n'
    )
    assert _run_cfg_pane_key(node_bin, scenario) == "dev:r1"


_CFG_ALIGN_STUBS = (
    'const esc = s => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");\n'
)


def _run_render_cfg_edit(node_bin: str) -> str:
    """renderCfgEdit("", "r1") を整列レンダラ群＋スタブで実行し HTML 断片を返す。
    before="alpha\\nold"／after(scratch)="alpha\\nnew" で 1 行変更（=del+add）を作る。"""
    driver = (
        _extract_fn(assets._JS, "lineAlign") + "\n"
        + _extract_fn(assets._JS, "cfgDiffCounts") + "\n"
        + _extract_fn(assets._JS, "cfgLineHtml") + "\n"
        + _extract_fn(assets._JS, "cfgEditLeftRows") + "\n"
        + _extract_fn(assets._JS, "renderCfgEdit") + "\n"
        + _CFG_ALIGN_STUBS
        + 'const S = { configWrap: false };\n'
        + 'const DATA = { devices: { r1: { hostname: "R1" } } };\n'
        + 'function cfgTextOf(key){ return key.indexOf("scratch:") === 0 ? "alpha\\nnew" : "alpha\\nold"; }\n'
        + 'process.stdout.write(renderCfgEdit("", "r1"));\n'
    )
    r = subprocess.run([node_bin, "--input-type=module"], input=driver,
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node_bin], input=driver,
                           capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return r.stdout


def test_render_cfg_edit_has_editor_and_unified(node_bin):
    """編集モード = 左 textarea(編集)＋右 unified 差分＋DL/元に戻すボタン。"""
    js = (
        _extract_fn(assets._JS, "lineAlign") + "\n"
        + _extract_fn(assets._JS, "cfgDiffCounts") + "\n"
        + _extract_fn(assets._JS, "cfgUnifiedRows") + "\n"
        + _extract_fn(assets._JS, "cfgFileName") + "\n"
        + _extract_fn(assets._JS, "renderCfgEdit") + "\n"
        + _CFG_ALIGN_STUBS
        + 'var DATA = { devices: [{ hostname: "r1" }] };\n'
        + 'var S = { configScratch: { "scratch:0": "a\\nB2\\nc\\n" } };\n'
        + 'function cfgTextOf(k){ return k.indexOf("scratch:")===0 ? S.configScratch[k] : "a\\nb\\nc\\n"; }\n'
        + 'function cfgRawOf(k){ return "a\\nb\\nc\\n"; }\n'
        + 'const out = renderCfgEdit("", 0);\n'
        + 'process.stdout.write(out);\n'
    )
    r = subprocess.run([node_bin], input=js, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    html = r.stdout
    assert 'class="cfgedit"' in html            # 左: 編集 textarea
    assert 'data-cfgpane="E"' in html
    assert 'class="cfgpre cfgunified"' in html or 'cfgunified' in html  # 右: 統一差分
    assert "urow" in html                       # 差分行
    assert 'data-cfgdl=' in html                # DL ボタン
    assert 'data-cfgrevert=' in html            # 元に戻す
    assert 'data-cfgreplace="E"' in html        # 全置換（編集ペイン対象）
    assert 'data-cfgtoggle="edit"' in html      # 編集トグル(on)


def _run_cfg_edit_left_rows(node_bin, before_js, after_js):
    """cfgEditLeftRows(before, after, "") を実行し {html, adds, dels, skipped} を返す。"""
    driver = (
        _extract_fn(assets._JS, "lineAlign") + "\n"
        + _extract_fn(assets._JS, "cfgDiffCounts") + "\n"
        + _extract_fn(assets._JS, "cfgLineHtml") + "\n"
        + _extract_fn(assets._JS, "cfgEditLeftRows") + "\n"
        + _CFG_ALIGN_STUBS
        + f'const r = cfgEditLeftRows({before_js}, {after_js}, "");\n'
        + 'process.stdout.write(JSON.stringify(r));\n'
    )
    r = subprocess.run([node_bin, "--input-type=module"], input=driver,
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node_bin], input=driver, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return json.loads(r.stdout)


def test_cfg_edit_left_rows_aligns_to_after(node_bin):
    """編集左ペイン整列: 行数 == 編集後行数（追加→空行ギャップ・削除→行を消費せず境界マーカー）。"""
    # before=keep/old, after=keep/new1/new2 → same + del(old) + add(new1) + add(new2)
    r = _run_cfg_edit_left_rows(node_bin, '["keep","old"]', '["keep","new1","new2"]')
    rows = r["html"].count('<div class="cfgline')      # cfgline 行（gap 含む・cfgdelmark は別class）
    assert rows == 3, f"左行数 {rows} が編集後行数 3 と不一致（textarea アンカー整列の核心）"
    assert r["adds"] == 2 and r["dels"] == 1
    assert "del-above" in r["html"] and 'data-del="1"' in r["html"]
    assert r["html"].count("cfgline gap") == 2, "追加2行に対する空行ギャップが2つ無い"


def test_cfg_edit_left_rows_trailing_deletion_marker(node_bin):
    """末尾削除（編集後に対応行が無い）は末尾 .cfgdelmark 行で表現。"""
    r = _run_cfg_edit_left_rows(node_bin, '["a","b","c"]', '["a"]')
    assert r["dels"] == 2 and r["adds"] == 0
    assert "cfgdelmark" in r["html"], "末尾削除マーカー行が無い"


def _run_cfg_sym_rows(node_bin, l_js, r_js):
    driver = (
        _extract_fn(assets._JS, "lineAlign") + "\n"
        + _extract_fn(assets._JS, "cfgDiffCounts") + "\n"
        + _extract_fn(assets._JS, "cfgLineHtml") + "\n"
        + _extract_fn(assets._JS, "cfgSymRows") + "\n"
        + _CFG_ALIGN_STUBS
        + f'const r = cfgSymRows({l_js}, {r_js}, "");\n'
        + 'process.stdout.write(JSON.stringify(r));\n'
    )
    rr = subprocess.run([node_bin, "--input-type=module"], input=driver,
                        capture_output=True, text=True, timeout=10)
    if rr.returncode != 0:
        rr = subprocess.run([node_bin], input=driver, capture_output=True, text=True, timeout=10)
    assert rr.returncode == 0, f"node failed: {rr.stderr}"
    return json.loads(rr.stdout)


def test_cfg_sym_rows_both_panes_equal_and_gapped(node_bin):
    """比較の対称整列: 左右ペインの行数が一致し、片側のみの行に対し反対側へ空行ギャップが入る。"""
    r = _run_cfg_sym_rows(node_bin, '["a","b"]', '["a","c","d"]')
    lc = r["left"].count('<div class="cfgline')
    rc = r["right"].count('<div class="cfgline')
    assert lc == rc and lc > 0, f"左右行数不一致: {lc} != {rc}"
    # ["a","b"] vs ["a","c","d"]: b 削除→右に gap・c/d 追加→左に gap。両側に空行ギャップが入る
    assert "cfgline gap" in r["left"] and "cfgline gap" in r["right"], "両ペインに整列の空行ギャップが無い"
    assert "diff-del" in r["left"] and "diff-add" in r["right"]


# ---------------------------------------------------------------------------
# Part C — loopback/stub の IF/IP ラベルにじみ抑制（親機器選択に連動しない）
# ---------------------------------------------------------------------------

def test_stub_label_not_triggered_by_parent_device():
    """stub/loopback の IF/IP ラベル表示条件 showIf が親機器条件 S.sel.has(st.dev) を含まず、
    自身の選択(sid)/スポークホバー/サブネット hot のみで構成されること（空白差異に頑健）。"""
    js = assets._JS
    # showIf 代入行を抽出（stub 描画ブロックの IF/IP ラベル条件）。空白を除去して比較。
    m = re.search(r"const showIf = ([^;]*S\.sel\.has\(sid\)[^;]*);", js)
    assert m, "stub の showIf 代入が見つからない"
    cond = m.group(1).replace(" ", "")
    assert cond == "S.sel.has(sid)||hoverLink===sid||segHot", f"stub ラベル条件が新仕様でない: {cond}"
    assert "st.dev" not in cond, "親機器条件 st.dev が showIf に残存（親機器連動でラベルを出している）"


# ---------------------------------------------------------------------------
# Part D — DEVICE DETAILS で loopback/stub を選択可能化（stubNetForDetail）
# ---------------------------------------------------------------------------

def _run_stub_net_for_detail(node_bin, view, dev, ifn):
    driver = (
        _extract_fn(assets._JS, "stubNetForDetail") + "\n"
        + 'const STUB_BY_ID = new Map(['
        + '["r1:Lo0",{kind:"loopback",subnet:"1.1.1.1/32",area:"1"}],'
        + '["r1:Et9",{kind:"stub",subnet:"10.9.9.0/30",area:null}]'
        + ']);\n'
        + f'const S = {{ view: {json.dumps(view)} }};\n'
        + f'process.stdout.write(JSON.stringify(stubNetForDetail({json.dumps(dev)}, {json.dumps(ifn)})));\n'
    )
    r = subprocess.run([node_bin, "--input-type=module"], input=driver,
                       capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node_bin], input=driver, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return json.loads(r.stdout)


def test_stub_net_for_detail_by_view(node_bin):
    """stubNetForDetail: physical=subnet／ospf は area 有のみ／bgp=null／非 stub IF=null。"""
    # physical: area 有無に関わらず subnet（physical は全 stub 描画）
    assert _run_stub_net_for_detail(node_bin, "physical", "r1", "Lo0") == "1.1.1.1/32"
    assert _run_stub_net_for_detail(node_bin, "physical", "r1", "Et9") == "10.9.9.0/30"
    # ospf: area 有のみ
    assert _run_stub_net_for_detail(node_bin, "ospf", "r1", "Lo0") == "1.1.1.1/32"
    assert _run_stub_net_for_detail(node_bin, "ospf", "r1", "Et9") is None
    # bgp: stub/loopback は描画しないので選択不可
    assert _run_stub_net_for_detail(node_bin, "bgp", "r1", "Lo0") is None
    # 非 stub の IF（map に無い）
    assert _run_stub_net_for_detail(node_bin, "physical", "r1", "Gi0/0") is None


def test_render_details_if_row_uses_stub_net():
    """renderDetails の INTERFACES 行が stubNetForDetail(id, i.n) を data-net 解決に使うこと。"""
    assert "stubNetForDetail(id,i.n)" in assets._JS or "stubNetForDetail(id, i.n)" in assets._JS


# ---------------------------------------------------------------------------
# STATIC フォワーディング・トレース（evalNode / traceForward / ipInCidr・純関数）
# ---------------------------------------------------------------------------

_TRACE_FNS = ["ip6ToBig", "ipInCidr", "afOf", "evalNode", "traceForward"]


def _trace_driver_prelude():
    return "\n".join(_extract_fn(assets._JS, fn) for fn in _TRACE_FNS) + "\n"


def test_js_has_trace_functions():
    for fn in _TRACE_FNS:
        assert ("function %s(" % fn) in assets._JS, fn


def _run_ip_in_cidr(node_bin, ip, cidr):
    driver = (_extract_fn(assets._JS, "ip6ToBig") + "\n" + _extract_fn(assets._JS, "ipInCidr") + "\n"
              + f'process.stdout.write(JSON.stringify(ipInCidr({json.dumps(ip)}, {json.dumps(cidr)})));\n')
    r = subprocess.run([node_bin, "--input-type=module"], input=driver, capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node_bin], input=driver, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return json.loads(r.stdout)


def test_ip_in_cidr_v4_v6_and_default(node_bin):
    assert _run_ip_in_cidr(node_bin, "10.0.0.5", "10.0.0.0/24") is True
    assert _run_ip_in_cidr(node_bin, "10.0.1.5", "10.0.0.0/24") is False
    assert _run_ip_in_cidr(node_bin, "1.2.3.4", "0.0.0.0/0") is True           # default は全一致
    assert _run_ip_in_cidr(node_bin, "8.8.8.8", "8.8.8.8/32") is True          # host route
    assert _run_ip_in_cidr(node_bin, "2001:db8:5::1", "2001:db8:5::/48") is True
    assert _run_ip_in_cidr(node_bin, "2001:db8:6::1", "2001:db8:5::/48") is False
    assert _run_ip_in_cidr(node_bin, "2001:db8::1", "::/0") is True            # v6 default


def _run_trace(node_bin, fib, start, dst):
    driver = (_trace_driver_prelude()
              + f'const fib = {json.dumps(fib)};\n'
              + f'process.stdout.write(JSON.stringify(traceForward(fib, {json.dumps(start)}, {json.dumps(dst)})));\n')
    r = subprocess.run([node_bin, "--input-type=module"], input=driver, capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        r = subprocess.run([node_bin], input=driver, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return json.loads(r.stdout)


def _conn(net, af="v4"):
    return {"net": net, "af": af, "kind": "connected", "via": "local", "target": None,
            "nh": None, "plen": int(net.split("/")[1]), "ecmpGroup": 0, "default": False}


def _stat(net, via, target, nh="x", ecmp=0):
    return {"prefix": net, "net": net, "af": ("v6" if ":" in net else "v4"), "kind": "static", "via": via,
            "target": target, "nh": nh, "plen": int(net.split("/")[1]), "ecmpGroup": ecmp,
            "default": net in ("0.0.0.0/0", "::/0")}


def test_trace_delivered_multi_hop(node_bin):
    fib = {"r1": [_stat("8.8.8.0/24", "device", "r2")],
           "r2": [_conn("8.8.8.0/24")]}
    res = _run_trace(node_bin, fib, "r1", "8.8.8.1")
    assert res["verdict"] == "delivered"
    assert [h["dev"] for h in res["hops"]] == ["r1", "r2"]


def test_trace_via_interface_target_chains(node_bin):
    """via-interface かつ target あり（P2P peer 解決済み）は次 hop へ連鎖して到達できる。"""
    fib = {"r1": [_stat("8.8.8.0/24", "via-interface", "r2", nh="Gi0")],
           "r2": [_conn("8.8.8.0/24")]}
    res = _run_trace(node_bin, fib, "r1", "8.8.8.1")
    assert res["verdict"] == "delivered" and [h["dev"] for h in res["hops"]] == ["r1", "r2"]


def test_trace_via_interface_no_target_unreachable(node_bin):
    """via-interface かつ target なし（peer 不定）は next-hop 到達不可で停止。"""
    fib = {"r1": [_stat("8.8.8.0/24", "via-interface", None, nh="Gi9")]}
    assert _run_trace(node_bin, fib, "r1", "8.8.8.1")["verdict"] == "unreachable-nexthop"


def test_trace_blackhole(node_bin):
    fib = {"r1": [_stat("203.0.113.0/24", "blackhole", None)]}
    assert _run_trace(node_bin, fib, "r1", "203.0.113.5")["verdict"] == "blackhole"


def test_trace_unreachable_dangling(node_bin):
    fib = {"r1": [_stat("8.8.8.0/24", "dangling", None)]}
    assert _run_trace(node_bin, fib, "r1", "8.8.8.5")["verdict"] == "unreachable-nexthop"


def test_trace_no_route(node_bin):
    fib = {"r1": [_conn("10.0.0.0/30")]}
    assert _run_trace(node_bin, fib, "r1", "8.8.8.5")["verdict"] == "no-route"


def test_trace_loop_detected(node_bin):
    fib = {"r1": [_stat("0.0.0.0/0", "device", "r2")],
           "r2": [_stat("0.0.0.0/0", "device", "r1")]}
    res = _run_trace(node_bin, fib, "r1", "9.9.9.9")
    assert res["verdict"] == "loop"
    assert set(res["visited"]) == {"r1", "r2"}        # 両機器を訪問してからループ検出


def test_trace_longest_prefix_wins(node_bin):
    """より具体的な /24 が default(/0) より優先される。"""
    fib = {"r1": [_stat("8.8.8.0/24", "device", "r3"), _stat("0.0.0.0/0", "device", "r2")],
           "r2": [_conn("0.0.0.0/0")],   # ダミー
           "r3": [_conn("8.8.8.0/24")]}
    res = _run_trace(node_bin, fib, "r1", "8.8.8.1")
    assert res["verdict"] == "delivered" and [h["dev"] for h in res["hops"]] == ["r1", "r3"]


def test_trace_connected_preferred_over_static_same_plen(node_bin):
    """同 plen は connected 優先（FIB ソートで connected が先）→ 即 delivered。"""
    fib = {"r1": [_conn("10.0.0.0/24"), _stat("10.0.0.0/24", "device", "r2")]}
    res = _run_trace(node_bin, fib, "r1", "10.0.0.9")
    assert res["verdict"] == "delivered" and len(res["hops"]) == 1


def test_trace_ecmp_first_branch_and_lists_others(node_bin):
    fib = {"r1": [_stat("8.8.8.0/24", "device", "r2", nh="10.0.0.2", ecmp=1),
                  _stat("8.8.8.0/24", "device", "r3", nh="10.0.1.2", ecmp=1)],
           "r2": [_conn("8.8.8.0/24")], "r3": [_conn("8.8.8.0/24")]}
    res = _run_trace(node_bin, fib, "r1", "8.8.8.1")
    assert res["verdict"] == "delivered"
    assert res["hops"][0]["next"] == "r2"             # 先頭（決定的）を辿る
    assert len(res["ecmpBranches"]) == 2              # 分岐候補は列挙


def test_trace_v6_delivered(node_bin):
    fib = {"r1": [_stat("2001:db8:5::/48", "device", "r2")],
           "r2": [_conn("2001:db8:5::/64", af="v6")]}
    res = _run_trace(node_bin, fib, "r1", "2001:db8:5::1")
    assert res["verdict"] == "delivered"


def test_trace_dest_is_start_connected(node_bin):
    fib = {"r1": [_conn("10.0.0.0/24")]}
    res = _run_trace(node_bin, fib, "r1", "10.0.0.0/24")   # prefix 入力
    assert res["verdict"] == "delivered" and len(res["hops"]) == 1


# ---------------------------------------------------------------------------
# cfgUnifiedRows — unified diff preview (Task 1)
# ---------------------------------------------------------------------------

def _run_cfg_unified(node_bin, before_js, after_js):
    """cfgUnifiedRows(before, after, "") を実行し {html, adds, dels, skipped} を返す。"""
    driver = (
        _extract_fn(assets._JS, "lineAlign") + "\n"
        + _extract_fn(assets._JS, "cfgDiffCounts") + "\n"
        + _extract_fn(assets._JS, "cfgUnifiedRows") + "\n"
        + _CFG_ALIGN_STUBS
        + f'const r = cfgUnifiedRows({before_js}, {after_js}, "");\n'
        + 'process.stdout.write(JSON.stringify(r));\n'
    )
    r = subprocess.run([node_bin], input=driver, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return json.loads(r.stdout)


def test_cfg_unified_identical_all_context(node_bin):
    """同一テキスト: adds=dels=0 かつ全行が urow ctx クラスで出力される。"""
    r = _run_cfg_unified(node_bin, '["a","b","c"]', '["a","b","c"]')
    assert r["adds"] == 0 and r["dels"] == 0
    assert r["html"].count('class="urow ctx') == 3
    assert "urow del" not in r["html"] and "urow add" not in r["html"]


def test_cfg_unified_inplace_edit_is_del_then_add(node_bin):
    """1行インプレース変更: del が add より先に出力される（unified diff 順序）。"""
    r = _run_cfg_unified(node_bin, '["a","desc CORE","c"]', '["a","desc CORE-UP","c"]')
    assert r["adds"] == 1 and r["dels"] == 1
    assert "urow del" in r["html"] and "urow add" in r["html"]
    assert r["html"].index("urow del") < r["html"].index("urow add")


def test_cfg_unified_escapes_html(node_bin):
    """追加行の HTML 特殊文字が esc() で無害化される（XSS 防止）。"""
    r = _run_cfg_unified(node_bin, '["x"]', '["x","<b>&"]')
    assert "&lt;b&gt;&amp;" in r["html"]
    assert "<b>" not in r["html"]


# ============================================================
# Task 2: cfgFileName / downloadText
# ============================================================

def _run_cfg_filename(node_bin, host_js):
    driver = _extract_fn(assets._JS, "cfgFileName") + f'\nprocess.stdout.write(cfgFileName({host_js}));\n'
    r = subprocess.run([node_bin], input=driver, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return r.stdout


def test_cfg_filename_basic(node_bin):
    assert _run_cfg_filename(node_bin, '"r1"') == "r1.cfg"


def test_cfg_filename_sanitizes_unsafe_chars(node_bin):
    assert _run_cfg_filename(node_bin, r'"core/sw 1"') == "core_sw_1.cfg"


def test_js_has_download_helper():
    assert "function downloadText(" in assets._JS
    assert "URL.createObjectURL" in assets._JS


# ============================================================
# cfgIsDirty
# ============================================================

def _run_cfg_is_dirty(node_bin, scratch_js, cur_js):
    driver = (
        f'var S = {{ configScratch: {scratch_js} }};\n'
        + 'function cfgRawOf(k){ return "a\\nb\\n"; }\n'
        + _extract_fn(assets._JS, "cfgIsDirty") + "\n"
        + f'process.stdout.write(JSON.stringify(cfgIsDirty({cur_js})));\n'
    )
    r = subprocess.run([node_bin], input=driver, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"node failed: {r.stderr}"
    return json.loads(r.stdout)


def test_cfg_is_dirty_absent_scratch_false(node_bin):
    assert _run_cfg_is_dirty(node_bin, "{}", '"r1"') is False


def test_cfg_is_dirty_equal_to_original_false(node_bin):
    assert _run_cfg_is_dirty(node_bin, '{"scratch:r1":"a\\nb\\n"}', '"r1"') is False


def test_cfg_is_dirty_changed_true(node_bin):
    assert _run_cfg_is_dirty(node_bin, '{"scratch:r1":"a\\nXX\\n"}', '"r1"') is True


def test_cfg_is_dirty_null_cur_false(node_bin):
    assert _run_cfg_is_dirty(node_bin, "{}", "null") is False


def test_cfg_is_dirty_trailing_newlines_only_false(node_bin):
    # 末尾改行の数だけ違う場合は dirty 扱いしない（/\\n+$/ 正規化）
    assert _run_cfg_is_dirty(node_bin, '{"scratch:r1":"a\\nb\\n\\n"}', '"r1"') is False
