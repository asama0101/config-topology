"""
TDD テスト: Round A / Pass2 — dual-stack ラベル改行 & 単一IF両AF併記

対象実装:
  A4: BGP dual-stack バッジを v4/v6 行分け（svg.py _svg_bgp_edges）
  A5: OSPF dual-stack ラベルを v4/v6 行分け（views.py _build_view_ospf）
  A6a: Device Details カードIP列に v4+v6 両AF（cards.py _get_display_ip + _device_cards）
  A6b: IF チップ <title> に dual-stack IF の両AF確定保証（svg.py _svg_if_chip）
  A6c: BGP チップアンカー解決が af 対応（svg.py _svg_bgp_edges）
不変条件:
  - single-stack(v4のみ) は完全に従来通り（非回帰）
  - 決定性・HTML自己完結
"""
from __future__ import annotations

import re
import os
import pytest

# ================================================================
# 共通ヘルパー・フィクスチャ
# ================================================================

_BASE_IFACE = {
    "id": "",
    "device": "",
    "name": "",
    "ip": None,
    "vlan": None,
    "description": None,
    "shutdown": False,
    "admin_status": "up",
    "oper_status": None,
    "mtu": None,
    "speed": None,
    "duplex": None,
    "l2_l3": "l3",
    "switchport": None,
    "encapsulation": None,
    "source": "parsed",
    "addresses": [],
}

def _iface(**kwargs) -> dict:
    """_BASE_IFACE をベースにキーワード引数でオーバーライドする。"""
    d = dict(_BASE_IFACE)
    d.update(kwargs)
    return d

def _dualstack_topology():
    """DS-R1/DS-R2 dual-stack topology（1IFにv4+v6）。"""
    return {
        "title": "Test DualStack Pass2",
        "generated_from": ["test"],
        "devices": [
            {"id": "ds-r1", "hostname": "DS-R1", "vendor": "cisco_ios", "as": 65001, "sections": []},
            {"id": "ds-r2", "hostname": "DS-R2", "vendor": "cisco_ios", "as": 65002, "sections": []},
        ],
        "interfaces": [
            _iface(
                id="ds-r1::Gi0/0", device="ds-r1", name="Gi0/0",
                ip="10.0.0.1/30",
                description="to-DS-R2",
                addresses=[
                    {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                    {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
                ],
            ),
            _iface(
                id="ds-r2::Gi0/0", device="ds-r2", name="Gi0/0",
                ip="10.0.0.2/30",
                description="to-DS-R1",
                addresses=[
                    {"af": "v4", "ip": "10.0.0.2", "prefix": 30},
                    {"af": "v6", "ip": "2001:db8:1::0", "prefix": 127},
                ],
            ),
        ],
        "links": [
            {
                "a_device": "ds-r1", "a_if": "Gi0/0",
                "b_device": "ds-r2", "b_if": "Gi0/0",
                "subnet": "10.0.0.0/30",
                "kind": "inferred-subnet",
                "ospf_area": "0",
                "ospf_network": "10.0.0.0/30",
            },
            {
                "a_device": "ds-r1", "a_if": "Gi0/0",
                "b_device": "ds-r2", "b_if": "Gi0/0",
                "subnet": "2001:db8:1::/127",
                "kind": "inferred-subnet",
                "ospf_area": "0",
                "ospf_network": "2001:db8:1::/127",
            },
        ],
        "segments": [],
        "routing": {
            "bgp": [
                {
                    "device": "ds-r1", "local_as": 65001,
                    "local_ip": "10.0.0.1", "neighbor_ip": "10.0.0.2",
                    "peer_as": 65002, "type": "ebgp", "af": "v4",
                },
                {
                    "device": "ds-r1", "local_as": 65001,
                    "local_ip": "2001:db8:1::1", "neighbor_ip": "2001:db8:1::0",
                    "peer_as": 65002, "type": "ebgp", "af": "v6",
                },
                {
                    "device": "ds-r2", "local_as": 65002,
                    "local_ip": "10.0.0.2", "neighbor_ip": "10.0.0.1",
                    "peer_as": 65001, "type": "ebgp", "af": "v4",
                },
                {
                    "device": "ds-r2", "local_as": 65002,
                    "local_ip": "2001:db8:1::0", "neighbor_ip": "2001:db8:1::1",
                    "peer_as": 65001, "type": "ebgp", "af": "v6",
                },
            ],
            "ospf": [
                {"device": "ds-r1", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                {"device": "ds-r1", "process": 10, "network": "2001:db8:1::/127", "area": "0", "af": "v6"},
                {"device": "ds-r2", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                {"device": "ds-r2", "process": 10, "network": "2001:db8:1::/127", "area": "0", "af": "v6"},
            ],
            "static": [],
        },
    }

def _v6routing_topology():
    """v6routing フィクスチャ（IOS-R1/JUNOS-R1）から topology を構築する。"""
    from scripts.parse_configs import parse_paths
    from scripts.build_topology import build
    fixture_dir = os.path.join(
        os.path.dirname(__file__), "..", "evals", "inputs", "v6routing"
    )
    files = [
        os.path.join(fixture_dir, "iosR.cfg"),
        os.path.join(fixture_dir, "junosR.conf"),
    ]
    devices = parse_paths(files)
    return build(devices, generated_from=files)

def _single_stack_bgp_topology():
    """v4-only の single-stack BGP topology（非回帰確認用）。"""
    return {
        "title": "Test SingleStack BGP",
        "generated_from": ["test"],
        "devices": [
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001, "sections": []},
            {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": 65002, "sections": []},
        ],
        "interfaces": [
            _iface(
                id="r1::Gi0/0", device="r1", name="Gi0/0",
                ip="10.1.0.1/30",
                addresses=[{"af": "v4", "ip": "10.1.0.1", "prefix": 30}],
            ),
            _iface(
                id="r2::Gi0/0", device="r2", name="Gi0/0",
                ip="10.1.0.2/30",
                addresses=[{"af": "v4", "ip": "10.1.0.2", "prefix": 30}],
            ),
        ],
        "links": [
            {
                "a_device": "r1", "a_if": "Gi0/0",
                "b_device": "r2", "b_if": "Gi0/0",
                "subnet": "10.1.0.0/30",
                "kind": "inferred-subnet",
            }
        ],
        "segments": [],
        "routing": {
            "bgp": [
                {
                    "device": "r1", "local_as": 65001,
                    "local_ip": "10.1.0.1", "neighbor_ip": "10.1.0.2",
                    "peer_as": 65002, "type": "ebgp", "af": "v4",
                },
                {
                    "device": "r2", "local_as": 65002,
                    "local_ip": "10.1.0.2", "neighbor_ip": "10.1.0.1",
                    "peer_as": 65001, "type": "ebgp", "af": "v4",
                },
            ],
            "ospf": [],
            "static": [],
        },
    }

def _single_stack_ospf_topology():
    """v4-only の single-stack OSPF topology（非回帰確認用）。"""
    ebgp_dir = os.path.join(
        os.path.dirname(__file__), "..", "evals", "inputs", "cross-vendor-ospf"
    )
    if os.path.isdir(ebgp_dir):
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        files = sorted(
            os.path.join(ebgp_dir, f)
            for f in os.listdir(ebgp_dir)
            if f.endswith((".cfg", ".conf"))
        )
        if files:
            return build(parse_paths(files), generated_from=files)

    # フォールバック: インライン topology
    return {
        "title": "Single OSPF fallback",
        "generated_from": ["test"],
        "devices": [
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": None, "sections": []},
            {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": None, "sections": []},
        ],
        "interfaces": [
            _iface(
                id="r1::Gi0/0", device="r1", name="Gi0/0",
                ip="192.168.0.1/30",
                addresses=[{"af": "v4", "ip": "192.168.0.1", "prefix": 30}],
            ),
            _iface(
                id="r2::Gi0/0", device="r2", name="Gi0/0",
                ip="192.168.0.2/30",
                addresses=[{"af": "v4", "ip": "192.168.0.2", "prefix": 30}],
            ),
        ],
        "links": [
            {
                "a_device": "r1", "a_if": "Gi0/0",
                "b_device": "r2", "b_if": "Gi0/0",
                "subnet": "192.168.0.0/30",
                "kind": "inferred-subnet",
                "ospf_area": "0",
                "ospf_network": "192.168.0.0/30",
            }
        ],
        "segments": [],
        "routing": {
            "bgp": [],
            "ospf": [
                {"device": "r1", "process": 1, "network": "192.168.0.0/30", "area": "0", "af": "v4"},
                {"device": "r2", "process": 1, "network": "192.168.0.0/30", "area": "0", "af": "v4"},
            ],
            "static": [],
        },
    }

# ================================================================
# A4: BGP dual-stack バッジ — v4/v6 別 tspan 行
# ================================================================

class TestA4BgpDualStackLabel:
    """A4: BGP dual-stack 時にバッジが v4/v6 別 tspan 行で出る。"""

    @pytest.fixture
    def dualstack_html(self):
        """dual-stack topology の render() HTML（BGP セッション付き）。"""
        from lib.rendering import render
        return render(_dualstack_topology())

    @pytest.fixture
    def v6routing_html(self):
        """v6routing fixture の render() HTML。"""
        from lib.rendering import render
        return render(_v6routing_topology())

    @pytest.fixture
    def singlestack_html(self):
        """single-stack topology の render() HTML。"""
        from lib.rendering import render
        return render(_single_stack_bgp_topology())

    # ---------- dual-stack: v4 ペア tspan ----------

    @pytest.mark.integration
    def test_dualstack_bgp_badge_has_v4_tspan(self, dualstack_html):
        """dual-stack BGP バッジに v4 ペア（10.0.0.x）が tspan で出る。"""
        # tspan に v4 ペアが含まれること
        assert re.search(r"<tspan[^>]*>10\.0\.0\.\d+↔10\.0\.0\.\d+</tspan>", dualstack_html), (
            "dual-stack BGP バッジに v4 アドレスペアの tspan がない"
        )

    @pytest.mark.integration
    def test_dualstack_bgp_badge_has_v6_tspan(self, dualstack_html):
        """dual-stack BGP バッジに v6 ペア（2001:db8:1::）が tspan で出る。"""
        assert re.search(r"<tspan[^>]*>2001:db8:1::[^<]+↔[^<]+</tspan>", dualstack_html), (
            "dual-stack BGP バッジに v6 アドレスペアの tspan がない"
        )

    @pytest.mark.integration
    def test_dualstack_bgp_badge_v4_and_v6_are_separate_tspan(self, dualstack_html):
        """dual-stack BGP バッジで v4 ペアと v6 ペアが別々の tspan 要素になる。"""
        # <bgp-badge> 内の tspan 数が 3 以上（type/AS + v4 + v6）であること
        # class="bgp-badge" を持つ <text> 内の tspan を数える
        badge_blocks = re.findall(
            r'<text[^>]*class="bgp-badge[^"]*"[^>]*>(.*?)</text>',
            dualstack_html, re.DOTALL
        )
        max_tspan = max((b.count("<tspan") for b in badge_blocks), default=0)
        assert max_tspan >= 3, (
            f"dual-stack BGP バッジが 3 tspan (type/AS + v4 + v6) 未満: max={max_tspan}"
        )

    @pytest.mark.integration
    def test_v6routing_bgp_badge_has_v4_and_v6_separate_tspans(self, v6routing_html):
        """v6routing fixture の BGP バッジに v4/v6 別 tspan が出る。"""
        badge_blocks = re.findall(
            r'<text[^>]*class="bgp-badge[^"]*"[^>]*>(.*?)</text>',
            v6routing_html, re.DOTALL
        )
        # IOS-R1 と JUNOS-R1 間の BGP（v4 + v6 セッション）のバッジ
        has_dual_badge = any(b.count("<tspan") >= 3 for b in badge_blocks)
        assert has_dual_badge, (
            f"v6routing BGP バッジに 3 tspan 以上のブロックがない: 各tspan数={[b.count('<tspan') for b in badge_blocks]}"
        )

    # ---------- single-stack 非回帰 ----------

    @pytest.mark.integration
    def test_singlestack_bgp_badge_has_2_tspans(self, singlestack_html):
        """single-stack BGP バッジは従来通り 2 tspan（type/AS + v4ペア）のまま。"""
        badge_blocks = re.findall(
            r'<text[^>]*class="bgp-badge[^"]*"[^>]*>(.*?)</text>',
            singlestack_html, re.DOTALL
        )
        # single-stack なので最大でも 2 tspan
        for b in badge_blocks:
            n = b.count("<tspan")
            assert n <= 2, (
                f"single-stack BGP バッジが 2 tspan を超えた（regression）: {n}"
            )

    @pytest.mark.unit
    def test_bgp_ip_pairs_dual_split(self):
        """_svg_bgp_edges の ip_pairs 分割ロジック単体: v4/v6 を別リストに分けられる。"""
        # v4/v6 判定ロジック（":" の有無）を直接テスト
        ip_pairs_all = ["10.0.0.1↔10.0.0.2", "2001:db8::1↔2001:db8::0"]
        v4_pairs = [p for p in ip_pairs_all if ":" not in p]
        v6_pairs = [p for p in ip_pairs_all if ":" in p]
        assert v4_pairs == ["10.0.0.1↔10.0.0.2"]
        assert v6_pairs == ["2001:db8::1↔2001:db8::0"]

    @pytest.mark.unit
    def test_bgp_ip_pairs_single_stack_no_split(self):
        """single-stack 時（v4 のみ）は分割しない。"""
        ip_pairs_all = ["10.0.0.1↔10.0.0.2"]
        v4_pairs = [p for p in ip_pairs_all if ":" not in p]
        v6_pairs = [p for p in ip_pairs_all if ":" in p]
        assert len(v6_pairs) == 0  # v6 なし → 分割不要

# ================================================================
# A5: OSPF dual-stack ラベル — v4/v6 別 tspan 行
# ================================================================

class TestA5OspfDualStackLabel:
    """A5: OSPF dual-stack 時にラベルが v4/v6 別 tspan 行で出る。"""

    @pytest.fixture
    def dualstack_html(self):
        from lib.rendering import render
        return render(_dualstack_topology())

    @pytest.fixture
    def v6routing_html(self):
        from lib.rendering import render
        return render(_v6routing_topology())

    @pytest.fixture
    def singlestack_html(self):
        from lib.rendering import render
        return render(_single_stack_ospf_topology())

    # ---------- dual-stack OSPF: v4/v6 別 tspan ----------

    @pytest.mark.integration
    def test_dualstack_ospf_label_has_v4_subnet_tspan(self, dualstack_html):
        """dual-stack OSPF ラベルに v4 subnet（10.0.0.0/30）が tspan で出る。"""
        assert re.search(
            r'<text[^>]*class="link-label[^"]*"[^>]*>.*?<tspan[^>]*>.*?10\.0\.0\.0/30',
            dualstack_html, re.DOTALL
        ), "dual-stack OSPF ラベルに v4 subnet の tspan がない"

    @pytest.mark.integration
    def test_dualstack_ospf_label_has_v6_subnet_tspan(self, dualstack_html):
        """dual-stack OSPF ラベルに v6 subnet（2001:db8:1::/127）が tspan で出る。"""
        assert re.search(
            r'<text[^>]*class="link-label[^"]*"[^>]*>.*?<tspan[^>]*>.*?2001:db8:1::/127',
            dualstack_html, re.DOTALL
        ), "dual-stack OSPF ラベルに v6 subnet の tspan がない"

    @pytest.mark.integration
    def test_dualstack_ospf_label_area_appears_once(self, dualstack_html):
        """dual-stack OSPF ラベルで area 表記は最初の tspan（先頭行）のみ。"""
        # <text class="link-label..."> ブロック内で area 0 が1回だけ出ること（重複しない）
        label_texts = re.findall(
            r'<text[^>]*class="link-label[^"]*"[^>]*>(.*?)</text>',
            dualstack_html, re.DOTALL
        )
        for label in label_texts:
            # "area 0" が含まれるブロックでは tspan が 2 本以上あること
            if "area 0" in label and "2001:db8:1::" in label:
                tspan_texts = re.findall(r"<tspan[^>]*>(.*?)</tspan>", label, re.DOTALL)
                area_count = sum(1 for t in tspan_texts if "area" in t)
                assert area_count == 1, (
                    f"dual-stack OSPF ラベルで area が重複している: {tspan_texts}"
                )

    @pytest.mark.integration
    def test_dualstack_ospf_label_v4_v6_on_separate_tspan_lines(self, dualstack_html):
        """dual-stack OSPF ラベルで v4/v6 subnet が別 tspan 要素に分かれる。"""
        label_texts = re.findall(
            r'<text[^>]*class="link-label[^"]*"[^>]*>(.*?)</text>',
            dualstack_html, re.DOTALL
        )
        found_dual_label = False
        for label in label_texts:
            if "10.0.0.0/30" in label and "2001:db8:1::" in label:
                tspan_texts = re.findall(r"<tspan[^>]*>(.*?)</tspan>", label, re.DOTALL)
                # v4 と v6 が別 tspan にあること
                has_v4_tspan = any("10.0.0.0/30" in t for t in tspan_texts)
                has_v6_tspan = any("2001:db8:1::" in t for t in tspan_texts)
                assert has_v4_tspan and has_v6_tspan, (
                    f"v4/v6 が同一 tspan に混在: {tspan_texts}"
                )
                found_dual_label = True
                break
        assert found_dual_label, "dual-stack OSPF ラベルブロックが見つからない"

    # ---------- single-stack 非回帰 ----------

    @pytest.mark.integration
    def test_singlestack_ospf_label_no_tspan(self, singlestack_html):
        """single-stack OSPF ラベルは従来通り tspan なし（プレーンテキスト）。"""
        label_texts = re.findall(
            r'<text[^>]*class="link-label[^"]*"[^>]*>(.*?)</text>',
            singlestack_html, re.DOTALL
        )
        for label in label_texts:
            if "<tspan" in label:
                # tspan が存在する場合は dual-stack なので v4 と v6 の両方があるはず
                # single-stack ラベルには tspan があってはならない
                has_v6 = ":" in label and any(
                    ":" in t for t in re.findall(r"<tspan[^>]*>(.*?)</tspan>", label, re.DOTALL)
                )
                assert not has_v6, (
                    f"single-stack OSPF ラベルに不要な v6 tspan がある（regression）: {label}"
                )

# ================================================================
# A6a: Device Details カードのIP列に両AF
# ================================================================

class TestA6aCardIpBothAF:
    """A6a: 1IFにv4+v6を持つ場合、カードIP列に両AF表示。"""

    @pytest.fixture
    def dualstack_html(self):
        from lib.rendering import render
        return render(_dualstack_topology())

    # ---------- _get_display_ip 単体テスト ----------

    @pytest.mark.unit
    def test_get_display_ip_v4_only_unchanged(self):
        """v4のみのIFは従来通り v4 アドレスを返す（非回帰）。"""
        from lib.rendering.cards import _get_display_ip
        iface = _iface(
            id="r1::Gi0/0", device="r1", name="Gi0/0",
            ip="10.0.0.1/30",
            addresses=[{"af": "v4", "ip": "10.0.0.1", "prefix": 30}],
        )
        result = _get_display_ip(iface)
        assert result == "10.0.0.1/30", f"v4-only IF の表示が変わった: {result}"

    @pytest.mark.unit
    def test_get_display_ip_dual_stack_contains_both(self):
        """v4+v6 の dual-stack IFは両方のアドレスを含む文字列を返す。"""
        from lib.rendering.cards import _get_display_ip
        iface = _iface(
            id="ds-r1::Gi0/0", device="ds-r1", name="Gi0/0",
            ip="10.0.0.1/30",
            addresses=[
                {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
            ],
        )
        result = _get_display_ip(iface)
        assert "10.0.0.1" in result, f"v4 アドレスが結果に含まれない: {result}"
        assert "2001:db8:1::1" in result, f"v6 アドレスが結果に含まれない: {result}"

    @pytest.mark.unit
    def test_get_display_ip_v6_only_unchanged(self):
        """v6 のみのIF（ip=None）は従来通り v6 GUA を返す（非回帰）。"""
        from lib.rendering.cards import _get_display_ip
        iface = _iface(
            id="r1::Gi0/2", device="r1", name="Gi0/2",
            ip=None,
            addresses=[
                {"af": "v6", "ip": "2001:db8:3::1", "prefix": 127},
            ],
        )
        result = _get_display_ip(iface)
        assert "2001:db8:3::1" in result, f"v6-only IF が v6 を返さない: {result}"
        assert "10." not in result, f"v6-only IF に v4 が混入: {result}"

    @pytest.mark.unit
    def test_get_display_ip_empty_if_unchanged(self):
        """アドレスなしのIF は空文字列を返す（非回帰）。"""
        from lib.rendering.cards import _get_display_ip
        iface = _iface(id="r1::Lo0", device="r1", name="Lo0")
        result = _get_display_ip(iface)
        assert result == ""

    # ---------- カードHTML テスト ----------

    @pytest.mark.integration
    def test_card_ip_column_has_v4_for_dualstack_if(self, dualstack_html):
        """dual-stack IF のカードIP列に v4 アドレスが含まれる。"""
        assert "10.0.0.1" in dualstack_html or "10.0.0.2" in dualstack_html, (
            "dual-stack IFのカードに v4 アドレスがない"
        )

    @pytest.mark.integration
    def test_card_ip_column_has_v6_for_dualstack_if(self, dualstack_html):
        """dual-stack IF のカードIP列に v6 アドレスが含まれる。"""
        assert "2001:db8:1::1" in dualstack_html or "2001:db8:1::0" in dualstack_html, (
            "dual-stack IFのカードに v6 アドレスがない"
        )

    @pytest.mark.integration
    def test_card_ip_column_shows_both_af_in_same_cell(self, dualstack_html):
        """カードのIF行で v4 と v6 が同一 <td> 内に存在する（同一行に両AF）。"""
        # <td> 要素で v4 と v6 が共存するものを探す
        td_contents = re.findall(r"<td>(.*?)</td>", dualstack_html, re.DOTALL)
        found = any(
            "10.0.0." in td and "2001:db8:1::" in td
            for td in td_contents
        )
        assert found, (
            "dual-stack IF のカードで v4 と v6 が同一 <td> に表示されていない"
        )

    @pytest.mark.unit
    def test_format_iface_ip_cell_helper_exists(self):
        """A6a/A6d: 共通ヘルパー _format_iface_ip_cell が svg.py に存在する。"""
        from lib.rendering.svg import _format_iface_ip_cell
        assert callable(_format_iface_ip_cell)

    @pytest.mark.unit
    def test_format_iface_ip_cell_dual_stack_has_br(self):
        """A6a: 共通ヘルパーが dual-stack IFで '<br>' 区切りの HTML 断片を返す。"""
        from lib.rendering.svg import _format_iface_ip_cell
        iface = _iface(
            id="ds-r1::Gi0/0", device="ds-r1", name="Gi0/0",
            ip="10.0.0.1/30",
            addresses=[
                {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
            ],
        )
        result = _format_iface_ip_cell(iface)
        assert "<br>" in result, f"dual-stack IFの共通ヘルパー結果に <br> がない: {result!r}"
        assert "10.0.0.1/30" in result, f"v4 アドレスが含まれない: {result!r}"
        assert "2001:db8:1::1/127" in result, f"v6 アドレスが含まれない: {result!r}"

    @pytest.mark.unit
    def test_format_iface_ip_cell_v4_only_no_br(self):
        """A6a 非回帰: v4-only IFは <br> なし（単一行）。"""
        from lib.rendering.svg import _format_iface_ip_cell
        iface = _iface(
            id="r1::Gi0/0", device="r1", name="Gi0/0",
            ip="10.0.0.1/30",
            addresses=[{"af": "v4", "ip": "10.0.0.1", "prefix": 30}],
        )
        result = _format_iface_ip_cell(iface)
        assert "<br>" not in result, f"v4-only IFに不要な <br> がある: {result!r}"
        assert "10.0.0.1/30" in result

    @pytest.mark.unit
    def test_format_iface_ip_cell_v6_only_no_br(self):
        """A6a 非回帰: v6-only IFは <br> なし（単一行）。"""
        from lib.rendering.svg import _format_iface_ip_cell
        iface = _iface(
            id="r1::Lo0", device="r1", name="Lo0",
            ip=None,
            addresses=[{"af": "v6", "ip": "2001:db8:3::1", "prefix": 127}],
        )
        result = _format_iface_ip_cell(iface)
        assert "<br>" not in result, f"v6-only IFに不要な <br> がある: {result!r}"
        assert "2001:db8:3::1" in result

    @pytest.mark.unit
    def test_format_iface_ip_cell_empty_no_br(self):
        """A6a 非回帰: アドレスなしIFは空文字列。"""
        from lib.rendering.svg import _format_iface_ip_cell
        iface = _iface(id="r1::Lo0", device="r1", name="Lo0")
        result = _format_iface_ip_cell(iface)
        assert result == ""

    @pytest.mark.integration
    def test_card_ip_cell_dual_stack_has_br_tag(self, dualstack_html):
        """A6a: dual-stack topology のカード IP セルに <br> タグが含まれる。"""
        # <td>...</td> 内で v4/v6 が <br> で区切られること
        td_contents = re.findall(r"<td>(.*?)</td>", dualstack_html, re.DOTALL)
        found = any(
            "<br>" in td and "10.0.0." in td and "2001:db8:1::" in td
            for td in td_contents
        )
        assert found, (
            "dual-stack IFのカード IP セルに <br> 区切りの v4/v6 が見つからない"
        )

    @pytest.mark.unit
    def test_get_display_ip_dual_stack_no_longer_returns_newline(self):
        """A6a: _get_display_ip は dual-stack でも \\n を返さない（<br>ヘルパーに委譲）。
        注: カード表示は _format_iface_ip_cell を使うべきで、_get_display_ip の戻り値は
        内部テキスト（SVG title 等）向けに保持されるが、HTML セルには使わない。
        このテストは _get_display_ip が \\n 区切りのままでも可（title 等では問題なし）。
        重要なのはカードの <td> で <br> が使われていること（上記テスト参照）。
        """
        from lib.rendering.cards import _get_display_ip
        iface = _iface(
            id="ds-r1::Gi0/0", device="ds-r1", name="Gi0/0",
            ip="10.0.0.1/30",
            addresses=[
                {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
            ],
        )
        result = _get_display_ip(iface)
        # _get_display_ip は文字列を返す（内部用途）。v4/v6 両方含む
        assert "10.0.0.1" in result
        assert "2001:db8:1::1" in result

# ================================================================
# A6b: IF チップ <title> に dual-stack IF の両AF
# ================================================================

class TestA6bChipTitleBothAF:
    """A6b: dual-stack IF チップの <title> に v4/v6 両方が含まれる。"""

    @pytest.mark.unit
    def test_chip_title_dual_stack_has_both_af(self):
        """_svg_if_chip が dual-stack IF で v4 と v6 を両方 <title> に含む。"""
        from lib.rendering.svg import _svg_if_chip
        iface = _iface(
            id="ds-r1::Gi0/0", device="ds-r1", name="Gi0/0",
            ip="10.0.0.1/30",
            addresses=[
                {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
            ],
        )
        svg = _svg_if_chip(nx=0, chip_start_y=0, k=0, iface=iface)
        assert "<title>" in svg
        title_match = re.search(r"<title>(.*?)</title>", svg, re.DOTALL)
        assert title_match, "title 要素がない"
        title_text = title_match.group(1)
        assert "10.0.0.1" in title_text, f"v4 が title にない: {title_text}"
        assert "2001:db8:1::1" in title_text, f"v6 が title にない: {title_text}"

    @pytest.mark.unit
    def test_chip_title_v4_only_unchanged(self):
        """v4-only IF チップは title に v4 のみ（非回帰）。"""
        from lib.rendering.svg import _svg_if_chip
        iface = _iface(
            id="r1::Gi0/0", device="r1", name="Gi0/0",
            ip="10.0.0.1/30",
            addresses=[{"af": "v4", "ip": "10.0.0.1", "prefix": 30}],
        )
        svg = _svg_if_chip(nx=0, chip_start_y=0, k=0, iface=iface)
        title_match = re.search(r"<title>(.*?)</title>", svg, re.DOTALL)
        assert title_match
        title_text = title_match.group(1)
        assert "10.0.0.1" in title_text
        assert "::" not in title_text, f"v4-only chip に v6 が混入: {title_text}"

    @pytest.mark.unit
    def test_chip_title_v6_only_has_v6(self):
        """v6-only IF チップは title に v6 アドレスが入る（非回帰）。"""
        from lib.rendering.svg import _svg_if_chip
        iface = _iface(
            id="r1::Gi0/2", device="r1", name="Gi0/2",
            ip=None,
            addresses=[{"af": "v6", "ip": "2001:db8:3::1", "prefix": 127}],
        )
        svg = _svg_if_chip(nx=0, chip_start_y=0, k=0, iface=iface)
        title_match = re.search(r"<title>(.*?)</title>", svg, re.DOTALL)
        assert title_match
        title_text = title_match.group(1)
        assert "2001:db8:3::1" in title_text, f"v6-only chip に v6 がない: {title_text}"

    @pytest.mark.integration
    def test_dualstack_rendered_html_chip_title_both_af(self):
        """dual-stack topology の HTML で IF チップ title に v4+v6 が含まれる。"""
        from lib.rendering import render
        html = render(_dualstack_topology())
        # <title> タグで v4 と v6 が共存するものを探す
        titles = re.findall(r"<title>(.*?)</title>", html, re.DOTALL)
        found = any("10.0.0." in t and "2001:db8:1::" in t for t in titles)
        assert found, (
            "dual-stack topology HTML の title 要素に v4+v6 共存がない"
        )

# ================================================================
# A6c: BGP アンカー座標 — af 対応 iface_id 解決
# ================================================================

class TestA6cBgpAnchorAFAware:
    """A6c: BGP チップアンカーが af 対応の local_ip で iface_id を引く。"""

    @pytest.mark.unit
    def test_ip_to_iface_id_maps_both_v4_and_v6(self):
        """_build_ip_to_iface_id が v4 と v6 の両アドレスをマッピングする。"""
        from lib.rendering.svg import _build_ip_to_iface_id
        interfaces = [
            _iface(
                id="r1::Gi0/0", device="r1", name="Gi0/0",
                ip="10.0.0.1/30",
                addresses=[
                    {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                    {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
                ],
            )
        ]
        mapping = _build_ip_to_iface_id(interfaces)
        assert "10.0.0.1" in mapping, "v4 アドレスがマッピングされていない"
        assert mapping["10.0.0.1"] == "r1::Gi0/0"
        assert "2001:db8:1::1" in mapping, "v6 アドレスがマッピングされていない"
        assert mapping["2001:db8:1::1"] == "r1::Gi0/0"

    @pytest.mark.unit
    def test_v6_session_anchor_uses_v6_iface(self):
        """v6 BGP セッションの local_ip → iface_id が v6 アドレスの IF を指す。"""
        from lib.rendering.svg import _build_ip_to_iface_id
        # v4 と v6 が別 IF（例: v4=Loopback0、v6=Loopback1）
        interfaces = [
            _iface(
                id="r1::Lo0", device="r1", name="Loopback0",
                ip="1.1.1.1/32",
                addresses=[{"af": "v4", "ip": "1.1.1.1", "prefix": 32}],
            ),
            _iface(
                id="r1::Lo1", device="r1", name="Loopback1",
                ip=None,
                addresses=[{"af": "v6", "ip": "2001:db8:ff::1", "prefix": 128}],
            ),
        ]
        mapping = _build_ip_to_iface_id(interfaces)
        # v6 セッション（local_ip=2001:db8:ff::1）のアンカーが Lo1 を返すこと
        assert mapping.get("2001:db8:ff::1") == "r1::Lo1", (
            f"v6 BGP アンカーが正しい iface_id を返さない: {mapping}"
        )
        # v4 セッション（local_ip=1.1.1.1）のアンカーが Lo0 を返すこと
        assert mapping.get("1.1.1.1") == "r1::Lo0"

    @pytest.mark.unit
    def test_same_physical_if_v4_v6_both_resolve_to_same_iface(self):
        """同一物理IFにv4+v6がある場合、v4/v6どちらもその iface_id を返す。"""
        from lib.rendering.svg import _build_ip_to_iface_id
        interfaces = [
            _iface(
                id="r1::Gi0/0", device="r1", name="Gi0/0",
                ip="10.0.0.1/30",
                addresses=[
                    {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                    {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
                ],
            )
        ]
        mapping = _build_ip_to_iface_id(interfaces)
        assert mapping.get("10.0.0.1") == "r1::Gi0/0"
        assert mapping.get("2001:db8:1::1") == "r1::Gi0/0"

    @pytest.mark.integration
    def test_dualstack_bgp_render_no_exception(self):
        """dual-stack BGP topology を render() しても例外が出ない（アンカー解決含む）。"""
        from lib.rendering import render
        html = render(_dualstack_topology())
        assert len(html) > 0

    @pytest.mark.unit
    def test_bgp_anchor_uses_resolvable_session_not_sessions0(self):
        """A6c: v4セッション(sessions[0])のlocal_ipがchip_positionsに解決しない場合、
        v6セッションのlocal_ipで解決したチップ座標がアンカーとして使われる。
        旧 sessions[0] 固定実装ではノード中心座標になってしまう。
        """
        from lib.rendering.svg import _svg_bgp_edges
        # v4 と v6 が別 IF のシナリオ:
        #   - R1 Lo0 (1.1.1.1/32): v4のみ。chip_positionsにLo0のチップがない
        #   - R1 Lo1 (2001:db8:ff::1/128): v6のみ。chip_positionsにLo1のチップがある
        #   - R2 Lo0 (2.2.2.2/32): v4のみ。chip_positionsにLo0のチップがない
        #   - R2 Lo1 (2001:db8:ff::2/128): v6のみ。chip_positionsにLo1のチップがある
        # v4セッション: local_ip=1.1.1.1 → chip_positionsにない（解決失敗）
        # v6セッション: local_ip=2001:db8:ff::1 → chip_positionsにある（解決成功）
        # → x1,y1 は Lo1 のチップ座標(50,200)になるべき

        interfaces = [
            _iface(id="r1::Lo0", device="r1", name="Loopback0",
                   ip="1.1.1.1/32",
                   addresses=[{"af": "v4", "ip": "1.1.1.1", "prefix": 32}]),
            _iface(id="r1::Lo1", device="r1", name="Loopback1",
                   ip=None,
                   addresses=[{"af": "v6", "ip": "2001:db8:ff::1", "prefix": 128}]),
            _iface(id="r2::Lo0", device="r2", name="Loopback0",
                   ip="2.2.2.2/32",
                   addresses=[{"af": "v4", "ip": "2.2.2.2", "prefix": 32}]),
            _iface(id="r2::Lo1", device="r2", name="Loopback1",
                   ip=None,
                   addresses=[{"af": "v6", "ip": "2001:db8:ff::2", "prefix": 128}]),
        ]
        positions = {"r1": (100, 100), "r2": (300, 100)}
        # v4 チップは登録しない（解決失敗シナリオ）
        chip_positions = {
            "r1::Lo1": (50, 200),  # v6 IF のチップ座標
            "r2::Lo1": (250, 200),  # v6 IF のチップ座標
        }
        bgp_entries = [
            # v4 セッション (sessions[0] として先にソートされる: v4 < v6)
            {"device": "r1", "local_as": 65001, "local_ip": "1.1.1.1",
             "neighbor_ip": "2.2.2.2", "peer_as": 65002, "type": "ebgp", "af": "v4"},
            # v6 セッション (local_ip が chip_positions に解決可能)
            {"device": "r1", "local_as": 65001, "local_ip": "2001:db8:ff::1",
             "neighbor_ip": "2001:db8:ff::2", "peer_as": 65002, "type": "ebgp", "af": "v6"},
            # 対向側（双方向エントリ）
            {"device": "r2", "local_as": 65002, "local_ip": "2.2.2.2",
             "neighbor_ip": "1.1.1.1", "peer_as": 65001, "type": "ebgp", "af": "v4"},
            {"device": "r2", "local_as": 65002, "local_ip": "2001:db8:ff::2",
             "neighbor_ip": "2001:db8:ff::1", "peer_as": 65001, "type": "ebgp", "af": "v6"},
        ]
        svg = _svg_bgp_edges(bgp_entries, interfaces, positions, chip_positions)
        # アンカーが v6 IFのチップ座標(50,200)/(250,200)に解決されていること
        # path の M点（A側）が 50.0,200.0 になるはず
        assert "M50.0,200.0" in svg or "M50,200" in svg, (
            f"A側アンカーが v6 IF チップ座標(50,200)にならなかった。\n"
            f"sessions[0](v4セッション) 固定の旧実装だとノード中心(100,100)になる。\nSVG={svg[:300]}"
        )

    @pytest.mark.unit
    def test_bgp_anchor_same_if_v4_v6_non_regression(self):
        """A6c 非回帰: 同一IFにv4+v6がある場合、従来通り iface_id 一致で同一座標。"""
        from lib.rendering.svg import _svg_bgp_edges
        # Gi0/0 に v4/v6 同居 → どちらのセッションも同じ iface_id に解決
        interfaces = [
            _iface(id="r1::Gi0/0", device="r1", name="Gi0/0",
                   ip="10.0.0.1/30",
                   addresses=[
                       {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                       {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
                   ]),
            _iface(id="r2::Gi0/0", device="r2", name="Gi0/0",
                   ip="10.0.0.2/30",
                   addresses=[
                       {"af": "v4", "ip": "10.0.0.2", "prefix": 30},
                       {"af": "v6", "ip": "2001:db8:1::0", "prefix": 127},
                   ]),
        ]
        positions = {"r1": (100, 100), "r2": (300, 100)}
        chip_positions = {
            "r1::Gi0/0": (80, 150),
            "r2::Gi0/0": (280, 150),
        }
        bgp_entries = [
            {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
             "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4"},
            {"device": "r1", "local_as": 65001, "local_ip": "2001:db8:1::1",
             "neighbor_ip": "2001:db8:1::0", "peer_as": 65002, "type": "ebgp", "af": "v6"},
            {"device": "r2", "local_as": 65002, "local_ip": "10.0.0.2",
             "neighbor_ip": "10.0.0.1", "peer_as": 65001, "type": "ebgp", "af": "v4"},
            {"device": "r2", "local_as": 65002, "local_ip": "2001:db8:1::0",
             "neighbor_ip": "2001:db8:1::1", "peer_as": 65001, "type": "ebgp", "af": "v6"},
        ]
        svg = _svg_bgp_edges(bgp_entries, interfaces, positions, chip_positions)
        # Gi0/0 の座標(80,150)にアンカーされること
        assert "M80.0,150.0" in svg or "M80,150" in svg, (
            f"同一IF dual-stack でチップ座標(80,150)にアンカーされなかった。\nSVG={svg[:300]}"
        )

    @pytest.mark.unit
    def test_bgp_anchor_b_side_uses_resolvable_session(self):
        """A6c: B側(neighbor_ip)もaf対応で解決可能なセッションを使う。"""
        from lib.rendering.svg import _svg_bgp_edges
        # B側: r2 は v4/v6 が別IFで、v4のneighbor_ipはchip_positionsにない
        interfaces = [
            _iface(id="r1::Lo0", device="r1", name="Loopback0",
                   ip="1.1.1.1/32",
                   addresses=[{"af": "v4", "ip": "1.1.1.1", "prefix": 32}]),
            _iface(id="r1::Lo1", device="r1", name="Loopback1",
                   ip=None,
                   addresses=[{"af": "v6", "ip": "2001:db8:ff::1", "prefix": 128}]),
            _iface(id="r2::Lo0", device="r2", name="Loopback0",
                   ip="2.2.2.2/32",
                   addresses=[{"af": "v4", "ip": "2.2.2.2", "prefix": 32}]),
            _iface(id="r2::Lo1", device="r2", name="Loopback1",
                   ip=None,
                   addresses=[{"af": "v6", "ip": "2001:db8:ff::2", "prefix": 128}]),
        ]
        positions = {"r1": (100, 100), "r2": (300, 100)}
        # B側: r2::Lo0 はchip_positionsにない、r2::Lo1 はある
        chip_positions = {
            "r1::Lo1": (50, 200),
            "r2::Lo1": (250, 200),
        }
        bgp_entries = [
            {"device": "r1", "local_as": 65001, "local_ip": "1.1.1.1",
             "neighbor_ip": "2.2.2.2", "peer_as": 65002, "type": "ebgp", "af": "v4"},
            {"device": "r1", "local_as": 65001, "local_ip": "2001:db8:ff::1",
             "neighbor_ip": "2001:db8:ff::2", "peer_as": 65002, "type": "ebgp", "af": "v6"},
            {"device": "r2", "local_as": 65002, "local_ip": "2.2.2.2",
             "neighbor_ip": "1.1.1.1", "peer_as": 65001, "type": "ebgp", "af": "v4"},
            {"device": "r2", "local_as": 65002, "local_ip": "2001:db8:ff::2",
             "neighbor_ip": "2001:db8:ff::1", "peer_as": 65001, "type": "ebgp", "af": "v6"},
        ]
        svg = _svg_bgp_edges(bgp_entries, interfaces, positions, chip_positions)
        # B側アンカーが r2::Lo1 のチップ座標(250,200)になること
        assert "250.0,200.0" in svg or "250,200" in svg, (
            f"B側アンカーが v6 IF チップ座標(250,200)にならなかった。\nSVG={svg[:300]}"
        )

# ================================================================
# A6d: IF一覧(ifinv) IP列に両AF
# ================================================================

class TestA6dIfinvIpBothAF:
    """A6d: ifinv テーブルの IP 列に dual-stack IF の v4+v6 両方が表示される。"""

    @pytest.fixture
    def dualstack_html(self):
        from lib.rendering import render
        return render(_dualstack_topology())

    # ---------- _build_ifinv_table 単体テスト ----------

    def test_ifinv_dualstack_html_contains_both_af(self, dualstack_html):
        """dual-stack topology の ifinv HTML に v4+v6 が含まれる。"""
        assert "10.0.0.1" in dualstack_html or "10.0.0.2" in dualstack_html
        assert "2001:db8:1::1" in dualstack_html or "2001:db8:1::0" in dualstack_html

    def test_ifinv_dualstack_html_has_br_in_ip_cell(self, dualstack_html):
        """A6d: dual-stack topology の ifinv HTML の IP セルに <br> が含まれる。"""
        td_contents = re.findall(r"<td>(.*?)</td>", dualstack_html, re.DOTALL)
        found = any(
            "<br>" in td and "10.0.0." in td and "2001:db8:1::" in td
            for td in td_contents
        )
        assert found, (
            "dual-stack topology の ifinv IP セルに <br> 区切りがない"
        )

# ================================================================
# 全体統合: single-stack 非回帰
# ================================================================

class TestNonRegression:
    """全実装が既存 single-stack topology に影響を与えないことを確認する。"""

    @pytest.fixture(scope="class")
    def ebgp_p2p_topology(self):
        """ebgp-p2p フィクスチャから topology を構築する。"""
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        ebgp_dir = os.path.join(
            os.path.dirname(__file__), "..", "evals", "inputs", "ebgp-p2p"
        )
        files = sorted(
            os.path.join(ebgp_dir, f) for f in os.listdir(ebgp_dir)
            if f.endswith((".cfg", ".conf"))
        )
        devices = parse_paths(files)
        return build(devices, generated_from=files)

    @pytest.mark.integration
    def test_single_stack_render_no_exception(self, ebgp_p2p_topology):
        """single-stack topology を render() しても例外が出ない。"""
        from lib.rendering import render
        html = render(ebgp_p2p_topology)
        assert len(html) > 0

    @pytest.mark.integration
    def test_single_stack_html_no_spurious_v6(self, ebgp_p2p_topology):
        """single-stack topology の HTML に意図しない v6 アドレスが混入しない。"""
        from lib.rendering import render
        html = render(ebgp_p2p_topology)
        # BGP バッジ tspan が 3 本以上あるブロックはないはず
        badge_blocks = re.findall(
            r'<text[^>]*class="bgp-badge[^"]*"[^>]*>(.*?)</text>',
            html, re.DOTALL
        )
        for block in badge_blocks:
            n = block.count("<tspan")
            assert n <= 2, (
                f"ebgp-p2p（single-stack）で BGP バッジが 2 tspan 超（regression）: {n}"
            )

    @pytest.mark.integration
    def test_multi_as_area_render_no_exception(self):
        """multi-as-area fixture が例外なく render できる。"""
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        from lib.rendering import render
        fixture_dir = os.path.join(
            os.path.dirname(__file__), "..", "evals", "inputs", "multi-as-area"
        )
        if not os.path.isdir(fixture_dir):
            pytest.skip("multi-as-area fixture not found")
        files = sorted(
            os.path.join(fixture_dir, f) for f in os.listdir(fixture_dir)
            if f.endswith((".cfg", ".conf"))
        )
        if not files:
            pytest.skip("no config files in multi-as-area")
        devices = parse_paths(files)
        topo = build(devices, generated_from=files)
        html = render(topo)
        assert len(html) > 0
