"""入力形式診断（#1 JunOS 波括弧ガード・#2 apply-groups 多用警告）のテスト。

TDD: RED フェーズ（失敗先行） → 実装後 GREEN。
"""
import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# サンプル config テキスト
# ---------------------------------------------------------------------------

# #1: JunOS 波括弧(hierarchical)形式の典型例
BRACE_JUNOS = """\
interfaces {
    ge-0/0/0 {
        unit 0 {
            family inet {
                address 10.0.0.1/30;
            }
        }
    }
    ge-0/0/1 {
        unit 0 {
            family inet {
                address 192.168.1.1/24;
            }
        }
    }
}
routing-options {
    static {
        route 0.0.0.0/0 next-hop 10.0.0.2;
    }
}
"""

# #2: groups 多用の JunOS set config
GROUPS_HEAVY_JUNOS = """\
set groups IF_TEMPLATE interfaces <ge-*> unit 0 family inet
set groups IF_TEMPLATE interfaces <ge-*> mtu 1500
set groups OSPF_BASE protocols ospf area 0.0.0.0 interface all
set groups OSPF_BASE protocols ospf area 0.0.0.0 interface all metric 10
set groups BGP_POLICY policy-options prefix-list DEFAULT_ROUTE 0.0.0.0/0
set apply-groups IF_TEMPLATE
set apply-groups OSPF_BASE
set apply-groups BGP_POLICY
set system host-name R1
"""

# 正常な JunOS set config（groups 不使用、通常 set 行が大半）
NORMAL_JUNOS_SET = """\
## Juniper JunOS configuration in `set` format (sample)
set system host-name R2
set interfaces ge-0/0/0 description to-R1
set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.2/30
set interfaces ge-0/0/1 description LAN2
set interfaces ge-0/0/1 unit 0 family inet address 192.168.2.1/24
set interfaces lo0 unit 0 family inet address 2.2.2.2/32
set routing-options autonomous-system 65002
set protocols bgp group ext type external
set protocols bgp group ext neighbor 10.0.0.1 peer-as 65001
set routing-options static route 0.0.0.0/0 next-hop 10.0.0.1
"""

# 正常な IOS config
NORMAL_IOS = """\
hostname R1
!
interface GigabitEthernet0/0
 description to-R2
 ip address 10.0.0.1 255.255.255.252
 no shutdown
!
"""

# set 行がほぼない謎のテキスト（JunOS 波括弧でもなく IOS でもない → diagnose_input は None）
UNKNOWN_TEXT = """\
some random text here
foo bar baz
no vendor detected
"""


# ---------------------------------------------------------------------------
# #1: diagnose_input テスト
# ---------------------------------------------------------------------------

class TestDiagnoseInput:
    """diagnose_input(text, filename) の単体テスト。"""

    def test_brace_junos_returns_warning(self):
        """波括弧 JunOS config は junos_brace_format 警告を返す。"""
        from lib.parsers import diagnose_input
        result = diagnose_input(BRACE_JUNOS, "router.conf")
        assert result is not None
        assert result["severity"] == "warning"
        assert result["kind"] == "junos_brace_format"
        assert "router.conf" in result["message"]
        assert result["refs"] == ["router.conf"]

    def test_brace_junos_message_contains_display_set_hint(self):
        """波括弧形式の警告メッセージに `display set` ヒントが含まれる。"""
        from lib.parsers import diagnose_input
        result = diagnose_input(BRACE_JUNOS, "r1.conf")
        assert result is not None
        assert "display set" in result["message"]

    def test_normal_junos_set_returns_none(self):
        """正常な JunOS set 形式では diagnose_input は None（偽陽性ゼロ）。"""
        from lib.parsers import diagnose_input
        result = diagnose_input(NORMAL_JUNOS_SET, "sample-junos-r2.conf")
        assert result is None

    def test_normal_ios_returns_none(self):
        """正常な IOS config では diagnose_input は None（偽陽性ゼロ）。"""
        from lib.parsers import diagnose_input
        result = diagnose_input(NORMAL_IOS, "router.cfg")
        assert result is None

    def test_unknown_text_without_braces_returns_none(self):
        """vendor unknown でも波括弧なしテキストは None を返す（波括弧条件不成立）。"""
        from lib.parsers import diagnose_input
        result = diagnose_input(UNKNOWN_TEXT, "mystery.txt")
        assert result is None

    def test_filename_appears_in_refs(self):
        """refs に渡した filename がそのまま含まれる。"""
        from lib.parsers import diagnose_input
        result = diagnose_input(BRACE_JUNOS, "my-device.conf")
        assert result is not None
        assert "my-device.conf" in result["refs"]

    def test_mostly_set_with_some_braces_returns_none(self):
        """set 行が過半の JunOS set config に少数 {} が混入しても偽陽性しない。

        例: description に波括弧を含む set 行は set ベースのまま detect。
        """
        from lib.parsers import diagnose_input
        # set 行が過半 → detect_vendor = juniper_junos → diagnose_input は None を返す
        text = (NORMAL_JUNOS_SET
                + "set system login message \"Welcome {R2}\"\n"
                + "set system login message \"Goodbye }\"\n")
        result = diagnose_input(text, "r2-with-braces-desc.conf")
        assert result is None

    def test_brace_config_with_sparse_set_lines_is_detected(self):
        """波括弧 config に set 行が 1〜2 行混在しても（set 比率 ≤ 0.05）検知する。"""
        from lib.parsers import diagnose_input
        text = BRACE_JUNOS + "set version 21.4R1;\n"
        result = diagnose_input(text, "partial.conf")
        assert result is not None
        assert result["kind"] == "junos_brace_format"


# ---------------------------------------------------------------------------
# #2: parse_junos diagnostics（apply-groups）テスト
# ---------------------------------------------------------------------------

class TestJunosApplyGroupsDiagnostics:
    """parse_junos(text, warnings, diagnostics=...) の groups 多用警告テスト。"""

    def test_groups_heavy_appends_warning(self):
        """groups 多用 config では diagnostics に junos_apply_groups_unexpanded が追加される。"""
        from lib.parsers.junos import parse_junos
        warnings = []
        diag = []
        parse_junos(GROUPS_HEAVY_JUNOS, warnings, diagnostics=diag)
        kinds = [d["kind"] for d in diag]
        assert "junos_apply_groups_unexpanded" in kinds

    def test_groups_heavy_warning_severity_and_message(self):
        """groups 多用警告の severity・message・refs フィールドが正しい。"""
        from lib.parsers.junos import parse_junos
        warnings = []
        diag = []
        parse_junos(GROUPS_HEAVY_JUNOS, warnings, diagnostics=diag, filename="r1.conf")
        entry = next(d for d in diag if d["kind"] == "junos_apply_groups_unexpanded")
        assert entry["severity"] == "warning"
        assert "display inheritance" in entry["message"]
        assert "r1.conf" in entry["refs"]

    def test_normal_junos_set_no_groups_warning(self):
        """正常な JunOS set config（groups 不使用）では groups 警告は発火しない。"""
        from lib.parsers.junos import parse_junos
        warnings = []
        diag = []
        parse_junos(NORMAL_JUNOS_SET, warnings, diagnostics=diag)
        kinds = [d["kind"] for d in diag]
        assert "junos_apply_groups_unexpanded" not in kinds

    def test_diagnostics_none_does_not_raise(self):
        """diagnostics=None（既定）では従来通り動作し例外なし（後方互換）。"""
        from lib.parsers.junos import parse_junos
        warnings = []
        dev = parse_junos(GROUPS_HEAVY_JUNOS, warnings)  # diagnostics 省略
        assert dev is not None  # Device が返る

    def test_diagnostics_none_with_normal_does_not_raise(self):
        """正常 config でも diagnostics=None（既定）で例外なし（後方互換）。"""
        from lib.parsers.junos import parse_junos
        warnings = []
        dev = parse_junos(NORMAL_JUNOS_SET, warnings)
        assert dev.hostname == "R2"

    def test_filename_none_refs_empty_or_omits(self):
        """filename 省略時（None）に refs が空または filename を含まない。"""
        from lib.parsers.junos import parse_junos
        warnings = []
        diag = []
        parse_junos(GROUPS_HEAVY_JUNOS, warnings, diagnostics=diag)
        # filename=None でも entry 自体は追加される（refs は空）
        entry = next((d for d in diag if d["kind"] == "junos_apply_groups_unexpanded"), None)
        assert entry is not None
        assert entry["refs"] == [] or None not in entry["refs"]


# ---------------------------------------------------------------------------
# #3: parse_config ディスパッチャ経由の diagnostics 引き渡しテスト
# ---------------------------------------------------------------------------

class TestParseConfigDispatcherDiagnostics:
    """parse_config(text, warnings, diagnostics=...) で junos diagnostics が通る。"""

    def test_parse_config_passes_diagnostics_to_junos(self):
        """parse_config 経由で JunOS groups 多用警告が diagnostics に届く。"""
        from lib.parsers import parse_config
        warnings = []
        diag = []
        parse_config(GROUPS_HEAVY_JUNOS, warnings, diagnostics=diag)
        kinds = [d["kind"] for d in diag]
        assert "junos_apply_groups_unexpanded" in kinds

    def test_parse_config_diagnostics_ios_no_groups_warning(self):
        """IOS config では parse_config 経由でも groups 警告は発生しない。"""
        from lib.parsers import parse_config
        warnings = []
        diag = []
        parse_config(NORMAL_IOS, warnings, diagnostics=diag)
        kinds = [d["kind"] for d in diag]
        assert "junos_apply_groups_unexpanded" not in kinds

    def test_parse_config_diagnostics_defaults_to_none(self):
        """parse_config の diagnostics 省略で後方互換（従来の挙動不変）。"""
        from lib.parsers import parse_config
        dev = parse_config(NORMAL_JUNOS_SET, [])
        assert dev is not None
        assert dev.hostname == "R2"


# ---------------------------------------------------------------------------
# #4: build_topology.py 統合テスト（波括弧 config → topology dict に diagnostics 載る）
# ---------------------------------------------------------------------------

class TestBuildTopologyIntegration:
    """build_topology.py を通じた end-to-end 統合テスト。"""

    def test_brace_config_produces_diagnostics_in_topology(self, tmp_path):
        """波括弧 JunOS config をファイルで渡すと topology dict に diagnostics が載る。"""
        import sys
        from pathlib import Path

        # build_topology.py の main を直接呼び出す
        skill_root = Path(__file__).resolve().parents[2]
        brace_cfg = tmp_path / "brace-router.conf"
        brace_cfg.write_text(BRACE_JUNOS, encoding="utf-8")
        out_dir = tmp_path / "topology"

        scripts_dir = skill_root / "scripts"
        sys.path.insert(0, str(skill_root))
        # scripts/build_topology.py の main を import して呼ぶ
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "build_topology_script", scripts_dir / "build_topology.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        ret = mod.main([str(brace_cfg), "-o", str(out_dir)])
        assert ret == 0

        # 出力 YAML に diagnostics が含まれるか確認
        from lib.topology_io import load_topology
        topo = load_topology(str(out_dir))
        assert "diagnostics" in topo
        kinds = [d["kind"] for d in topo["diagnostics"]]
        assert "junos_brace_format" in kinds

    def test_normal_configs_produce_no_diagnostics(self, tmp_path):
        """正常な IOS / JunOS(set) config では topology に diagnostics キーが出ない。"""
        import sys
        from pathlib import Path

        skill_root = Path(__file__).resolve().parents[2]
        # 正常な JunOS set config を書く
        junos_cfg = tmp_path / "normal.conf"
        junos_cfg.write_text(NORMAL_JUNOS_SET, encoding="utf-8")
        out_dir = tmp_path / "topology_normal"

        scripts_dir = skill_root / "scripts"
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "build_topology_script2", scripts_dir / "build_topology.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        ret = mod.main([str(junos_cfg), "-o", str(out_dir)])
        assert ret == 0

        from lib.topology_io import load_topology
        topo = load_topology(str(out_dir))
        # 正常 config では diagnostics キーが出ないか、出ても空
        assert "diagnostics" not in topo or not topo["diagnostics"]
