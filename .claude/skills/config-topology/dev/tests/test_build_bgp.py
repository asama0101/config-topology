"""§7.3 BGP 対向解決（local_ip / type / 片側オーバーレイ）のテスト。"""
import pytest

from lib.models import Address, BgpNeighbor, Device, Interface
from lib.build import build_bgp

pytestmark = pytest.mark.unit


def _dev(hostname, asn, ifs, nbs):
    d = Device(hostname=hostname, vendor="cisco_ios", as_=asn)
    d.interfaces = ifs
    d.bgp = nbs
    return d


def test_ebgp_with_local_ip_resolved():
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4")])
    bgp = build_bgp([("r1", r1)])
    assert bgp == [{"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                    "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4"}]


def test_ibgp_same_as():
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65001, "v4")])
    assert build_bgp([("r1", r1)])[0]["type"] == "ibgp"


def test_unknown_peer_as_none():
    r1 = _dev("R1", 65001, [], [BgpNeighbor("203.0.113.9", None, "v4")])
    e = build_bgp([("r1", r1)])[0]
    assert e["type"] == "unknown" and e["peer_as"] is None and e["local_ip"] is None


def test_local_ip_none_when_no_matching_subnet():
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "192.168.1.1", 24)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4")])
    assert build_bgp([("r1", r1)])[0]["local_ip"] is None


def test_v6_neighbor_uses_v6_local_ip():
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v6", "2001:db8::1", 64),
                                                Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("2001:db8::2", 65002, "v6")])
    e = build_bgp([("r1", r1)])[0]
    assert e["af"] == "v6" and e["local_ip"] == "2001:db8::1"


def test_v6_link_local_not_used_as_local_ip():
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v6", "fe80::1", 64, scope="link-local")])],
              [BgpNeighbor("fe80::2", 65002, "v6")])
    # link-local は local_ip に使わない → None
    assert build_bgp([("r1", r1)])[0]["local_ip"] is None


def test_unknown_when_local_as_none():
    from lib.models import BgpNeighbor, Device
    d = Device(hostname="X", vendor="juniper_junos", as_=None)
    d.interfaces = []
    d.bgp = [BgpNeighbor("10.0.0.2", 65002, "v4")]
    e = build_bgp([("x", d)])[0]
    assert e["local_as"] is None
    assert e["type"] == "unknown"          # local_as 不明 → unknown（両者既知でないと ebgp にしない）


# ---------------------------------------------------------------------------
# C1: update_source フォールバックによる local_ip 解決テスト
# ---------------------------------------------------------------------------

def test_ibgp_loopback_update_source_ifname_resolves_local_ip():
    """iBGP over loopback: サブネット一致が None でも update-source Loopback0 で local_ip が解決されること。"""
    # Arrange: R1 は Gi0/0 (10.0.0.1/30) と Loopback0 (1.1.1.1/32) を持つ。
    #          neighbor は 2.2.2.2（別セグメント）→ サブネット一致では None。
    #          update-source Loopback0 → Loopback0 の 1.1.1.1 を local_ip に解決。
    r1 = _dev("R1", 65001,
              [Interface(name="GigabitEthernet0/0",
                         addresses=[Address("v4", "10.0.0.1", 30)]),
               Interface(name="Loopback0",
                         addresses=[Address("v4", "1.1.1.1", 32)])],
              [BgpNeighbor("2.2.2.2", 65001, "v4", update_source="Loopback0")])
    bgp = build_bgp([("r1", r1)])
    assert bgp[0]["local_ip"] == "1.1.1.1"


def test_ibgp_loopback_update_source_ip_resolves_local_ip():
    """JunOS local-address（IP 直接指定）で local_ip が解決されること。"""
    # Arrange: neighbor 2.2.2.2（直結外）、update_source="1.1.1.1"（v4 IP 文字列）
    r1 = _dev("R1", 65001,
              [Interface(name="ge-0/0/0",
                         addresses=[Address("v4", "10.0.0.1", 30)]),
               Interface(name="lo0",
                         addresses=[Address("v4", "1.1.1.1", 32)])],
              [BgpNeighbor("2.2.2.2", 65001, "v4", update_source="1.1.1.1")])
    bgp = build_bgp([("r1", r1)])
    assert bgp[0]["local_ip"] == "1.1.1.1"


def test_subnet_match_unchanged_when_update_source_present():
    """サブネット一致が成功する場合、update_source があっても既存ロジックの結果を使うこと（不変）。"""
    # Arrange: neighbor 10.0.0.2 は Gi0 の 10.0.0.0/30 サブネット内 → サブネット一致が成功
    r1 = _dev("R1", 65001,
              [Interface(name="GigabitEthernet0/0",
                         addresses=[Address("v4", "10.0.0.1", 30)]),
               Interface(name="Loopback0",
                         addresses=[Address("v4", "1.1.1.1", 32)])],
              [BgpNeighbor("10.0.0.2", 65001, "v4", update_source="Loopback0")])
    bgp = build_bgp([("r1", r1)])
    # サブネット一致が優先され Gi0 の 10.0.0.1 になること（Loopback0 ではない）
    assert bgp[0]["local_ip"] == "10.0.0.1"


def test_update_source_nonexistent_ifname_returns_none():
    """update_source に存在しない IF 名が指定されている場合、local_ip は None のままであること。"""
    # Arrange: update_source="Loopback99" だが Loopback99 は存在しない
    r1 = _dev("R1", 65001,
              [Interface(name="GigabitEthernet0/0",
                         addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("2.2.2.2", 65001, "v4", update_source="Loopback99")])
    bgp = build_bgp([("r1", r1)])
    assert bgp[0]["local_ip"] is None


def test_update_source_ip_af_mismatch_returns_none():
    """update_source が IP（JunOS local-address）で AF が一致しない場合、local_ip は None になること。"""
    # Arrange: af="v4" の neighbor だが update_source="2001:db8::1"（v6 IP）
    r1 = _dev("R1", 65001,
              [Interface(name="lo0",
                         addresses=[Address("v6", "2001:db8::1", 128)])],
              [BgpNeighbor("10.0.0.2", 65001, "v4", update_source="2001:db8::1")])
    bgp = build_bgp([("r1", r1)])
    assert bgp[0]["local_ip"] is None


def test_update_source_sets_update_source_field_in_bgp_entry():
    """build_bgp の出力エントリに update_source が値ありのとき 'update_source' キーが含まれること。"""
    r1 = _dev("R1", 65001,
              [Interface(name="Loopback0",
                         addresses=[Address("v4", "1.1.1.1", 32)])],
              [BgpNeighbor("2.2.2.2", 65001, "v4", update_source="Loopback0")])
    bgp = build_bgp([("r1", r1)])
    assert "update_source" in bgp[0]
    assert bgp[0]["update_source"] == "Loopback0"


def test_no_update_source_omits_key_in_bgp_entry():
    """update_source が None（デフォルト）の場合、build_bgp 出力に 'update_source' キーが出ないこと。"""
    r1 = _dev("R1", 65001,
              [Interface(name="GigabitEthernet0/0",
                         addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4")])
    bgp = build_bgp([("r1", r1)])
    # update_source なし → キー省略（golden byte 不変）
    assert "update_source" not in bgp[0]


# ---------------------------------------------------------------------------
# C1 [correctness MED]: _resolve_local_ip — IP 直指定ブランチの link-local 除外
# ---------------------------------------------------------------------------

def test_update_source_link_local_ip_v6_returns_none():
    """update_source が link-local アドレス（fe80::1）の v6 neighbor で local_ip が None になること。

    サブネット一致ブランチ・IF 名解決ブランチが link-local を除外するのと整合。
    IP 直指定ブランチ（JunOS local-address）でも is_link_local なら None を返すこと。
    """
    # Arrange: v6 neighbor、update_source が link-local IP
    r1 = _dev("R1", 65001,
              [Interface(name="lo0",
                         addresses=[Address("v6", "2001:db8::1", 128)])],
              [BgpNeighbor("2001:db8::2", 65001, "v6", update_source="fe80::1")])
    # Act
    bgp = build_bgp([("r1", r1)])
    # Assert: link-local の update_source は local_ip に使わない → None
    assert bgp[0]["local_ip"] is None


# ---------------------------------------------------------------------------
# C4: build_bgp — route_reflector_client / next_hop_self 透過テスト
# ---------------------------------------------------------------------------

def test_build_bgp_rrc_true_emits_key():
    """route_reflector_client=True の BgpNeighbor を持つ Device の build_bgp 出力に 'route_reflector_client': True が含まれること。"""
    # Arrange
    r1 = _dev("RR", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65001, "v4", route_reflector_client=True)])
    # Act
    bgp = build_bgp([("rr", r1)])
    # Assert
    assert bgp[0].get("route_reflector_client") is True


def test_build_bgp_rrc_false_omits_key():
    """route_reflector_client=False（デフォルト）の場合、build_bgp 出力に 'route_reflector_client' キーが出ないこと（golden byte 不変）。"""
    # Arrange
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4")])
    # Act
    bgp = build_bgp([("r1", r1)])
    # Assert
    assert "route_reflector_client" not in bgp[0]


def test_build_bgp_nhs_true_emits_key():
    """next_hop_self=True の BgpNeighbor の build_bgp 出力に 'next_hop_self': True が含まれること。"""
    # Arrange
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4", next_hop_self=True)])
    # Act
    bgp = build_bgp([("r1", r1)])
    # Assert
    assert bgp[0].get("next_hop_self") is True


def test_build_bgp_nhs_false_omits_key():
    """next_hop_self=False（デフォルト）の場合、build_bgp 出力に 'next_hop_self' キーが出ないこと（golden byte 不変）。"""
    # Arrange
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4")])
    # Act
    bgp = build_bgp([("r1", r1)])
    # Assert
    assert "next_hop_self" not in bgp[0]


def test_build_bgp_both_flags_true():
    """route_reflector_client=True かつ next_hop_self=True の場合、両キーが build_bgp 出力に含まれること。"""
    # Arrange
    r1 = _dev("RR", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65001, "v4",
                           route_reflector_client=True, next_hop_self=True)])
    # Act
    bgp = build_bgp([("rr", r1)])
    # Assert
    assert bgp[0].get("route_reflector_client") is True
    assert bgp[0].get("next_hop_self") is True


def test_build_bgp_golden_unchanged_no_flags():
    """フラグなし（デフォルト）の場合、build_bgp 出力の基本キー集合が既存 golden と一致すること（byte 不変確認）。"""
    # Arrange: 既存 golden と同じ構成（update_source なし、フラグなし）
    r1 = _dev("R1", 65001,
              [Interface(name="GigabitEthernet0/0",
                         addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4")])
    # Act
    bgp = build_bgp([("r1", r1)])
    e = bgp[0]
    # Assert: 既存フィールドのみ含むこと（新規フラグキーが混入しない）
    expected_keys = {"device", "local_as", "local_ip", "neighbor_ip", "peer_as", "type", "af"}
    assert set(e.keys()) == expected_keys


# ---------------------------------------------------------------------------
# C4b: build_bgp — timers / send_community 透過テスト
# ---------------------------------------------------------------------------

def test_build_bgp_timers_emits_key():
    """timers=(10, 30) の BgpNeighbor の build_bgp 出力に 'timers': {"keepalive": 10, "holdtime": 30} が含まれること。"""
    # Arrange
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65001, "v4", timers=(10, 30))])
    # Act
    bgp = build_bgp([("r1", r1)])
    # Assert
    assert "timers" in bgp[0]
    assert bgp[0]["timers"] == {"keepalive": 10, "holdtime": 30}


def test_build_bgp_timers_none_omits_key():
    """timers=None（デフォルト）の場合、build_bgp 出力に 'timers' キーが出ないこと（golden byte 不変）。"""
    # Arrange
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4")])
    # Act
    bgp = build_bgp([("r1", r1)])
    # Assert
    assert "timers" not in bgp[0]


def test_build_bgp_send_community_emits_key():
    """send_community='both' の BgpNeighbor の build_bgp 出力に 'send_community': 'both' が含まれること。"""
    # Arrange
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4", send_community="both")])
    # Act
    bgp = build_bgp([("r1", r1)])
    # Assert
    assert "send_community" in bgp[0]
    assert bgp[0]["send_community"] == "both"


def test_build_bgp_send_community_none_omits_key():
    """send_community=None（デフォルト）の場合、build_bgp 出力に 'send_community' キーが出ないこと（golden byte 不変）。"""
    # Arrange
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4")])
    # Act
    bgp = build_bgp([("r1", r1)])
    # Assert
    assert "send_community" not in bgp[0]


def test_build_bgp_timers_and_send_community_combined():
    """timers と send_community が同時に設定されたとき、build_bgp 出力に両キーが含まれること。"""
    # Arrange
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4",
                           timers=(10, 30), send_community="standard")])
    # Act
    bgp = build_bgp([("r1", r1)])
    e = bgp[0]
    # Assert
    assert e["timers"] == {"keepalive": 10, "holdtime": 30}
    assert e["send_community"] == "standard"


def test_build_bgp_golden_unchanged_with_new_fields_absent():
    """timers=None かつ send_community=None の場合、build_bgp 出力の既存キー集合が変わらないこと（golden byte 不変）。"""
    # Arrange
    r1 = _dev("R1", 65001,
              [Interface(name="GigabitEthernet0/0",
                         addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4")])
    # Act
    bgp = build_bgp([("r1", r1)])
    e = bgp[0]
    # Assert: 新規フィールドが混入しない（既存 golden と同一キー集合）
    expected_keys = {"device", "local_as", "local_ip", "neighbor_ip", "peer_as", "type", "af"}
    assert set(e.keys()) == expected_keys


# ---------------------------------------------------------------------------
# C1b: build_bgp — peer_group 透過テスト（omit-when-None）
# ---------------------------------------------------------------------------

def test_build_bgp_peer_group_passthrough():
    """peer_group="PG" の BgpNeighbor の build_bgp 出力に 'peer_group': 'PG' が含まれること。

    壊すと peer_group が出力されない → アサート失敗（壊すと赤）。
    """
    # Arrange
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.5", 65010, "v4", peer_group="PG")])
    # Act
    bgp = build_bgp([("r1", r1)])
    # Assert
    assert "peer_group" in bgp[0]
    assert bgp[0]["peer_group"] == "PG"


def test_build_bgp_peer_group_none_omits_key():
    """peer_group=None（デフォルト）の場合、build_bgp 出力に 'peer_group' キーが出ないこと（golden byte 不変）。

    壊すと 'peer_group': None が混入し既存 golden が変化 → アサート失敗（壊すと赤）。
    """
    # Arrange
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4")])
    # Act
    bgp = build_bgp([("r1", r1)])
    # Assert
    assert "peer_group" not in bgp[0]
    expected_keys = {"device", "local_as", "local_ip", "neighbor_ip", "peer_as", "type", "af"}
    assert set(bgp[0].keys()) == expected_keys


# ---------------------------------------------------------------------------
# #7: build_bgp — bgp_type 明示フィールドによる type 判定優先
# ---------------------------------------------------------------------------

def test_build_bgp_explicit_bgp_type_ibgp_overrides_as_comparison():
    """BgpNeighbor.bgp_type='ibgp' が設定されていると、peer_as!=local_as でも type='ibgp' になること。

    group type internal + peer-as 異なる JunOS ケースをモデル化。
    """
    # Arrange: local_as=65001, peer_as=65002 なら通常は ebgp だが、
    #          bgp_type='ibgp' 明示があれば ibgp になること。
    nb = BgpNeighbor("10.0.0.2", 65002, "v4")
    nb.bgp_type = "ibgp"
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [nb])
    # Act
    bgp = build_bgp([("r1", r1)])
    # Assert
    assert bgp[0]["type"] == "ibgp"


def test_build_bgp_explicit_bgp_type_ebgp_overrides_as_comparison():
    """BgpNeighbor.bgp_type='ebgp' が設定されていると、peer_as==local_as でも type='ebgp' になること。"""
    # Arrange: local_as=65001, peer_as=65001 なら通常は ibgp だが、
    #          bgp_type='ebgp' 明示があれば ebgp になること。
    nb = BgpNeighbor("10.0.0.2", 65001, "v4")
    nb.bgp_type = "ebgp"
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [nb])
    # Act
    bgp = build_bgp([("r1", r1)])
    # Assert
    assert bgp[0]["type"] == "ebgp"


def test_build_bgp_explicit_local_as_used_for_type_when_bgp_type_absent():
    """BgpNeighbor.bgp_type=None だが local_as が設定されている場合、
    local_as vs peer_as で type を判定すること。

    local_as=65099（neighbor 個別）, peer_as=65099 → ibgp と判定。
    """
    # Arrange
    nb = BgpNeighbor("203.0.113.1", 65099, "v4")
    nb.local_as = 65099   # 個別 local-as と peer-as が一致 → ibgp
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [nb])
    # Act
    bgp = build_bgp([("r1", r1)])
    # Assert
    assert bgp[0]["type"] == "ibgp"


def test_build_bgp_local_as_overrides_device_as_for_type():
    """BgpNeighbor.local_as が設定されている場合、Device.as_ ではなく nb.local_as で type を判定すること。

    Device.as_=65001, nb.local_as=65099, peer_as=65001 → Device.as_ vs peer_as なら ibgp だが、
    nb.local_as(65099) vs peer_as(65001) → ebgp になること。
    """
    # Arrange
    nb = BgpNeighbor("10.0.0.2", 65001, "v4")
    nb.local_as = 65099   # Device.as_=65001 だが local_as=65099 → peer_as=65001 と異なる → ebgp
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [nb])
    # Act
    bgp = build_bgp([("r1", r1)])
    # Assert
    assert bgp[0]["type"] == "ebgp"


def test_build_bgp_bgp_type_none_local_as_none_falls_back_to_device_as():
    """bgp_type=None, local_as=None の場合、従来通り Device.as_ vs peer_as で判定すること（回帰）。"""
    # Arrange: 既存の動作が変わらないことを保証
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4")])
    bgp = build_bgp([("r1", r1)])
    assert bgp[0]["type"] == "ebgp"   # 65001 != 65002 → ebgp（従来通り）


def test_build_bgp_bgp_type_none_local_as_none_ibgp_regression():
    """bgp_type=None, local_as=None の場合、peer_as==Device.as_ → ibgp（回帰）。"""
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65001, "v4")])
    bgp = build_bgp([("r1", r1)])
    assert bgp[0]["type"] == "ibgp"
