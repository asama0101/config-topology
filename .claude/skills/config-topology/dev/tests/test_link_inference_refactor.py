"""
回帰固定テスト: _infer_links_and_segments リファクタ用

目的:
  _infer_links_and_segments のリファクタ（if/else → 単一 addresses ループへの統一）前後で
  出力が完全に同一であることを保証するための回帰テスト。

テストケース:
  1. IPv4-only (addresses なし, ip フィールドのみ) の 2 台 → link が 1 本生成される
  2. dual-stack (v4 + v6 addresses) の 2 台 → v4/v6 双方の link が生成される
  3. 同一サブネット 3 台 → segment が 1 個生成される
  4. link-local アドレスのみの IF は結線されない
  5. prefix=0 の境界値
  6. shutdown=True の IF は除外される
  7. ip=None の IF は除外される
  8. 同一機器内の同一サブネット → 自己ループを作らない
  9. addresses あり (v4 のみ) で 2 台 → link が 1 本生成される
 10. segment の id / subnet / members が正しい
"""

from __future__ import annotations

import pytest

from lib.parsers.base import (
    AF_V4,
    AF_V6,
    SCOPE_LINK_LOCAL,
    Device,
    Interface,
    OspfNetwork,
)


# ================================================================
# ヘルパー
# ================================================================

def make_device(hostname: str, interfaces: list[Interface] | None = None) -> Device:
    return Device(
        hostname=hostname,
        vendor="cisco_ios",
        asn=None,
        interfaces=interfaces or [],
    )


def make_iface_ip_only(name: str, ip: str | None, shutdown: bool = False) -> Interface:
    """旧形式: addresses なし、ip フィールドのみ設定した Interface を返す。"""
    return Interface(name=name, ip=ip, description=None, shutdown=shutdown)


def make_iface_with_addresses(
    name: str,
    addresses: list[dict],
    shutdown: bool = False,
) -> Interface:
    """新形式: addresses あり（ip フィールドは addresses から派生）の Interface を返す。"""
    # ip は _infer_links_and_segments では addresses から計算するが、
    # Interface の ip フィールドは必須引数のため None をセットしておく。
    # （addresses が設定されていれば ip フィールドは参照されない）
    iface = Interface(name=name, ip=None, description=None, shutdown=shutdown)
    iface.addresses = addresses
    return iface


def run_infer(devices: list[Device]) -> tuple[list[dict], list[dict]]:
    """_infer_links_and_segments を直接呼び出す。"""
    from scripts.build_topology import _assign_device_ids, _infer_links_and_segments

    device_ids = _assign_device_ids(devices)
    return _infer_links_and_segments(devices, device_ids)


# ================================================================
# テストクラス
# ================================================================

class TestLinkInferenceIPv4Only:
    """Case 1: IPv4-only, addresses なし (旧形式 ip フィールドのみ) の回帰テスト。"""

    @pytest.mark.unit
    def test_two_devices_same_subnet_creates_one_link(self):
        """旧形式 ip フィールドを持つ 2 台が同一サブネット → link が 1 本生成される。"""
        # Arrange
        d1 = make_device("R1", [make_iface_ip_only("eth0", "10.0.0.1/30")])
        d2 = make_device("R2", [make_iface_ip_only("eth0", "10.0.0.2/30")])

        # Act
        links, segments = run_infer([d1, d2])

        # Assert
        assert len(links) == 1
        assert segments == []

    @pytest.mark.unit
    def test_link_fields_correct_for_ip_only(self):
        """旧形式 ip フィールドのみ: link フィールドが正しい。"""
        # Arrange
        d1 = make_device("R1", [make_iface_ip_only("GigabitEthernet0/0", "10.0.0.1/30")])
        d2 = make_device("R2", [make_iface_ip_only("ge-0/0/0", "10.0.0.2/30")])

        # Act
        links, segments = run_infer([d1, d2])

        # Assert
        link = links[0]
        assert link["a_device"] == "r1"
        assert link["a_if"] == "GigabitEthernet0/0"
        assert link["b_device"] == "r2"
        assert link["b_if"] == "ge-0/0/0"
        assert link["subnet"] == "10.0.0.0/30"
        assert link["kind"] == "inferred-subnet"

    @pytest.mark.unit
    def test_ip_none_if_excluded(self):
        """ip=None の IF は結線から除外される。"""
        # Arrange
        d1 = make_device("R1", [make_iface_ip_only("eth0", None)])
        d2 = make_device("R2", [make_iface_ip_only("eth0", "10.0.0.2/30")])

        # Act
        links, segments = run_infer([d1, d2])

        # Assert
        assert links == []
        assert segments == []

    @pytest.mark.unit
    def test_shutdown_if_creates_admin_down_link(self):
        """shutdown=True の IF が対向 up IF と同一サブネット → admin_down=True のリンクを生成する。
        （旧: shutdown IF は結線から除外された。admin_down リンク機能追加により仕様変更。）
        """
        # Arrange
        d1 = make_device("R1", [make_iface_ip_only("eth0", "10.0.0.1/30", shutdown=True)])
        d2 = make_device("R2", [make_iface_ip_only("eth0", "10.0.0.2/30")])

        # Act
        links, segments = run_infer([d1, d2])

        # Assert
        assert len(links) == 1
        assert links[0].get("admin_down") is True
        assert segments == []

    @pytest.mark.unit
    def test_same_device_same_subnet_no_self_loop(self):
        """同一機器内の 2 IF が同一サブネット → 自己ループを作らない。"""
        # Arrange
        d1 = make_device("R1", [
            make_iface_ip_only("eth0", "10.0.0.1/30"),
            make_iface_ip_only("eth1", "10.0.0.2/30"),
        ])

        # Act
        links, segments = run_infer([d1])

        # Assert
        assert links == []
        assert segments == []

    @pytest.mark.unit
    def test_prefix_zero_boundary(self):
        """prefix=0 (0.0.0.0/0) の境界値: network が 0.0.0.0/0 になっても処理できる。"""
        # Arrange
        d1 = make_device("R1", [make_iface_ip_only("eth0", "10.0.0.1/0")])
        d2 = make_device("R2", [make_iface_ip_only("eth0", "10.0.0.2/0")])

        # Act
        links, segments = run_infer([d1, d2])

        # Assert: 同一 /0 ネットワークなので link が 1 本
        assert len(links) == 1

    @pytest.mark.unit
    def test_invalid_ip_excluded_gracefully(self):
        """不正な ip 文字列は ValueError で除外されクラッシュしない。"""
        # Arrange
        d1 = make_device("R1", [make_iface_ip_only("eth0", "not-an-ip")])
        d2 = make_device("R2", [make_iface_ip_only("eth0", "10.0.0.2/30")])

        # Act
        links, segments = run_infer([d1, d2])

        # Assert: d1 の IF は除外されスタブに
        assert links == []


class TestLinkInferenceDualStack:
    """Case 2: dual-stack (addresses あり) の回帰テスト。"""

    @pytest.mark.unit
    def test_addresses_v4_creates_link(self):
        """addresses (v4) を持つ 2 台が同一サブネット → v4 link が生成される。"""
        # Arrange
        addrs1 = [{"af": AF_V4, "ip": "10.0.0.1", "prefix": 30}]
        addrs2 = [{"af": AF_V4, "ip": "10.0.0.2", "prefix": 30}]
        d1 = make_device("R1", [make_iface_with_addresses("eth0", addrs1)])
        d2 = make_device("R2", [make_iface_with_addresses("eth0", addrs2)])

        # Act
        links, segments = run_infer([d1, d2])

        # Assert
        assert len(links) == 1
        assert links[0]["subnet"] == "10.0.0.0/30"

    @pytest.mark.unit
    def test_dual_stack_creates_both_v4_and_v6_links(self):
        """dual-stack (v4 + v6) の 2 台 → v4/v6 双方の link が生成される。"""
        # Arrange
        addrs1 = [
            {"af": AF_V4, "ip": "10.0.0.1", "prefix": 30},
            {"af": AF_V6, "ip": "2001:db8::1", "prefix": 64},
        ]
        addrs2 = [
            {"af": AF_V4, "ip": "10.0.0.2", "prefix": 30},
            {"af": AF_V6, "ip": "2001:db8::2", "prefix": 64},
        ]
        d1 = make_device("R1", [make_iface_with_addresses("eth0", addrs1)])
        d2 = make_device("R2", [make_iface_with_addresses("eth0", addrs2)])

        # Act
        links, segments = run_infer([d1, d2])

        # Assert: v4 と v6 で link が 2 本
        assert len(links) == 2
        subnets = {l["subnet"] for l in links}
        assert "10.0.0.0/30" in subnets
        assert "2001:db8::/64" in subnets

    @pytest.mark.unit
    def test_link_local_only_if_excluded(self):
        """link-local アドレスのみの IF は結線されない。"""
        # Arrange
        addrs1 = [{"af": AF_V6, "ip": "fe80::1", "prefix": 64, "scope": SCOPE_LINK_LOCAL}]
        addrs2 = [{"af": AF_V6, "ip": "fe80::2", "prefix": 64, "scope": SCOPE_LINK_LOCAL}]
        d1 = make_device("R1", [make_iface_with_addresses("eth0", addrs1)])
        d2 = make_device("R2", [make_iface_with_addresses("eth0", addrs2)])

        # Act
        links, segments = run_infer([d1, d2])

        # Assert: link-local は除外されるため link なし
        assert links == []
        assert segments == []

    @pytest.mark.unit
    def test_link_local_without_scope_field_excluded_by_ip_check(self):
        """scope フィールドなしでも fe80:: アドレスは link-local として除外される。"""
        # Arrange: scope フィールドなしで fe80:: を直接渡す
        addrs1 = [{"af": AF_V6, "ip": "fe80::1", "prefix": 10}]
        addrs2 = [{"af": AF_V6, "ip": "fe80::2", "prefix": 10}]
        d1 = make_device("R1", [make_iface_with_addresses("eth0", addrs1)])
        d2 = make_device("R2", [make_iface_with_addresses("eth0", addrs2)])

        # Act
        links, segments = run_infer([d1, d2])

        # Assert: is_link_local チェックで除外される
        assert links == []

    @pytest.mark.unit
    def test_same_if_dual_v4_only_registered_once(self):
        """同一 IF が同一 network に複数アドレスを持っても members に IF は 1 回のみ登録される。"""
        # Arrange: primary + secondary で同一 /24 に属するアドレス
        addrs1 = [
            {"af": AF_V4, "ip": "192.168.1.1", "prefix": 24},
            {"af": AF_V4, "ip": "192.168.1.10", "prefix": 24, "secondary": True},
        ]
        addrs2 = [{"af": AF_V4, "ip": "192.168.1.2", "prefix": 24}]
        d1 = make_device("R1", [make_iface_with_addresses("eth0", addrs1)])
        d2 = make_device("R2", [make_iface_with_addresses("eth0", addrs2)])

        # Act
        links, segments = run_infer([d1, d2])

        # Assert: dedup により members=2 → link が 1 本（segment にならない）
        assert len(links) == 1
        assert segments == []


class TestLinkInferenceSegment:
    """Case 3: 3 台以上が同一サブネット → segment の回帰テスト。"""

    @pytest.mark.unit
    def test_three_devices_creates_segment(self):
        """同一サブネット 3 台 → segment が 1 個生成される。"""
        # Arrange
        d1 = make_device("SW1", [make_iface_ip_only("eth0", "192.168.1.1/24")])
        d2 = make_device("SW2", [make_iface_ip_only("eth0", "192.168.1.2/24")])
        d3 = make_device("SW3", [make_iface_ip_only("eth0", "192.168.1.3/24")])

        # Act
        links, segments = run_infer([d1, d2, d3])

        # Assert
        assert links == []
        assert len(segments) == 1

    @pytest.mark.unit
    def test_segment_fields_correct(self):
        """segment の id / subnet / members が正しい。"""
        # Arrange
        d1 = make_device("SW1", [make_iface_ip_only("eth0", "192.168.1.1/24")])
        d2 = make_device("SW2", [make_iface_ip_only("eth0", "192.168.1.2/24")])
        d3 = make_device("SW3", [make_iface_ip_only("eth0", "192.168.1.3/24")])

        # Act
        links, segments = run_infer([d1, d2, d3])

        # Assert
        seg = segments[0]
        assert seg["id"] == "seg-192_168_1_0_24"
        assert seg["subnet"] == "192.168.1.0/24"
        assert sorted(seg["members"]) == ["sw1::eth0", "sw2::eth0", "sw3::eth0"]

    @pytest.mark.unit
    def test_segment_members_sorted(self):
        """segment members は昇順ソート済みであること（決定性）。"""
        # Arrange
        d1 = make_device("ZZZ", [make_iface_ip_only("eth0", "10.1.1.1/24")])
        d2 = make_device("AAA", [make_iface_ip_only("eth0", "10.1.1.2/24")])
        d3 = make_device("MMM", [make_iface_ip_only("eth0", "10.1.1.3/24")])

        # Act
        links, segments = run_infer([d1, d2, d3])

        # Assert
        members = segments[0]["members"]
        assert members == sorted(members)

    @pytest.mark.unit
    def test_seg_id_uses_correct_replace_pattern(self):
        """seg_id は network_str の '.' を '_'、'/' を '_' に置換した形式。"""
        # Arrange
        d1 = make_device("A", [make_iface_ip_only("eth0", "10.1.2.1/28")])
        d2 = make_device("B", [make_iface_ip_only("eth0", "10.1.2.2/28")])
        d3 = make_device("C", [make_iface_ip_only("eth0", "10.1.2.3/28")])

        # Act
        links, segments = run_infer([d1, d2, d3])

        # Assert: "10.1.2.0/28" → "10_1_2_0_28"
        assert segments[0]["id"] == "seg-10_1_2_0_28"


class TestLinkInferenceEquivalence:
    """IP フィールドと addresses の等価性確認テスト。

    リファクタの核心: ip フィールドのみのケースと addresses フィールドに変換したケースで
    まったく同じ links/segments が生成されることを確認する。
    """

    @pytest.mark.unit
    def test_ip_only_vs_addresses_same_result(self):
        """ip フィールドのみ vs addresses フィールドで同一の link が生成される。"""
        # Arrange: 旧形式（ip のみ）
        d1_old = make_device("R1", [make_iface_ip_only("eth0", "172.16.0.1/29")])
        d2_old = make_device("R2", [make_iface_ip_only("eth0", "172.16.0.2/29")])

        # Arrange: 新形式（addresses）
        d1_new = make_device("R1", [make_iface_with_addresses("eth0", [
            {"af": AF_V4, "ip": "172.16.0.1", "prefix": 29}
        ])])
        d2_new = make_device("R2", [make_iface_with_addresses("eth0", [
            {"af": AF_V4, "ip": "172.16.0.2", "prefix": 29}
        ])])

        # Act
        links_old, segs_old = run_infer([d1_old, d2_old])
        links_new, segs_new = run_infer([d1_new, d2_new])

        # Assert: subnet と kind が一致すること（a/b は同一 hostname のため同一）
        assert links_old[0]["subnet"] == links_new[0]["subnet"]
        assert links_old[0]["kind"] == links_new[0]["kind"]
        assert segs_old == segs_new == []

    @pytest.mark.unit
    def test_addresses_empty_vs_ip_none_both_excluded(self):
        """addresses=[] かつ ip=None の IF は除外される（旧形式フォールバックと等価）。"""
        # Arrange
        iface = Interface(name="eth0", ip=None, description=None, shutdown=False)
        iface.addresses = []
        d = make_device("R1", [iface])
        d2 = make_device("R2", [make_iface_ip_only("eth0", "10.0.0.2/30")])

        # Act
        links, segments = run_infer([d, d2])

        # Assert
        assert links == []
        assert segments == []


# ================================================================
# ヘルパー（OSPF テスト用）
# ================================================================

def make_device_with_ospf(
    hostname: str,
    interfaces: list[Interface],
    ospf_entries: list[OspfNetwork],
) -> Device:
    """OSPF エントリ付き Device を生成するファクトリ関数。"""
    dev = Device(
        hostname=hostname,
        vendor="cisco_ios",
        asn=None,
        interfaces=interfaces,
        ospf=ospf_entries,
    )
    return dev


def run_build(devices: list[Device]) -> dict:
    """build() を直接呼び出し、topology dict を返す。"""
    from scripts.build_topology import build

    filenames = [f"{dev.hostname}.cfg" for dev in devices]
    return build(devices, generated_from=filenames)


# ================================================================
# OSPF アノテーション回帰テスト
# ================================================================

class TestOspfAnnotationLink:
    """links に ospf_area / ospf_network が正しく付与されることを検証する回帰テスト（IPv4）。"""

    @pytest.mark.unit
    def test_link_gets_ospf_area_when_both_ends_same_area(self):
        """両端機器が同一 OSPF area → ospf_area に単一 area 文字列が付与される。"""
        # Arrange
        d1 = make_device_with_ospf(
            "R1",
            interfaces=[make_iface_ip_only("eth0", "10.0.0.1/30")],
            ospf_entries=[OspfNetwork(process=1, network="10.0.0.0/30", area="0")],
        )
        d2 = make_device_with_ospf(
            "R2",
            interfaces=[make_iface_ip_only("eth0", "10.0.0.2/30")],
            ospf_entries=[OspfNetwork(process=1, network="10.0.0.0/30", area="0")],
        )

        # Act
        topo = run_build([d1, d2])
        links = topo["links"]

        # Assert
        assert len(links) == 1
        link = links[0]
        assert link.get("ospf_area") == "0"
        assert link.get("ospf_network") == "10.0.0.0/30"

    @pytest.mark.unit
    def test_link_gets_ospf_area_when_both_ends_different_area(self):
        """両端機器が異なる OSPF area → ospf_area に昇順スラッシュ区切りが付与される。"""
        # Arrange
        d1 = make_device_with_ospf(
            "R1",
            interfaces=[make_iface_ip_only("eth0", "10.1.1.1/30")],
            ospf_entries=[OspfNetwork(process=1, network="10.1.1.0/30", area="0")],
        )
        d2 = make_device_with_ospf(
            "R2",
            interfaces=[make_iface_ip_only("eth0", "10.1.1.2/30")],
            ospf_entries=[OspfNetwork(process=1, network="10.1.1.0/30", area="1")],
        )

        # Act
        topo = run_build([d1, d2])
        links = topo["links"]

        # Assert
        assert len(links) == 1
        link = links[0]
        assert link.get("ospf_area") == "0/1"
        assert link.get("ospf_network") == "10.1.1.0/30"

    @pytest.mark.unit
    def test_link_gets_ospf_area_when_only_one_end_participates(self):
        """片端のみ OSPF 参加 → その端の area が ospf_area に付与される。"""
        # Arrange
        d1 = make_device_with_ospf(
            "R1",
            interfaces=[make_iface_ip_only("eth0", "10.2.2.1/30")],
            ospf_entries=[OspfNetwork(process=1, network="10.2.2.0/30", area="2")],
        )
        # d2 は OSPF 設定なし
        d2 = make_device_with_ospf(
            "R2",
            interfaces=[make_iface_ip_only("eth0", "10.2.2.2/30")],
            ospf_entries=[],
        )

        # Act
        topo = run_build([d1, d2])
        links = topo["links"]

        # Assert
        assert len(links) == 1
        link = links[0]
        assert link.get("ospf_area") == "2"
        assert link.get("ospf_network") == "10.2.2.0/30"

    @pytest.mark.unit
    def test_link_no_ospf_area_when_no_ospf(self):
        """両端とも OSPF 非参加のリンク → ospf_area / ospf_network フィールドが付かない。"""
        # Arrange
        d1 = make_device_with_ospf(
            "R1",
            interfaces=[make_iface_ip_only("eth0", "10.3.3.1/30")],
            ospf_entries=[],
        )
        d2 = make_device_with_ospf(
            "R2",
            interfaces=[make_iface_ip_only("eth0", "10.3.3.2/30")],
            ospf_entries=[],
        )

        # Act
        topo = run_build([d1, d2])
        links = topo["links"]

        # Assert
        assert len(links) == 1
        link = links[0]
        assert "ospf_area" not in link
        assert "ospf_network" not in link

    @pytest.mark.unit
    def test_link_ospf_area_uses_normalized_dotted_decimal(self):
        """JunOS 形式の dotted-decimal area（"0.0.0.0"）は正規化されて "0" になる。"""
        # Arrange: R1 が JunOS 形式（0.0.0.0）、R2 が IOS 形式（"0"）の同一エリア
        d1 = make_device_with_ospf(
            "R1",
            interfaces=[make_iface_ip_only("eth0", "10.4.4.1/30")],
            ospf_entries=[OspfNetwork(process=None, network="10.4.4.0/30", area="0.0.0.0")],
        )
        d2 = make_device_with_ospf(
            "R2",
            interfaces=[make_iface_ip_only("eth0", "10.4.4.2/30")],
            ospf_entries=[OspfNetwork(process=1, network="10.4.4.0/30", area="0")],
        )

        # Act
        topo = run_build([d1, d2])
        links = topo["links"]

        # Assert: 正規化後は同一 area "0" → 単一値（スラッシュ区切りにならない）
        assert len(links) == 1
        link = links[0]
        assert link.get("ospf_area") == "0"
        assert link.get("ospf_network") == "10.4.4.0/30"

    @pytest.mark.unit
    def test_link_ospf_subnet_matching_uses_subnet_of(self):
        """OSPF network 文 の CIDR がリンクサブネットを包含する場合も ospf_area が付与される。

        例: network 10.5.0.0/16 area 1 → link subnet 10.5.1.0/30 は包含される。
        """
        # Arrange
        d1 = make_device_with_ospf(
            "R1",
            interfaces=[make_iface_ip_only("eth0", "10.5.1.1/30")],
            ospf_entries=[OspfNetwork(process=1, network="10.5.0.0/16", area="1")],
        )
        d2 = make_device_with_ospf(
            "R2",
            interfaces=[make_iface_ip_only("eth0", "10.5.1.2/30")],
            ospf_entries=[OspfNetwork(process=1, network="10.5.0.0/16", area="1")],
        )

        # Act
        topo = run_build([d1, d2])
        links = topo["links"]

        # Assert
        assert len(links) == 1
        link = links[0]
        assert link.get("ospf_area") == "1"
        assert link.get("ospf_network") == "10.5.1.0/30"


class TestOspfAnnotationSegment:
    """segments に ospf_area / ospf_network が正しく付与されることを検証する回帰テスト。"""

    @pytest.mark.unit
    def test_segment_gets_ospf_area_when_all_members_same_area(self):
        """全メンバー機器が同一 OSPF area → ospf_area に単一 area 文字列が付与される。"""
        # Arrange: 3 台が同一 /24 サブネット（segment になる）
        d1 = make_device_with_ospf(
            "SW1",
            interfaces=[make_iface_ip_only("eth0", "192.168.10.1/24")],
            ospf_entries=[OspfNetwork(process=1, network="192.168.10.0/24", area="0")],
        )
        d2 = make_device_with_ospf(
            "SW2",
            interfaces=[make_iface_ip_only("eth0", "192.168.10.2/24")],
            ospf_entries=[OspfNetwork(process=1, network="192.168.10.0/24", area="0")],
        )
        d3 = make_device_with_ospf(
            "SW3",
            interfaces=[make_iface_ip_only("eth0", "192.168.10.3/24")],
            ospf_entries=[OspfNetwork(process=1, network="192.168.10.0/24", area="0")],
        )

        # Act
        topo = run_build([d1, d2, d3])
        segments = topo["segments"]

        # Assert
        assert len(segments) == 1
        seg = segments[0]
        assert seg.get("ospf_area") == "0"
        assert seg.get("ospf_network") == "192.168.10.0/24"

    @pytest.mark.unit
    def test_segment_gets_ospf_area_slash_separated_when_mixed_areas(self):
        """メンバー機器の area が混在 → 昇順スラッシュ区切りが付与される。"""
        # Arrange: d1/d2 は area=0、d3 は area=1
        d1 = make_device_with_ospf(
            "SW1",
            interfaces=[make_iface_ip_only("eth0", "192.168.20.1/24")],
            ospf_entries=[OspfNetwork(process=1, network="192.168.20.0/24", area="0")],
        )
        d2 = make_device_with_ospf(
            "SW2",
            interfaces=[make_iface_ip_only("eth0", "192.168.20.2/24")],
            ospf_entries=[OspfNetwork(process=1, network="192.168.20.0/24", area="0")],
        )
        d3 = make_device_with_ospf(
            "SW3",
            interfaces=[make_iface_ip_only("eth0", "192.168.20.3/24")],
            ospf_entries=[OspfNetwork(process=1, network="192.168.20.0/24", area="1")],
        )

        # Act
        topo = run_build([d1, d2, d3])
        segments = topo["segments"]

        # Assert
        assert len(segments) == 1
        seg = segments[0]
        assert seg.get("ospf_area") == "0/1"
        assert seg.get("ospf_network") == "192.168.20.0/24"

    @pytest.mark.unit
    def test_segment_no_ospf_area_when_no_ospf(self):
        """全メンバーが OSPF 非参加 → ospf_area / ospf_network フィールドが付かない。"""
        # Arrange
        d1 = make_device_with_ospf(
            "SW1",
            interfaces=[make_iface_ip_only("eth0", "192.168.30.1/24")],
            ospf_entries=[],
        )
        d2 = make_device_with_ospf(
            "SW2",
            interfaces=[make_iface_ip_only("eth0", "192.168.30.2/24")],
            ospf_entries=[],
        )
        d3 = make_device_with_ospf(
            "SW3",
            interfaces=[make_iface_ip_only("eth0", "192.168.30.3/24")],
            ospf_entries=[],
        )

        # Act
        topo = run_build([d1, d2, d3])
        segments = topo["segments"]

        # Assert
        assert len(segments) == 1
        seg = segments[0]
        assert "ospf_area" not in seg
        assert "ospf_network" not in seg


class TestOspfAnnotationDualStack:
    """dual-stack 環境での OSPF アノテーション回帰テスト（IPv4 + IPv6）。"""

    @pytest.mark.unit
    def test_v4_link_gets_ospf_area_from_ospfv2(self):
        """OSPFv2（af=v4）の network 文 → IPv4 link に ospf_area が付与される。"""
        # Arrange
        addrs1 = [
            {"af": AF_V4, "ip": "10.10.0.1", "prefix": 30},
            {"af": AF_V6, "ip": "2001:db8:a::1", "prefix": 64},
        ]
        addrs2 = [
            {"af": AF_V4, "ip": "10.10.0.2", "prefix": 30},
            {"af": AF_V6, "ip": "2001:db8:a::2", "prefix": 64},
        ]
        d1 = make_device_with_ospf(
            "R1",
            interfaces=[make_iface_with_addresses("eth0", addrs1)],
            ospf_entries=[OspfNetwork(process=1, network="10.10.0.0/30", area="0", af=AF_V4)],
        )
        d2 = make_device_with_ospf(
            "R2",
            interfaces=[make_iface_with_addresses("eth0", addrs2)],
            ospf_entries=[OspfNetwork(process=1, network="10.10.0.0/30", area="0", af=AF_V4)],
        )

        # Act
        topo = run_build([d1, d2])
        links = topo["links"]

        # Assert: v4 link と v6 link の 2 本が生成される
        assert len(links) == 2
        v4_links = [l for l in links if ":" not in l["subnet"]]
        v6_links = [l for l in links if ":" in l["subnet"]]
        assert len(v4_links) == 1
        assert len(v6_links) == 1

        # v4 link には ospf_area が付与されている
        v4_link = v4_links[0]
        assert v4_link.get("ospf_area") == "0"
        assert v4_link.get("ospf_network") == "10.10.0.0/30"

        # v6 link には OSPFv2 の area は付与されない（af 不一致）
        v6_link = v6_links[0]
        assert "ospf_area" not in v6_link

    @pytest.mark.unit
    def test_v6_link_gets_ospf_area_from_ospfv3(self):
        """OSPFv3（af=v6）の network 文 → IPv6 link に ospf_area が付与される。"""
        # Arrange: OSPFv3 エントリを持つ dual-stack 機器
        addrs1 = [
            {"af": AF_V4, "ip": "10.10.1.1", "prefix": 30},
            {"af": AF_V6, "ip": "2001:db8:b::1", "prefix": 64},
        ]
        addrs2 = [
            {"af": AF_V4, "ip": "10.10.1.2", "prefix": 30},
            {"af": AF_V6, "ip": "2001:db8:b::2", "prefix": 64},
        ]
        d1 = make_device_with_ospf(
            "R1",
            interfaces=[make_iface_with_addresses("eth0", addrs1)],
            ospf_entries=[OspfNetwork(process=1, network="2001:db8:b::/64", area="0", af=AF_V6)],
        )
        d2 = make_device_with_ospf(
            "R2",
            interfaces=[make_iface_with_addresses("eth0", addrs2)],
            ospf_entries=[OspfNetwork(process=1, network="2001:db8:b::/64", area="0", af=AF_V6)],
        )

        # Act
        topo = run_build([d1, d2])
        links = topo["links"]

        # Assert: v4/v6 の 2 本
        assert len(links) == 2
        v4_links = [l for l in links if ":" not in l["subnet"]]
        v6_links = [l for l in links if ":" in l["subnet"]]
        assert len(v4_links) == 1
        assert len(v6_links) == 1

        # v6 link には ospf_area が付与されている
        v6_link = v6_links[0]
        assert v6_link.get("ospf_area") == "0"
        assert v6_link.get("ospf_network") == "2001:db8:b::/64"

        # v4 link には OSPFv3 の area は付与されない（af 不一致）
        v4_link = v4_links[0]
        assert "ospf_area" not in v4_link
