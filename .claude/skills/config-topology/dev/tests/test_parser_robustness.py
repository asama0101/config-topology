"""
パーサ堅牢化テスト (TDD: RED → GREEN → REFACTOR)

C1: OSPF wildcard マスク変換の不正入力検証
  - _wildcard_to_prefixlen が不正入力で ValueError を raise すること
  - parse() が不正 OSPF network 行をスキップし stderr に WARN を出すこと
  - 正常系・既存 OSPF テストが緑のまま維持されること

C2: sort_addresses の sentinel 丸めの意図明示（挙動固定テスト）
  - invalid IP を含む addresses でもクラッシュしないこと
  - invalid IP が決定的に末尾へ配置されること
  - 複数回呼んでも順序が安定（決定的）であること
"""

import pytest

import sys
import os

# ================================================================
# C1: _wildcard_to_prefixlen 不正入力テスト
# ================================================================


class TestWildcardToPrefixlenValidation:
    """_wildcard_to_prefixlen が不正入力で ValueError を raise すること。"""

    @pytest.mark.unit
    def test_raises_on_fewer_than_4_octets(self):
        """3 オクテット (0.0.0) → ValueError。"""
        from lib.parsers.cisco_ios import _wildcard_to_prefixlen
        with pytest.raises(ValueError, match="invalid OSPF wildcard mask"):
            _wildcard_to_prefixlen("0.0.0")

    @pytest.mark.unit
    def test_raises_on_more_than_4_octets(self):
        """5 オクテット (0.0.0.0.0) → ValueError。"""
        from lib.parsers.cisco_ios import _wildcard_to_prefixlen
        with pytest.raises(ValueError, match="invalid OSPF wildcard mask"):
            _wildcard_to_prefixlen("0.0.0.0.0")

    @pytest.mark.unit
    def test_raises_on_octet_above_255(self):
        """オクテット値 300 (> 255) → ValueError。"""
        from lib.parsers.cisco_ios import _wildcard_to_prefixlen
        with pytest.raises(ValueError, match="invalid OSPF wildcard mask"):
            _wildcard_to_prefixlen("0.0.0.300")

    @pytest.mark.unit
    def test_raises_on_negative_octet(self):
        """オクテット値 -1 (< 0) → ValueError。"""
        from lib.parsers.cisco_ios import _wildcard_to_prefixlen
        with pytest.raises(ValueError, match="invalid OSPF wildcard mask"):
            _wildcard_to_prefixlen("0.0.0.-1")

    @pytest.mark.unit
    def test_raises_on_non_numeric_octet(self):
        """非数値オクテット (0.0.0.x) → ValueError。"""
        from lib.parsers.cisco_ios import _wildcard_to_prefixlen
        with pytest.raises(ValueError, match="invalid OSPF wildcard mask"):
            _wildcard_to_prefixlen("0.0.0.x")

    @pytest.mark.unit
    def test_raises_on_empty_string(self):
        """空文字列 → ValueError。"""
        from lib.parsers.cisco_ios import _wildcard_to_prefixlen
        with pytest.raises(ValueError, match="invalid OSPF wildcard mask"):
            _wildcard_to_prefixlen("")

    @pytest.mark.unit
    def test_raises_on_single_octet(self):
        """単一数値 ("255") → ValueError。"""
        from lib.parsers.cisco_ios import _wildcard_to_prefixlen
        with pytest.raises(ValueError, match="invalid OSPF wildcard mask"):
            _wildcard_to_prefixlen("255")

    # --- 正常系回帰テスト ---

    @pytest.mark.unit
    def test_valid_wildcard_slash24(self):
        """0.0.0.255 → 24 (正常系回帰)。"""
        from lib.parsers.cisco_ios import _wildcard_to_prefixlen
        assert _wildcard_to_prefixlen("0.0.0.255") == 24

    @pytest.mark.unit
    def test_valid_wildcard_slash30(self):
        """0.0.0.3 → 30 (正常系回帰)。"""
        from lib.parsers.cisco_ios import _wildcard_to_prefixlen
        assert _wildcard_to_prefixlen("0.0.0.3") == 30

    @pytest.mark.unit
    def test_valid_wildcard_slash32(self):
        """0.0.0.0 → 32 (ホストルート回帰)。"""
        from lib.parsers.cisco_ios import _wildcard_to_prefixlen
        assert _wildcard_to_prefixlen("0.0.0.0") == 32

    @pytest.mark.unit
    def test_valid_wildcard_slash16(self):
        """0.0.255.255 → 16 (正常系回帰)。"""
        from lib.parsers.cisco_ios import _wildcard_to_prefixlen
        assert _wildcard_to_prefixlen("0.0.255.255") == 16

    @pytest.mark.unit
    def test_valid_wildcard_slash8(self):
        """0.255.255.255 → 8 (正常系回帰)。"""
        from lib.parsers.cisco_ios import _wildcard_to_prefixlen
        assert _wildcard_to_prefixlen("0.255.255.255") == 8


# ================================================================
# C1: parse() での不正 OSPF network 行スキップ + WARN 出力
# ================================================================


class TestOspfNetworkInvalidSkipWithWarn:
    """不正 OSPF network 行はスキップされ、かつ stderr に WARN が出ること。"""

    _VALID_PREFIX = (
        "hostname R1\n"
        "!\n"
        "router ospf 1\n"
    )
    _SUFFIX = "!\n"

    @pytest.mark.integration
    def test_invalid_wildcard_3octets_skipped(self, capsys):
        """3 オクテット wildcard → OspfNetwork なし + stderr WARN。"""
        from lib.parsers.cisco_ios import parse
        text = (
            self._VALID_PREFIX
            + " network 10.0.0.0 0.0.0 area 0\n"
            + self._SUFFIX
        )
        device = parse(text)
        assert len(device.ospf) == 0, f"Expected 0 ospf, got {device.ospf}"
        captured = capsys.readouterr()
        assert "[WARN]" in captured.err, f"Expected WARN in stderr, got: {captured.err!r}"
        assert "0.0.0" in captured.err

    @pytest.mark.integration
    def test_invalid_wildcard_octet_over255_skipped(self, capsys):
        """オクテット > 255 の wildcard → OspfNetwork なし + stderr WARN。"""
        from lib.parsers.cisco_ios import parse
        text = (
            self._VALID_PREFIX
            + " network 10.0.0.0 0.0.0.300 area 0\n"
            + self._SUFFIX
        )
        device = parse(text)
        assert len(device.ospf) == 0, f"Expected 0 ospf, got {device.ospf}"
        captured = capsys.readouterr()
        assert "[WARN]" in captured.err
        assert "0.0.0.300" in captured.err

    @pytest.mark.integration
    def test_invalid_wildcard_nonnumeric_skipped(self, capsys):
        """非数値オクテット wildcard → OspfNetwork なし + stderr WARN。"""
        from lib.parsers.cisco_ios import parse
        text = (
            self._VALID_PREFIX
            + " network 10.0.0.0 0.0.0.x area 0\n"
            + self._SUFFIX
        )
        device = parse(text)
        assert len(device.ospf) == 0, f"Expected 0 ospf, got {device.ospf}"
        captured = capsys.readouterr()
        assert "[WARN]" in captured.err
        assert "0.0.0.x" in captured.err

    @pytest.mark.integration
    def test_valid_network_no_warn(self, capsys):
        """正常 wildcard → OspfNetwork が生成され、WARN は出ないこと。"""
        from lib.parsers.cisco_ios import parse
        text = (
            self._VALID_PREFIX
            + " network 192.168.1.0 0.0.0.255 area 0\n"
            + self._SUFFIX
        )
        device = parse(text)
        assert len(device.ospf) == 1
        assert device.ospf[0].network == "192.168.1.0/24"
        captured = capsys.readouterr()
        assert "[WARN]" not in captured.err, f"Unexpected WARN: {captured.err!r}"

    @pytest.mark.integration
    def test_mixed_valid_and_invalid_keep_valid(self, capsys):
        """有効 + 無効が混在するとき、有効分だけ生成される。"""
        from lib.parsers.cisco_ios import parse
        text = (
            self._VALID_PREFIX
            + " network 192.168.1.0 0.0.0.255 area 0\n"
            + " network 10.0.0.0 0.0.0 area 0\n"   # 不正（3オクテット）
            + " network 10.1.0.0 0.0.255.255 area 1\n"
            + self._SUFFIX
        )
        device = parse(text)
        assert len(device.ospf) == 2, f"Expected 2 ospf, got {device.ospf}"
        networks = {o.network for o in device.ospf}
        assert "192.168.1.0/24" in networks
        assert "10.1.0.0/16" in networks
        captured = capsys.readouterr()
        assert "[WARN]" in captured.err

    @pytest.mark.integration
    def test_warn_contains_addr_and_wildcard_and_area(self, capsys):
        """WARN メッセージに addr, wildcard, area が含まれること。"""
        from lib.parsers.cisco_ios import parse
        text = (
            self._VALID_PREFIX
            + " network 172.16.0.0 bad.wildcard area 2\n"
            + self._SUFFIX
        )
        parse(text)
        captured = capsys.readouterr()
        assert "172.16.0.0" in captured.err
        assert "bad.wildcard" in captured.err
        assert "2" in captured.err


# ================================================================
# C1: 既存 OSPF 正常系回帰テスト（変更後も緑を維持）
# ================================================================


class TestOspfNormalCaseRegression:
    """既存の OSPF network パーステストが変更後も緑であること（回帰保護）。"""

    @pytest.mark.unit
    def test_ospf_wildcard_0_0_0_255_to_slash24(self):
        """0.0.0.255 → /24 の変換が正常に機能すること。"""
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n!\nrouter ospf 1\n"
            " network 192.168.1.0 0.0.0.255 area 0\n!\n"
        )
        device = parse(text)
        assert len(device.ospf) == 1
        assert device.ospf[0].network == "192.168.1.0/24"
        assert device.ospf[0].area == "0"
        assert device.ospf[0].process == 1

    @pytest.mark.unit
    def test_ospf_wildcard_0_0_0_3_to_slash30(self):
        """0.0.0.3 → /30 の変換が正常に機能すること。"""
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n!\nrouter ospf 1\n"
            " network 10.0.0.0 0.0.0.3 area 0\n!\n"
        )
        device = parse(text)
        assert len(device.ospf) == 1
        assert device.ospf[0].network == "10.0.0.0/30"

    @pytest.mark.unit
    def test_ospf_wildcard_all_ones_still_skipped(self):
        """255.255.255.255 (全1 wildcard = /0) は引き続きスキップ。"""
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n!\nrouter ospf 1\n"
            " network 10.0.0.0 255.255.255.255 area 0\n!\n"
        )
        device = parse(text)
        assert len(device.ospf) == 0

    @pytest.mark.unit
    def test_ospf_multiple_networks_parsed(self):
        """複数の正常 OSPF ネットワーク文が正しくパースされること。"""
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n!\nrouter ospf 1\n"
            " network 192.168.1.0 0.0.0.255 area 0\n"
            " network 10.0.0.0 0.0.0.3 area 0\n"
            "!\n"
        )
        device = parse(text)
        assert len(device.ospf) == 2
        nets = {o.network for o in device.ospf}
        assert "192.168.1.0/24" in nets
        assert "10.0.0.0/30" in nets


# ================================================================
# C2: sort_addresses の sentinel 丸め（挙動固定テスト）
# ================================================================


class TestSortAddressesSentinelBehavior:
    """invalid IP を含む addresses でも sort_addresses がクラッシュせず、
    invalid が決定的に末尾へ来ること。"""

    @pytest.mark.unit
    def test_invalid_ip_does_not_crash(self):
        """invalid IP (INVALID) を含む addresses でクラッシュしないこと。"""
        from lib.parsers.base import sort_addresses
        addresses = [
            {"af": "v4", "ip": "INVALID", "prefix": 24},
            {"af": "v4", "ip": "10.0.0.1", "prefix": 24},
        ]
        result = sort_addresses(addresses)
        assert len(result) == 2

    @pytest.mark.unit
    def test_invalid_ip_placed_at_end(self):
        """invalid IP (INVALID) は有効 IP より後（末尾）に配置されること。"""
        from lib.parsers.base import sort_addresses
        addresses = [
            {"af": "v4", "ip": "INVALID", "prefix": 24},
            {"af": "v4", "ip": "10.0.0.1", "prefix": 24},
        ]
        result = sort_addresses(addresses)
        assert result[0]["ip"] == "10.0.0.1"
        assert result[1]["ip"] == "INVALID"

    @pytest.mark.unit
    def test_invalid_ip_v6_placed_at_end(self):
        """invalid v6 IP は有効 v6 IP より後に配置されること。"""
        from lib.parsers.base import sort_addresses
        addresses = [
            {"af": "v6", "ip": "NOT_AN_IP", "prefix": 64},
            {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
        ]
        result = sort_addresses(addresses)
        assert result[0]["ip"] == "2001:db8::1"
        assert result[1]["ip"] == "NOT_AN_IP"

    @pytest.mark.unit
    def test_sort_is_deterministic_multiple_calls(self):
        """複数回呼んでも同じ順序が返ること（決定性）。"""
        from lib.parsers.base import sort_addresses
        addresses = [
            {"af": "v4", "ip": "INVALID", "prefix": 24},
            {"af": "v4", "ip": "192.168.1.1", "prefix": 24},
            {"af": "v4", "ip": "10.0.0.1", "prefix": 24},
        ]
        result1 = sort_addresses(addresses)
        result2 = sort_addresses(addresses)
        result3 = sort_addresses(addresses)
        assert [a["ip"] for a in result1] == [a["ip"] for a in result2]
        assert [a["ip"] for a in result2] == [a["ip"] for a in result3]

    @pytest.mark.unit
    def test_sort_does_not_mutate_input(self):
        """sort_addresses は元のリストを変更しないこと（非破壊）。"""
        from lib.parsers.base import sort_addresses
        addresses = [
            {"af": "v4", "ip": "INVALID", "prefix": 24},
            {"af": "v4", "ip": "10.0.0.1", "prefix": 24},
        ]
        original_order = [a["ip"] for a in addresses]
        sort_addresses(addresses)
        assert [a["ip"] for a in addresses] == original_order

    @pytest.mark.unit
    def test_invalid_ip_addr_dict_not_modified(self):
        """invalid IP エントリの dict 自体が改変されていないこと。"""
        from lib.parsers.base import sort_addresses
        invalid_entry = {"af": "v4", "ip": "INVALID", "prefix": 24}
        addresses = [invalid_entry, {"af": "v4", "ip": "10.0.0.1", "prefix": 24}]
        sort_addresses(addresses)
        # 元の dict の ip フィールドが sentinel で置き換えられていないこと
        assert invalid_entry["ip"] == "INVALID"

    @pytest.mark.unit
    def test_multiple_invalid_ips_at_end(self):
        """複数の invalid IP がすべて有効 IP の後に来ること。"""
        from lib.parsers.base import sort_addresses
        addresses = [
            {"af": "v4", "ip": "BAD1", "prefix": 24},
            {"af": "v4", "ip": "10.0.0.1", "prefix": 24},
            {"af": "v4", "ip": "BAD2", "prefix": 16},
            {"af": "v4", "ip": "192.168.1.1", "prefix": 24},
        ]
        result = sort_addresses(addresses)
        valid_ips = {"10.0.0.1", "192.168.1.1"}
        invalid_ips = {"BAD1", "BAD2"}
        result_ips = [a["ip"] for a in result]
        # 先頭 2 件が有効 IP であること
        assert set(result_ips[:2]) == valid_ips
        # 末尾 2 件が invalid IP であること
        assert set(result_ips[2:]) == invalid_ips

    @pytest.mark.unit
    def test_all_valid_ips_sorted_correctly(self):
        """valid IP のみの場合は通常昇順ソートが維持されること（回帰）。"""
        from lib.parsers.base import sort_addresses
        addresses = [
            {"af": "v4", "ip": "192.168.1.1", "prefix": 24},
            {"af": "v4", "ip": "10.0.0.1", "prefix": 24},
        ]
        result = sort_addresses(addresses)
        assert result[0]["ip"] == "10.0.0.1"
        assert result[1]["ip"] == "192.168.1.1"

    @pytest.mark.unit
    def test_empty_addresses_returns_empty(self):
        """空リストを渡すと空リストが返ること。"""
        from lib.parsers.base import sort_addresses
        result = sort_addresses([])
        assert result == []

    @pytest.mark.unit
    def test_v4_before_v6(self):
        """v4 アドレスは v6 アドレスより前に来ること（af 順）。"""
        from lib.parsers.base import sort_addresses
        addresses = [
            {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
            {"af": "v4", "ip": "10.0.0.1", "prefix": 24},
        ]
        result = sort_addresses(addresses)
        assert result[0]["af"] == "v4"
        assert result[1]["af"] == "v6"
