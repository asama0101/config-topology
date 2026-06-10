"""TDD テスト: BGP IF チップ <-> BGP Sessions 表行 双方向ハイライト連動

実装方針:
- svg.py に _build_bgp_source_iface_map を追加（(device, neighbor_ip) -> source iface_id）
- cards.py BGP 行に data-iface-id を付与（iBGP/eBGP 問わず）
- data-loopback-iface-id は BGP 行から廃止（static 行には残す）
- assets.py JS の tr[data-bgp-id] click で toggleIfChipHighlight も呼ぶ
- SVG bgp-session の data-a-iface と cards 行 data-iface-id が一致すること
"""
import os
import re
import sys
import copy

import pytest

# conftest.py が sys.path を設定するが、念のためここでも設定
_SKILL_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _SKILL_ROOT not in sys.path:
    sys.path.insert(0, _SKILL_ROOT)


# ---------------------------------------------------------------------------
# フィクスチャ・ヘルパー
# ---------------------------------------------------------------------------

def _make_ebgp_physical_topology():
    """eBGP-over-physical: local_ip が physical IF（r1::Gi0/0、r2::ge-0/0/0）に対応。"""
    return {
        "title": "eBGP Physical IF Test",
        "generated_from": [],
        "devices": [
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001, "sections": []},
            {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": 65002, "sections": []},
        ],
        "interfaces": [
            {"id": "r1::Gi0/0", "device": "r1", "name": "GigabitEthernet0/0",
             "ip": "10.0.0.1/30", "vlan": None, "description": None, "shutdown": False,
             "addresses": [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}],
             "admin_status": "up"},
            {"id": "r2::Gi0/0", "device": "r2", "name": "GigabitEthernet0/0",
             "ip": "10.0.0.2/30", "vlan": None, "description": None, "shutdown": False,
             "addresses": [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}],
             "admin_status": "up"},
        ],
        "links": [
            {"a_device": "r1", "a_if": "GigabitEthernet0/0",
             "b_device": "r2", "b_if": "GigabitEthernet0/0",
             "subnet": "10.0.0.0/30", "kind": "inferred-subnet"},
        ],
        "segments": [],
        "routing": {
            "bgp": [
                {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                 "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp"},
                {"device": "r2", "local_as": 65002, "local_ip": "10.0.0.2",
                 "neighbor_ip": "10.0.0.1", "peer_as": 65001, "type": "ebgp"},
            ],
            "ospf": [],
            "static": [],
        },
    }


def _make_ebgp_loopback_topology():
    """eBGP-over-loopback: local_ip が loopback IF（r1::Loopback0、r2::Loopback0）に対応。"""
    return {
        "title": "eBGP Loopback IF Test",
        "generated_from": [],
        "devices": [
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001, "sections": []},
            {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": 65002, "sections": []},
        ],
        "interfaces": [
            {"id": "r1::Loopback0", "device": "r1", "name": "Loopback0",
             "ip": "10.255.0.1/32", "vlan": None, "description": None, "shutdown": False,
             "addresses": [{"af": "v4", "ip": "10.255.0.1", "prefix": 32}],
             "admin_status": "up"},
            {"id": "r1::Gi0/0", "device": "r1", "name": "GigabitEthernet0/0",
             "ip": "10.0.0.1/30", "vlan": None, "description": None, "shutdown": False,
             "addresses": [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}],
             "admin_status": "up"},
            {"id": "r2::Loopback0", "device": "r2", "name": "Loopback0",
             "ip": "10.255.0.2/32", "vlan": None, "description": None, "shutdown": False,
             "addresses": [{"af": "v4", "ip": "10.255.0.2", "prefix": 32}],
             "admin_status": "up"},
            {"id": "r2::Gi0/0", "device": "r2", "name": "GigabitEthernet0/0",
             "ip": "10.0.0.2/30", "vlan": None, "description": None, "shutdown": False,
             "addresses": [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}],
             "admin_status": "up"},
        ],
        "links": [
            {"a_device": "r1", "a_if": "GigabitEthernet0/0",
             "b_device": "r2", "b_if": "GigabitEthernet0/0",
             "subnet": "10.0.0.0/30", "kind": "inferred-subnet"},
        ],
        "segments": [],
        "routing": {
            "bgp": [
                # eBGP だが loopback 経由（local_ip = loopback IP）
                {"device": "r1", "local_as": 65001, "local_ip": "10.255.0.1",
                 "neighbor_ip": "10.255.0.2", "peer_as": 65002, "type": "ebgp"},
                {"device": "r2", "local_as": 65002, "local_ip": "10.255.0.2",
                 "neighbor_ip": "10.255.0.1", "peer_as": 65001, "type": "ebgp"},
            ],
            "ospf": [],
            "static": [],
        },
    }


def _make_ibgp_loopback_topology():
    """iBGP-over-loopback: local_ip が Loopback IP（解決可能）。"""
    return {
        "title": "iBGP Loopback Test",
        "generated_from": [],
        "devices": [
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001, "sections": []},
            {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": 65001, "sections": []},
        ],
        "interfaces": [
            {"id": "r1::Loopback0", "device": "r1", "name": "Loopback0",
             "ip": "10.255.0.1/32", "vlan": None, "description": None, "shutdown": False,
             "addresses": [{"af": "v4", "ip": "10.255.0.1", "prefix": 32}],
             "admin_status": "up"},
            {"id": "r1::Gi0/0", "device": "r1", "name": "GigabitEthernet0/0",
             "ip": "10.0.0.1/30", "vlan": None, "description": None, "shutdown": False,
             "addresses": [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}],
             "admin_status": "up"},
            {"id": "r2::Loopback0", "device": "r2", "name": "Loopback0",
             "ip": "10.255.0.2/32", "vlan": None, "description": None, "shutdown": False,
             "addresses": [{"af": "v4", "ip": "10.255.0.2", "prefix": 32}],
             "admin_status": "up"},
            {"id": "r2::Gi0/0", "device": "r2", "name": "GigabitEthernet0/0",
             "ip": "10.0.0.2/30", "vlan": None, "description": None, "shutdown": False,
             "addresses": [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}],
             "admin_status": "up"},
        ],
        "links": [
            {"a_device": "r1", "a_if": "GigabitEthernet0/0",
             "b_device": "r2", "b_if": "GigabitEthernet0/0",
             "subnet": "10.0.0.0/30", "kind": "inferred-subnet"},
        ],
        "segments": [],
        "routing": {
            "bgp": [
                {"device": "r1", "local_as": 65001, "local_ip": "10.255.0.1",
                 "neighbor_ip": "10.255.0.2", "peer_as": 65001, "type": "ibgp"},
                {"device": "r2", "local_as": 65001, "local_ip": "10.255.0.2",
                 "neighbor_ip": "10.255.0.1", "peer_as": 65001, "type": "ibgp"},
            ],
            "ospf": [],
            "static": [
                {"device": "r1", "prefix": "0.0.0.0/0", "next_hop": "10.0.0.2"},
            ],
        },
    }


def _make_ibgp_null_local_ip_topology():
    """iBGP-over-loopback: local_ip=null（iBGP over loopback で更新元アドレス未解決）。

    この場合はその機器の loopback（iface_id ソート先頭）を source IF とする。
    """
    return {
        "title": "iBGP Null LocalIP Test",
        "generated_from": [],
        "devices": [
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001, "sections": []},
            {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": 65001, "sections": []},
        ],
        "interfaces": [
            {"id": "r1::Loopback0", "device": "r1", "name": "Loopback0",
             "ip": "10.255.0.1/32", "vlan": None, "description": None, "shutdown": False,
             "addresses": [], "admin_status": "up"},
            {"id": "r1::Gi0/0", "device": "r1", "name": "GigabitEthernet0/0",
             "ip": "10.0.0.1/30", "vlan": None, "description": None, "shutdown": False,
             "addresses": [], "admin_status": "up"},
            {"id": "r2::Loopback0", "device": "r2", "name": "Loopback0",
             "ip": "10.255.0.2/32", "vlan": None, "description": None, "shutdown": False,
             "addresses": [], "admin_status": "up"},
            {"id": "r2::Gi0/0", "device": "r2", "name": "GigabitEthernet0/0",
             "ip": "10.0.0.2/30", "vlan": None, "description": None, "shutdown": False,
             "addresses": [], "admin_status": "up"},
        ],
        "links": [],
        "segments": [],
        "routing": {
            "bgp": [
                # local_ip=null: loopback フォールバック
                {"device": "r1", "local_as": 65001, "local_ip": None,
                 "neighbor_ip": "10.255.0.2", "peer_as": 65001, "type": "ibgp"},
                {"device": "r2", "local_as": 65001, "local_ip": None,
                 "neighbor_ip": "10.255.0.1", "peer_as": 65001, "type": "ibgp"},
            ],
            "ospf": [],
            "static": [],
        },
    }


def _make_ibgp_physical_topology():
    """iBGP-over-physical: local_ip が physical IF（iBGP でも physical 経由のケース）。"""
    return {
        "title": "iBGP Physical IF Test",
        "generated_from": [],
        "devices": [
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001, "sections": []},
            {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": 65001, "sections": []},
        ],
        "interfaces": [
            {"id": "r1::Gi0/0", "device": "r1", "name": "GigabitEthernet0/0",
             "ip": "10.0.0.1/30", "vlan": None, "description": None, "shutdown": False,
             "addresses": [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}],
             "admin_status": "up"},
            {"id": "r2::Gi0/0", "device": "r2", "name": "GigabitEthernet0/0",
             "ip": "10.0.0.2/30", "vlan": None, "description": None, "shutdown": False,
             "addresses": [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}],
             "admin_status": "up"},
        ],
        "links": [
            {"a_device": "r1", "a_if": "GigabitEthernet0/0",
             "b_device": "r2", "b_if": "GigabitEthernet0/0",
             "subnet": "10.0.0.0/30", "kind": "inferred-subnet"},
        ],
        "segments": [],
        "routing": {
            "bgp": [
                # iBGP だが physical 経由（local_ip = physical IF の IP）
                {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                 "neighbor_ip": "10.0.0.2", "peer_as": 65001, "type": "ibgp"},
                {"device": "r2", "local_as": 65001, "local_ip": "10.0.0.2",
                 "neighbor_ip": "10.0.0.1", "peer_as": 65001, "type": "ibgp"},
            ],
            "ospf": [],
            "static": [],
        },
    }


def _make_unresolvable_bgp_topology():
    """local_ip が解決不能（IP に対応する IF がない）なケース。"""
    return {
        "title": "Unresolvable BGP Test",
        "generated_from": [],
        "devices": [
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001, "sections": []},
            {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": 65002, "sections": []},
        ],
        "interfaces": [
            # r1 は GigabitEthernet0/0 しかない
            {"id": "r1::Gi0/0", "device": "r1", "name": "GigabitEthernet0/0",
             "ip": "10.0.0.1/30", "vlan": None, "description": None, "shutdown": False,
             "addresses": [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}],
             "admin_status": "up"},
        ],
        "links": [],
        "segments": [],
        "routing": {
            "bgp": [
                # local_ip=192.168.99.1 は interfaces に存在しない
                {"device": "r1", "local_as": 65001, "local_ip": "192.168.99.1",
                 "neighbor_ip": "192.168.99.2", "peer_as": 65002, "type": "ebgp"},
            ],
            "ospf": [],
            "static": [],
        },
    }


def _make_external_bgp_topology():
    """外部ピア（ext: プレフィックス）の BGP topology。"""
    return {
        "title": "External BGP Test",
        "generated_from": [],
        "devices": [
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001, "sections": []},
        ],
        "interfaces": [
            {"id": "r1::Gi0/0", "device": "r1", "name": "GigabitEthernet0/0",
             "ip": "10.0.0.1/30", "vlan": None, "description": None, "shutdown": False,
             "addresses": [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}],
             "admin_status": "up"},
        ],
        "links": [],
        "segments": [],
        "routing": {
            "bgp": [
                # 外部ピア（neighbor_ip が外部デバイスを指す）
                {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                 "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp"},
            ],
            "ospf": [],
            "static": [],
        },
    }


@pytest.fixture(scope="module")
def sample_topology():
    """examples/topology/ の層別 YAML を load_topology() で読み込む。"""
    from lib.topology_io import load_topology
    examples_dir = os.path.join(os.path.dirname(__file__), "..", "examples")
    return load_topology(os.path.join(examples_dir, "topology"))


@pytest.fixture(scope="module")
def rendered_html_examples(sample_topology):
    """examples topology の render 済み HTML。"""
    from lib.rendering import render
    return render(sample_topology)


# ---------------------------------------------------------------------------
# Section 1: _build_bgp_source_iface_map のユニットテスト
# ---------------------------------------------------------------------------

class TestBuildBgpSourceIfaceMap:
    """_build_bgp_source_iface_map のユニットテスト。"""

    def _get_fn(self):
        from lib.rendering.svg import _build_bgp_source_iface_map
        return _build_bgp_source_iface_map

    @pytest.mark.unit
    def test_ebgp_physical_resolves_physical_iface(self):
        """eBGP-over-physical: local_ip が physical IF の IP → その iface_id を返す。"""
        fn = self._get_fn()
        topo = _make_ebgp_physical_topology()
        result = fn(topo["routing"]["bgp"], topo["interfaces"])
        # r1 の BGP session: local_ip=10.0.0.1 → r1::Gi0/0
        assert result.get(("r1", "10.0.0.2")) == "r1::Gi0/0", \
            f"eBGP-over-physical: r1 の source iface が正しくない: {result}"
        # r2 の BGP session: local_ip=10.0.0.2 → r2::Gi0/0
        assert result.get(("r2", "10.0.0.1")) == "r2::Gi0/0", \
            f"eBGP-over-physical: r2 の source iface が正しくない: {result}"

    @pytest.mark.unit
    def test_ebgp_loopback_resolves_loopback_iface(self):
        """eBGP-over-loopback: local_ip が loopback IF の IP → loopback iface_id を返す。"""
        fn = self._get_fn()
        topo = _make_ebgp_loopback_topology()
        result = fn(topo["routing"]["bgp"], topo["interfaces"])
        assert result.get(("r1", "10.255.0.2")) == "r1::Loopback0", \
            f"eBGP-over-loopback: r1 の source iface が loopback でない: {result}"
        assert result.get(("r2", "10.255.0.1")) == "r2::Loopback0", \
            f"eBGP-over-loopback: r2 の source iface が loopback でない: {result}"

    @pytest.mark.unit
    def test_ibgp_loopback_with_local_ip_resolves(self):
        """iBGP-over-loopback（local_ip あり）: local_ip が Loopback IP → loopback iface_id。"""
        fn = self._get_fn()
        topo = _make_ibgp_loopback_topology()
        result = fn(topo["routing"]["bgp"], topo["interfaces"])
        assert result.get(("r1", "10.255.0.2")) == "r1::Loopback0", \
            f"iBGP loopback (local_ip): r1 の source iface が正しくない: {result}"
        assert result.get(("r2", "10.255.0.1")) == "r2::Loopback0", \
            f"iBGP loopback (local_ip): r2 の source iface が正しくない: {result}"

    @pytest.mark.unit
    def test_ibgp_null_local_ip_falls_back_to_first_loopback(self):
        """iBGP local_ip=null → その機器の loopback（iface_id ソート先頭）にフォールバック。"""
        fn = self._get_fn()
        topo = _make_ibgp_null_local_ip_topology()
        result = fn(topo["routing"]["bgp"], topo["interfaces"])
        # r1 に Loopback0 がある → r1::Loopback0 にフォールバック
        assert result.get(("r1", "10.255.0.2")) == "r1::Loopback0", \
            f"iBGP local_ip=null: r1 が loopback にフォールバックしていない: {result}"
        assert result.get(("r2", "10.255.0.1")) == "r2::Loopback0", \
            f"iBGP local_ip=null: r2 が loopback にフォールバックしていない: {result}"

    @pytest.mark.unit
    def test_ibgp_physical_resolves_physical_iface(self):
        """iBGP-over-physical: local_ip が physical IF → physical iface_id を返す。"""
        fn = self._get_fn()
        topo = _make_ibgp_physical_topology()
        result = fn(topo["routing"]["bgp"], topo["interfaces"])
        assert result.get(("r1", "10.0.0.2")) == "r1::Gi0/0", \
            f"iBGP-over-physical: r1 の source iface が physical でない: {result}"
        assert result.get(("r2", "10.0.0.1")) == "r2::Gi0/0", \
            f"iBGP-over-physical: r2 の source iface が physical でない: {result}"

    @pytest.mark.unit
    def test_unresolvable_local_ip_key_absent(self):
        """local_ip があるが対応 IF がない → キーを持たない（解決不能）。"""
        fn = self._get_fn()
        topo = _make_unresolvable_bgp_topology()
        result = fn(topo["routing"]["bgp"], topo["interfaces"])
        # local_ip=192.168.99.1 は interfaces に存在しないのでキー不在
        assert ("r1", "192.168.99.2") not in result, \
            f"解決不能ケースでキーが入っている: {result}"

    @pytest.mark.unit
    def test_external_peer_resolves_local_iface(self):
        """外部ピア BGP でも local_ip から source iface_id を解決できる。"""
        fn = self._get_fn()
        topo = _make_external_bgp_topology()
        result = fn(topo["routing"]["bgp"], topo["interfaces"])
        assert result.get(("r1", "10.0.0.2")) == "r1::Gi0/0", \
            f"外部ピア: r1 の source iface が正しくない: {result}"

    @pytest.mark.unit
    def test_empty_bgp_entries_returns_empty(self):
        """BGP エントリが空のとき空 dict を返す。"""
        fn = self._get_fn()
        result = fn([], [])
        assert result == {}, "空エントリで空 dict を返すべき"

    @pytest.mark.unit
    def test_deterministic_output(self):
        """同じ入力で2回呼んでも同じ結果（決定性）。"""
        fn = self._get_fn()
        topo = _make_ebgp_physical_topology()
        r1 = fn(topo["routing"]["bgp"], topo["interfaces"])
        r2 = fn(topo["routing"]["bgp"], topo["interfaces"])
        assert r1 == r2, "決定性違反: 同一入力で異なる出力"

    @pytest.mark.unit
    def test_no_loopback_and_null_local_ip_key_absent(self):
        """local_ip=null かつ機器に loopback が存在しない → キーを持たない。"""
        fn = self._get_fn()
        bgp_entries = [
            {"device": "r1", "local_as": 65001, "local_ip": None,
             "neighbor_ip": "10.0.0.2", "peer_as": 65001, "type": "ibgp"},
        ]
        interfaces = [
            {"id": "r1::Gi0/0", "device": "r1", "name": "GigabitEthernet0/0",
             "ip": "10.0.0.1/30", "addresses": []},
        ]
        result = fn(bgp_entries, interfaces)
        assert ("r1", "10.0.0.2") not in result, \
            f"loopback なし・local_ip=null でキーが入っている: {result}"


# ---------------------------------------------------------------------------
# Section 2: cards HTML の data-iface-id 付与検証
# ---------------------------------------------------------------------------

class TestCardsDataIfaceId:
    """BGP 行 cards HTML の data-iface-id 付与テスト。"""

    @pytest.mark.unit
    def test_ebgp_physical_row_has_data_iface_id(self):
        """eBGP-over-physical: BGP 行に data-iface-id="r1::Gi0/0" が付く。"""
        from lib.rendering import render
        html = render(_make_ebgp_physical_topology())
        # r1 の BGP Sessions 行に data-iface-id="r1::Gi0/0" が付いていること
        assert 'data-iface-id="r1::Gi0/0"' in html, \
            "eBGP-over-physical: r1 の BGP 行に data-iface-id='r1::Gi0/0' がない"

    @pytest.mark.unit
    def test_ebgp_physical_row_has_data_bgp_id_併記(self):
        """eBGP 行に data-bgp-id と data-iface-id が両方付く（併記）。"""
        from lib.rendering import render
        html = render(_make_ebgp_physical_topology())
        # data-bgp-id と data-iface-id を両方含む tr が存在すること
        pattern = re.compile(r'<tr[^>]+data-bgp-id="[^"]+"[^>]+data-iface-id="[^"]+"')
        pattern2 = re.compile(r'<tr[^>]+data-iface-id="[^"]+"[^>]+data-bgp-id="[^"]+"')
        assert pattern.search(html) or pattern2.search(html), \
            "BGP 行に data-bgp-id と data-iface-id が併記されていない"

    @pytest.mark.unit
    def test_ebgp_loopback_row_has_loopback_iface_id(self):
        """eBGP-over-loopback: BGP 行に data-iface-id="r1::Loopback0" が付く。"""
        from lib.rendering import render
        html = render(_make_ebgp_loopback_topology())
        assert 'data-iface-id="r1::Loopback0"' in html, \
            "eBGP-over-loopback: r1 の BGP 行に data-iface-id='r1::Loopback0' がない"

    @pytest.mark.unit
    def test_ibgp_loopback_row_has_data_iface_id_r1(self):
        """iBGP-over-loopback: r1 の BGP 行に data-iface-id='r1::Loopback0' が付く。"""
        from lib.rendering import render
        html = render(_make_ibgp_loopback_topology())
        assert 'data-iface-id="r1::Loopback0"' in html, \
            "iBGP-over-loopback: r1 の BGP 行に data-iface-id='r1::Loopback0' がない"

    @pytest.mark.unit
    def test_ibgp_loopback_row_has_data_iface_id_r2(self):
        """iBGP-over-loopback: r2 の BGP 行に data-iface-id='r2::Loopback0' が付く。"""
        from lib.rendering import render
        html = render(_make_ibgp_loopback_topology())
        assert 'data-iface-id="r2::Loopback0"' in html, \
            "iBGP-over-loopback: r2 の BGP 行に data-iface-id='r2::Loopback0' がない"

    @pytest.mark.unit
    def test_ibgp_loopback_bgp_row_no_data_loopback_iface_id(self):
        """iBGP BGP 行に data-loopback-iface-id が付かない（BGP 行は data-iface-id に統一）。

        注意: 実装変更前は iBGP 行に data-loopback-iface-id が付いていたが、
        本実装変更では BGP 行の連動属性を data-iface-id に統一する。
        static 行の data-loopback-iface-id はそのまま維持。
        """
        from lib.rendering import render
        html = render(_make_ibgp_loopback_topology())
        # BGP Sessions テーブルのみ抽出
        bgp_section = re.search(
            r'BGP Sessions</h4>.*?<table[^>]*>.*?</table>',
            html, re.DOTALL
        )
        if bgp_section is None:
            pytest.skip("BGP Sessions テーブルが存在しない")
        bgp_html = bgp_section.group(0)
        assert "data-loopback-iface-id" not in bgp_html, \
            "BGP 行に data-loopback-iface-id が付いている（data-iface-id に統一すべき）"

    @pytest.mark.unit
    def test_ibgp_physical_row_has_physical_iface_id(self):
        """iBGP-over-physical: BGP 行に data-iface-id='r1::Gi0/0' が付く。"""
        from lib.rendering import render
        html = render(_make_ibgp_physical_topology())
        assert 'data-iface-id="r1::Gi0/0"' in html, \
            "iBGP-over-physical: r1 の BGP 行に data-iface-id='r1::Gi0/0' がない"

    @pytest.mark.unit
    def test_unresolvable_bgp_row_no_data_iface_id(self):
        """解決不能の BGP 行には data-iface-id が付かない（クラッシュしない）。"""
        from lib.rendering import render
        html = render(_make_unresolvable_bgp_topology())
        # data-iface-id が付かないことを確認（クラッシュしないことが主目的）
        bgp_section = re.search(
            r'BGP Sessions</h4>.*?<table[^>]*>.*?</table>',
            html, re.DOTALL
        )
        if bgp_section:
            bgp_html = bgp_section.group(0)
            # data-iface-id が付いていないこと（解決不能なので）
            assert 'data-iface-id="r1::Gi0/0"' not in bgp_html, \
                "解決不能 BGP 行に data-iface-id が付いている"

    @pytest.mark.unit
    def test_static_row_still_has_loopback_iface_id(self):
        """static 行の data-loopback-iface-id は変更なし（維持）。"""
        from lib.rendering import render
        # static ルートの宛先が Loopback に対応するトポロジー
        topo = {
            "title": "Static Loopback Test",
            "generated_from": [],
            "devices": [
                {"id": "acc1", "hostname": "ACC1", "vendor": "cisco_ios", "as": None, "sections": []},
                {"id": "acc2", "hostname": "ACC2", "vendor": "cisco_ios", "as": None, "sections": []},
            ],
            "interfaces": [
                {"id": "acc1::Gi0/0", "device": "acc1", "name": "GigabitEthernet0/0",
                 "ip": "10.0.0.1/30", "vlan": None, "description": None, "shutdown": False,
                 "addresses": [], "admin_status": "up"},
                {"id": "acc2::Loopback0", "device": "acc2", "name": "Loopback0",
                 "ip": "10.255.3.2/32", "vlan": None, "description": None, "shutdown": False,
                 "addresses": [], "admin_status": "up"},
                {"id": "acc2::Gi0/0", "device": "acc2", "name": "GigabitEthernet0/0",
                 "ip": "10.0.0.2/30", "vlan": None, "description": None, "shutdown": False,
                 "addresses": [], "admin_status": "up"},
            ],
            "links": [],
            "segments": [],
            "routing": {
                "bgp": [],
                "ospf": [],
                "static": [
                    {"device": "acc1", "prefix": "10.255.3.2/32", "next_hop": "10.0.0.2"},
                ],
            },
        }
        html = render(topo)
        # static 行に data-loopback-iface-id が付いていること
        assert 'data-loopback-iface-id="acc2::Loopback0"' in html, \
            "static 行の data-loopback-iface-id が消えた（維持すべき）"

    @pytest.mark.unit
    def test_examples_topology_ebgp_row_has_data_iface_id(self, rendered_html_examples):
        """examples topology（eBGP）の BGP 行に data-iface-id が付く。"""
        # examples topology: r1::GigabitEthernet0/0（local_ip=10.0.0.1）
        assert 'data-iface-id="r1::GigabitEthernet0/0"' in rendered_html_examples, \
            "examples topology: r1 BGP 行に data-iface-id='r1::GigabitEthernet0/0' がない"


# ---------------------------------------------------------------------------
# Section 3: SVG data-a-iface と cards data-iface-id の一致検証
# ---------------------------------------------------------------------------

class TestSvgAndCardsIfaceAlignment:
    """SVG bgp-session の data-a-iface と cards 行の data-iface-id が同一機器・同一 neighbor で一致。"""

    def _extract_svg_a_iface_map(self, html: str) -> dict[str, str]:
        """bgp-session <g> から {bgp_id: a_iface_id} マップを構築する。"""
        result = {}
        # data-a-iface と data-bgp-id を持つ bgp-session <g> を抽出
        pattern = re.compile(
            r'<g[^>]+class="bgp-session"[^>]*data-bgp-id="([^"]+)"[^>]*data-a-iface="([^"]+)"'
        )
        pattern2 = re.compile(
            r'<g[^>]+class="bgp-session"[^>]*data-a-iface="([^"]+)"[^>]*data-bgp-id="([^"]+)"'
        )
        for m in pattern.finditer(html):
            result[m.group(1)] = m.group(2)
        for m in pattern2.finditer(html):
            result[m.group(2)] = m.group(1)
        return result

    def _extract_cards_iface_map(self, html: str) -> dict[str, str]:
        """cards の BGP 行 <tr> から {bgp_id: iface_id} マップを構築する。

        同じ bgp_id に複数の行（両端分）がある場合は最初のものを返す。
        """
        result = {}
        pattern = re.compile(
            r'<tr[^>]+data-bgp-id="([^"]+)"[^>]+data-iface-id="([^"]+)"'
        )
        pattern2 = re.compile(
            r'<tr[^>]+data-iface-id="([^"]+)"[^>]+data-bgp-id="([^"]+)"'
        )
        for m in pattern.finditer(html):
            bgp_id = m.group(1)
            iface_id = m.group(2)
            if bgp_id not in result:
                result[bgp_id] = iface_id
        for m in pattern2.finditer(html):
            iface_id = m.group(1)
            bgp_id = m.group(2)
            if bgp_id not in result:
                result[bgp_id] = iface_id
        return result

    @pytest.mark.unit
    def test_ebgp_physical_svg_a_iface_matches_cards_iface_id(self):
        """eBGP-over-physical: SVG data-a-iface と cards data-iface-id が一致する。

        bgp_id="r1|r2" の SVG a-iface と r1 側 cards 行の data-iface-id が同一であること。
        """
        from lib.rendering import render
        html = render(_make_ebgp_physical_topology())
        svg_map = self._extract_svg_a_iface_map(html)
        cards_map = self._extract_cards_iface_map(html)
        # bgp_id が両方に存在すること
        common_ids = set(svg_map) & set(cards_map)
        assert common_ids, \
            f"SVG と cards に共通 bgp_id がない\nSVG: {svg_map}\nCards: {cards_map}"
        # 共通 bgp_id で iface が一致すること
        for bgp_id in common_ids:
            assert svg_map[bgp_id] == cards_map[bgp_id], \
                (f"bgp_id={bgp_id!r}: SVG data-a-iface={svg_map[bgp_id]!r} と "
                 f"cards data-iface-id={cards_map[bgp_id]!r} が不一致")

    @pytest.mark.unit
    def test_ibgp_loopback_svg_a_iface_matches_cards_iface_id(self):
        """iBGP-over-loopback: SVG data-a-iface と cards data-iface-id が一致する。"""
        from lib.rendering import render
        html = render(_make_ibgp_loopback_topology())
        svg_map = self._extract_svg_a_iface_map(html)
        cards_map = self._extract_cards_iface_map(html)
        common_ids = set(svg_map) & set(cards_map)
        assert common_ids, \
            f"iBGP: SVG と cards に共通 bgp_id がない\nSVG: {svg_map}\nCards: {cards_map}"
        for bgp_id in common_ids:
            assert svg_map[bgp_id] == cards_map[bgp_id], \
                (f"iBGP bgp_id={bgp_id!r}: SVG={svg_map[bgp_id]!r} != "
                 f"cards={cards_map[bgp_id]!r}")

    @pytest.mark.unit
    def test_examples_topology_svg_and_cards_iface_alignment(self, sample_topology):
        """examples topology（eBGP）: SVG data-a-iface と cards data-iface-id が一致する。"""
        from lib.rendering import render
        html = render(sample_topology)
        svg_map = self._extract_svg_a_iface_map(html)
        cards_map = self._extract_cards_iface_map(html)
        common_ids = set(svg_map) & set(cards_map)
        assert common_ids, \
            f"examples: SVG と cards に共通 bgp_id がない\nSVG: {svg_map}\nCards: {cards_map}"
        for bgp_id in common_ids:
            assert svg_map[bgp_id] == cards_map[bgp_id], \
                (f"examples bgp_id={bgp_id!r}: SVG={svg_map[bgp_id]!r} != "
                 f"cards={cards_map[bgp_id]!r}")


# ---------------------------------------------------------------------------
# Section 4: JS 配線の検証（assets.py）
# ---------------------------------------------------------------------------

class TestJsWiring:
    """assets.py の JS 配線テスト。"""

    @pytest.fixture(scope="class")
    def js_body(self, sample_topology):
        """JS 本体を返す（sample_topology から render した HTML の script セクション）。"""
        from lib.rendering import render
        html = render(sample_topology)
        idx = html.find("<script>")
        assert idx >= 0, "<script> タグが見つからない"
        return html[idx:]

    @pytest.mark.unit
    def test_bgp_row_click_calls_toggle_bgp_highlight(self, js_body):
        """tr[data-bgp-id] click ハンドラ内で toggleBgpHighlight が呼ばれる。"""
        assert "toggleBgpHighlight" in js_body, \
            "JS に toggleBgpHighlight 呼び出しがない"

    @pytest.mark.unit
    def test_bgp_row_click_calls_toggle_if_chip_highlight(self, js_body):
        """tr[data-bgp-id] click ハンドラ内で toggleIfChipHighlight も呼ばれる（新規配線）。

        row→chip+session 双方向連動のため、BGP 行クリック時に
        toggleIfChipHighlight(ifaceId) が呼ばれる配線が必要。
        """
        # tr[data-bgp-id] の click 登録コード付近に toggleIfChipHighlight があること
        # 実装上の注意: 「data-bgp-id を持つ tr の click」コンテキストで呼ばれること
        bgp_row_handler_start = js_body.find("tr[data-bgp-id]")
        assert bgp_row_handler_start >= 0, \
            "JS に tr[data-bgp-id] の参照がない"
        # tr[data-bgp-id] から 500 文字以内に toggleIfChipHighlight があること
        handler_window = js_body[bgp_row_handler_start:bgp_row_handler_start + 500]
        assert "toggleIfChipHighlight" in handler_window, \
            (f"tr[data-bgp-id] click ハンドラから 500 文字以内に toggleIfChipHighlight がない\n"
             f"ハンドラ周辺:\n{handler_window}")

    @pytest.mark.unit
    def test_bgp_row_click_uses_data_iface_id_attr(self, js_body):
        """tr[data-bgp-id] click ハンドラが data-iface-id 属性を参照して chip を光らせる。"""
        bgp_row_handler_start = js_body.find("tr[data-bgp-id]")
        assert bgp_row_handler_start >= 0
        handler_window = js_body[bgp_row_handler_start:bgp_row_handler_start + 500]
        assert "data-iface-id" in handler_window, \
            (f"tr[data-bgp-id] click ハンドラが data-iface-id 属性を参照していない\n"
             f"ハンドラ周辺:\n{handler_window}")

    @pytest.mark.unit
    def test_tr_loopback_iface_id_selector_excludes_data_iface_id(self, js_body):
        """tr[data-loopback-iface-id]:not([data-iface-id]) セレクタが維持される（二重登録回避）。

        BGP 行が data-iface-id を持つことで、loopback 専用セレクタから自動的に外れる。
        セレクタ自体は :not([data-iface-id]) を含んでいること。
        """
        assert "not([data-iface-id])" in js_body, \
            "tr[data-loopback-iface-id]:not([data-iface-id]) セレクタが消えた（二重登録回避のため維持必須）"

    @pytest.mark.unit
    def test_toggle_bgp_highlight_function_exists(self, js_body):
        """toggleBgpHighlight 関数が JS に存在する（非回帰）。"""
        assert "function toggleBgpHighlight" in js_body, \
            "toggleBgpHighlight 関数が消えた"

    @pytest.mark.unit
    def test_toggle_if_chip_highlight_function_exists(self, js_body):
        """toggleIfChipHighlight 関数が JS に存在する（非回帰）。"""
        assert "function toggleIfChipHighlight" in js_body, \
            "toggleIfChipHighlight 関数が消えた"


# ---------------------------------------------------------------------------
# Section 5: _build_bgp_chip_iface_ids のチップ集合不変性確認
# ---------------------------------------------------------------------------

class TestBgpChipIfaceIdsUnchanged:
    """_build_bgp_chip_iface_ids の返り値が変化していないことを確認する。

    今回の実装では _build_bgp_chip_iface_ids に触れない方針のため、
    examples topology で返り値が期待通りであることを確認する（非回帰）。
    """

    @pytest.mark.unit
    def test_examples_ebgp_chip_set_contains_both_ends(self, sample_topology):
        """examples topology（eBGP）でチップ集合が local 側・neighbor 側の両 IF を含む。"""
        from lib.rendering.views import _build_bgp_chip_iface_ids
        bgp_entries = sample_topology["routing"]["bgp"]
        interfaces = sample_topology["interfaces"]
        chip_ids = _build_bgp_chip_iface_ids(bgp_entries, interfaces)
        # r1 側（local_ip=10.0.0.1 → r1::GigabitEthernet0/0）
        assert "r1::GigabitEthernet0/0" in chip_ids, \
            "チップ集合に r1::GigabitEthernet0/0 が含まれない"
        # r2 側（neighbor_ip=10.0.0.2 → r2::ge-0/0/0）
        assert "r2::ge-0/0/0" in chip_ids, \
            "チップ集合に r2::ge-0/0/0 が含まれない"

    @pytest.mark.unit
    def test_ibgp_loopback_chip_set_contains_neighbor_chip(self):
        """iBGP topology でチップ集合が neighbor 側チップも含む（neighbor_ip→iface 不変）。"""
        from lib.rendering.views import _build_bgp_chip_iface_ids
        topo = _make_ibgp_loopback_topology()
        chip_ids = _build_bgp_chip_iface_ids(topo["routing"]["bgp"], topo["interfaces"])
        # r1 の neighbor_ip=10.255.0.2 → r2::Loopback0（neighbor 側チップ）
        assert "r2::Loopback0" in chip_ids, \
            "チップ集合から r2::Loopback0（neighbor 側）が消えた"
        assert "r1::Loopback0" in chip_ids, \
            "チップ集合から r1::Loopback0（local 側）が消えた"


# ---------------------------------------------------------------------------
# Section 6: 決定性確認
# ---------------------------------------------------------------------------

class TestDeterminism:
    """同一入力 → 同一出力の決定性確認。"""

    @pytest.mark.unit
    def test_render_twice_same_output(self, sample_topology):
        """examples topology を2回 render して byte 一致。"""
        from lib.rendering import render
        html1 = render(sample_topology)
        html2 = render(sample_topology)
        assert html1 == html2, "render が非決定的: 2回の出力が異なる"

    @pytest.mark.unit
    def test_ibgp_render_twice_same_output(self):
        """iBGP topology を2回 render して byte 一致。"""
        from lib.rendering import render
        topo = _make_ibgp_loopback_topology()
        html1 = render(topo)
        html2 = render(topo)
        assert html1 == html2, "iBGP render が非決定的: 2回の出力が異なる"


# ---------------------------------------------------------------------------
# Section 7: 既存テストとの互換性確認（非回帰）
# ---------------------------------------------------------------------------

class TestRegressionExistingFeatures:
    """既存機能の非回帰確認。"""

    @pytest.mark.unit
    def test_bgp_row_still_has_data_bgp_id(self, rendered_html_examples):
        """BGP 行に data-bgp-id が引き続き付いている（#5 既存機能非回帰）。"""
        assert 'data-bgp-id=' in rendered_html_examples, \
            "BGP 行の data-bgp-id が消えた（非回帰）"

    @pytest.mark.unit
    def test_bgp_session_svg_still_has_data_bgp_id(self, rendered_html_examples):
        """bgp-session <g> に data-bgp-id が引き続き付いている（非回帰）。"""
        assert re.search(
            r'class="bgp-session"[^>]*data-bgp-id=',
            rendered_html_examples
        ), "bgp-session SVG の data-bgp-id が消えた（非回帰）"

    @pytest.mark.unit
    def test_static_loopback_row_unchanged(self, rendered_html_examples):
        """static 行の data-loopback-iface-id は変更なし（examples topology には static ルートがないのでスキップ）。"""
        pytest.skip(
            "examples topology に static ルートが無いため "
            "Section2 test_static_row_still_has_loopback_iface_id で代替"
        )

    @pytest.mark.unit
    def test_ebgp_row_no_data_loopback_iface_id_in_bgp_section(self, rendered_html_examples):
        """eBGP 行（examples）に data-loopback-iface-id が付かない（非回帰）。"""
        bgp_section = re.search(
            r'BGP Sessions</h4>.*?<table[^>]*>.*?</table>',
            rendered_html_examples, re.DOTALL
        )
        if bgp_section is None:
            pytest.skip("BGP Sessions テーブルが存在しない")
        bgp_html = bgp_section.group(0)
        assert "data-loopback-iface-id" not in bgp_html, \
            "eBGP 行に data-loopback-iface-id が付いている（BGP 行には不要）"

    @pytest.mark.unit
    def test_toggle_ospf_highlight_still_exists(self, rendered_html_examples):
        """toggleOspfHighlight が HTML から消えていない（非回帰）。"""
        assert "toggleOspfHighlight" in rendered_html_examples, \
            "toggleOspfHighlight が消えた（非回帰）"


# ---------------------------------------------------------------------------
# Section 5: _build_bgp_source_iface_map 追加テスト
# (a) loopback 複数でソート先頭フォールバック
# (b) IPv6 BGP セッション解決
# ---------------------------------------------------------------------------

class TestBuildBgpSourceIfaceMapAdditional:
    """_build_bgp_source_iface_map の追加エッジケーステスト。"""

    @staticmethod
    def _get_fn():
        from lib.rendering.svg import _build_bgp_source_iface_map
        return _build_bgp_source_iface_map

    @pytest.mark.unit
    def test_multiple_loopbacks_fallback_uses_iface_id_sort_first(self):
        """local_ip=null で複数 Loopback が存在する場合、iface_id ソート先頭を返す。

        Loopback0, Loopback1, Loopback100 が存在する場合:
        iface_id ソートで r1::Loopback0 < r1::Loopback1 < r1::Loopback100
        → フォールバックは r1::Loopback0 を返す。
        """
        fn = self._get_fn()
        bgp_entries = [
            {"device": "r1", "local_as": 65001, "local_ip": None,
             "neighbor_ip": "10.255.0.2", "peer_as": 65001, "type": "ibgp"},
        ]
        interfaces = [
            # 複数 loopback。id ソートで Loopback0 < Loopback1 < Loopback100
            {"id": "r1::Loopback100", "device": "r1", "name": "Loopback100",
             "ip": "10.255.0.100/32", "addresses": [{"af": "v4", "ip": "10.255.0.100", "prefix": 32}]},
            {"id": "r1::Loopback1", "device": "r1", "name": "Loopback1",
             "ip": "10.255.0.3/32", "addresses": [{"af": "v4", "ip": "10.255.0.3", "prefix": 32}]},
            {"id": "r1::Loopback0", "device": "r1", "name": "Loopback0",
             "ip": "10.255.0.1/32", "addresses": [{"af": "v4", "ip": "10.255.0.1", "prefix": 32}]},
        ]
        result = fn(bgp_entries, interfaces)
        assert ("r1", "10.255.0.2") in result, \
            f"local_ip=null+複数 Loopback でキーが存在しない: {result}"
        assert result[("r1", "10.255.0.2")] == "r1::Loopback0", (
            f"iface_id ソート先頭 'r1::Loopback0' が選ばれなかった: "
            f"got {result[('r1', '10.255.0.2')]!r}"
        )

    @pytest.mark.unit
    def test_multiple_loopbacks_loopback0_lt_loopback1_lt_loopback100(self):
        """iface_id ソートで Loopback0 < Loopback1 < Loopback100 の順序を確認。

        Python str ソートで 'r1::Loopback0' < 'r1::Loopback1' < 'r1::Loopback100' であること。
        """
        ids = ["r1::Loopback100", "r1::Loopback1", "r1::Loopback0"]
        assert sorted(ids)[0] == "r1::Loopback0", (
            f"ソート先頭が 'r1::Loopback0' でない: sorted={sorted(ids)}"
        )

    @pytest.mark.unit
    def test_ipv6_bgp_session_local_ip_v6_resolves_to_v6_iface(self):
        """IPv6 BGP セッション（local_ip が IPv6 GUA）で v6 IF が解決される。

        local_ip="2001:db8::1" に対応する v6 アドレスを持つ IF が解決されること。
        """
        fn = self._get_fn()
        bgp_entries = [
            {"device": "r1", "local_as": 65001, "local_ip": "2001:db8::1",
             "neighbor_ip": "2001:db8::2", "peer_as": 65002, "type": "ebgp"},
        ]
        interfaces = [
            {
                "id": "r1::Gi0/0",
                "device": "r1",
                "name": "GigabitEthernet0/0",
                "ip": None,
                "addresses": [
                    {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
                ],
            },
        ]
        result = fn(bgp_entries, interfaces)
        assert ("r1", "2001:db8::2") in result, (
            f"IPv6 BGP セッションで (r1, 2001:db8::2) が解決されなかった: {result}"
        )
        assert result[("r1", "2001:db8::2")] == "r1::Gi0/0", (
            f"IPv6 local_ip 解決が 'r1::Gi0/0' でなかった: got {result.get(('r1', '2001:db8::2'))!r}"
        )

    @pytest.mark.unit
    def test_ipv6_bgp_session_normalized_local_ip_resolves(self):
        """IPv6 BGP セッション: 正規化形式 local_ip でも解決される。

        local_ip="2001:db8:0:0::1"（非短縮形）で addresses に "2001:db8::1" がある場合。
        """
        fn = self._get_fn()
        bgp_entries = [
            {"device": "r1", "local_as": 65001, "local_ip": "2001:0db8:0000:0000:0000:0000:0000:0001",
             "neighbor_ip": "2001:db8::2", "peer_as": 65002, "type": "ebgp"},
        ]
        interfaces = [
            {
                "id": "r1::Gi0/0",
                "device": "r1",
                "name": "GigabitEthernet0/0",
                "ip": None,
                "addresses": [
                    {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
                ],
            },
        ]
        # local_ip を正規化した "2001:db8::1" が iface の ip と一致する
        result = fn(bgp_entries, interfaces)
        assert ("r1", "2001:db8::2") in result, (
            f"正規化 IPv6 local_ip で (r1, 2001:db8::2) が解決されなかった: {result}"
        )
        assert result[("r1", "2001:db8::2")] == "r1::Gi0/0", (
            f"正規化 IPv6 local_ip 解決が 'r1::Gi0/0' でなかった: got {result.get(('r1', '2001:db8::2'))!r}"
        )
