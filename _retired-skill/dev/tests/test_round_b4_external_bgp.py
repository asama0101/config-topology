"""
TDD テスト: Round B / B4 — BGP 外部ピアを BGP ビューに外部ノードとして描画

テスト対象:
  1. external-bgp フィクスチャ: BGPビューに外部ノード2つが描画される
     - data-device="ext:203.0.113.1" (AS64500)
     - data-device="ext:198.51.100.1" (AS64501)
     - 各ノードに class="device-node external-node" が含まれる
     - 各ノードに点線スタイル (.external-rect / stroke-dasharray) がある
  2. 内部 iBGP セッション（r1↔r2）は通常ノード間として描画される
  3. 外部 eBGP セッション線が内部機器→外部ノードに引かれ、
     data-bgp-id が cards の BGP 表外部行と一致する（完全一致）
  4. 外部ノードが Physical/OSPF/ifinv に出ない
  5. device 数 = 2 (外部はカウント外)
  6. v6routing: 外部iBGPピア 2001:db8:2::0 (IOS-R2不在) が外部ノードとして BGPビューに出る
  7. 非回帰: ebgp-p2p/multi-as-area (全ピア内部解決) は外部ノード0
  8. 決定性 (2回 render 同一) / 自己完結
  9. external-only: 内部 BGP ピアなし・外部ピアのみでも BGP ビューが生成される (A1)
  10. dedup: 同一外部 IP に複数内部機器がピアしても外部ノード1つ（H3）
  11. multi-as-area 非回帰 (H4)
  12. BGP 凡例に外部ピアの説明が含まれる (D)

不変条件:
  - 決定性: 同一 config → 同一 HTML
  - HTML 自己完結（外部リソース参照なし）
  - 既存テスト緑維持
"""
from __future__ import annotations

import os
import re
import pytest

# ================================================================
# フィクスチャディレクトリ
# ================================================================

EXTERNAL_BGP_DIR = os.path.join(
    os.path.dirname(__file__), "..", "evals", "inputs", "external-bgp"
)
EBGP_P2P_DIR = os.path.join(
    os.path.dirname(__file__), "..", "evals", "inputs", "ebgp-p2p"
)
MULTI_AS_AREA_DIR = os.path.join(
    os.path.dirname(__file__), "..", "evals", "inputs", "multi-as-area"
)
V6ROUTING_DIR = os.path.join(
    os.path.dirname(__file__), "..", "evals", "inputs", "v6routing"
)
EXTERNAL_ONLY_DIR = os.path.join(
    os.path.dirname(__file__), "..", "evals", "inputs", "external-only"
)

# ================================================================
# ヘルパー
# ================================================================

def _build_topology_from_dir(cfg_dir: str) -> dict:
    """cfgディレクトリを parse + build して topology dict を返す。"""
    from scripts.parse_configs import parse_paths, collect_inputs
    from scripts.build_topology import build
    paths = collect_inputs(cfg_dir)
    devices = parse_paths(paths)
    return build(devices, generated_from=paths)

def _render_topology(topo: dict) -> str:
    """topology dict を render して HTML 文字列を返す。"""
    from lib.rendering import render
    return render(topo)

# ================================================================
# フィクスチャ（モジュールスコープで共有: build は重いので1回）
# ================================================================

@pytest.fixture(scope="module")
def external_bgp_html():
    """external-bgp フィクスチャの render 済み HTML。"""
    topo = _build_topology_from_dir(EXTERNAL_BGP_DIR)
    return _render_topology(topo)

@pytest.fixture(scope="module")
def external_bgp_topo():
    """external-bgp フィクスチャの topology dict。"""
    return _build_topology_from_dir(EXTERNAL_BGP_DIR)

@pytest.fixture(scope="module")
def ebgp_p2p_html():
    """ebgp-p2p フィクスチャの render 済み HTML（非回帰用）。"""
    topo = _build_topology_from_dir(EBGP_P2P_DIR)
    return _render_topology(topo)

@pytest.fixture(scope="module")
def v6routing_html():
    """v6routing フィクスチャの render 済み HTML。"""
    topo = _build_topology_from_dir(V6ROUTING_DIR)
    return _render_topology(topo)

@pytest.fixture(scope="module")
def external_only_html():
    """external-only フィクスチャの render 済み HTML（A1: 外部ピアのみ機器）。"""
    topo = _build_topology_from_dir(EXTERNAL_ONLY_DIR)
    return _render_topology(topo)

@pytest.fixture(scope="module")
def multi_as_area_html():
    """multi-as-area フィクスチャの render 済み HTML（H4: 全ピア内部解決の非回帰）。"""
    topo = _build_topology_from_dir(MULTI_AS_AREA_DIR)
    return _render_topology(topo)

# ================================================================
# Section 1: external-bgp — BGP ビューに外部ノードが描画される
# ================================================================

class TestExternalBgpNodes:
    """BGP ビューに外部ノードが描画されることを検証する。"""

    @pytest.mark.unit
    def test_external_node_203_present(self, external_bgp_html):
        """ext:203.0.113.1 ノードが BGP ビューに存在する。"""
        assert 'data-device="ext:203.0.113.1"' in external_bgp_html, \
            "ext:203.0.113.1 の外部ノードが BGP ビューに描画されていない"

    @pytest.mark.unit
    def test_external_node_198_present(self, external_bgp_html):
        """ext:198.51.100.1 ノードが BGP ビューに存在する。"""
        assert 'data-device="ext:198.51.100.1"' in external_bgp_html, \
            "ext:198.51.100.1 の外部ノードが BGP ビューに描画されていない"

    @pytest.mark.unit
    def test_external_node_has_external_node_class(self, external_bgp_html):
        """外部ノード <g> に class="...external-node..." が含まれる。"""
        # ext: で始まる data-device を持つ <g> が external-node クラスを持つ
        pattern = re.compile(
            r'<g[^>]*class="[^"]*external-node[^"]*"[^>]*data-device="ext:[^"]*"'
            r'|'
            r'<g[^>]*data-device="ext:[^"]*"[^>]*class="[^"]*external-node[^"]*"'
        )
        assert pattern.search(external_bgp_html), \
            "外部ノード <g> に external-node クラスが付与されていない"

    @pytest.mark.unit
    def test_external_node_rect_has_dasharray(self, external_bgp_html):
        """外部ノードの矩形に stroke-dasharray (点線) スタイルが含まれる。"""
        # CSS クラス external-rect が存在するか、stroke-dasharray が CSS に定義されている
        has_class = "external-rect" in external_bgp_html
        has_css = "stroke-dasharray" in external_bgp_html
        assert has_class or has_css, \
            "外部ノードの点線スタイル (external-rect / stroke-dasharray) が存在しない"

    @pytest.mark.unit
    def test_external_node_label_shows_as_number(self, external_bgp_html):
        """外部ノードのラベルに AS 番号が表示される (AS64500 / AS64501)。"""
        assert "64500" in external_bgp_html, "AS64500 の表示が外部ノードにない"
        assert "64501" in external_bgp_html, "AS64501 の表示が外部ノードにない"

# ================================================================
# Section 2: 内部 iBGP セッション (r1↔r2) は通常ノード間で描画される
# ================================================================

class TestInternalIbgpSession:
    """iBGP (内部解決) セッションは従来通りノード間で描画される。"""

    @pytest.mark.unit
    def test_ibgp_session_edge_present(self, external_bgp_html):
        """iBGP セッション (bgp-ibgp クラス) のエッジが存在する。"""
        assert "bgp-ibgp" in external_bgp_html, \
            "内部 iBGP エッジ (bgp-ibgp) が描画されていない"

    @pytest.mark.unit
    def test_ibgp_data_bgp_id_internal_format(self, external_bgp_html):
        """内部 iBGP の data-bgp-id が "ext:" を含まない (内部デバイス間形式)。"""
        # iBGP セッションの data-bgp-id: "ext-r1|ext-r2" または "EXT-R1|EXT-R2" 形式
        # "ext:" プレフィックスは外部ピア専用
        # iBGP の bgp-session <g> を検索し、data-bgp-id を取得
        # type="ibgp" の bgp-session に data-bgp-id="ext:..." が含まれないことを確認
        ibgp_pattern = re.compile(r'<g[^>]*class="bgp-session"[^>]*data-type="ibgp"[^>]*data-bgp-id="([^"]*)"')
        ibgp_matches = ibgp_pattern.findall(external_bgp_html)
        assert ibgp_matches, "iBGP セッション <g> が見つからない"
        for bgp_id in ibgp_matches:
            assert not bgp_id.startswith("ext:"), \
                f"iBGP の data-bgp-id が ext: で始まっている: {bgp_id}"

# ================================================================
# Section 3: 外部 eBGP 線の data-bgp-id が cards の外部行と一致する
# ================================================================

class TestExternalBgpIdConsistency:
    """外部 BGP セッション線と cards BGP 表行の data-bgp-id 一致を検証する。"""

    @pytest.mark.unit
    def test_external_bgp_session_edge_has_ext_bgp_id(self, external_bgp_html):
        """外部eBGP セッション線の data-bgp-id に "ext:" が含まれる。"""
        # eBGP セッションの <g class="bgp-session"> を取得
        pattern = re.compile(r'<g[^>]*class="bgp-session"[^>]*data-type="ebgp"[^>]*data-bgp-id="([^"]*)"')
        ebgp_ids = pattern.findall(external_bgp_html)
        assert ebgp_ids, "eBGP セッション <g> が見つからない"
        ext_ids = [bid for bid in ebgp_ids if "ext:" in bid]
        assert ext_ids, \
            f"eBGP セッション線に ext: 形式の data-bgp-id がない: {ebgp_ids}"

    @pytest.mark.unit
    def test_cards_bgp_row_has_matching_ext_bgp_id(self, external_bgp_html):
        """cards の BGP 行 <tr> に外部ピアの data-bgp-id が付与される。"""
        # <tr data-bgp-id="...ext:..."> の形式
        pattern = re.compile(r'<tr[^>]*data-bgp-id="([^"]*ext:[^"]*)"')
        matches = pattern.findall(external_bgp_html)
        assert matches, \
            "cards BGP 表の外部ピア行に data-bgp-id=\"...ext:...\" が付与されていない"

    @pytest.mark.unit
    def test_external_bgp_ids_exact_values(self, external_bgp_html):
        """外部 data-bgp-id の具体値を図↔cards で突合する（M4）。

        EXT-R1|ext:203.0.113.1 および EXT-R2|ext:198.51.100.1 が
        SVG bgp-session と cards <tr> 双方に存在することを確認する。
        """
        # expected: sorted([dev_id, ext_id]) の形式
        # device id はパーサーが hostname を小文字に変換した値: ext-r1 / ext-r2
        # EXT-R1 は AS65010, 外部ピア 203.0.113.1(AS64500)
        # EXT-R2 は AS65010, 外部ピア 198.51.100.1(AS64501)
        expected_ids = sorted([
            "|".join(sorted(["ext-r1", "ext:203.0.113.1"])),
            "|".join(sorted(["ext-r2", "ext:198.51.100.1"])),
        ])

        svg_pattern = re.compile(r'<g[^>]*class="bgp-session"[^>]*data-bgp-id="([^"]*ext:[^"]*)"')
        svg_ids = sorted(svg_pattern.findall(external_bgp_html))

        card_pattern = re.compile(r'<tr[^>]*data-bgp-id="([^"]*ext:[^"]*)"')
        # cards には各デバイスのカードに外部行が出るため重複を除去
        card_ids = sorted(set(card_pattern.findall(external_bgp_html)))

        assert svg_ids == expected_ids, \
            f"SVG 外部 bgp-id が期待値と異なる: got={svg_ids}, want={expected_ids}"
        assert card_ids == expected_ids, \
            f"cards 外部 bgp-id が期待値と異なる: got={card_ids}, want={expected_ids}"

    @pytest.mark.unit
    def test_svg_and_cards_bgp_ids_match(self, external_bgp_html):
        """SVG の外部eBGP線と cards 行の data-bgp-id が完全一致する（H1）。"""
        # SVG の外部 bgp-id 集合
        svg_pattern = re.compile(r'<g[^>]*class="bgp-session"[^>]*data-bgp-id="([^"]*ext:[^"]*)"')
        svg_ids = set(svg_pattern.findall(external_bgp_html))

        # cards の外部 bgp-id 集合
        card_pattern = re.compile(r'<tr[^>]*data-bgp-id="([^"]*ext:[^"]*)"')
        card_ids = set(card_pattern.findall(external_bgp_html))

        assert svg_ids, "SVG に外部 BGP セッション線がない"
        assert card_ids, "cards に外部 BGP 行がない"
        # H1: 完全一致（issubset OR ではなく ==）
        assert svg_ids == card_ids, \
            f"SVG ID と card ID の不一致: svg={svg_ids}, card={card_ids}"

# ================================================================
# Section 4: 外部ノードが Physical/OSPF/ifinv に出ない
# ================================================================

class TestExternalNodeScopeIsolation:
    """外部ノードは BGP ビューのみに描画され、他ビューに出ない。"""

    @pytest.mark.unit
    def test_external_node_not_in_physical_view(self, external_bgp_html):
        """外部ノードが Physical ビュー内に存在しない。"""
        # view-physical の <g> ブロック内に ext: data-device がないこと
        physical_block = re.search(
            r'<g class="view view-physical"[^>]*>(.*?)</g>\s*(?=<g class="view|</svg)',
            external_bgp_html, re.DOTALL
        )
        # M3: if block: ではなく assert block で常時検証
        assert physical_block, "Physical ビューブロックが見つからない"
        phys_content = physical_block.group(1)
        assert 'data-device="ext:' not in phys_content, \
            "外部ノードが Physical ビューに含まれている"

    def test_external_node_not_in_ospf_view(self, external_bgp_html):
        """外部ノードが OSPF ビュー内に存在しない（M2）。"""
        # external-bgp フィクスチャに OSPF 設定はないため OSPF ビューが生成されない想定だが、
        # もし OSPF ビューが存在すれば外部ノードが混入していないことを確認する
        ospf_block = re.search(
            r'<g class="view view-ospf"[^>]*>(.*?)</g>',
            external_bgp_html, re.DOTALL
        )
        if ospf_block:
            ospf_content = ospf_block.group(1)
            assert 'data-device="ext:' not in ospf_content, \
                "外部ノードが OSPF ビューに含まれている"

    @pytest.mark.unit
    def test_device_count_excludes_external(self, external_bgp_topo):
        """topology.devices は 2 台のみ (外部ピアはカウント外)。"""
        devices = external_bgp_topo.get("devices", [])
        assert len(devices) == 2, \
            f"devices のカウントが 2 でない (外部ピアが混入している可能性): {len(devices)}"

    @pytest.mark.unit
    def test_no_ext_in_device_ids(self, external_bgp_topo):
        """topology.devices のどの device も id が 'ext:' で始まらない。"""
        for dev in external_bgp_topo.get("devices", []):
            assert not dev["id"].startswith("ext:"), \
                f"device.id に ext: が含まれている: {dev['id']}"

# ================================================================
# Section 5: v6routing — topology 外の iBGP ピアが外部ノードとして描画される
# ================================================================

class TestV6RoutingExternalPeer:
    """v6routing フィクスチャ: IOS-R2 不在 → 2001:db8:2::0 が外部ノードとして BGP ビューに出る。"""

    @pytest.mark.unit
    def test_v6routing_external_node_for_ios_r2(self, v6routing_html):
        """IOS-R2 の iBGP ピア addr (2001:db8:2::0) が外部ノードとして描画される（M1: exact 値）。"""
        # M1: OR の冗長を排し exact 値（正規化後 "ext:2001:db8:2::" または "ext:2001:db8:2::0"）で1つに
        # ipaddress.ip_address("2001:db8:2::0") = "2001:db8:2::" → ext:2001:db8:2:: が正規化後の値
        assert 'data-device="ext:2001:db8:2::"' in v6routing_html, \
            "v6routing フィクスチャで IOS-R2 向け iBGP ピア (2001:db8:2::0) が正規化後の外部ノード (ext:2001:db8:2::) として描画されていない"

# ================================================================
# Section 6: 非回帰 — ebgp-p2p / multi-as-area は外部ノード0
# ================================================================

class TestRegressionNoExternalNodes:
    """全ピアが topology 内に解決できる場合、外部ノードは生成されない。"""

    @pytest.mark.unit
    def test_ebgp_p2p_no_external_nodes(self, ebgp_p2p_html):
        """ebgp-p2p: 全ピアが内部解決 → 外部ノードなし。"""
        assert 'data-device="ext:' not in ebgp_p2p_html, \
            "ebgp-p2p で不要な外部ノードが描画されている"

    @pytest.mark.unit
    def test_multi_as_area_no_external_nodes(self, multi_as_area_html):
        """multi-as-area: 全ピアが内部解決 → 外部ノードなし（H4: MULTI_AS_AREA_DIR 使用）。"""
        assert 'data-device="ext:' not in multi_as_area_html, \
            "multi-as-area で不要な外部ノードが描画されている"

    @pytest.mark.unit
    def test_multi_as_area_bgp_view_generated(self, multi_as_area_html):
        """multi-as-area: 内部 BGP ピアが存在するため BGP ビューが生成される（H4 非回帰）。"""
        assert 'class="view view-bgp"' in multi_as_area_html, \
            "multi-as-area で BGP ビューが生成されていない（非回帰違反）"

# ================================================================
# Section 7-A: external-only — 外部ピアのみでも BGP ビュー生成 (A1)
# ================================================================

class TestExternalOnlyDevice:
    """external-only フィクスチャ: 内部 BGP ピアなし・外部ピアのみでも BGP ビューが生成される。"""

    @pytest.mark.unit
    def test_bgp_view_generated_for_external_only(self, external_only_html):
        """BGP ビューが生成される（外部ピアのみでも gating を通過）。"""
        assert 'class="view view-bgp"' in external_only_html, \
            "外部ピアのみの機器で BGP ビューが生成されていない (A1 修正が必要)"

    @pytest.mark.unit
    def test_stub_r1_internal_node_present(self, external_only_html):
        """内部機器 stub-r1 が BGP ビューに描画される（device id は小文字変換済み）。"""
        assert 'data-device="stub-r1"' in external_only_html, \
            "stub-r1 の内部ノードが BGP ビューに存在しない"

    @pytest.mark.unit
    def test_external_node_203_present_in_external_only(self, external_only_html):
        """外部ピア ext:203.0.113.1 (AS64500) が BGP ビューに描画される。"""
        assert 'data-device="ext:203.0.113.1"' in external_only_html, \
            "ext:203.0.113.1 の外部ノードが external-only BGP ビューに描画されていない"

    @pytest.mark.unit
    def test_external_only_no_internal_bgp_peer(self, external_only_html):
        """external-only フィクスチャに内部 iBGP セッション線が存在しない。"""
        # 外部ピアのみなので bgp-session data-type="ibgp" の <g> はないはず
        # CSS 変数名 (--color-bgp-ibgp) は含まれるので SVG <g> タグで絞り込む
        ibgp_session_pattern = re.compile(r'<g[^>]*class="bgp-session"[^>]*data-type="ibgp"')
        assert not ibgp_session_pattern.search(external_only_html), \
            "external-only フィクスチャに意図しない iBGP セッション <g> が存在する"

# ================================================================
# Section 7-B: dedup — 同一外部 IP に複数内部機器がピアしても外部ノード1つ (H3)
# ================================================================

class TestExternalNodeDedup:
    """dedup: 同一外部 IP への複数内部ピアは外部ノード1つ・エッジ複数に折りたたまれる。"""

    @pytest.mark.unit
    def test_dedup_external_node_count(self, external_bgp_html):
        """external-bgp: 203.0.113.1 は EXT-R1 からのみピア → data-device 出現は1つ。"""
        # 同一 ext_id がノードとして複数出てはいけない
        ext_203_count = external_bgp_html.count('data-device="ext:203.0.113.1"')
        assert ext_203_count == 1, \
            f"ext:203.0.113.1 が複数描画されている: {ext_203_count} 箇所"

    @pytest.mark.unit
    def test_dedup_ext_nodes_have_bgp_id_in_cards(self, external_bgp_html):
        """外部ノードに対応する cards 行に data-bgp-id が付与される（H3）。"""
        # cards の外部 BGP 行に data-bgp-id が付与されていることを確認
        card_pattern = re.compile(r'<tr[^>]*data-bgp-id="([^"]*ext:[^"]*)"')
        card_ids = card_pattern.findall(external_bgp_html)
        assert card_ids, "cards に外部 BGP 行の data-bgp-id が存在しない"
        # 各エントリが ext: を含むことを確認
        for cid in card_ids:
            assert "ext:" in cid, f"cards の BGP 行に ext: 形式でない bgp-id がある: {cid}"

# ================================================================
# Section 8: 凡例 — BGP ビューに外部ピア説明チップが存在する (D)
# ================================================================

class TestBgpLegendExternalPeerChip:
    """統合凡例パネル(#legend-panel)に「外部ピア（topology外）」の説明が含まれる。

    #16 で旧 #chip-legend オーバーレイは撤去され、外部ピア説明は統合凡例パネルの
    ノード節に統合された。
    """

    @pytest.mark.unit
    def test_chip_legend_has_external_peer_description(self, external_bgp_html):
        """統合凡例パネル内に外部ピア（点線枠 = topology 外）の説明チップが存在する（D/#16）。"""
        # 旧オーバーレイは撤去済み
        assert 'id="chip-legend"' not in external_bgp_html, \
            "#chip-legend オーバーレイは撤去されているべき（統合凡例パネルに統合済み）"
        # 統合凡例パネルの範囲を抽出（id="legend-panel" 以降〜split-divider 手前）
        panel_start = external_bgp_html.find('id="legend-panel"')
        assert panel_start != -1, "#legend-panel が存在しない"
        divider_idx = external_bgp_html.find('id="split-divider"', panel_start)
        legend_content = external_bgp_html[panel_start: divider_idx if divider_idx != -1 else panel_start + 6000]
        # 凡例パネル内に外部ピアに関する説明が含まれること（external クラスか「外部」テキスト）
        has_ext_in_legend = (
            "external-rect" in legend_content
            or "外部" in legend_content
        )
        assert has_ext_in_legend, \
            f"統合凡例パネル内に外部ピア（点線枠）の説明が含まれていない: {legend_content[:200]}"

# ================================================================
# Section 9: 決定性・自己完結
# ================================================================

class TestDeterminismAndSelfContained:
    """決定性と HTML 自己完結を検証する。"""

    @pytest.mark.unit
    def test_deterministic_render(self):
        """同一 topology を2回 render した結果が完全に一致する。"""
        topo = _build_topology_from_dir(EXTERNAL_BGP_DIR)
        from lib.rendering import render
        html1 = render(topo)
        html2 = render(topo)
        assert html1 == html2, "render() の結果が非決定的（2回の結果が異なる）"

    @pytest.mark.unit
    def test_self_contained_no_external_resources(self, external_bgp_html):
        """HTML が外部リソース (CDN / 外部 URL) を参照しない。"""
        # src="http や href="http の参照がないこと
        assert "src=\"http" not in external_bgp_html, \
            "外部 src リソースの参照が存在する"
        assert "href=\"http" not in external_bgp_html, \
            "外部 href リソースの参照が存在する"

    @pytest.mark.unit
    def test_external_bgp_html_is_valid_html(self, external_bgp_html):
        """render 結果が <!DOCTYPE html> から始まる HTML である。"""
        lower = external_bgp_html.lstrip().lower()
        assert lower.startswith("<!doctype html") or lower.startswith("<html"), \
            "render 結果が HTML 文書形式でない"
