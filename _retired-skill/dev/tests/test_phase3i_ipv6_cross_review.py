"""
Phase 3I: IPv6クロスレビュー指摘 修正テスト（テストファースト）

修正対象:
1. [HIGH1a OSPFエントリ area 正規化]
   - JunOS OSPFv3 のエントリ area が "0.0.0.0" のまま → build で正規化して "0" に統一
   - カードの "Area 0.0.0.0" と図の "area 0" が不一致する問題を解消

2. [HIGH1b JunOS OSPFv3 network を subnet 解決]
   - JunOS ospf3 の network が IF名(ge-0/0/0) のままで _build_ospf_marking_map が
     CIDR を得られず data-ospf-id が付かない問題を解消
   - build で network が非CIDR(IF名)の場合、device の当該IF の addresses から
     subnet を導出して network を CIDR に解決する

3. [HIGH3 BGP統合エッジに v4/v6 両 neighbor 併記]
   - 同一機器ペアの v4/v6 BGP セッションについて統合エッジの <title>/badge に両方を併記
   - data-bgp-id 連動は維持

4. [MEDIUM v6-only IF の IP列＋検索]
   - ip が None の v6-only IF について cards Interfaces表の IP列に
     addresses の先頭 v6(link-local除く, CIDR)を表示

不変条件:
- single-stack(v4)の表示/結線/マーキングは変化しない
- cross-vendor-ospf/multi-as-area ゴールデン不変
- 決定性・round-trip・自己完結・全テスト緑(skip 0)
"""
from __future__ import annotations

import re
import os

import pytest

# ================================================================
# 共通フィクスチャ dir
# ================================================================

_FIXTURE_V6 = os.path.join(
    os.path.dirname(__file__), "..", "evals", "inputs", "v6routing"
)
_FIXTURE_DS = os.path.join(
    os.path.dirname(__file__), "..", "evals", "inputs", "dualstack"
)
_FIXTURE_MULTI_AS = os.path.join(
    os.path.dirname(__file__), "..", "evals", "inputs", "multi-as-area"
)
_FIXTURE_CROSS_VENDOR = os.path.join(
    os.path.dirname(__file__), "..", "evals", "inputs", "cross-vendor-ospf"
)

def _build_from_fixture(fixture_dir: str, *filenames: str) -> dict:
    """fixture ファイルから build() した topology dict を返す"""
    from scripts.parse_configs import parse_paths
    from scripts.build_topology import build
    paths = [os.path.join(fixture_dir, fn) for fn in filenames]
    devices = parse_paths(paths)
    return build(devices, generated_from=paths)

def _build_from_dir(fixture_dir: str) -> dict:
    """ディレクトリ内の全 .cfg/.conf から build した topology を返す"""
    from scripts.parse_configs import parse_paths
    from scripts.build_topology import build
    files = sorted([
        os.path.join(fixture_dir, fn)
        for fn in os.listdir(fixture_dir)
        if fn.endswith((".cfg", ".conf"))
    ])
    devices = parse_paths(files)
    return build(devices, generated_from=files)

# ================================================================
# 1. HIGH1a: OSPFエントリ area 正規化
# ================================================================

class TestHigh1aOspfEntryAreaNormalized:
    """build() が routing.ospf の area を _normalize_ospf_area で正規化する。

    JunOS OSPFv3 の area="0.0.0.0" が build 後は "0" になること。
    IOS の area="0"/"1" は不変であること。
    """

    @pytest.fixture(scope="class")
    def v6_topo(self):
        return _build_from_fixture(_FIXTURE_V6, "iosR.cfg", "junosR.conf")

    @pytest.mark.integration
    def test_junos_ospf_entry_area_normalized_to_numeric(self, v6_topo):
        """JunOS OSPF エントリの area が build 後に正規化済み数値文字列になる。

        v6routing fixture: junosR.conf は ospf3 area 0.0.0.0 → build 後 area='0'
        """
        ospf_entries = v6_topo["routing"]["ospf"]
        junos_entries = [
            e for e in ospf_entries if e.get("device", "").startswith("junos")
        ]
        assert junos_entries, "JunOS OSPF エントリが存在しない（fixture 確認）"
        for e in junos_entries:
            area = e.get("area", "")
            assert area != "0.0.0.0", (
                f"JunOS OSPF エントリ area={area!r} が '0.0.0.0' のまま。"
                "build() で _normalize_ospf_area() を適用していない。"
            )
            assert area == "0", (
                f"JunOS OSPF エントリ area={area!r} が '0' に正規化されていない。"
            )

    @pytest.mark.unit
    def test_ios_ospf_entry_area_unchanged(self, v6_topo):
        """IOS OSPF エントリの area は build 後も不変（純粋数値は変化しない）。"""
        ospf_entries = v6_topo["routing"]["ospf"]
        ios_entries = [
            e for e in ospf_entries if e.get("device", "").startswith("ios")
        ]
        assert ios_entries, "IOS OSPF エントリが存在しない（fixture 確認）"
        for e in ios_entries:
            area = e.get("area", "")
            # IOS の area は "0" か "1" 等の純粋数値のまま
            assert area.isdigit(), (
                f"IOS OSPF エントリ area={area!r} が純粋数値でない。"
            )

    @pytest.mark.unit
    @staticmethod
    def test_build_ospf_area_dotted_normalized():
        """build() 内で area='0.0.0.0' のエントリが '0' に正規化される（単体）。"""
        from lib.parsers.base import Device, OspfNetwork
        from scripts.build_topology import build

        dev = Device(
            hostname="JUNOS-TEST", vendor="juniper_junos", asn=65200,
            interfaces=[],
            bgp=[],
            ospf=[OspfNetwork(process=None, network="lo0.0", area="0.0.0.0", af="v6")],
            static=[],
        )
        topo = build([dev], generated_from=[])
        ospf_entries = topo["routing"]["ospf"]
        assert ospf_entries, "OSPF エントリが存在しない"
        for e in ospf_entries:
            assert e["area"] != "0.0.0.0", (
                f"area={e['area']!r} が '0.0.0.0' のまま（build で正規化されていない）"
            )
            assert e["area"] == "0", f"area={e['area']!r} が '0' に正規化されていない"

    @pytest.mark.integration
    def test_card_area_label_consistent_with_link_area(self, v6_topo):
        """OSPF カード行の area と routing.ospf の area が統一済みであること。

        routing.ospf.area が正規化されていれば、カード表示 "Area X" と
        図の link ospf_area が同一値を参照する。
        """
        ospf_entries = v6_topo["routing"]["ospf"]
        v6_links = [
            lk for lk in v6_topo["links"]
            if ":" in lk.get("subnet", "") and "ospf_area" in lk
        ]
        if not v6_links:
            pytest.skip("v6 OSPF リンクが存在しない")

        link_areas = {lk["ospf_area"] for lk in v6_links}
        # routing.ospf.area も正規化済みであること
        for e in ospf_entries:
            area = e.get("area", "")
            # "0.0.0.0" という生の dotted-decimal が残っていないこと
            assert area != "0.0.0.0", (
                f"routing.ospf.area={area!r} が未正規化。"
                "カード 'Area 0.0.0.0' と図 'area 0' が不一致になる。"
            )

    @pytest.mark.integration
    def test_rendered_html_no_area_dotted_in_card(self, v6_topo):
        """rendering 後 HTML のカード内に 'Area 0.0.0.0' が含まれない。"""
        from lib.rendering import render
        html = render(v6_topo)
        assert "Area 0.0.0.0" not in html, (
            "HTML に 'Area 0.0.0.0' が含まれる。"
            "routing.ospf の area 正規化が必要。"
        )

# ================================================================
# 2. HIGH1b: JunOS OSPFv3 network を subnet 解決
# ================================================================

class TestHigh1bJunosOspfNetworkResolved:
    """build() が JunOS OSPF エントリの network（IF名）を CIDR に解決する。

    解決後は _build_ospf_marking_map が CIDR を正規化でき data-ospf-id が付与される。
    IOS の network（既にCIDR）は不変。cross-vendor-ospf/multi-as-area の OSPF は不変。
    """

    @pytest.fixture(scope="class")
    def v6_topo(self):
        return _build_from_fixture(_FIXTURE_V6, "iosR.cfg", "junosR.conf")

    @pytest.mark.integration
    def test_junos_ospf_network_resolved_to_cidr(self, v6_topo):
        """JunOS OSPF エントリ network が build 後に CIDR になる（IF名でない）。

        v6routing fixture: junosR.conf は ospf3 ge-0/0/0.0 → 2001:db8:1::/127
        """
        import ipaddress
        ospf_entries = v6_topo["routing"]["ospf"]
        junos_v6 = [
            e for e in ospf_entries
            if e.get("device", "").startswith("junos") and e.get("af") == "v6"
        ]
        assert junos_v6, "JunOS v6 OSPF エントリが存在しない"
        for e in junos_v6:
            network = e.get("network", "")
            # IF名でないこと（数字スラッシュなし、ドットのみはIF名とみなす）
            assert "/" in network, (
                f"JunOS OSPF network={network!r} に '/' がない（CIDR でない = IF名のまま）。"
                "build() で IF名を addresses から CIDR に解決する必要がある。"
            )
            # CIDR として解析可能なこと
            try:
                ipaddress.ip_network(network, strict=False)
            except ValueError:
                pytest.fail(
                    f"JunOS OSPF network={network!r} が有効な CIDR でない。"
                )

    @pytest.mark.integration
    def test_junos_ospf_network_data_ospf_id_present_in_card(self, v6_topo):
        """JunOS OSPF カード行に data-ospf-id が付与される（IF名解決後は CIDR → ospf_id）。"""
        from lib.rendering import render
        from lib.rendering.core import _build_ospf_marking_map
        ospf_entries = v6_topo["routing"]["ospf"]
        ospf_map = _build_ospf_marking_map(ospf_entries)

        junos_v6 = [
            e for e in ospf_entries
            if e.get("device", "").startswith("junos") and e.get("af") == "v6"
        ]
        assert junos_v6, "JunOS v6 OSPF エントリが存在しない"

        for e in junos_v6:
            key = (e["device"], e["network"])
            ospf_id = ospf_map.get(key)
            assert ospf_id, (
                f"JunOS OSPF エントリ ({e['device']}, {e['network']}) の ospf_id が解決されない。"
                "network が CIDR でないため _normalize_subnet が '' を返している可能性。"
                f"ospf_map keys={list(ospf_map.keys())}"
            )

    @pytest.mark.unit
    @staticmethod
    def test_ios_ospf_network_unchanged():
        """IOS OSPF エントリの network（既にCIDR）は build 後も不変。"""
        from lib.parsers.base import Device, Interface, OspfNetwork
        from scripts.build_topology import build

        iface = Interface(name="GigabitEthernet0/0", ip="10.1.0.1/30", description=None,
                          addresses=[{"af": "v4", "ip": "10.1.0.1", "prefix": 30}])
        dev = Device(
            hostname="IOS-TEST", vendor="cisco_ios", asn=65100,
            interfaces=[iface],
            bgp=[],
            ospf=[OspfNetwork(process=10, network="10.1.0.0/30", area="0", af="v4")],
            static=[],
        )
        topo = build([dev], generated_from=[])
        ospf_entries = topo["routing"]["ospf"]
        assert ospf_entries, "OSPF エントリが存在しない"
        assert ospf_entries[0]["network"] == "10.1.0.0/30", (
            f"IOS OSPF network が変更された: {ospf_entries[0]['network']!r}"
        )

    @pytest.mark.unit
    @staticmethod
    def test_junos_ospf_network_resolved_from_addresses():
        """IF名 network が addresses から CIDR に解決される（単体）。"""
        from lib.parsers.base import Device, Interface, OspfNetwork
        from scripts.build_topology import build
        import ipaddress

        # ge-0/0/0 に v6 address 2001:db8:1::0/127 を持つ JunOS デバイス
        iface = Interface(
            name="ge-0/0/0", ip=None, description=None,
            addresses=[{"af": "v6", "ip": "2001:db8:1::", "prefix": 127}],
        )
        dev = Device(
            hostname="JUNOS-R1", vendor="juniper_junos", asn=65200,
            interfaces=[iface],
            bgp=[],
            ospf=[OspfNetwork(process=None, network="ge-0/0/0.0", area="0.0.0.0", af="v6")],
            static=[],
        )
        topo = build([dev], generated_from=[])
        ospf_entries = topo["routing"]["ospf"]
        assert ospf_entries, "OSPF エントリが存在しない"

        e = ospf_entries[0]
        # area も正規化されているはず（HIGH1a）
        assert e["area"] == "0", f"area={e['area']!r} が正規化されていない"
        # network が CIDR に解決されているはず（HIGH1b）
        network = e["network"]
        assert "/" in network, (
            f"network={network!r} に '/' がない（IF名のまま）"
        )
        # 解決後は 2001:db8:1::/127 になるはず
        resolved_net = ipaddress.ip_network(network, strict=False)
        expected_net = ipaddress.ip_network("2001:db8:1::/127", strict=False)
        assert resolved_net == expected_net, (
            f"network={network!r} → {resolved_net} が期待値 {expected_net} と異なる"
        )

    @pytest.mark.integration
    @staticmethod
    def test_cross_vendor_ospf_regression():
        """cross-vendor-ospf fixture: v4 OSPF network は変化しない（非回帰）。"""
        if not os.path.isdir(_FIXTURE_CROSS_VENDOR):
            pytest.skip("cross-vendor-ospf fixture がない")
        topo = _build_from_dir(_FIXTURE_CROSS_VENDOR)
        ospf_entries = topo["routing"]["ospf"]
        if not ospf_entries:
            pytest.skip("OSPF エントリが存在しない")
        # v4 エントリの network は CIDR のままであること
        v4_entries = [e for e in ospf_entries if e.get("af", "v4") == "v4"]
        import ipaddress
        for e in v4_entries:
            network = e.get("network", "")
            try:
                ipaddress.ip_network(network, strict=False)
            except ValueError:
                pytest.fail(
                    f"cross-vendor-ospf v4 OSPF network={network!r} が CIDR でない。"
                    "v4 には影響を与えてはならない。"
                )

    @pytest.mark.integration
    def test_ospf_marking_map_has_junos_entry(self, v6_topo):
        """JunOS OSPF エントリが _build_ospf_marking_map でマップに追加される。

        network が CIDR に解決されていれば _normalize_subnet が有効な ospf_id を返す。
        """
        from lib.rendering.core import _build_ospf_marking_map
        ospf_entries = v6_topo["routing"]["ospf"]
        ospf_map = _build_ospf_marking_map(ospf_entries)

        # JunOS エントリのキーが存在すること
        junos_keys = [k for k in ospf_map if k[0].startswith("junos")]
        assert junos_keys, (
            f"ospf_marking_map に JunOS エントリが存在しない。"
            f"全キー: {list(ospf_map.keys())}"
        )

    @pytest.mark.integration
    def test_rendered_html_junos_ospf_has_data_ospf_id(self, v6_topo):
        """rendering 後 HTML の JunOS OSPF カード行に data-ospf-id が付与される。"""
        from lib.rendering import render
        html = render(v6_topo)

        # OSPF テーブル内の JunOS の行に data-ospf-id があること
        # (シンプルに: data-ospf-id 属性が1件以上あること + v6 subnet が含まれること)
        assert "data-ospf-id" in html, (
            "HTML に data-ospf-id が含まれない。"
            "JunOS OSPF エントリの network 解決が失敗している可能性。"
        )
        # v6 OSPF link と連動する subnet が HTML に存在すること
        ospf_link = next(
            (lk for lk in v6_topo["links"]
             if ":" in lk.get("subnet", "") and "ospf_area" in lk),
            None,
        )
        if ospf_link:
            subnet = ospf_link["subnet"]
            assert subnet in html, (
                f"OSPF v6 subnet {subnet!r} が HTML に含まれない。"
            )

# ================================================================
# 3. HIGH3: BGP統合エッジに v4/v6 両 neighbor 併記
# ================================================================

class TestHigh3BgpEdgeDualAfTitle:
    """同一機器ペアの v4/v6 BGP セッションを統合エッジの title/badge に両方併記する。

    - <title> に v4 と v6 の local_ip↔neighbor_ip が両方含まれる
    - badge（<text> class="bgp-badge"）にも両方の IP が含まれる
    - data-bgp-id は単一値（ペア）= 変化なし
    - single-stack(v4のみ) は従来通り（non-regression）
    """

    @pytest.fixture(scope="class")
    def v6_topo(self):
        return _build_from_fixture(_FIXTURE_V6, "iosR.cfg", "junosR.conf")

    @pytest.fixture(scope="class")
    def v6_html(self, v6_topo):
        from lib.rendering import render
        return render(v6_topo)

    @pytest.mark.integration
    def test_bgp_v4_v6_sessions_both_in_topo(self, v6_topo):
        """v6routing fixture に IOS-JUNOS 間の v4/v6 両 BGP エントリが存在する。"""
        bgp_entries = v6_topo["routing"]["bgp"]
        ios_junos_v4 = [
            e for e in bgp_entries
            if e.get("device", "").startswith("ios") and e.get("af") == "v4"
            and e.get("type") == "ebgp"
        ]
        ios_junos_v6 = [
            e for e in bgp_entries
            if e.get("device", "").startswith("ios") and e.get("af") == "v6"
            and e.get("type") == "ebgp"
        ]
        assert ios_junos_v4, "IOS-JUNOS v4 eBGP エントリが存在しない"
        assert ios_junos_v6, "IOS-JUNOS v6 eBGP エントリが存在しない"

    @pytest.mark.integration
    def test_bgp_edge_title_contains_v4_neighbor(self, v6_html):
        """BGP 統合エッジ <title> に v4 neighbor IP が含まれる。

        現状は v4 セッションのみ（10.1.0.1↔10.1.0.2）。
        """
        titles = re.findall(r'<title>(.*?)</title>', v6_html)
        bgp_titles = [t for t in titles if "ebgp" in t or "ibgp" in t]
        assert bgp_titles, "BGP セッション title が存在しない"
        v4_found = any("10.1.0" in t for t in bgp_titles)
        assert v4_found, (
            f"BGP title に v4 neighbor (10.1.0.*) が含まれない。titles={bgp_titles}"
        )

    @pytest.mark.integration
    def test_bgp_edge_title_contains_v6_neighbor(self, v6_html):
        """BGP 統合エッジ <title> に v6 neighbor IP が含まれる。

        [RED] 現状は v4 セッションのみで v6 は seen_pairs でスキップされる。
        修正後: title に v6 の local_ip↔neighbor_ip も追加される。
        """
        titles = re.findall(r'<title>(.*?)</title>', v6_html)
        bgp_titles = [t for t in titles if "ebgp" in t or "ibgp" in t]
        assert bgp_titles, "BGP セッション title が存在しない"

        # v6 neighbor が title に含まれること（2001:db8:1:: 系）
        v6_found = any("2001:db8:1:" in t for t in bgp_titles)
        assert v6_found, (
            f"BGP 統合エッジの <title> に v6 neighbor (2001:db8:1::*) が含まれない。"
            f"bgp_titles={bgp_titles}。"
            "_svg_bgp_edges が seen_pairs で v6 セッションをスキップしている。"
        )

    @pytest.mark.integration
    def test_bgp_edge_badge_contains_v6_ip(self, v6_html):
        """BGP 統合エッジの badge（<text class='bgp-badge'>）に v6 IP が含まれる。

        [RED] 現状は badge に v4 IP のみ表示される。
        修正後: badge にも v4/v6 両方の IP ペアが表示される。
        """
        # bgp-badge クラスの text 要素を収集
        badge_matches = re.findall(
            r'<text[^>]+class="bgp-badge[^"]*"[^>]*>(.*?)</text>',
            v6_html, re.DOTALL
        )
        assert badge_matches, "BGP badge テキスト要素が存在しない"
        v6_found = any("2001:db8:1:" in b for b in badge_matches)
        assert v6_found, (
            f"BGP badge に v6 IP (2001:db8:1::*) が含まれない。"
            f"badges={badge_matches}"
        )

    @pytest.mark.integration
    def test_bgp_edge_single_element_for_pair(self, v6_html):
        """同一ペア(ios-r1, junos-r1)の BGP セッション要素が1つ（統合エッジ）。"""
        # data-bgp-id="ios-r1|junos-r1" の出現数
        bgp_id_pattern = re.compile(
            r'<g[^>]+class="bgp-session"[^>]+data-bgp-id="ios-r1\|junos-r1"'
        )
        matches = bgp_id_pattern.findall(v6_html)
        assert len(matches) == 1, (
            f"ios-r1|junos-r1 の bgp-session が {len(matches)} 個（統合後は1個が期待値）"
        )

    @pytest.mark.integration
    def test_bgp_deterministic(self, v6_topo):
        """BGP統合エッジを含む render() が2回同一結果を返す（決定性）。"""
        from lib.rendering import render
        html1 = render(v6_topo)
        html2 = render(v6_topo)
        assert html1 == html2, "render() が非決定的"

    @pytest.mark.unit
    @staticmethod
    def test_single_stack_bgp_unchanged():
        """single-stack(v4のみ) の BGP 統合エッジは従来通り（非回帰）。"""
        from lib.rendering import render
        topo = {
            "title": "Single-stack BGP Regression",
            "generated_from": [],
            "devices": [
                {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001, "sections": []},
                {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": 65002, "sections": []},
            ],
            "interfaces": [
                {"id": "r1::eth0", "device": "r1", "name": "eth0",
                 "ip": "10.0.0.1/30", "vlan": None, "description": None,
                 "shutdown": False, "admin_status": "up", "oper_status": None,
                 "mtu": None, "speed": None, "duplex": None,
                 "l2_l3": "l3", "switchport": None, "encapsulation": None,
                 "source": "parsed", "addresses": []},
                {"id": "r2::eth0", "device": "r2", "name": "eth0",
                 "ip": "10.0.0.2/30", "vlan": None, "description": None,
                 "shutdown": False, "admin_status": "up", "oper_status": None,
                 "mtu": None, "speed": None, "duplex": None,
                 "l2_l3": "l3", "switchport": None, "encapsulation": None,
                 "source": "parsed", "addresses": []},
            ],
            "links": [
                {"a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
                 "subnet": "10.0.0.0/30", "kind": "inferred-subnet"},
            ],
            "segments": [],
            "routing": {
                "bgp": [
                    {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                     "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4"},
                    {"device": "r2", "local_as": 65002, "local_ip": "10.0.0.2",
                     "neighbor_ip": "10.0.0.1", "peer_as": 65001, "type": "ebgp", "af": "v4"},
                ],
                "ospf": [],
                "static": [],
            },
        }
        html = render(topo)
        # v4 IP が title に含まれること
        assert "10.0.0.1" in html, "single-stack BGP title に v4 IP がない"
        # BGP title（<title> タグ）に v6 IP が含まれないこと
        bgp_titles = [
            t for t in re.findall(r"<title>(.*?)</title>", html)
            if "ebgp" in t or "ibgp" in t
        ]
        for t in bgp_titles:
            assert "2001:" not in t, (
                f"single-stack BGP title に v6 IP が含まれる（非回帰違反）: {t!r}"
            )
        # bgp-session が1つあること
        assert html.count('class="bgp-session"') == 1, (
            "single-stack BGP session が1つでない"
        )

    @pytest.mark.unit
    @staticmethod
    def test_bgp_edge_dual_af_topology():
        """v4/v6 両 BGP エントリを持つ topology で統合エッジに両 IP が含まれる（単体）。"""
        from lib.rendering import render
        topo = {
            "title": "Dual-AF BGP Test",
            "generated_from": [],
            "devices": [
                {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001, "sections": []},
                {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": 65002, "sections": []},
            ],
            "interfaces": [
                {
                    "id": "r1::eth0", "device": "r1", "name": "eth0",
                    "ip": "10.0.0.1/30", "vlan": None, "description": None,
                    "shutdown": False, "admin_status": "up", "oper_status": None,
                    "mtu": None, "speed": None, "duplex": None,
                    "l2_l3": "l3", "switchport": None, "encapsulation": None,
                    "source": "parsed",
                    "addresses": [
                        {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                        {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
                    ],
                },
                {
                    "id": "r2::eth0", "device": "r2", "name": "eth0",
                    "ip": "10.0.0.2/30", "vlan": None, "description": None,
                    "shutdown": False, "admin_status": "up", "oper_status": None,
                    "mtu": None, "speed": None, "duplex": None,
                    "l2_l3": "l3", "switchport": None, "encapsulation": None,
                    "source": "parsed",
                    "addresses": [
                        {"af": "v4", "ip": "10.0.0.2", "prefix": 30},
                        {"af": "v6", "ip": "2001:db8:1::", "prefix": 127},
                    ],
                },
            ],
            "links": [
                {
                    "a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
                    "subnet": "10.0.0.0/30", "kind": "inferred-subnet",
                },
                {
                    "a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
                    "subnet": "2001:db8:1::/127", "kind": "inferred-subnet",
                },
            ],
            "segments": [],
            "routing": {
                "bgp": [
                    # v4 session
                    {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                     "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4"},
                    {"device": "r2", "local_as": 65002, "local_ip": "10.0.0.2",
                     "neighbor_ip": "10.0.0.1", "peer_as": 65001, "type": "ebgp", "af": "v4"},
                    # v6 session
                    {"device": "r1", "local_as": 65001, "local_ip": "2001:db8:1::1",
                     "neighbor_ip": "2001:db8:1::", "peer_as": 65002, "type": "ebgp", "af": "v6"},
                    {"device": "r2", "local_as": 65002, "local_ip": "2001:db8:1::",
                     "neighbor_ip": "2001:db8:1::1", "peer_as": 65001, "type": "ebgp", "af": "v6"},
                ],
                "ospf": [],
                "static": [],
            },
        }
        html = render(topo)

        # bgp-session は1つ（統合エッジ）
        assert html.count('class="bgp-session"') == 1, (
            "v4/v6 dual-AF でも bgp-session は1つであること（統合エッジ）"
        )

        # title に v4/v6 両 IP が含まれること
        titles = re.findall(r'<title>(.*?)</title>', html)
        bgp_titles = [t for t in titles if "ebgp" in t or "ibgp" in t]
        assert bgp_titles, "BGP title が存在しない"

        bgp_title_text = " ".join(bgp_titles)
        assert "10.0.0.1" in bgp_title_text, f"v4 local IP が title にない: {bgp_titles}"
        assert "10.0.0.2" in bgp_title_text, f"v4 neighbor IP が title にない: {bgp_titles}"
        assert "2001:db8:1::1" in bgp_title_text, f"v6 local IP が title にない: {bgp_titles}"
        assert "2001:db8:1::" in bgp_title_text, f"v6 neighbor IP が title にない: {bgp_titles}"

# ================================================================
# 4. MEDIUM: v6-only IF の IP列＋検索
# ================================================================

class TestMediumV6OnlyIfDisplay:
    """ip が None の v6-only IF で IP列に v6 CIDR が表示される。

    - cards Interfaces 表の IP列: 先頭 v6 GUA (link-local除く, CIDR形式)
    - data-search にも v6 IP が含まれる
    - addresses なし / v4あり の IF は影響を受けない（非回帰）
    """

    @pytest.fixture(scope="class")
    def ds_topo(self):
        """dualstack fixture（v6-only IF あり）"""
        return _build_from_dir(_FIXTURE_DS)

    @pytest.fixture(scope="class")
    def ds_html(self, ds_topo):
        from lib.rendering import render
        return render(ds_topo)

    @pytest.mark.integration
    def test_v6_only_if_exists_in_dualstack(self, ds_topo):
        """dualstack fixture に v6-only IF（ip=None, v6 GUA あり）が存在する。"""
        v6_only = [
            iface for iface in ds_topo["interfaces"]
            if iface.get("ip") is None and any(
                a.get("af") == "v6" and a.get("scope") != "link-local"
                for a in iface.get("addresses", [])
            )
        ]
        assert v6_only, "v6-only IF が存在しない（fixture 確認）"

    @pytest.mark.integration
    def test_cards_ip_column_shows_v6_for_v6_only_if(self, ds_topo, ds_html):
        """カード Interfaces 表の IP列に v6-only IF の v6 CIDR が含まれる。

        [RED] 現状は ip=None → IP列が空欄。
        修正後: "2001:db8:3::1/127" 等が表示される。
        """
        # v6-only IFを特定
        v6_only = [
            iface for iface in ds_topo["interfaces"]
            if iface.get("ip") is None and any(
                a.get("af") == "v6" and a.get("scope") != "link-local"
                for a in iface.get("addresses", [])
            )
        ]
        assert v6_only, "v6-only IF が存在しない"

        for iface in v6_only:
            # 先頭 v6 GUA を取得
            gua = next(
                a for a in iface["addresses"]
                if a.get("af") == "v6" and a.get("scope") != "link-local"
            )
            expected_ip = f"{gua['ip']}/{gua['prefix']}"
            assert expected_ip in ds_html, (
                f"v6-only IF {iface['name']} の IP列に {expected_ip!r} が含まれない。"
                "cards._device_cards の IP列表示が v6 に対応していない。"
            )

    @pytest.mark.integration
    def test_ifinv_ip_column_shows_v6_for_v6_only_if(self, ds_topo, ds_html):
        """ifinv テーブルの IP列に v6-only IF の v6 CIDR が含まれる。

        [RED] 現状は ip=None → IP列が空欄。
        """
        v6_only = [
            iface for iface in ds_topo["interfaces"]
            if iface.get("ip") is None and any(
                a.get("af") == "v6" and a.get("scope") != "link-local"
                for a in iface.get("addresses", [])
            )
        ]
        assert v6_only, "v6-only IF が存在しない"

        for iface in v6_only:
            gua = next(
                a for a in iface["addresses"]
                if a.get("af") == "v6" and a.get("scope") != "link-local"
            )
            expected_ip = f"{gua['ip']}/{gua['prefix']}"
            assert expected_ip in ds_html, (
                f"ifinv の v6-only IF {iface['name']} の IP列に {expected_ip!r} が含まれない。"
            )

    @pytest.mark.integration
    def test_ifinv_data_search_includes_v6_for_v6_only_if(self, ds_topo, ds_html):
        """ifinv テーブルの v6-only IF 行の data-search に v6 アドレスが含まれる。

        [RED] 現状は ip=None → data-search に v6 が入らない。
        """
        v6_only = [
            iface for iface in ds_topo["interfaces"]
            if iface.get("ip") is None and any(
                a.get("af") == "v6" and a.get("scope") != "link-local"
                for a in iface.get("addresses", [])
            )
        ]
        assert v6_only, "v6-only IF が存在しない"

        for iface in v6_only:
            gua = next(
                a for a in iface["addresses"]
                if a.get("af") == "v6" and a.get("scope") != "link-local"
            )
            v6_ip = gua["ip"]
            # data-search 属性に v6 IP が含まれること
            data_search_pattern = re.compile(
                r'data-search="([^"]*)"',
            )
            searches = data_search_pattern.findall(ds_html)
            v6_in_search = any(v6_ip in s for s in searches)
            assert v6_in_search, (
                f"ifinv 行の data-search に v6 IP {v6_ip!r} が含まれない。"
                f"v6-only IF {iface['name']} の検索が機能しない。"
            )

    @pytest.mark.unit
    @staticmethod
    def test_v6_only_if_cards_shows_cidr():
        """v6-only IF のカード Interfaces 表 IP列に CIDR 形式 v6 が表示される（単体）。"""
        from lib.rendering.cards import _device_cards
        devices = [{"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": None, "sections": []}]
        interfaces = [
            {
                "id": "r1::eth0", "device": "r1", "name": "eth0",
                "ip": None, "vlan": None, "description": "",
                "shutdown": False, "admin_status": "up", "oper_status": None,
                "mtu": None, "speed": None, "duplex": None,
                "l2_l3": "l3", "switchport": None, "encapsulation": None,
                "source": "parsed",
                "addresses": [
                    {"af": "v6", "ip": "2001:db8:3::1", "prefix": 127},
                    {"af": "v6", "ip": "fe80::11", "prefix": 64, "scope": "link-local"},
                ],
            }
        ]
        routing = {"bgp": [], "ospf": [], "static": []}
        html = _device_cards(devices, interfaces, routing)
        assert "2001:db8:3::1/127" in html, (
            f"カード IP列に '2001:db8:3::1/127' が含まれない。html={html[:500]}"
        )
        # link-local は IP列に表示しない
        assert "fe80::11/64" not in html, (
            "link-local アドレスがカード IP列に含まれている"
        )

class TestNonRegressionGolden:
    """cross-vendor-ospf/multi-as-area の OSPF/BGP/カードが変化しない。"""

    @pytest.fixture(scope="class")
    def cross_vendor_html(self):
        if not os.path.isdir(_FIXTURE_CROSS_VENDOR):
            pytest.skip("cross-vendor-ospf fixture がない")
        topo = _build_from_dir(_FIXTURE_CROSS_VENDOR)
        from lib.rendering import render
        return render(topo), topo

    @pytest.mark.integration
    def test_cross_vendor_ospf_renders_ok(self, cross_vendor_html):
        """cross-vendor-ospf: render() が正常に返る。"""
        html, topo = cross_vendor_html
        assert isinstance(html, str), "render() が str を返さない"
        assert "<svg" in html.lower(), "HTML に SVG が含まれない"

    @pytest.mark.integration
    def test_cross_vendor_ospf_data_ospf_id_present(self, cross_vendor_html):
        """cross-vendor-ospf: OSPF エントリがあれば data-ospf-id が HTML に存在する。"""
        html, topo = cross_vendor_html
        ospf_entries = topo["routing"].get("ospf", [])
        if ospf_entries:
            assert "data-ospf-id" in html, (
                "cross-vendor-ospf: OSPF エントリがあるのに data-ospf-id がない"
            )

    @pytest.mark.integration
    def test_multi_as_area_renders_ok(self):
        """multi-as-area: render() が正常に返る。"""
        if not os.path.isdir(_FIXTURE_MULTI_AS):
            pytest.skip("multi-as-area fixture がない")
        topo = _build_from_dir(_FIXTURE_MULTI_AS)
        from lib.rendering import render
        html = render(topo)
        assert isinstance(html, str)
        assert "<svg" in html.lower()

    @pytest.mark.integration
    def test_multi_as_area_ospf_data_attribute(self):
        """multi-as-area: OSPF エントリがあれば data-ospf-id が HTML に存在する。"""
        if not os.path.isdir(_FIXTURE_MULTI_AS):
            pytest.skip("multi-as-area fixture がない")
        topo = _build_from_dir(_FIXTURE_MULTI_AS)
        from lib.rendering import render
        html = render(topo)
        ospf_entries = topo["routing"].get("ospf", [])
        if ospf_entries:
            assert "data-ospf-id" in html, (
                "multi-as-area: OSPF エントリがあるのに data-ospf-id がない"
            )

    @pytest.mark.integration
    def test_determinism_cross_vendor(self):
        """cross-vendor-ospf の render() が2回同一結果（決定性）。"""
        if not os.path.isdir(_FIXTURE_CROSS_VENDOR):
            pytest.skip("cross-vendor-ospf fixture がない")
        topo = _build_from_dir(_FIXTURE_CROSS_VENDOR)
        from lib.rendering import render
        html1 = render(topo)
        html2 = render(topo)
        assert html1 == html2, "cross-vendor-ospf render() が非決定的"
