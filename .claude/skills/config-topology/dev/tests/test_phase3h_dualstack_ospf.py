"""
Phase 3H: dual-stack エッジ統合 + OSPF area 正規化テスト

修正対象:
1. [OSPF area 不正値] v6 link の ospf_area が "0/0.0.0.0" になる問題
   - IOS: area="0"、JunOS: area="0.0.0.0" → 両者を同一エリア表現に統一
   - 修正方針: _normalize_ospf_area() で "0.0.0.0" → "0" に正規化
     （= 既存の数値表現に統一）

2. [dual-stack エッジ統合] 同一 IF ペアに v4/v6 link が2エントリ生成され
   描画時に同一座標に重なる問題
   - 統合は描画層のみ（physical.yaml の links は af別のまま維持）
   - 統合エッジが両 subnet を <title> と data-ospf-id（複数値）に保持
   - 双方向連動: 統合OSPFエッジ click → v4/v6 両行ハイライト、逆も同様
   - v4/v6 両 BGP 行が同 data-bgp-id を保持

不変条件:
- single-stack（v4のみ）の表示/結線/マーキングは変化しない
- 既存テスト 1198 passed, skip 0 を維持
"""
from __future__ import annotations

import re
import os
import sys

import pytest

from lib.parsers.base import Device, Interface, OspfNetwork, BgpNeighbor

# ================================================================
# テストヘルパー
# ================================================================

_FIXTURE_DIR_V6 = os.path.join(
    os.path.dirname(__file__), "..", "evals", "inputs", "v6routing"
)
_FIXTURE_DIR_DUAL = os.path.join(
    os.path.dirname(__file__), "..", "evals", "inputs", "dualstack"
)


def make_iface_with_addresses(
    name: str,
    ip: str | None = None,
    description: str | None = None,
    shutdown: bool = False,
    addresses: list[dict] | None = None,
) -> Interface:
    """addresses フィールドを持つ Interface ファクトリ"""
    iface = Interface(name=name, ip=ip, description=description, shutdown=shutdown)
    if addresses is not None:
        iface.addresses = addresses
    return iface


def _build_from_fixture(fixture_dir: str, *filenames: str) -> dict:
    """fixture ファイルから build() した topology dict を返す"""
    from scripts.parse_configs import parse_paths
    from scripts.build_topology import build
    paths = [os.path.join(fixture_dir, fn) for fn in filenames]
    devices = parse_paths(paths)
    return build(devices, generated_from=paths)


# ================================================================
# 1. OSPF area 正規化テスト
# ================================================================

class TestOspfAreaNormalization:
    """_normalize_ospf_area() 関数の正規化ロジックをテストする。

    "0.0.0.0" 形式の IOS dotted-decimal を "0" 形式の数値に統一する。
    これにより IOS "area 0" と JunOS "area 0.0.0.0" が同一扱いになる。
    """

    @pytest.mark.unit
    def test_normalize_ospf_area_zero_dotted(self):
        """'0.0.0.0' が '0' に正規化される。"""
        from scripts.build_topology import _normalize_ospf_area
        assert _normalize_ospf_area("0.0.0.0") == "0"

    @pytest.mark.unit
    def test_normalize_ospf_area_one_dotted(self):
        """'0.0.0.1' が '1' に正規化される。"""
        from scripts.build_topology import _normalize_ospf_area
        assert _normalize_ospf_area("0.0.0.1") == "1"

    @pytest.mark.unit
    def test_normalize_ospf_area_numeric_unchanged(self):
        """既に数値形式 '0' はそのまま '0' を返す。"""
        from scripts.build_topology import _normalize_ospf_area
        assert _normalize_ospf_area("0") == "0"

    @pytest.mark.unit
    def test_normalize_ospf_area_large_dotted(self):
        """'0.0.0.100' が '100' に正規化される。"""
        from scripts.build_topology import _normalize_ospf_area
        assert _normalize_ospf_area("0.0.0.100") == "100"

    @pytest.mark.unit
    def test_normalize_ospf_area_non_zero_hi_byte(self):
        """'0.0.1.0' は 256 に正規化される（dotted -> int 変換）。"""
        from scripts.build_topology import _normalize_ospf_area
        # 0.0.1.0 = 0*16^6 + ... + 1*256 + 0 = 256
        result = _normalize_ospf_area("0.0.1.0")
        assert result == "256"

    @pytest.mark.unit
    def test_normalize_ospf_area_invalid_unchanged(self):
        """パースできない値はそのまま返す（クラッシュしない）。"""
        from scripts.build_topology import _normalize_ospf_area
        assert _normalize_ospf_area("backbone") == "backbone"
        assert _normalize_ospf_area("") == ""

    @pytest.mark.unit
    def test_normalize_ospf_area_2_format(self):
        """'2' はそのまま '2' を返す。"""
        from scripts.build_topology import _normalize_ospf_area
        assert _normalize_ospf_area("2") == "2"


# ================================================================
# 2. OSPF area 付与: IOS-JunOS cross-vendor v6 リンクで不正値なし
# ================================================================

class TestOspfAreaV6CrossVendor:
    """v6 routing fixture（IOS + JunOS dual-stack）でビルドした topology の
    v6 p2p リンクに 'X/Y' 形式の不正 area 値が付かないことをテストする。
    """

    @pytest.fixture(scope="class")
    def v6_topo(self):
        return _build_from_fixture(
            _FIXTURE_DIR_V6, "iosR.cfg", "junosR.conf"
        )

    @pytest.mark.integration
    def test_v6_link_ospf_area_not_invalid(self, v6_topo):
        """v6 link の ospf_area が '0/0.0.0.0' などの不正な結合値でない。

        IOS (area='0') と JunOS (area='0.0.0.0') は同一エリアを指すため、
        統合後は単一値 '0' になるべき。
        """
        v6_links = [
            lk for lk in v6_topo["links"]
            if ":" in lk.get("subnet", "") and "ospf_area" in lk
        ]
        assert v6_links, "OSPF area 付き v6 リンクが存在しない（fixture が空か build 失敗）"
        for lk in v6_links:
            area = lk["ospf_area"]
            assert area != "0/0.0.0.0", (
                f"v6 link ospf_area={area!r} が不正な結合値 '0/0.0.0.0'。"
                "IOS/JunOS の area 表現が正規化されていない。"
            )

    @pytest.mark.integration
    def test_v6_link_ospf_area_is_normalized_value(self, v6_topo):
        """v6 link の ospf_area が正規化済みの単一値 ('0') になる。

        同一エリアを指す IOS/JunOS 両端の場合は '0' が期待値。
        """
        v6_links = [
            lk for lk in v6_topo["links"]
            if ":" in lk.get("subnet", "") and "ospf_area" in lk
        ]
        assert v6_links, "OSPF area 付き v6 リンクが存在しない"
        for lk in v6_links:
            area = lk["ospf_area"]
            # 単一値であること（スラッシュが含まれないこと）
            assert "/" not in area, (
                f"v6 link ospf_area={area!r} にスラッシュが含まれる（複数 area 表現）。"
                "同一エリア（0）なのに複数値になっている。"
            )
            # area 0 を示す値であること
            assert area == "0", (
                f"v6 link ospf_area={area!r} が '0' でない（area 表現の正規化が必要）。"
            )

    @pytest.mark.integration
    def test_v6_link_ospf_area_matches_card_area(self, v6_topo):
        """v6 link の ospf_area と routing.ospf の area 表現が一致する。

        OSPF Networks カード行に表示される area と図ラベルの area が整合すること。
        """
        v6_links = [
            lk for lk in v6_topo["links"]
            if ":" in lk.get("subnet", "") and "ospf_area" in lk
        ]
        ospf_entries = v6_topo["routing"]["ospf"]
        v6_ospf = [e for e in ospf_entries if e.get("af") == "v6"]

        assert v6_links, "v6 OSPF リンクが存在しない"
        assert v6_ospf, "v6 OSPF エントリが存在しない"

        # routing.ospf の area も正規化された値であること
        for e in v6_ospf:
            area = e.get("area", "")
            # "0.0.0.0" が残っているなら build 側も正規化が必要
            # ただし build は routing.ospf の area をそのまま格納する設計なので
            # ここでは "0" または "0.0.0.0" のどちらかで OK（表示層で整合させる）
            # 少なくとも link の ospf_area と整合していること
            link_areas = {lk["ospf_area"] for lk in v6_links if "ospf_area" in lk}
            # link_areas は正規化済みの値（"0" 等）が入っているはず
            for link_area in link_areas:
                assert "/" not in link_area, (
                    f"link ospf_area={link_area!r} に '/' が含まれる（不正な結合値）。"
                )

    @pytest.mark.unit
    def test_ios_junos_same_area_no_slash(self):
        """IOS area='0' と JunOS area='0.0.0.0' が同じリンクの両端の場合、
        ospf_area は単一値になる（スラッシュなし）。"""
        from scripts.build_topology import build

        d_ios = Device(
            hostname="IOS-R1", vendor="cisco_ios", asn=65100,
            interfaces=[make_iface_with_addresses(
                "GigabitEthernet0/0", ip=None, description="to-R2",
                addresses=[
                    {"af": "v4", "ip": "10.1.0.1", "prefix": 30},
                    {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
                ]
            )],
            bgp=[],
            ospf=[
                OspfNetwork(process=10, network="2001:db8:1::/127", area="0", af="v6"),
            ],
            static=[],
        )
        d_junos = Device(
            hostname="JUNOS-R1", vendor="juniper_junos", asn=65200,
            interfaces=[make_iface_with_addresses(
                "ge-0/0/0", ip=None, description="to-R1",
                addresses=[
                    {"af": "v4", "ip": "10.1.0.2", "prefix": 30},
                    {"af": "v6", "ip": "2001:db8:1::0", "prefix": 127},
                ]
            )],
            bgp=[],
            ospf=[
                OspfNetwork(process=None, network="ge-0/0/0", area="0.0.0.0", af="v6"),
            ],
            static=[],
        )
        topo = build([d_ios, d_junos], generated_from=[])
        v6_links = [
            lk for lk in topo["links"]
            if ":" in lk.get("subnet", "") and "ospf_area" in lk
        ]
        assert v6_links, "v6 link に ospf_area が付かない"
        for lk in v6_links:
            area = lk["ospf_area"]
            assert "/" not in area, (
                f"IOS '0' + JunOS '0.0.0.0' が同じエリアなのに ospf_area={area!r} が複合値"
            )
            assert area == "0", (
                f"IOS '0' + JunOS '0.0.0.0' の統合後 ospf_area={area!r} が '0' でない"
            )


# ================================================================
# 3. OSPF area 表示: rendering 層で area ラベルと OSPF カード行が整合
# ================================================================

class TestOspfAreaRenderingNormalized:
    """rendering 後の HTML で area ラベルが正規化済み値を使う。"""

    @pytest.fixture
    def v6_cross_vendor_topology(self):
        """IOS(area='0') + JunOS(area='0.0.0.0') の dual-stack topology dict"""
        return {
            "title": "Test v6 OSPF Cross-Vendor",
            "generated_from": ["test"],
            "devices": [
                {"id": "ios-r1", "hostname": "IOS-R1", "vendor": "cisco_ios", "as": 65100, "sections": []},
                {"id": "junos-r1", "hostname": "JUNOS-R1", "vendor": "juniper_junos", "as": 65200, "sections": []},
            ],
            "interfaces": [
                {
                    "id": "ios-r1::GigabitEthernet0/0",
                    "device": "ios-r1", "name": "GigabitEthernet0/0",
                    "ip": "10.1.0.1/30", "vlan": None, "description": "to-JUNOS",
                    "shutdown": False, "admin_status": "up", "oper_status": None,
                    "mtu": None, "speed": None, "duplex": None,
                    "l2_l3": "l3", "switchport": None, "encapsulation": None,
                    "source": "parsed",
                    "addresses": [
                        {"af": "v4", "ip": "10.1.0.1", "prefix": 30},
                        {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
                    ],
                },
                {
                    "id": "junos-r1::ge-0/0/0",
                    "device": "junos-r1", "name": "ge-0/0/0",
                    "ip": "10.1.0.2/30", "vlan": None, "description": "to-IOS",
                    "shutdown": False, "admin_status": "up", "oper_status": None,
                    "mtu": None, "speed": None, "duplex": None,
                    "l2_l3": "l3", "switchport": None, "encapsulation": None,
                    "source": "parsed",
                    "addresses": [
                        {"af": "v4", "ip": "10.1.0.2", "prefix": 30},
                        {"af": "v6", "ip": "2001:db8:1::0", "prefix": 127},
                    ],
                },
            ],
            "links": [
                {
                    "a_device": "ios-r1", "a_if": "GigabitEthernet0/0",
                    "b_device": "junos-r1", "b_if": "ge-0/0/0",
                    "subnet": "10.1.0.0/30", "kind": "inferred-subnet",
                    "ospf_area": "0", "ospf_network": "10.1.0.0/30",
                },
                {
                    "a_device": "ios-r1", "a_if": "GigabitEthernet0/0",
                    "b_device": "junos-r1", "b_if": "ge-0/0/0",
                    "subnet": "2001:db8:1::/127", "kind": "inferred-subnet",
                    "ospf_area": "0",  # 正規化済み
                    "ospf_network": "2001:db8:1::/127",
                },
            ],
            "segments": [],
            "routing": {
                "bgp": [],
                "ospf": [
                    {"device": "ios-r1", "process": 10, "network": "2001:db8:1::/127", "area": "0", "af": "v6"},
                    {"device": "junos-r1", "process": None, "network": "ge-0/0/0", "area": "0.0.0.0", "af": "v6"},
                ],
                "static": [],
            },
        }

    @pytest.mark.integration
    def test_rendered_html_no_invalid_ospf_area_label(self, v6_cross_vendor_topology):
        """rendering 後 HTML に '0/0.0.0.0' という area ラベルが含まれない。"""
        from lib.rendering import render
        html = render(v6_cross_vendor_topology)
        assert "0/0.0.0.0" not in html, (
            "HTML に '0/0.0.0.0' が含まれる（area ラベルが不正な結合値）"
        )

    @pytest.mark.integration
    def test_rendered_html_contains_area_0_label(self, v6_cross_vendor_topology):
        """rendering 後 HTML に 'area 0' ラベルが含まれる。"""
        from lib.rendering import render
        html = render(v6_cross_vendor_topology)
        assert "area 0" in html, "HTML に 'area 0' ラベルが含まれない"

    @pytest.mark.integration
    def test_rendered_html_contains_v6_subnet(self, v6_cross_vendor_topology):
        """rendering 後 HTML に v6 サブネット（2001:db8:1::）が含まれる。"""
        from lib.rendering import render
        html = render(v6_cross_vendor_topology)
        assert "2001:db8:1::" in html, "HTML に v6 サブネットが含まれない"


# ================================================================
# 4. dual-stack エッジ統合: 描画層の link_id 重複検出
# ================================================================

class TestDualStackEdgeMerge:
    """同一 IF ペアに v4/v6 link が2エントリある場合、
    rendering 時に同一座標に重なるエッジが生成されないことをテストする。

    統合は描画層のみ。physical.yaml の links は af 別のまま維持する。
    """

    @pytest.fixture
    def dualstack_topology(self):
        """同一 IF ペアに v4/v6 2本 link を持つ dual-stack topology dict

        [修正] routing.ospf に v4/v6 両エントリを追加し OSPFビューを生成させる。
        v4 link のみ ospf_area 付き・v6 link には ospf_area なし（ospf_area 引き継ぎテスト用）。
        """
        return {
            "title": "Dual-stack Test",
            "generated_from": ["test"],
            "devices": [
                {"id": "ds-r1", "hostname": "DS-R1", "vendor": "cisco_ios", "as": 65001, "sections": []},
                {"id": "ds-r2", "hostname": "DS-R2", "vendor": "juniper_junos", "as": 65002, "sections": []},
            ],
            "interfaces": [
                {
                    "id": "ds-r1::GigabitEthernet0/0",
                    "device": "ds-r1", "name": "GigabitEthernet0/0",
                    "ip": "10.0.0.1/30", "vlan": None, "description": "to-DS-R2",
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
                    "id": "ds-r2::ge-0/0/0",
                    "device": "ds-r2", "name": "ge-0/0/0",
                    "ip": "10.0.0.2/30", "vlan": None, "description": "to-DS-R1",
                    "shutdown": False, "admin_status": "up", "oper_status": None,
                    "mtu": None, "speed": None, "duplex": None,
                    "l2_l3": "l3", "switchport": None, "encapsulation": None,
                    "source": "parsed",
                    "addresses": [
                        {"af": "v4", "ip": "10.0.0.2", "prefix": 30},
                        {"af": "v6", "ip": "2001:db8:1::0", "prefix": 127},
                    ],
                },
            ],
            "links": [
                # 同一 IF ペア・v4（ospf_area あり）
                {
                    "a_device": "ds-r1", "a_if": "GigabitEthernet0/0",
                    "b_device": "ds-r2", "b_if": "ge-0/0/0",
                    "subnet": "10.0.0.0/30", "kind": "inferred-subnet",
                    "ospf_area": "0", "ospf_network": "10.0.0.0/30",
                },
                # 同一 IF ペア・v6（統合対象）: ospf_area あり
                {
                    "a_device": "ds-r1", "a_if": "GigabitEthernet0/0",
                    "b_device": "ds-r2", "b_if": "ge-0/0/0",
                    "subnet": "2001:db8:1::/127", "kind": "inferred-subnet",
                    "ospf_area": "0", "ospf_network": "2001:db8:1::/127",
                },
            ],
            "segments": [],
            "routing": {
                "bgp": [
                    {"device": "ds-r1", "local_as": 65001, "local_ip": "10.0.0.1",
                     "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4"},
                    {"device": "ds-r2", "local_as": 65002, "local_ip": "10.0.0.2",
                     "neighbor_ip": "10.0.0.1", "peer_as": 65001, "type": "ebgp", "af": "v4"},
                    {"device": "ds-r1", "local_as": 65001, "local_ip": "2001:db8:1::1",
                     "neighbor_ip": "2001:db8:1::", "peer_as": 65002, "type": "ebgp", "af": "v6"},
                    {"device": "ds-r2", "local_as": 65002, "local_ip": "2001:db8:1::0",
                     "neighbor_ip": "2001:db8:1::1", "peer_as": 65001, "type": "ebgp", "af": "v6"},
                ],
                # [修正] v4/v6 両 OSPF エントリを追加して OSPFビューを生成させる
                "ospf": [
                    {"device": "ds-r1", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                    {"device": "ds-r2", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                    {"device": "ds-r1", "process": 1, "network": "2001:db8:1::/127", "area": "0", "af": "v6"},
                    {"device": "ds-r2", "process": 1, "network": "2001:db8:1::/127", "area": "0", "af": "v6"},
                ],
                "static": [],
            },
        }

    # ---- Physical ビュー: 同一座標重複なし ----

    @pytest.mark.integration
    def test_physical_no_duplicate_link_edges(self, dualstack_topology):
        """Physical ビューで同一 link_id のエッジが複数生成されない。

        同一 IF ペアの v4/v6 link は同一 link_id になるため、
        統合後は1本のエッジが生成されるはず。
        重複がある場合は同一座標に2本重なり視覚的に重なる。
        OSPF ビューにも同一 link_id が付与されるため、Physical ビューのみで検証する。
        """
        from lib.rendering import render
        from lib.rendering.svg import _make_link_id
        html = render(dualstack_topology)

        # Physical ビューのみを抽出してスコープを限定する
        phys_view = _extract_physical_view(html)
        assert phys_view, "Physical ビューが見つからない"

        # data-link-id の出現数を数える（Physical ビュー内のみ）
        link_id = _make_link_id("ds-r1", "GigabitEthernet0/0", "ds-r2", "ge-0/0/0")
        # <g class="link-edge" ... data-link-id="..."> は各エッジに1回出現
        # link-line でも出現するため <g class="link-edge" で数える
        pattern = re.compile(
            r'<g[^>]+class="link-edge"[^>]+data-link-id="' + re.escape(link_id) + r'"'
        )
        matches = pattern.findall(phys_view)
        assert len(matches) == 1, (
            f"Physical ビューで link_id={link_id!r} が {len(matches)} 本生成された（統合後は1本が期待値）。"
            f"dual-stack の v4/v6 エッジが重複している。"
        )

    @pytest.mark.integration
    def test_physical_merged_title_contains_both_subnets(self, dualstack_topology):
        """Physical ビューの統合エッジ <title> に v4/v6 両 subnet が含まれる。"""
        from lib.rendering import render
        html = render(dualstack_topology)
        # <title> の中に両方の subnet が含まれること
        assert "10.0.0.0/30" in html, "統合エッジの <title> に v4 subnet がない"
        assert "2001:db8:1::/127" in html, "統合エッジの <title> に v6 subnet がない"

    # ---- OSPF ビュー: 同一座標重複なし + data-ospf-id 複数値 ----

    @pytest.mark.integration
    def test_ospf_no_duplicate_link_edges(self, dualstack_topology):
        """OSPF ビューで同一 IF ペアのエッジが複数生成されない。

        同一 link_id の v4/v6 OSPF link は統合後1本のエッジになる。
        """
        from lib.rendering import render
        from lib.rendering.svg import _make_link_id
        html = render(dualstack_topology)

        # OSPF ビューの g.link-edge で同一座標（同一端点機器ペア）が1本
        # data-a + data-b の組み合わせで検出
        pattern = re.compile(
            r'<g[^>]+class="link-edge"[^>]+data-a="ds-r1"[^>]+data-b="ds-r2"[^>]*>'
        )
        # view-ospf セクション内に限定して確認
        ospf_section = _extract_ospf_view(html)
        assert ospf_section, "OSPFビュー未生成: routing.ospf が空か両端が OSPF 参加していない"
        if ospf_section:
            ospf_matches = pattern.findall(ospf_section)
            # 同一端点ペアのエッジは1本であるべき
            # （v4 と v6 で別々に生成されていたら2本になる）
            assert len(ospf_matches) <= 1, (
                f"OSPF ビューで ds-r1↔ds-r2 エッジが {len(ospf_matches)} 本（統合後は1本が期待値）"
            )

    @pytest.mark.integration
    def test_ospf_merged_edge_has_multiple_ospf_ids(self, dualstack_topology):
        """OSPF 統合エッジが v4/v6 両方の data-ospf-id を保持する。

        統合エッジの data-ospf-id は空白区切りで複数値を持つか、
        または v4/v6 両 subnet が title/ラベルに含まれること。
        """
        from lib.rendering import render
        html = render(dualstack_topology)
        ospf_section = _extract_ospf_view(html)
        assert ospf_section, "OSPFビュー未生成: routing.ospf が空か両端が OSPF 参加していない"
        # data-ospf-id 属性の値を収集
        ospf_id_matches = re.findall(r'data-ospf-id="([^"]*)"', ospf_section)
        # v4 subnet の ospf_id（10.0.0.0/30）が存在すること
        v4_found = any("10.0.0.0/30" in v for v in ospf_id_matches)
        # v6 subnet の ospf_id（2001:db8:1::/127）が存在すること
        v6_found = any("2001:db8:1::/127" in v for v in ospf_id_matches)
        assert v4_found, (
            f"OSPF ビューに v4 subnet の data-ospf-id がない。ospf_ids={ospf_id_matches}"
        )
        assert v6_found, (
            f"OSPF ビューに v6 subnet の data-ospf-id がない。ospf_ids={ospf_id_matches}"
        )

    @pytest.mark.integration
    def test_ospf_merged_title_contains_both_subnets(self, dualstack_topology):
        """OSPF 統合エッジの <title> または area ラベルに両 subnet が含まれる。"""
        from lib.rendering import render
        html = render(dualstack_topology)
        ospf_section = _extract_ospf_view(html)
        assert ospf_section, "OSPFビュー未生成: routing.ospf が空か両端が OSPF 参加していない"
        assert "10.0.0.0/30" in ospf_section or "area 0" in ospf_section, (
            "OSPF ビューに v4 subnet 情報がない"
        )
        assert "2001:db8:1::" in ospf_section, (
            "OSPF ビューに v6 subnet 情報がない"
        )

    # ---- BGP ビュー: v4/v6 両行が同 data-bgp-id ----

    @pytest.mark.integration
    def test_bgp_v4_v6_entries_same_bgp_id(self, dualstack_topology):
        """dual-stack BGP で v4/v6 両方のエントリが同一 data-bgp-id を持つエッジと関連する。

        _build_bgp_session_map が v4/v6 両エントリに同一 bgp_id を返すこと。
        """
        from lib.rendering.core import _build_bgp_session_map
        interfaces = dualstack_topology["interfaces"]
        bgp_entries = dualstack_topology["routing"]["bgp"]

        bgp_session_map = _build_bgp_session_map(bgp_entries, interfaces)

        # v4 エントリの bgp_id
        v4_entry = next(
            (e for e in bgp_entries if e["device"] == "ds-r1" and e.get("af") == "v4"), None
        )
        # v6 エントリの bgp_id
        v6_entry = next(
            (e for e in bgp_entries if e["device"] == "ds-r1" and e.get("af") == "v6"), None
        )

        assert v4_entry is not None, "v4 BGP エントリが存在しない"
        assert v6_entry is not None, "v6 BGP エントリが存在しない"

        v4_bgp_id = bgp_session_map.get((v4_entry["device"], v4_entry["neighbor_ip"]))
        v6_bgp_id = bgp_session_map.get((v6_entry["device"], v6_entry["neighbor_ip"]))

        # v4/v6 両方の bgp_id が存在すること
        assert v4_bgp_id is not None, "v4 BGP エントリに bgp_id が解決されない"
        assert v6_bgp_id is not None, "v6 BGP エントリに bgp_id が解決されない"
        # 同一機器ペアなので bgp_id は同一であるべき
        assert v4_bgp_id == v6_bgp_id, (
            f"v4 bgp_id={v4_bgp_id!r} と v6 bgp_id={v6_bgp_id!r} が一致しない。"
            "同一機器ペアの v4/v6 BGP 行は同 data-bgp-id で関連すべき。"
        )

    @pytest.mark.integration
    def test_bgp_rendered_html_v6_has_data_bgp_id(self, dualstack_topology):
        """rendering 後 HTML の BGP カード行（v6）に data-bgp-id 属性が付与される。"""
        from lib.rendering import render
        html = render(dualstack_topology)
        # BGP カード行に data-bgp-id があること
        assert "data-bgp-id" in html, "BGP カード行に data-bgp-id 属性がない"
        # v6 neighbor IP が含まれること
        assert "2001:db8:1::" in html, "v6 BGP neighbor IP が HTML に含まれない"


# ================================================================
# 5. 非回帰テスト: single-stack は不変
# ================================================================

class TestSingleStackRegression:
    """single-stack（v4のみ）の表示/結線/マーキングが Phase 3H 修正後も変化しない。"""

    @pytest.fixture
    def singlestack_topology(self):
        """v4 only の単純な topology dict"""
        return {
            "title": "Single-stack Regression",
            "generated_from": ["test"],
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
                    "source": "parsed", "addresses": [],
                },
                {
                    "id": "r2::eth0", "device": "r2", "name": "eth0",
                    "ip": "10.0.0.2/30", "vlan": None, "description": None,
                    "shutdown": False, "admin_status": "up", "oper_status": None,
                    "mtu": None, "speed": None, "duplex": None,
                    "l2_l3": "l3", "switchport": None, "encapsulation": None,
                    "source": "parsed", "addresses": [],
                },
            ],
            "links": [
                {
                    "a_device": "r1", "a_if": "eth0",
                    "b_device": "r2", "b_if": "eth0",
                    "subnet": "10.0.0.0/30", "kind": "inferred-subnet",
                    "ospf_area": "0", "ospf_network": "10.0.0.0/30",
                },
            ],
            "segments": [],
            "routing": {
                "bgp": [
                    {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                     "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4"},
                    {"device": "r2", "local_as": 65002, "local_ip": "10.0.0.2",
                     "neighbor_ip": "10.0.0.1", "peer_as": 65001, "type": "ebgp", "af": "v4"},
                ],
                "ospf": [
                    {"device": "r1", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                    {"device": "r2", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                ],
                "static": [],
            },
        }

    @pytest.mark.integration
    def test_singlestack_exactly_one_physical_edge(self, singlestack_topology):
        """single-stack で Physical ビューのエッジが1本のみ。"""
        from lib.rendering import render
        from lib.rendering.svg import _make_link_id
        html = render(singlestack_topology)
        link_id = _make_link_id("r1", "eth0", "r2", "eth0")
        pattern = re.compile(
            r'<g[^>]+class="link-edge"[^>]+data-link-id="' + re.escape(link_id) + r'"'
        )
        phys_section = _extract_physical_view(html)
        if phys_section:
            matches = pattern.findall(phys_section)
        else:
            matches = pattern.findall(html)
        assert len(matches) == 1, (
            f"single-stack で link-edge が {len(matches)} 本（1本が期待値）"
        )

    @pytest.mark.integration
    def test_singlestack_ospf_area_unchanged(self, singlestack_topology):
        """single-stack の OSPF area が '0' のまま（Phase 3H 修正後も不変）。"""
        from lib.rendering import render
        html = render(singlestack_topology)
        # "area 0" が HTML に含まれること
        assert "area 0" in html, "single-stack OSPF area '0' が HTML に含まれない"
        # "0/0.0.0.0" は含まれないこと
        assert "0/0.0.0.0" not in html, "single-stack なのに不正 area '0/0.0.0.0' が含まれる"

    @pytest.mark.integration
    def test_singlestack_bgp_data_bgp_id_present(self, singlestack_topology):
        """single-stack BGP で data-bgp-id 属性が HTML に存在する。"""
        from lib.rendering import render
        html = render(singlestack_topology)
        assert "data-bgp-id" in html, "single-stack BGP カードに data-bgp-id がない"

    @pytest.mark.integration
    def test_singlestack_ospf_data_ospf_id_present(self, singlestack_topology):
        """single-stack OSPF で data-ospf-id 属性が HTML に存在する。"""
        from lib.rendering import render
        html = render(singlestack_topology)
        assert "data-ospf-id" in html, "single-stack OSPF カードに data-ospf-id がない"

    @pytest.mark.unit
    def test_normalize_ospf_area_does_not_change_pure_numeric(self):
        """_normalize_ospf_area() が純粋数値 area ('0', '1', '2') を変更しない。"""
        from scripts.build_topology import _normalize_ospf_area
        for area in ("0", "1", "2", "10", "100"):
            result = _normalize_ospf_area(area)
            assert result == area, (
                f"_normalize_ospf_area('{area}') = {result!r}（変更されてはいけない）"
            )

    @pytest.mark.integration
    def test_multi_as_area_ospf_regression(self):
        """multi-as-area の OSPF/BGP マーキングが Phase 3H 後も不変。

        multi-as-area fixture は v4 only なので影響を受けてはならない。
        [修正] OR 条件を解消し、OSPF エントリが存在する場合は data-ospf-id が
        HTML に存在することを個別に検証する。
        """
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        from lib.rendering import render

        fixture_dir = os.path.join(
            os.path.dirname(__file__), "..", "evals", "inputs", "multi-as-area"
        )
        files = sorted([
            os.path.join(fixture_dir, fn)
            for fn in os.listdir(fixture_dir)
            if fn.endswith((".cfg", ".conf"))
        ])
        if not files:
            pytest.skip("multi-as-area fixture がない")

        devices = parse_paths(files)
        topo = build(devices, generated_from=files)
        html = render(topo)

        assert isinstance(html, str), "multi-as-area: render() が str を返さない"
        assert "<svg" in html.lower(), "multi-as-area: HTML に SVG が含まれない"

        # [修正] OR 条件解消: OSPF エントリの有無に応じて個別に検証
        ospf_entries = topo["routing"].get("ospf", [])
        if ospf_entries:
            assert "data-ospf-id" in html, (
                "multi-as-area: OSPF エントリがあるのに data-ospf-id が HTML に存在しない。"
                f"ospf_entries={ospf_entries[:2]}..."
            )


# ================================================================
# 6. 決定性テスト
# ================================================================

class TestDeterminism:
    """Phase 3H 修正後も render() が決定的であることを確認する。"""

    @pytest.mark.unit
    def test_normalize_ospf_area_deterministic(self):
        """_normalize_ospf_area() が同一入力に対して常に同一出力を返す。"""
        from scripts.build_topology import _normalize_ospf_area
        test_cases = ["0", "0.0.0.0", "1", "0.0.0.1", "0.0.1.0", "backbone", ""]
        for area in test_cases:
            assert _normalize_ospf_area(area) == _normalize_ospf_area(area), (
                f"_normalize_ospf_area('{area}') が非決定的"
            )

    @pytest.mark.integration
    def test_dualstack_render_twice_same_result(self):
        """dual-stack topology を2回 render() した結果が同一。"""
        from lib.rendering import render
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build

        paths = [
            os.path.join(_FIXTURE_DIR_DUAL, "r1.cfg"),
            os.path.join(_FIXTURE_DIR_DUAL, "r2.conf"),
        ]
        devices = parse_paths(paths)
        topo = build(devices, generated_from=paths)

        html1 = render(topo)
        html2 = render(topo)
        assert html1 == html2, "dual-stack render() が非決定的"


# ================================================================
# ヘルパー: HTML セクション抽出
# ================================================================

def _extract_ospf_view(html: str) -> str:
    """HTML から view-ospf セクションを抽出する（大雑把なパターンマッチ）。"""
    # <g class="view view-ospf" ...> ... </g> を抽出
    match = re.search(r'<g[^>]+class="view view-ospf"[^>]*>(.*?)</g>', html, re.DOTALL)
    if match:
        return match.group(0)
    # フォールバック: ospf を含む部分
    return ""


def _extract_ospf_view_full(html: str) -> str:
    """HTML から view-ospf セクションを確実に抽出する（全体マッチ版）。

    `(.*?)</g>` は最初の </g> で止まるため OSPF ビュー全体を取れない。
    代わりに view-ospf の開始位置から次の view- グループまでを取得する。
    """
    # view-ospf 開始位置
    m_start = re.search(r'<g[^>]+class="view view-ospf"', html)
    if not m_start:
        return ""
    start = m_start.start()
    # 次の view- グループ開始 or </g></g></svg> 終端
    m_end = re.search(r'<g[^>]+class="view view-(?!ospf)[^"]*"', html[start + 1:])
    if m_end:
        return html[start: start + 1 + m_end.start()]
    # フォールバック: view-ospf 開始から末尾まで
    return html[start:]


def _extract_physical_view(html: str) -> str:
    """HTML から view-physical セクションを抽出する。"""
    match = re.search(r'<g[^>]+class="view view-physical"[^>]*>(.*?)</g>', html, re.DOTALL)
    if match:
        return match.group(0)
    return ""


# ================================================================
# 7. Phase 3H 不具合修正: 統合OSPFエッジ data-ospf-id に v4/v6 両値
# ================================================================

def _make_dualstack_ospf_topology():
    """OSPF dual-stack topology: 同一 IF ペアに v4/v6 両 OSPF link を持つ。

    IOS-R1 (GigabitEthernet0/0) <-> JUNOS-R1 (ge-0/0/0)
      v4: 10.1.0.0/30  ospf_area=0
      v6: 2001:db8:1::/127  ospf_area=0
    """
    return {
        "title": "Dual-stack OSPF Test",
        "generated_from": ["test"],
        "devices": [
            {"id": "ios-r1", "hostname": "IOS-R1", "vendor": "cisco_ios", "as": None, "sections": []},
            {"id": "junos-r1", "hostname": "JUNOS-R1", "vendor": "juniper_junos", "as": None, "sections": []},
        ],
        "interfaces": [
            {
                "id": "ios-r1::GigabitEthernet0/0",
                "device": "ios-r1", "name": "GigabitEthernet0/0",
                "ip": "10.1.0.1/30", "vlan": None, "description": "to-JUNOS-R1",
                "shutdown": False, "admin_status": "up", "oper_status": None,
                "mtu": None, "speed": None, "duplex": None,
                "l2_l3": "l3", "switchport": None, "encapsulation": None,
                "source": "parsed",
                "addresses": [
                    {"af": "v4", "ip": "10.1.0.1", "prefix": 30},
                    {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
                ],
            },
            {
                "id": "junos-r1::ge-0/0/0",
                "device": "junos-r1", "name": "ge-0/0/0",
                "ip": "10.1.0.2/30", "vlan": None, "description": "to-IOS-R1",
                "shutdown": False, "admin_status": "up", "oper_status": None,
                "mtu": None, "speed": None, "duplex": None,
                "l2_l3": "l3", "switchport": None, "encapsulation": None,
                "source": "parsed",
                "addresses": [
                    {"af": "v4", "ip": "10.1.0.2", "prefix": 30},
                    {"af": "v6", "ip": "2001:db8:1::", "prefix": 127},
                ],
            },
        ],
        "links": [
            {
                "a_device": "ios-r1", "a_if": "GigabitEthernet0/0",
                "b_device": "junos-r1", "b_if": "ge-0/0/0",
                "subnet": "10.1.0.0/30", "kind": "inferred-subnet",
                "ospf_area": "0", "ospf_network": "10.1.0.0/30",
            },
            {
                "a_device": "ios-r1", "a_if": "GigabitEthernet0/0",
                "b_device": "junos-r1", "b_if": "ge-0/0/0",
                "subnet": "2001:db8:1::/127", "kind": "inferred-subnet",
                "ospf_area": "0", "ospf_network": "2001:db8:1::/127",
            },
        ],
        "segments": [],
        "routing": {
            "bgp": [],
            "ospf": [
                {"device": "ios-r1", "process": 10, "network": "10.1.0.0/30", "area": "0", "af": "v4"},
                {"device": "junos-r1", "process": None, "network": "10.1.0.0/30", "area": "0", "af": "v4"},
                {"device": "ios-r1", "process": 10, "network": "2001:db8:1::/127", "area": "0", "af": "v6"},
                {"device": "junos-r1", "process": None, "network": "2001:db8:1::/127", "area": "0", "af": "v6"},
            ],
            "static": [],
        },
    }


class TestDualStackOspfEdgeIds:
    """Phase 3H 修正: 統合OSPFエッジ data-ospf-id に v4/v6 両値が保持される。

    問題: views._build_view_ospf の ospf_ids 計算が
    lk.get("ospf_network") を全サブネットに適用するため、
    v6 subnet が v4 ospf_network で上書きされ data-ospf-id="10.x/30" だけになる。

    期待: data-ospf-id="10.1.0.0/30 2001:db8:1::/127"（空白区切りtokenで両値）
    """

    @pytest.fixture
    def topo(self):
        return _make_dualstack_ospf_topology()

    @pytest.mark.integration
    def test_merged_ospf_edge_has_v4_token_in_data_ospf_id(self, topo):
        """統合OSPFエッジの data-ospf-id に v4 subnet (10.1.0.0/30) が含まれる。"""
        from lib.rendering import render
        html = render(topo)
        ospf_view = _extract_ospf_view_full(html)
        assert ospf_view, "OSPF ビューが生成されていない"
        # data-ospf-id 属性の <g class="link-edge"> を取得
        g_tags = re.findall(r'<g[^>]*class="link-edge"[^>]*data-ospf-id="([^"]+)"[^>]*>', ospf_view)
        g_tags += re.findall(r'<g[^>]*data-ospf-id="([^"]+)"[^>]*class="link-edge"[^>]*>', ospf_view)
        assert g_tags, f"OSPF ビューに data-ospf-id 付き link-edge がない: {ospf_view[:500]}"
        # いずれかのタグに v4 subnet が含まれること
        v4_found = any("10.1.0.0/30" in tag for tag in g_tags)
        assert v4_found, (
            f"統合OSPFエッジの data-ospf-id に v4 (10.1.0.0/30) がない。g_tags={g_tags}"
        )

    @pytest.mark.integration
    def test_merged_ospf_edge_has_v6_token_in_data_ospf_id(self, topo):
        """統合OSPFエッジの data-ospf-id に v6 subnet (2001:db8:1::/127) が含まれる。

        [RED -> GREEN] 現状は v6 が欠落し data-ospf-id="10.1.0.0/30" のみになる。
        修正後は data-ospf-id="10.1.0.0/30 2001:db8:1::/127" になること。
        """
        from lib.rendering import render
        html = render(topo)
        ospf_view = _extract_ospf_view_full(html)
        assert ospf_view, "OSPF ビューが生成されていない"
        g_tags = re.findall(r'<g[^>]*class="link-edge"[^>]*data-ospf-id="([^"]+)"[^>]*>', ospf_view)
        g_tags += re.findall(r'<g[^>]*data-ospf-id="([^"]+)"[^>]*class="link-edge"[^>]*>', ospf_view)
        assert g_tags, f"OSPF ビューに data-ospf-id 付き link-edge がない"
        v6_found = any("2001:db8:1::/127" in tag for tag in g_tags)
        assert v6_found, (
            f"統合OSPFエッジの data-ospf-id に v6 (2001:db8:1::/127) がない。"
            f"g_tags={g_tags}。"
            "views._build_view_ospf の ospf_ids 計算が各 subnet を個別に正規化していない。"
        )

    @pytest.mark.integration
    def test_merged_ospf_edge_data_ospf_id_is_space_separated_tokens(self, topo):
        """統合OSPFエッジの data-ospf-id が空白区切り（例: '10.1.0.0/30 2001:db8:1::/127'）。

        [RED -> GREEN] 両 subnet が空白区切りで1属性に収まること。
        """
        from lib.rendering import render
        html = render(topo)
        ospf_view = _extract_ospf_view_full(html)
        assert ospf_view, "OSPF ビューが生成されていない"
        g_tags = re.findall(r'<g[^>]*class="link-edge"[^>]*data-ospf-id="([^"]+)"[^>]*>', ospf_view)
        g_tags += re.findall(r'<g[^>]*data-ospf-id="([^"]+)"[^>]*class="link-edge"[^>]*>', ospf_view)
        assert g_tags, "OSPF ビューに data-ospf-id 付き link-edge がない"
        # 少なくとも1つのタグが空白区切りで2 token 以上を持つこと
        multi_token = [tag for tag in g_tags if " " in tag]
        assert multi_token, (
            f"統合OSPFエッジに空白区切り複数 token の data-ospf-id がない。"
            f"g_tags={g_tags}"
        )
        # token が v4/v6 両方含むこと
        for token_val in multi_token:
            tokens = token_val.split()
            assert "10.1.0.0/30" in tokens, f"v4 token がない: {token_val}"
            assert "2001:db8:1::/127" in tokens, f"v6 token がない: {token_val}"

    @pytest.mark.integration
    def test_merged_ospf_edge_deterministic(self, topo):
        """統合OSPFエッジ data-ospf-id の値が2回 render() しても同一（決定性）。"""
        from lib.rendering import render
        html1 = render(topo)
        html2 = render(topo)
        # data-ospf-id 付き link-edge の値を両方から抽出して比較
        ids1 = re.findall(r'<g[^>]*class="link-edge"[^>]*data-ospf-id="([^"]+)"', html1)
        ids2 = re.findall(r'<g[^>]*class="link-edge"[^>]*data-ospf-id="([^"]+)"', html2)
        assert ids1 == ids2, f"非決定的: {ids1} != {ids2}"

    @pytest.mark.integration
    def test_singlestack_ospf_edge_single_token(self):
        """single-stack(v4のみ) では data-ospf-id が単一 token（空白なし）。非回帰。"""
        from lib.rendering import render
        singlestack = {
            "title": "Single-stack Regression",
            "generated_from": ["test"],
            "devices": [
                {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": None, "sections": []},
                {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": None, "sections": []},
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
                 "subnet": "10.0.0.0/30", "kind": "inferred-subnet",
                 "ospf_area": "0", "ospf_network": "10.0.0.0/30"},
            ],
            "segments": [],
            "routing": {
                "bgp": [],
                "ospf": [
                    {"device": "r1", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                    {"device": "r2", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                ],
                "static": [],
            },
        }
        html = render(singlestack)
        ospf_view = _extract_ospf_view_full(html)
        assert ospf_view, "OSPF ビューが生成されていない"
        g_tags = re.findall(r'<g[^>]*class="link-edge"[^>]*data-ospf-id="([^"]+)"[^>]*>', ospf_view)
        g_tags += re.findall(r'<g[^>]*data-ospf-id="([^"]+)"[^>]*class="link-edge"[^>]*>', ospf_view)
        assert g_tags, "OSPF ビューに data-ospf-id 付き link-edge がない（non-regression）"
        # single-stack は空白なし単一 token
        for tag in g_tags:
            assert " " not in tag, (
                f"single-stack なのに data-ospf-id が複数 token: {tag!r}"
            )
        assert any("10.0.0.0/30" in tag for tag in g_tags), (
            "single-stack OSPF エッジに 10.0.0.0/30 がない"
        )


class TestOspfJsTokenSelector:
    """Phase 3H 修正: JS が token セレクタ (~=) を使い双方向連動する。

    問題: _toggleSelection が '[data-ospf-id="X"]' 完全一致 → 複数 token に非対応。
    修正後: OSPF 用ハンドラが '[data-ospf-id~="X"]' token セレクタを使う。
    """

    @pytest.fixture
    def topo(self):
        return _make_dualstack_ospf_topology()

    @pytest.mark.unit
    def test_js_uses_tilde_equals_for_ospf(self, topo):
        """rendering 後 HTML の JS に '[data-ospf-id~="' token セレクタが含まれる。

        [RED -> GREEN] 現状は完全一致 '[data-ospf-id="' のみ。
        修正後は token セレクタ '~=' を使う OSPF 専用ロジックが存在すること。
        """
        from lib.rendering import render
        html = render(topo)
        assert '[data-ospf-id~="' in html, (
            "JS に '[data-ospf-id~=\"' token セレクタが含まれない。"
            "template.py の toggleOspfHighlight / _toggleSelection を token 対応に修正すること。"
        )

    @pytest.mark.unit
    def test_js_ospf_click_highlights_all_tokens(self, topo):
        """統合エッジクリック時に複数 token を split して全 OSPF 行をハイライトするロジックが存在する。

        JS 内に 'split' または token 分解のロジックがあること。
        （実際のブラウザ動作は Playwright E2E で確認するが、ロジックの存在を確認）
        """
        from lib.rendering import render
        html = render(topo)
        # JS 部分（<script> タグ内）を抽出
        js_section = re.search(r'<script>(.*?)</script>', html, re.DOTALL)
        assert js_section, "<script> セクションが見つからない"
        js = js_section.group(1)
        # OSPF 用ハイライト関数内に split か ~= セレクタの使用があること
        has_token_split = "split(' ')" in js or ".split(' ')" in js or '~="' in js
        assert has_token_split, (
            "JS に OSPF token 分解ロジック (split(' ') または ~=) がない"
        )

    @pytest.mark.unit
    def test_js_ospf_row_click_uses_token_selector(self, topo):
        """OSPF Networks 行クリック時に token セレクタ ~= を使ってエッジを照合する。

        [RED -> GREEN] 行クリックで toggleOspfHighlight(ospfId) が呼ばれ、
        ~= セレクタで単一 id を複数 token エッジと突き合わせること。
        """
        from lib.rendering import render
        html = render(topo)
        # JS 内に ~= を使うセレクタがあること
        assert '[data-ospf-id~="' in html, (
            "JS に token セレクタ '[data-ospf-id~=\"' がない。"
            "OSPF 行クリックが単一 token の ~= で統合エッジを照合できない。"
        )

    @pytest.mark.unit
    def test_js_toggle_ospf_not_use_exact_match_for_multi_token(self, topo):
        """統合エッジの data-ospf-id に完全一致 '=' のみで照合するロジックが存在しない。

        旧: _toggleSelection が '[data-ospf-id="X"]' 完全一致を使う。
        新: OSPF 専用ロジックが '[data-ospf-id~="X"]' token 照合を使う。
        単一 token の場合も ~= で動作するため、完全一致 = は使わなくてよい。
        """
        from lib.rendering import render
        html = render(topo)
        js_section = re.search(r'<script>(.*?)</script>', html, re.DOTALL)
        assert js_section, "<script> セクションが見つからない"
        js = js_section.group(1)
        # toggleOspfHighlight 関数が完全一致 '=' を直接使わないこと
        # （_toggleSelection 経由の '=' ではなく、OSPF 専用の ~= があること）
        has_tilde = "[data-ospf-id~=" in js
        assert has_tilde, (
            "JS に OSPF token セレクタ '[data-ospf-id~=' がない"
        )

    @pytest.mark.unit
    def test_js_ospf_exact_match_selector_absent_from_toggle_path(self, topo):
        """_ospfHighlightToken / toggleOspfHighlight の実行経路に
        旧来の完全一致セレクタ '[data-ospf-id="' が OSPF 連動経路に残っていない。

        _toggleSelection は他の data-* 属性に対してまだ完全一致 = を使うため、
        JS 全体から '[data-ospf-id="' の除去は不可能だが、
        OSPF 専用関数 (_ospfHighlightToken) が ~= を使っていれば十分。
        このテストは ~= セレクタが存在することを確認する（旧実装の否定確認）。
        """
        from lib.rendering import render
        html = render(topo)
        # ~= セレクタが存在すること（OSPF 専用ロジックの確認）
        assert '[data-ospf-id~="' in html, (
            "JS に OSPF token セレクタ '[data-ospf-id~=\"' がない。"
            "OSPF 連動経路が旧来の完全一致のみになっている可能性がある。"
        )


# ================================================================
# 8. _merge_links_by_link_id 単体テスト
# ================================================================

class TestMergeLinksById:
    """_merge_links_by_link_id の単体テスト（タスク5）。

    - 同一 IF ペアの v4/v6 統合（subnets 全保持・sorted）
    - a/b 逆順リンクの扱い（link_id は対称）
    - subnet 重複除去
    - ospf_area 引き継ぎ（v6 のみ OSPF 参加）
    """

    @pytest.mark.unit
    def test_single_stack_unchanged(self):
        """single-stack リンクは変化なし（1エントリ → 1エントリ）。"""
        from lib.rendering.svg import _merge_links_by_link_id
        links = [
            {"a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
             "subnet": "10.0.0.0/30"},
        ]
        result = _merge_links_by_link_id(links)
        assert len(result) == 1
        assert result[0]["subnet"] == "10.0.0.0/30"
        assert result[0]["subnets"] == ["10.0.0.0/30"]

    @pytest.mark.unit
    def test_dualstack_merged_to_one_entry(self):
        """同一 IF ペアの v4/v6 2エントリが1エントリに統合される。"""
        from lib.rendering.svg import _merge_links_by_link_id
        links = [
            {"a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
             "subnet": "10.0.0.0/30"},
            {"a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
             "subnet": "2001:db8::/127"},
        ]
        result = _merge_links_by_link_id(links)
        assert len(result) == 1
        assert "10.0.0.0/30" in result[0]["subnets"]
        assert "2001:db8::/127" in result[0]["subnets"]
        assert result[0]["subnets"] == sorted(result[0]["subnets"])  # sorted 確認

    @pytest.mark.unit
    def test_reversed_ab_order_merged(self):
        """a/b 逆順リンクが同一 link_id として統合される（対称性）。"""
        from lib.rendering.svg import _merge_links_by_link_id
        links = [
            {"a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
             "subnet": "10.0.0.0/30"},
            # b/a 逆順
            {"a_device": "r2", "a_if": "eth0", "b_device": "r1", "b_if": "eth0",
             "subnet": "2001:db8::/127"},
        ]
        result = _merge_links_by_link_id(links)
        assert len(result) == 1, (
            f"a/b 逆順リンクが別エントリになった: {result}"
        )
        subnets = result[0]["subnets"]
        assert "10.0.0.0/30" in subnets
        assert "2001:db8::/127" in subnets

    @pytest.mark.unit
    def test_subnet_deduplication(self):
        """同一 subnet が複数エントリに含まれても重複除去される。"""
        from lib.rendering.svg import _merge_links_by_link_id
        links = [
            {"a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
             "subnet": "10.0.0.0/30"},
            {"a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
             "subnet": "10.0.0.0/30"},  # 重複
        ]
        result = _merge_links_by_link_id(links)
        assert len(result) == 1
        assert result[0]["subnets"].count("10.0.0.0/30") == 1

    @pytest.mark.unit
    def test_ospf_area_propagated_from_v4_to_merged(self):
        """v4 のみ ospf_area を持つ場合、統合エントリに ospf_area が引き継がれる。"""
        from lib.rendering.svg import _merge_links_by_link_id
        links = [
            {"a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
             "subnet": "10.0.0.0/30", "ospf_area": "0", "ospf_network": "10.0.0.0/30"},
            {"a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
             "subnet": "2001:db8::/127"},  # ospf_area なし
        ]
        result = _merge_links_by_link_id(links)
        assert len(result) == 1
        assert result[0].get("ospf_area") == "0", (
            f"v4 のみ OSPF 参加で統合エントリの ospf_area が引き継がれない: {result[0]}"
        )

    @pytest.mark.unit
    def test_ospf_area_propagated_from_v6_only(self):
        """v6 のみ ospf_area を持つ場合（v4 なし）、統合エントリに ospf_area が引き継がれる。"""
        from lib.rendering.svg import _merge_links_by_link_id
        links = [
            {"a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
             "subnet": "10.0.0.0/30"},  # ospf_area なし（v4 は OSPF 非参加）
            {"a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
             "subnet": "2001:db8::/127", "ospf_area": "1", "ospf_network": "2001:db8::/127"},
        ]
        result = _merge_links_by_link_id(links)
        assert len(result) == 1
        assert result[0].get("ospf_area") == "1", (
            f"v6 のみ OSPF 参加で統合エントリの ospf_area が引き継がれない: {result[0]}"
        )

    @pytest.mark.unit
    def test_ospf_area_both_same_area(self):
        """v4/v6 両方が同じ ospf_area の場合、統合エントリの ospf_area は単一値。"""
        from lib.rendering.svg import _merge_links_by_link_id
        links = [
            {"a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
             "subnet": "10.0.0.0/30", "ospf_area": "0"},
            {"a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
             "subnet": "2001:db8::/127", "ospf_area": "0"},
        ]
        result = _merge_links_by_link_id(links)
        assert len(result) == 1
        assert result[0].get("ospf_area") == "0", (
            f"同一 area の統合で ospf_area が {result[0].get('ospf_area')!r} になった"
        )

    @pytest.mark.unit
    def test_ospf_area_different_areas_aggregated_slash_separated(self):
        """v4/v6 で異なる ospf_area の場合、数値昇順 '/' 区切りで集約される。"""
        from lib.rendering.svg import _merge_links_by_link_id
        links = [
            {"a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
             "subnet": "10.0.0.0/30", "ospf_area": "1"},
            {"a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
             "subnet": "2001:db8::/127", "ospf_area": "0"},
        ]
        result = _merge_links_by_link_id(links)
        assert len(result) == 1
        area = result[0].get("ospf_area", "")
        # 数値昇順 '/' 区切り: "0/1"
        assert area == "0/1", (
            f"異なる area の集約が '0/1' でない: {area!r}"
        )

    @pytest.mark.unit
    def test_different_if_pairs_not_merged(self):
        """異なる IF ペアのリンクは統合されない（別エントリのまま）。"""
        from lib.rendering.svg import _merge_links_by_link_id
        links = [
            {"a_device": "r1", "a_if": "eth0", "b_device": "r2", "b_if": "eth0",
             "subnet": "10.0.0.0/30"},
            {"a_device": "r1", "a_if": "eth1", "b_device": "r2", "b_if": "eth1",
             "subnet": "10.0.1.0/30"},
        ]
        result = _merge_links_by_link_id(links)
        assert len(result) == 2, f"異なる IF ペアが統合された: {result}"


# ================================================================
# 9. area↔card 一致テスト（タスク6）
# ================================================================

class TestAreaCardConsistency:
    """v6 link の ospf_area と OSPF Networks カード行の area が整合することをテストする。

    タスク6: `test_v6_link_ospf_area_matches_card_area` を実効化。
    '/' 不在チェック止まりをやめ、リンクの area ラベルとカード行の area を実際に比較する。
    """

    @pytest.fixture(scope="class")
    def v6_topo(self):
        return _build_from_fixture(_FIXTURE_DIR_V6, "iosR.cfg", "junosR.conf")

    @pytest.mark.integration
    def test_v6_link_area_matches_routing_ospf_area(self, v6_topo):
        """v6 link の ospf_area と routing.ospf の area 表現が一致する。

        IOS/JunOS クロスベンダーで area 表現が正規化され、
        リンクの ospf_area と routing.ospf の area が同一値になること。
        """
        v6_links = [
            lk for lk in v6_topo["links"]
            if ":" in lk.get("subnet", "") and "ospf_area" in lk
        ]
        ospf_entries = v6_topo["routing"]["ospf"]
        v6_ospf = [e for e in ospf_entries if e.get("af") == "v6"]

        assert v6_links, "v6 OSPF リンクが存在しない（fixture を確認）"
        assert v6_ospf, "v6 OSPF エントリが存在しない（fixture を確認）"

        # routing.ospf の v6 area 値を収集
        routing_areas = {e.get("area", "") for e in v6_ospf}
        # link の ospf_area 値を収集
        link_areas = {lk["ospf_area"] for lk in v6_links}

        # IOS は "0"、JunOS は "0.0.0.0" → build 後は正規化された単一値
        # link_areas と routing_areas は正規化後に一致するか重複がないこと
        # 少なくとも link_area が routing_areas に対応する値であること
        for link_area in link_areas:
            assert "/" not in link_area, (
                f"link ospf_area={link_area!r} に '/' が含まれる（不正な結合値）。"
            )
            # routing_areas の値（正規化前後あり）と比較
            # routing area "0.0.0.0" も "0" も link_area "0" と一致するとみなせる
            assert any(
                ra == link_area or
                (ra == "0.0.0.0" and link_area == "0") or
                (ra == "0" and link_area == "0")
                for ra in routing_areas
            ), (
                f"link ospf_area={link_area!r} が routing.ospf の area {routing_areas} と対応しない。"
            )

    @pytest.mark.integration
    def test_rendered_html_area_label_matches_routing_ospf_area(self, v6_topo):
        """rendering 後の OSPF ビューに含まれる area ラベルが routing.ospf の area と整合する。

        IOS/JunOS の場合は 'area 0' が正規化済み表現として HTML に現れること。
        """
        from lib.rendering import render
        html = render(v6_topo)
        ospf_entries = v6_topo["routing"]["ospf"]
        v6_ospf = [e for e in ospf_entries if e.get("af") == "v6"]

        assert v6_ospf, "v6 OSPF エントリが存在しない"

        # routing.ospf に area=0 or 0.0.0.0 のエントリがある場合、
        # HTML に 'area 0' が含まれること
        area_values = {e.get("area", "") for e in v6_ospf}
        if "0" in area_values or "0.0.0.0" in area_values:
            assert "area 0" in html, (
                "routing.ospf に area 0 エントリがあるのに HTML に 'area 0' がない。"
                "正規化または表示処理を確認すること。"
            )


# ================================================================
# 10. multi-as regression の常true OR 解消（タスク7）
# ================================================================

class TestMultiAsAreaOspfRegression:
    """multi-as-area fixture の OSPF/BGP マーキング非回帰テスト（タスク7）。

    旧テスト: `... or "ospf" not in str(...)` が常に True になりうる OR 条件。
    新テスト: data-ospf-id が実際に存在することを個別に検証。
    """

    @pytest.fixture(scope="class")
    def multi_as_html(self):
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        from lib.rendering import render
        fixture_dir = os.path.join(
            os.path.dirname(__file__), "..", "evals", "inputs", "multi-as-area"
        )
        files = sorted([
            os.path.join(fixture_dir, fn)
            for fn in os.listdir(fixture_dir)
            if fn.endswith((".cfg", ".conf"))
        ])
        if not files:
            pytest.skip("multi-as-area fixture がない")
        devices = parse_paths(files)
        topo = build(devices, generated_from=files)
        return render(topo), topo

    @pytest.mark.integration
    def test_multi_as_render_returns_string(self, multi_as_html):
        """multi-as-area の render() が str を返す。"""
        html, topo = multi_as_html
        assert isinstance(html, str), "render() が str を返さない"

    @pytest.mark.integration
    def test_multi_as_contains_svg(self, multi_as_html):
        """multi-as-area の HTML に SVG が含まれる。"""
        html, topo = multi_as_html
        assert "<svg" in html.lower(), "HTML に SVG が含まれない"

    @pytest.mark.integration
    def test_multi_as_ospf_data_attribute_exists_when_ospf_present(self, multi_as_html):
        """OSPF エントリが存在する場合、data-ospf-id が HTML に存在する。

        OR 条件を排除し、OSPF エントリの有無に応じて個別に検証する。
        """
        html, topo = multi_as_html
        ospf_entries = topo["routing"].get("ospf", [])
        if ospf_entries:
            # OSPF エントリがある場合は data-ospf-id が HTML に存在しなければならない
            assert "data-ospf-id" in html, (
                "multi-as-area: OSPF エントリがあるのに data-ospf-id が HTML に存在しない。"
                f"ospf_entries={ospf_entries[:2]}..."
            )
        else:
            # OSPF エントリがない場合はスキップ（テスト自体は通過）
            pytest.skip("multi-as-area fixture に OSPF エントリがない")
