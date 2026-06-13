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
            "dualstack_ifs:0,bgp_sessions:0,ospf_networks:0,static_routes:0}};"
            "const POS={};const VIEWS=['physical','stats','addr','ifs'];\n")
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
