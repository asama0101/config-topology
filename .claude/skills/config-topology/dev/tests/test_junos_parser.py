"""§6.2 Juniper JunOS パーサのテスト。附録 B.2 と各マッピング行を検証。"""
import pytest

from lib.parsers.junos import parse_junos

pytestmark = pytest.mark.unit


def _parse(text):
    warnings = []
    return parse_junos(text, warnings), warnings


def test_b2_device_fields(junos_cfg_text):
    dev, _ = _parse(junos_cfg_text)
    assert dev.hostname == "R2"
    assert dev.vendor == "juniper_junos"
    assert dev.as_ == 65002
    assert dev.ospf_router_id is None
    assert dev.bgp_router_id is None


def test_b2_interfaces(junos_cfg_text):
    dev, _ = _parse(junos_cfg_text)
    names = [i.name for i in dev.interfaces]
    assert names == ["ge-0/0/0", "ge-0/0/1", "lo0"]

    ge0 = dev.interfaces[0]
    assert ge0.description == "to-R1"
    assert [(a.af, a.ip, a.prefix) for a in ge0.addresses] == [("v4", "10.0.0.2", 30)]
    assert ge0.derived_ip() == "10.0.0.2/30"
    assert ge0.shutdown is False
    assert ge0.admin_status == "up"
    assert ge0.l2_l3 == "l3"
    assert ge0.switchport is None


def test_b2_bgp(junos_cfg_text):
    dev, _ = _parse(junos_cfg_text)
    assert len(dev.bgp) == 1
    nb = dev.bgp[0]
    assert (nb.neighbor_ip, nb.peer_as, nb.af) == ("10.0.0.1", 65001, "v4")


def test_b2_static(junos_cfg_text):
    dev, _ = _parse(junos_cfg_text)
    assert len(dev.static) == 1
    s = dev.static[0]
    assert (s.prefix, s.next_hop, s.af) == ("0.0.0.0/0", "10.0.0.1", "v4")


def test_b2_no_ospf(junos_cfg_text):
    dev, _ = _parse(junos_cfg_text)
    assert dev.ospf == []


def test_unit_aggregation_multiple_addresses():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.1.1/24\n")
    dev, _ = _parse(text)
    assert len(dev.interfaces) == 1
    assert len(dev.interfaces[0].addresses) == 2


def test_disable_sets_admin_down():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 disable\n")
    dev, _ = _parse(text)
    assert dev.interfaces[0].shutdown is True
    assert dev.interfaces[0].admin_status == "down"


def test_inet6_and_link_local():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8::1/64\n"
            "set interfaces ge-0/0/0 unit 0 family inet6 address fe80::1/64\n")
    dev, _ = _parse(text)
    addrs = {(a.af, a.ip, a.scope) for a in dev.interfaces[0].addresses}
    assert ("v6", "2001:db8::1", None) in addrs
    assert ("v6", "fe80::1", "link-local") in addrs
    assert dev.interfaces[0].l2_l3 == "l3"


def test_ethernet_switching_is_l2():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family ethernet-switching\n")
    dev, _ = _parse(text)
    assert dev.interfaces[0].l2_l3 == "l2"


def test_l2_priority_over_l3():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family ethernet-switching\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/24\n")
    dev, _ = _parse(text)
    assert dev.interfaces[0].l2_l3 == "l2"


def test_mtu_speed_encapsulation():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 mtu 9000\n"
            "set interfaces ge-0/0/0 speed 10g\n"
            "set interfaces ge-0/0/0 encapsulation flexible-ethernet-services\n")
    dev, _ = _parse(text)
    i = dev.interfaces[0]
    assert i.mtu == 9000 and i.speed == "10g"
    assert i.encapsulation == "flexible-ethernet-services"


def test_router_id_sets_bgp_and_ospf_fallback():
    text = ("set system host-name X\n"
            "set routing-options router-id 9.9.9.9\n")
    dev, _ = _parse(text)
    assert dev.bgp_router_id == "9.9.9.9"
    assert dev.ospf_router_id == "9.9.9.9"


def test_v6_bgp_neighbor():
    text = ("set system host-name X\n"
            "set protocols bgp group g neighbor 2001:db8::2 peer-as 65010\n")
    dev, _ = _parse(text)
    nb = dev.bgp[0]
    assert (nb.neighbor_ip, nb.peer_as, nb.af) == ("2001:db8::2", 65010, "v6")


def test_ospf_v2_network_from_if_subnet():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 192.168.5.1/24\n"
            "set protocols ospf area 0.0.0.0 interface ge-0/0/0.0\n")
    dev, _ = _parse(text)
    o = dev.ospf[0]
    assert (o.process, o.network, o.area, o.af) == (None, "192.168.5.0/24", "0", "v4")


def test_ospf3_network_is_base_if_name():
    text = ("set system host-name X\n"
            "set protocols ospf3 area 0.0.0.1 interface ge-0/0/0.0\n")
    dev, _ = _parse(text)
    o = dev.ospf[0]
    assert (o.process, o.network, o.area, o.af) == (None, "ge-0/0/0", "1", "v6")


def test_v6_static_route():
    text = ("set system host-name X\n"
            "set routing-options rib inet6.0 static route 2001:db8:1::/48 next-hop 2001:db8::2\n")
    dev, _ = _parse(text)
    s = dev.static[0]
    assert (s.prefix, s.next_hop, s.af) == ("2001:db8:1::/48", "2001:db8::2", "v6")


def test_dispatch_parse_config(ios_cfg_text, junos_cfg_text):
    from lib.parsers import parse_config
    assert parse_config(ios_cfg_text).vendor == "cisco_ios"
    assert parse_config(junos_cfg_text).vendor == "juniper_junos"
    assert parse_config("foo bar\nbaz qux\n") is None


def test_host_name_quotes_stripped():
    dev, _ = _parse('set system host-name "edge-r1"\n')
    assert dev.hostname == "edge-r1"


def test_bad_address_line_warns_not_crash():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address NOTANIP/24\n")
    dev, warnings = _parse(text)
    assert dev.interfaces[0].addresses == []
    assert len(warnings) >= 1


def test_ospf_v2_fallback_to_if_name_when_no_v4():
    # IF に v4 アドレスが無ければ network は base IF 名にフォールバック（§6.2）
    text = ("set system host-name X\n"
            "set protocols ospf area 0 interface ge-0/0/5.0\n")
    dev, _ = _parse(text)
    o = [x for x in dev.ospf if x.af == "v4"][0]
    assert o.network == "ge-0/0/5"


def test_b2_all_interface_details(junos_cfg_text):
    dev, _ = _parse(junos_cfg_text)
    ge1 = dev.interfaces[1]
    assert ge1.name == "ge-0/0/1" and ge1.description == "LAN2"
    assert ge1.derived_ip() == "192.168.2.1/24" and ge1.l2_l3 == "l3"
    lo0 = dev.interfaces[2]
    assert lo0.name == "lo0" and lo0.derived_ip() == "2.2.2.2/32"


# ---------------------------------------------------------------------------
# C2: OSPF interface パラメータ抽出（JunOS）
# ---------------------------------------------------------------------------

def test_junos_ospf_metric_as_cost():
    """set protocols ospf area <a> interface <if> metric <n> が ospf["cost"]=int(n) に入ること。"""
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n"
            "set protocols ospf area 0 interface ge-0/0/0.0 metric 100\n")
    dev, warnings = _parse(text)
    assert warnings == []
    iface = dev.interfaces[0]
    assert iface.ospf is not None
    assert iface.ospf["cost"] == 100


def test_junos_ospf_interface_type_as_network_type():
    """set protocols ospf area <a> interface <if> interface-type p2p が ospf["network_type"]="p2p" に入ること。"""
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n"
            "set protocols ospf area 0 interface ge-0/0/0.0 interface-type p2p\n")
    dev, warnings = _parse(text)
    assert warnings == []
    iface = dev.interfaces[0]
    assert iface.ospf is not None
    assert iface.ospf["network_type"] == "p2p"


def test_junos_ospf_passive():
    """set protocols ospf area <a> interface <if> passive が ospf["passive"]=True に入ること。"""
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 192.168.1.1/24\n"
            "set protocols ospf area 0 interface ge-0/0/0.0 passive\n")
    dev, warnings = _parse(text)
    assert warnings == []
    iface = dev.interfaces[0]
    assert iface.ospf is not None
    assert iface.ospf["passive"] is True


def test_junos_ospf_all_three_subkeys():
    """metric + interface-type + passive の3サブキーが同時に設定されること。"""
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n"
            "set protocols ospf area 0 interface ge-0/0/0.0 metric 50\n"
            "set protocols ospf area 0 interface ge-0/0/0.0 interface-type p2p\n"
            "set protocols ospf area 0 interface ge-0/0/0.0 passive\n")
    dev, _ = _parse(text)
    iface = dev.interfaces[0]
    assert iface.ospf == {"cost": 50, "network_type": "p2p", "passive": True}


def test_junos_ospf_no_param_leaves_ospf_none():
    """OSPF パラメータが無い IF は ospf=None のまま。"""
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n"
            "set protocols ospf area 0 interface ge-0/0/0.0\n")
    dev, _ = _parse(text)
    iface = dev.interfaces[0]
    assert iface.ospf is None


def test_junos_ospf_passive_only_targets_named_interface():
    """passive は指定 IF のみに付き、他の IF には影響しないこと。"""
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n"
            "set interfaces ge-0/0/1 unit 0 family inet address 192.168.1.1/24\n"
            "set protocols ospf area 0 interface ge-0/0/1.0 passive\n")
    dev, _ = _parse(text)
    ge0 = [i for i in dev.interfaces if i.name == "ge-0/0/0"][0]
    ge1 = [i for i in dev.interfaces if i.name == "ge-0/0/1"][0]
    assert ge0.ospf is None
    assert ge1.ospf is not None and ge1.ospf["passive"] is True


def test_junos_ospf3_metric_also_sets_cost():
    """ospf3 の metric も ospf["cost"] に入ること。"""
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8::1/64\n"
            "set protocols ospf3 area 0 interface ge-0/0/0.0 metric 200\n")
    dev, warnings = _parse(text)
    assert warnings == []
    iface = dev.interfaces[0]
    assert iface.ospf is not None
    assert iface.ospf["cost"] == 200


# ---------------------------------------------------------------------------
# 修正 2: _ensure_ospf が base.py から import されていること（DRY 解消）
# ---------------------------------------------------------------------------

def test_junos_parser_uses_ensure_ospf_from_base():
    """junos.py が base.py の ensure_ospf を使用し、独自の _ensure_ospf を持たないこと。

    DRY 解消: ios.py と junos.py の同一 _ensure_ospf 実装を base.py に集約。
    """
    import inspect
    import lib.parsers.junos as junos_mod
    import lib.parsers.base as base_mod
    # base に ensure_ospf が存在すること
    assert hasattr(base_mod, 'ensure_ospf'), "base.py に ensure_ospf が存在しない"
    # junos モジュールが base から ensure_ospf を import しており、
    # モジュールスコープで参照可能であること
    assert hasattr(junos_mod, 'ensure_ospf'), "junos.py が base.ensure_ospf を import していない"
    # junos.py 内でローカル定義の _ensure_ospf が無いこと
    src = inspect.getsource(junos_mod)
    assert 'def _ensure_ospf' not in src, "junos.py にまだ _ensure_ospf がローカル定義されている（DRY 未解消）"


def test_ios_parser_uses_ensure_ospf_from_base():
    """ios.py が base.py の ensure_ospf を使用し、独自の _ensure_ospf を持たないこと。"""
    import inspect
    import lib.parsers.ios as ios_mod
    import lib.parsers.base as base_mod
    assert hasattr(base_mod, 'ensure_ospf'), "base.py に ensure_ospf が存在しない"
    assert hasattr(ios_mod, 'ensure_ospf'), "ios.py が base.ensure_ospf を import していない"
    src = inspect.getsource(ios_mod)
    assert 'def _ensure_ospf' not in src, "ios.py にまだ _ensure_ospf がローカル定義されている（DRY 未解消）"


# ---------------------------------------------------------------------------
# 修正 5: JunOS 正規表現の冗長 (.*)?$ 除去テスト
# ---------------------------------------------------------------------------

def test_junos_parser_regex_no_redundant_optional_group():
    """junos.py の OSPF regex に冗長な (.*)?$ がないこと（修正後 (.*)$ のみ）。

    (.*)?$ は `(.*)?` で量指定子が重複（`.*` は常に空文字列にマッチするため
    末尾の `?` は無意味）。挙動は (.*)$ と同じだが冗長であり linter 警告対象。
    """
    import inspect
    import lib.parsers.junos as junos_mod
    src = inspect.getsource(junos_mod)
    # 冗長パターンが残っていないこと
    assert '(.*)?$' not in src, "junos.py に冗長な (.*)?$ が残っている（(.*)$ に修正すること）"
