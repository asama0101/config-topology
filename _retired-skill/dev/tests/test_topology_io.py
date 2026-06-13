"""
TDD テスト: topology_io.dump_topology() / load_topology()

テスト方針:
  1. round-trip: examples/topology/ → dump → load が完全一致（idempotent）
     正本は examples/topology/（層別 YAML ディレクトリ）に一本化
  2. 決定性: 同一 dict を2回 dump してバイト一致
  3. レイアウト: _meta.yaml / devices.yaml / physical.yaml が常に生成
     routing.* は非空プロトコルのみ生成（空では生成しない）
  4. 欠落耐性: routing.* ファイルが無い dir を load → routing キーが [] で例外なし
  5. 参照整合エラー:
     - interfaces[].device が不正 → ValueError（ファイル名・不正値含む）
     - links[].a_device/b_device が不正 → ValueError
     - links[].a_if/b_if が不正 → ValueError
     - segments[].members が不正 → ValueError
     - routing.bgp[].device が不正 → ValueError
     - routing.ospf[].device が不正 → ValueError
     - routing.static[].device が不正 → ValueError
  6. schema_version: _meta.yaml に "1.0" が出る
     未知メジャー "2.0" → 警告が stderr に出るが load は成功
  7. セキュリティ: 危険な YAML タグ（!!python/object 等）は safe_load でオブジェクト生成されない
  8. in_dir 不存在 / _meta.yaml 欠落 は明確なエラー
  A. routing キー汎用化: vrrp 等の任意キーの round-trip・不正キーの警告+スキップ
  B. 堅牢性: list/None 形式の不正 YAML → ValueError（ファイル名含む）; id 欠落 → ValueError
"""

from __future__ import annotations

import io
import os
import warnings

import pytest
import yaml

from lib.topology_io import dump_topology, load_topology

# ================================================================
# フィクスチャ
# D. golden 一本化: examples/topology/ の層別 YAML を正本とする
# ================================================================

_EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "examples")
_TOPOLOGY_DIR = os.path.join(_EXAMPLES_DIR, "topology")


@pytest.fixture
def sample_topology() -> dict:
    """examples/topology/ を load_topology() で読み込む（正本: 層別 YAML）。"""
    return load_topology(_TOPOLOGY_DIR)


@pytest.fixture
def dumped_dir(tmp_path, sample_topology) -> str:
    """sample_topology を tmp_path に dump した dir パスを返す。"""
    out = str(tmp_path / "topo")
    dump_topology(sample_topology, out)
    return out


# ================================================================
# 1. round-trip（最重要）
# ================================================================

@pytest.mark.unit
def test_roundtrip_equals_original(sample_topology, tmp_path):
    """dump → load が元の topology dict と完全一致する。"""
    # Arrange
    out_dir = str(tmp_path / "rt")

    # Act
    dump_topology(sample_topology, out_dir)
    loaded = load_topology(out_dir)

    # Assert: 全キー完全一致
    assert loaded["title"] == sample_topology["title"]
    assert loaded["generated_from"] == sample_topology["generated_from"]
    assert loaded["devices"] == sample_topology["devices"]
    assert loaded["interfaces"] == sample_topology["interfaces"]
    assert loaded["links"] == sample_topology["links"]
    assert loaded["segments"] == sample_topology["segments"]
    assert loaded["routing"] == sample_topology["routing"]
    # まとめて比較
    assert loaded == sample_topology


# ================================================================
# 2. 決定性
# ================================================================

@pytest.mark.unit
def test_dump_deterministic(sample_topology, tmp_path):
    """同一 dict を2回 dump した各ファイルがバイト一致する。"""
    dir1 = str(tmp_path / "d1")
    dir2 = str(tmp_path / "d2")

    dump_topology(sample_topology, dir1)
    dump_topology(sample_topology, dir2)

    for filename in [
        "_meta.yaml",
        "devices.yaml",
        "physical.yaml",
        "routing.bgp.yaml",
        "routing.ospf.yaml",
        "routing.static.yaml",
    ]:
        path1 = os.path.join(dir1, filename)
        path2 = os.path.join(dir2, filename)
        assert os.path.exists(path1), f"{filename} が dir1 に存在しない"
        assert os.path.exists(path2), f"{filename} が dir2 に存在しない"
        with open(path1, "rb") as f1, open(path2, "rb") as f2:
            assert f1.read() == f2.read(), f"{filename} のバイト列が一致しない"


# ================================================================
# 3. レイアウト
# ================================================================

@pytest.mark.unit
def test_layout_mandatory_files_exist(dumped_dir):
    """_meta.yaml / devices.yaml / physical.yaml が常に生成される。"""
    for fname in ["_meta.yaml", "devices.yaml", "physical.yaml"]:
        assert os.path.exists(os.path.join(dumped_dir, fname)), \
            f"必須ファイル {fname} が存在しない"


@pytest.mark.unit
def test_layout_routing_files_exist_when_nonempty(dumped_dir):
    """sample は bgp/ospf/static すべて非空 → 3ファイルが生成される。"""
    for fname in ["routing.bgp.yaml", "routing.ospf.yaml", "routing.static.yaml"]:
        assert os.path.exists(os.path.join(dumped_dir, fname)), \
            f"routing ファイル {fname} が存在しない"


@pytest.mark.unit
def test_layout_routing_files_absent_when_empty(tmp_path):
    """routing.* が空の dict では当該 YAML ファイルが生成されない。"""
    topo = {
        "title": "Empty",
        "generated_from": [],
        "devices": [],
        "interfaces": [],
        "links": [],
        "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }
    out_dir = str(tmp_path / "empty")
    dump_topology(topo, out_dir)

    for fname in ["routing.bgp.yaml", "routing.ospf.yaml", "routing.static.yaml"]:
        assert not os.path.exists(os.path.join(out_dir, fname)), \
            f"空 routing なのに {fname} が生成された"


@pytest.mark.unit
def test_layout_partial_routing(tmp_path, sample_topology):
    """bgp のみ非空なら routing.bgp.yaml だけが生成される。"""
    topo = dict(sample_topology)
    topo["routing"] = {
        "bgp": sample_topology["routing"]["bgp"],
        "ospf": [],
        "static": [],
    }
    out_dir = str(tmp_path / "partial")
    dump_topology(topo, out_dir)

    assert os.path.exists(os.path.join(out_dir, "routing.bgp.yaml"))
    assert not os.path.exists(os.path.join(out_dir, "routing.ospf.yaml"))
    assert not os.path.exists(os.path.join(out_dir, "routing.static.yaml"))


@pytest.mark.unit
def test_layout_devices_yaml_always_written_even_empty(tmp_path):
    """devices が空でも devices.yaml は書く（基盤）。"""
    topo = {
        "title": "NoDevices",
        "generated_from": [],
        "devices": [],
        "interfaces": [],
        "links": [],
        "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }
    out_dir = str(tmp_path / "nodev")
    dump_topology(topo, out_dir)

    assert os.path.exists(os.path.join(out_dir, "devices.yaml"))


# ================================================================
# 4. 欠落耐性
# ================================================================

@pytest.mark.unit
def test_missing_routing_files_load_as_empty_lists(dumped_dir):
    """routing.* ファイルを消して load → 各キーが [] で例外なし。"""
    for fname in ["routing.bgp.yaml", "routing.ospf.yaml", "routing.static.yaml"]:
        path = os.path.join(dumped_dir, fname)
        if os.path.exists(path):
            os.remove(path)

    loaded = load_topology(dumped_dir)
    assert loaded["routing"]["bgp"] == []
    assert loaded["routing"]["ospf"] == []
    assert loaded["routing"]["static"] == []


@pytest.mark.unit
def test_routing_keys_always_present(tmp_path):
    """routing.* が全部ないとき、routing dict は bgp/ospf/static キーを持つ。"""
    topo = {
        "title": "T",
        "generated_from": [],
        "devices": [],
        "interfaces": [],
        "links": [],
        "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }
    out_dir = str(tmp_path / "norout")
    dump_topology(topo, out_dir)
    # routing ファイルが生成されていないので load すると全部空リスト
    loaded = load_topology(out_dir)
    assert "bgp" in loaded["routing"]
    assert "ospf" in loaded["routing"]
    assert "static" in loaded["routing"]


# ================================================================
# 5. 参照整合エラー
# ================================================================

def _write_yaml(path: str, data) -> None:
    """テスト用ヘルパー: data を YAML ファイルに書く。"""
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=True, default_flow_style=False, allow_unicode=True)


@pytest.fixture
def corrupted_dir(dumped_dir) -> str:
    """dump 済み dir を返すファクトリ（各テストで個別ファイルを改ざんする）。"""
    return dumped_dir


@pytest.mark.unit
def test_integrity_invalid_interface_device(tmp_path, sample_topology):
    """interfaces[].device が存在しない device id → ValueError（ファイル名と不正値を含む）。"""
    out_dir = str(tmp_path / "bad_iface_dev")
    dump_topology(sample_topology, out_dir)

    # devices.yaml を直接改ざん
    dev_path = os.path.join(out_dir, "devices.yaml")
    with open(dev_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["interfaces"][0]["device"] = "nonexistent-device"
    _write_yaml(dev_path, data)

    with pytest.raises(ValueError) as exc_info:
        load_topology(out_dir)
    msg = str(exc_info.value)
    assert "nonexistent-device" in msg
    assert "device" in msg.lower()


@pytest.mark.unit
def test_integrity_invalid_link_a_device(tmp_path, sample_topology):
    """links[].a_device が存在しない device id → ValueError。"""
    out_dir = str(tmp_path / "bad_link_adev")
    dump_topology(sample_topology, out_dir)

    phys_path = os.path.join(out_dir, "physical.yaml")
    with open(phys_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["links"][0]["a_device"] = "ghost-device"
    _write_yaml(phys_path, data)

    with pytest.raises(ValueError) as exc_info:
        load_topology(out_dir)
    msg = str(exc_info.value)
    assert "ghost-device" in msg


@pytest.mark.unit
def test_integrity_invalid_link_b_device(tmp_path, sample_topology):
    """links[].b_device が存在しない device id → ValueError。"""
    out_dir = str(tmp_path / "bad_link_bdev")
    dump_topology(sample_topology, out_dir)

    phys_path = os.path.join(out_dir, "physical.yaml")
    with open(phys_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["links"][0]["b_device"] = "phantom"
    _write_yaml(phys_path, data)

    with pytest.raises(ValueError) as exc_info:
        load_topology(out_dir)
    assert "phantom" in str(exc_info.value)


@pytest.mark.unit
def test_integrity_invalid_link_a_if(tmp_path, sample_topology):
    """links[].a_if が a_device の IF 名に存在しない → ValueError。"""
    out_dir = str(tmp_path / "bad_link_aif")
    dump_topology(sample_topology, out_dir)

    phys_path = os.path.join(out_dir, "physical.yaml")
    with open(phys_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["links"][0]["a_if"] = "NoSuchInterface999"
    _write_yaml(phys_path, data)

    with pytest.raises(ValueError) as exc_info:
        load_topology(out_dir)
    assert "NoSuchInterface999" in str(exc_info.value)


@pytest.mark.unit
def test_integrity_invalid_link_b_if(tmp_path, sample_topology):
    """links[].b_if が b_device の IF 名に存在しない → ValueError。"""
    out_dir = str(tmp_path / "bad_link_bif")
    dump_topology(sample_topology, out_dir)

    phys_path = os.path.join(out_dir, "physical.yaml")
    with open(phys_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["links"][0]["b_if"] = "NonExistentIF"
    _write_yaml(phys_path, data)

    with pytest.raises(ValueError) as exc_info:
        load_topology(out_dir)
    assert "NonExistentIF" in str(exc_info.value)


@pytest.mark.unit
def test_integrity_invalid_segment_member(tmp_path):
    """segments[].members が interface id 集合に存在しない → ValueError。"""
    topo = {
        "title": "T",
        "generated_from": [],
        "devices": [
            {"id": "sw1", "hostname": "SW1", "vendor": "cisco_ios", "as": None, "sections": []},
            {"id": "sw2", "hostname": "SW2", "vendor": "cisco_ios", "as": None, "sections": []},
            {"id": "sw3", "hostname": "SW3", "vendor": "cisco_ios", "as": None, "sections": []},
        ],
        "interfaces": [
            {"id": "sw1::eth0", "device": "sw1", "name": "eth0", "ip": "10.1.1.1/24", "vlan": None, "description": None, "shutdown": False},
            {"id": "sw2::eth0", "device": "sw2", "name": "eth0", "ip": "10.1.1.2/24", "vlan": None, "description": None, "shutdown": False},
            {"id": "sw3::eth0", "device": "sw3", "name": "eth0", "ip": "10.1.1.3/24", "vlan": None, "description": None, "shutdown": False},
        ],
        "links": [],
        "segments": [
            {"id": "seg-10_1_1_0_24", "subnet": "10.1.1.0/24",
             "members": ["sw1::eth0", "sw2::eth0", "sw3::eth0"]},
        ],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }
    out_dir = str(tmp_path / "bad_seg")
    dump_topology(topo, out_dir)

    phys_path = os.path.join(out_dir, "physical.yaml")
    with open(phys_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["segments"][0]["members"].append("ghost::if999")
    _write_yaml(phys_path, data)

    with pytest.raises(ValueError) as exc_info:
        load_topology(out_dir)
    assert "ghost::if999" in str(exc_info.value)


@pytest.mark.unit
def test_integrity_invalid_routing_bgp_device(tmp_path, sample_topology):
    """routing.bgp[].device が存在しない device id → ValueError。"""
    out_dir = str(tmp_path / "bad_bgp_dev")
    dump_topology(sample_topology, out_dir)

    bgp_path = os.path.join(out_dir, "routing.bgp.yaml")
    with open(bgp_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["bgp"][0]["device"] = "deleted-device"
    _write_yaml(bgp_path, data)

    with pytest.raises(ValueError) as exc_info:
        load_topology(out_dir)
    msg = str(exc_info.value)
    assert "deleted-device" in msg
    assert "routing.bgp.yaml" in msg


@pytest.mark.unit
def test_integrity_invalid_routing_ospf_device(tmp_path, sample_topology):
    """routing.ospf[].device が存在しない device id → ValueError。"""
    out_dir = str(tmp_path / "bad_ospf_dev")
    dump_topology(sample_topology, out_dir)

    ospf_path = os.path.join(out_dir, "routing.ospf.yaml")
    with open(ospf_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["ospf"][0]["device"] = "gone-device"
    _write_yaml(ospf_path, data)

    with pytest.raises(ValueError) as exc_info:
        load_topology(out_dir)
    msg = str(exc_info.value)
    assert "gone-device" in msg
    assert "routing.ospf.yaml" in msg


@pytest.mark.unit
def test_integrity_invalid_routing_static_device(tmp_path, sample_topology):
    """routing.static[].device が存在しない device id → ValueError。"""
    out_dir = str(tmp_path / "bad_static_dev")
    dump_topology(sample_topology, out_dir)

    static_path = os.path.join(out_dir, "routing.static.yaml")
    with open(static_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["static"][0]["device"] = "missing-device"
    _write_yaml(static_path, data)

    with pytest.raises(ValueError) as exc_info:
        load_topology(out_dir)
    msg = str(exc_info.value)
    assert "missing-device" in msg
    assert "routing.static.yaml" in msg


# ================================================================
# 6. schema_version
# ================================================================

@pytest.mark.unit
def test_schema_version_in_meta(dumped_dir):
    """_meta.yaml に schema_version: "1.0" が出力される。"""
    meta_path = os.path.join(dumped_dir, "_meta.yaml")
    with open(meta_path, encoding="utf-8") as f:
        meta = yaml.safe_load(f)
    assert meta["schema_version"] == "1.0"


@pytest.mark.unit
def test_unknown_major_version_warns_but_loads(dumped_dir, capsys):
    """未知メジャー "2.0" → stderr に警告が出るが load は成功する。"""
    meta_path = os.path.join(dumped_dir, "_meta.yaml")
    with open(meta_path, encoding="utf-8") as f:
        meta = yaml.safe_load(f)
    meta["schema_version"] = "2.0"
    _write_yaml(meta_path, meta)

    result = load_topology(dumped_dir)
    captured = capsys.readouterr()
    assert "2.0" in captured.err or "2" in captured.err
    # load は成功（例外なし）
    assert "title" in result


# ================================================================
# 7. セキュリティ: 危険な YAML タグ
# ================================================================

@pytest.mark.unit
def test_safe_load_rejects_python_object_tag(dumped_dir):
    """!!python/object タグを含む YAML を load しても任意オブジェクトが生成されない。"""
    # _meta.yaml に危険タグを埋め込む
    dangerous_yaml = (
        "schema_version: '1.0'\n"
        "title: !!python/object/apply:os.system ['echo pwned']\n"
        "generated_from: []\n"
    )
    meta_path = os.path.join(dumped_dir, "_meta.yaml")
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write(dangerous_yaml)

    # yaml.safe_load は !!python/object を解釈できないので例外を出す
    # (任意オブジェクトが生成されないことが重要)
    with pytest.raises(yaml.YAMLError):
        load_topology(dumped_dir)


# ================================================================
# 8. ディレクトリ/ファイル欠落エラー
# ================================================================

@pytest.mark.unit
def test_load_nonexistent_dir_raises():
    """存在しない dir を load → 分かりやすいエラー（FileNotFoundError か ValueError）。"""
    with pytest.raises((FileNotFoundError, ValueError)):
        load_topology("/nonexistent/path/12345")


@pytest.mark.unit
def test_load_missing_meta_raises(dumped_dir):
    """_meta.yaml が欠落していると FileNotFoundError か ValueError。"""
    os.remove(os.path.join(dumped_dir, "_meta.yaml"))
    with pytest.raises((FileNotFoundError, ValueError)):
        load_topology(dumped_dir)


@pytest.mark.unit
def test_load_missing_devices_raises(dumped_dir):
    """devices.yaml が欠落していると FileNotFoundError か ValueError。"""
    os.remove(os.path.join(dumped_dir, "devices.yaml"))
    with pytest.raises((FileNotFoundError, ValueError)):
        load_topology(dumped_dir)


@pytest.mark.unit
def test_load_missing_physical_raises(dumped_dir):
    """physical.yaml が欠落していると FileNotFoundError か ValueError。"""
    os.remove(os.path.join(dumped_dir, "physical.yaml"))
    with pytest.raises((FileNotFoundError, ValueError)):
        load_topology(dumped_dir)


# ================================================================
# 9. 出力ディレクトリが存在しない場合に自動生成
# ================================================================

@pytest.mark.unit
def test_dump_creates_outdir(sample_topology, tmp_path):
    """out_dir が存在しなくても dump_topology が自動作成する。"""
    new_dir = str(tmp_path / "new" / "nested" / "dir")
    assert not os.path.exists(new_dir)
    dump_topology(sample_topology, new_dir)
    assert os.path.isdir(new_dir)
    assert os.path.exists(os.path.join(new_dir, "_meta.yaml"))


# ================================================================
# 10. YAML 内容の正確性（ファイル内容の key/value 検証）
# ================================================================

@pytest.mark.unit
def test_meta_yaml_contains_title_and_generated_from(dumped_dir, sample_topology):
    """_meta.yaml に title と generated_from が含まれる。"""
    with open(os.path.join(dumped_dir, "_meta.yaml"), encoding="utf-8") as f:
        meta = yaml.safe_load(f)
    assert meta["title"] == sample_topology["title"]
    assert meta["generated_from"] == sample_topology["generated_from"]


@pytest.mark.unit
def test_devices_yaml_contains_devices_and_interfaces(dumped_dir, sample_topology):
    """devices.yaml に devices と interfaces が含まれる。"""
    with open(os.path.join(dumped_dir, "devices.yaml"), encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["devices"] == sample_topology["devices"]
    assert data["interfaces"] == sample_topology["interfaces"]


@pytest.mark.unit
def test_physical_yaml_contains_links_and_segments(dumped_dir, sample_topology):
    """physical.yaml に links と segments が含まれる。"""
    with open(os.path.join(dumped_dir, "physical.yaml"), encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["links"] == sample_topology["links"]
    assert data["segments"] == sample_topology["segments"]


@pytest.mark.unit
def test_routing_bgp_yaml_content(dumped_dir, sample_topology):
    """routing.bgp.yaml に bgp エントリが含まれる。"""
    with open(os.path.join(dumped_dir, "routing.bgp.yaml"), encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["bgp"] == sample_topology["routing"]["bgp"]


@pytest.mark.unit
def test_routing_ospf_yaml_content(dumped_dir, sample_topology):
    """routing.ospf.yaml に ospf エントリが含まれる。"""
    with open(os.path.join(dumped_dir, "routing.ospf.yaml"), encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["ospf"] == sample_topology["routing"]["ospf"]


@pytest.mark.unit
def test_routing_static_yaml_content(dumped_dir, sample_topology):
    """routing.static.yaml に static エントリが含まれる。"""
    with open(os.path.join(dumped_dir, "routing.static.yaml"), encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["static"] == sample_topology["routing"]["static"]


# ================================================================
# A. routing キー汎用化
# ================================================================

def _make_vrrp_topology(base: dict) -> dict:
    """base topology に vrrp キーを追加したコピーを返す。"""
    import copy
    topo = copy.deepcopy(base)
    topo["routing"]["vrrp"] = [
        {"device": list(topo["devices"])[0]["id"], "group": 1, "vip": "10.255.0.1"},
    ]
    return topo


@pytest.mark.unit
def test_routing_generic_key_roundtrip(sample_topology, tmp_path):
    """vrrp などの任意 routing キーが dump → load で完全保持される（round-trip）。"""
    import copy
    topo = copy.deepcopy(sample_topology)
    # devices の最初の id を使って vrrp エントリを作る
    first_dev_id = topo["devices"][0]["id"]
    topo["routing"]["vrrp"] = [
        {"device": first_dev_id, "group": 1, "vip": "10.255.0.1"},
    ]
    out_dir = str(tmp_path / "vrrp_rt")
    dump_topology(topo, out_dir)
    loaded = load_topology(out_dir)
    assert "vrrp" in loaded["routing"], "load 後 routing に vrrp キーが存在しない"
    assert loaded["routing"]["vrrp"] == topo["routing"]["vrrp"], \
        "vrrp エントリが round-trip 後に不一致"


@pytest.mark.unit
def test_routing_generic_key_file_generated(sample_topology, tmp_path):
    """vrrp キーが非空なら routing.vrrp.yaml が生成される。"""
    import copy
    topo = copy.deepcopy(sample_topology)
    first_dev_id = topo["devices"][0]["id"]
    topo["routing"]["vrrp"] = [{"device": first_dev_id, "group": 1}]
    out_dir = str(tmp_path / "vrrp_file")
    dump_topology(topo, out_dir)
    assert os.path.exists(os.path.join(out_dir, "routing.vrrp.yaml")), \
        "routing.vrrp.yaml が生成されていない"


@pytest.mark.unit
def test_routing_generic_key_file_absent_when_empty(sample_topology, tmp_path):
    """vrrp キーが空リストなら routing.vrrp.yaml は生成されない。"""
    import copy
    topo = copy.deepcopy(sample_topology)
    topo["routing"]["vrrp"] = []
    out_dir = str(tmp_path / "vrrp_empty")
    dump_topology(topo, out_dir)
    assert not os.path.exists(os.path.join(out_dir, "routing.vrrp.yaml")), \
        "空 vrrp なのに routing.vrrp.yaml が生成された"


@pytest.mark.unit
def test_routing_invalid_key_warned_and_skipped(tmp_path, capsys, sample_topology):
    """不正キー（スペース含む）は stderr 警告されスキップされる（ファイル生成なし）。"""
    import copy
    topo = copy.deepcopy(sample_topology)
    # スペースを含む不正キー
    topo["routing"]["a b"] = [{"device": "r1"}]
    out_dir = str(tmp_path / "invalid_key")
    dump_topology(topo, out_dir)
    captured = capsys.readouterr()
    # 不正キーに関する警告が stderr に出る
    assert "a b" in captured.err or "invalid" in captured.err.lower() or \
        "warn" in captured.err.lower() or captured.err != "", \
        "不正 routing キーに対して stderr 警告が出ていない"
    # 不正キーのファイルは生成されない
    assert not os.path.exists(os.path.join(out_dir, "routing.a b.yaml")), \
        "不正キー 'a b' のファイルが生成された"


@pytest.mark.unit
def test_routing_all_keys_generic_roundtrip(sample_topology, tmp_path):
    """bgp/ospf/static/vrrp/isis を含む topology の complete round-trip。"""
    import copy
    topo = copy.deepcopy(sample_topology)
    first_dev_id = topo["devices"][0]["id"]
    topo["routing"]["isis"] = [{"device": first_dev_id, "net": "49.0001.0001.0001.0001.00"}]
    topo["routing"]["vrrp"] = [{"device": first_dev_id, "group": 1, "vip": "10.0.0.254"}]
    out_dir = str(tmp_path / "multi_proto")
    dump_topology(topo, out_dir)
    loaded = load_topology(out_dir)
    assert loaded["routing"]["isis"] == topo["routing"]["isis"]
    assert loaded["routing"]["vrrp"] == topo["routing"]["vrrp"]
    assert loaded["routing"]["bgp"] == topo["routing"]["bgp"]


# ================================================================
# B. 堅牢性: 不正 YAML 形式 → ValueError
# ================================================================

@pytest.mark.unit
def test_load_list_devices_yaml_raises_valueerror(tmp_path, sample_topology):
    """devices.yaml が list 形式（dict でない）の場合 ValueError が発生する（ファイル名含む）。"""
    out_dir = str(tmp_path / "bad_list_dev")
    dump_topology(sample_topology, out_dir)
    # devices.yaml を list 形式で上書き
    dev_path = os.path.join(out_dir, "devices.yaml")
    with open(dev_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(["item1", "item2"], f)
    with pytest.raises(ValueError) as exc_info:
        load_topology(out_dir)
    msg = str(exc_info.value)
    assert "devices.yaml" in msg, f"エラーメッセージにファイル名がない: {msg}"


@pytest.mark.unit
def test_load_list_physical_yaml_raises_valueerror(tmp_path, sample_topology):
    """physical.yaml が list 形式（dict でない）の場合 ValueError が発生する（ファイル名含む）。"""
    out_dir = str(tmp_path / "bad_list_phys")
    dump_topology(sample_topology, out_dir)
    phys_path = os.path.join(out_dir, "physical.yaml")
    with open(phys_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(["item1"], f)
    with pytest.raises(ValueError) as exc_info:
        load_topology(out_dir)
    msg = str(exc_info.value)
    assert "physical.yaml" in msg, f"エラーメッセージにファイル名がない: {msg}"


@pytest.mark.unit
def test_load_scalar_meta_yaml_raises_valueerror(tmp_path, sample_topology):
    """_meta.yaml がスカラー（dict でない）の場合 ValueError が発生する（ファイル名含む）。"""
    out_dir = str(tmp_path / "bad_scalar_meta")
    dump_topology(sample_topology, out_dir)
    meta_path = os.path.join(out_dir, "_meta.yaml")
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write("just a string\n")
    with pytest.raises(ValueError) as exc_info:
        load_topology(out_dir)
    msg = str(exc_info.value)
    assert "_meta.yaml" in msg, f"エラーメッセージにファイル名がない: {msg}"


@pytest.mark.unit
def test_validate_missing_device_id_raises_valueerror(tmp_path):
    """devices[] に id キーがない要素は ValueError を送出する（ファイル名明示）。"""
    topo = {
        "title": "T",
        "generated_from": [],
        "devices": [
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": None, "sections": []},
        ],
        "interfaces": [],
        "links": [],
        "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }
    out_dir = str(tmp_path / "no_id_dev")
    dump_topology(topo, out_dir)
    # devices.yaml の devices[0] から id キーを削除
    dev_path = os.path.join(out_dir, "devices.yaml")
    with open(dev_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    del data["devices"][0]["id"]
    with open(dev_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=True)
    with pytest.raises((ValueError, KeyError)):
        load_topology(out_dir)


@pytest.mark.unit
def test_error_message_uses_basename_not_abspath(tmp_path, sample_topology):
    """参照整合エラーメッセージが絶対パスでなく basename のみを含む。"""
    out_dir = str(tmp_path / "basename_check")
    dump_topology(sample_topology, out_dir)
    dev_path = os.path.join(out_dir, "devices.yaml")
    with open(dev_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["interfaces"][0]["device"] = "nonexistent"
    with open(dev_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=True)
    with pytest.raises(ValueError) as exc_info:
        load_topology(out_dir)
    msg = str(exc_info.value)
    # 絶対パス（/home/... や /tmp/...）が含まれていないこと
    assert out_dir not in msg, \
        f"エラーメッセージに絶対パスが含まれている: {msg}"
    # basename が含まれている
    assert "devices.yaml" in msg, f"basename が含まれていない: {msg}"


@pytest.mark.unit
def test_yaml_error_in_routing_file_raises(tmp_path, sample_topology):
    """routing ファイルに !!python/object タグを含む場合 YAMLError または ValueError。"""
    out_dir = str(tmp_path / "yaml_err_routing")
    dump_topology(sample_topology, out_dir)
    bgp_path = os.path.join(out_dir, "routing.bgp.yaml")
    dangerous = "bgp:\n  - !!python/object/apply:os.system ['echo pwned']\n"
    with open(bgp_path, "w", encoding="utf-8") as f:
        f.write(dangerous)
    with pytest.raises((yaml.YAMLError, ValueError)):
        load_topology(out_dir)


# ================================================================
# D. golden 一本化の補完テスト
# ================================================================

@pytest.mark.unit
def test_golden_from_yaml_dir(sample_topology):
    """load_topology(examples/topology) が正しい topology を返す（title チェック）。"""
    assert "title" in sample_topology
    assert isinstance(sample_topology["devices"], list)
    assert len(sample_topology["devices"]) >= 1


@pytest.mark.unit
def test_golden_roundtrip_from_yaml_dir(sample_topology, tmp_path):
    """examples/topology/ → dump → load が完全一致する（二重 round-trip）。"""
    out_dir = str(tmp_path / "rt2")
    dump_topology(sample_topology, out_dir)
    loaded = load_topology(out_dir)
    assert loaded == sample_topology


# ================================================================
# Phase C #7: ospf_area / ospf_network の round-trip テスト
# ================================================================

@pytest.mark.unit
def test_link_with_ospf_area_roundtrip(sample_topology, tmp_path):
    """links に ospf_area / ospf_network が含まれる topology の dump → load round-trip。"""
    import copy
    topo = copy.deepcopy(sample_topology)
    assert topo["links"], "前提: sample_topology に links が存在すること（vacuous 防止）"
    topo["links"][0]["ospf_area"] = "0"
    topo["links"][0]["ospf_network"] = topo["links"][0]["subnet"]

    out_dir = str(tmp_path / "ospf_area_rt")
    dump_topology(topo, out_dir)
    loaded = load_topology(out_dir)

    # round-trip 一致
    assert loaded["links"] == topo["links"], \
        f"ospf_area 付き links が round-trip 後に不一致"


@pytest.mark.unit
def test_link_without_ospf_area_roundtrip(sample_topology, tmp_path):
    """ospf_area が欠如している links の dump → load round-trip（後方互換）。"""
    import copy
    topo = copy.deepcopy(sample_topology)
    # links の ospf_area を確実に欠如させる（既存フィールドがあれば削除）
    for lk in topo["links"]:
        lk.pop("ospf_area", None)
        lk.pop("ospf_network", None)

    out_dir = str(tmp_path / "no_ospf_area_rt")
    dump_topology(topo, out_dir)
    loaded = load_topology(out_dir)

    # ospf_area なしで round-trip 一致
    assert loaded["links"] == topo["links"], \
        f"ospf_area なし links が round-trip 後に不一致"


@pytest.mark.unit
def test_link_ospf_area_null_roundtrip(sample_topology, tmp_path):
    """ospf_area=None の links が dump → load で None のまま保持される。"""
    import copy
    topo = copy.deepcopy(sample_topology)
    assert topo["links"], "前提: sample_topology に links が存在すること（vacuous 防止）"
    topo["links"][0]["ospf_area"] = None
    topo["links"][0]["ospf_network"] = None

    out_dir = str(tmp_path / "ospf_null_rt")
    dump_topology(topo, out_dir)
    loaded = load_topology(out_dir)

    assert loaded["links"] == topo["links"], \
        f"ospf_area=None が round-trip 後に変化した"


@pytest.mark.unit
def test_link_ospf_area_mismatch_roundtrip(sample_topology, tmp_path):
    """ospf_area が '0/1' 形式（area 不一致）でも round-trip 一致する。"""
    import copy
    topo = copy.deepcopy(sample_topology)
    assert topo["links"], "前提: sample_topology に links が存在すること（vacuous 防止）"
    topo["links"][0]["ospf_area"] = "0/1"
    topo["links"][0]["ospf_network"] = topo["links"][0]["subnet"]

    out_dir = str(tmp_path / "ospf_mismatch_rt")
    dump_topology(topo, out_dir)
    loaded = load_topology(out_dir)

    assert loaded["links"] == topo["links"], \
        f"ospf_area='0/1' が round-trip 後に不一致"


@pytest.mark.unit
def test_link_ospf_area_does_not_break_reference_integrity(sample_topology, tmp_path):
    """ospf_area フィールド追加後も参照整合チェックが通る（T-refint: ospf_area 値も検証）。"""
    import copy
    topo = copy.deepcopy(sample_topology)
    assert topo["links"], "前提: sample_topology に links が存在すること（vacuous 防止）"
    topo["links"][0]["ospf_area"] = "0"
    topo["links"][0]["ospf_network"] = topo["links"][0]["subnet"]

    out_dir = str(tmp_path / "ospf_integrity")
    dump_topology(topo, out_dir)
    # 例外なく load できること（参照整合が壊れていない）
    loaded = load_topology(out_dir)
    assert loaded is not None
    # ospf_area フィールドが実際に round-trip 後も '0' として保持されること
    assert loaded["links"][0].get("ospf_area") == "0", \
        f"ospf_area='0' が round-trip 後に変化した: {loaded['links'][0]}"
    assert loaded["links"][0].get("ospf_network") == topo["links"][0]["subnet"], \
        f"ospf_network が round-trip 後に変化した: {loaded['links'][0]}"


# ================================================================
# #7: segment ospf_area round-trip テスト
# ================================================================

def _make_segment_topology_with_ospf():
    """segment に ospf_area が付いた人工 topology を返す。"""
    return {
        "title": "Segment OSPF Area Test",
        "generated_from": [],
        "devices": [
            {"id": "core1", "hostname": "CORE1", "vendor": "cisco_ios", "as": None, "sections": []},
            {"id": "acc1", "hostname": "ACC1", "vendor": "cisco_ios", "as": None, "sections": []},
            {"id": "acc2", "hostname": "ACC2", "vendor": "cisco_ios", "as": None, "sections": []},
        ],
        "interfaces": [
            {"id": "core1::GigabitEthernet0/2", "device": "core1",
             "name": "GigabitEthernet0/2", "ip": "192.168.50.1/24",
             "vlan": None, "description": None, "shutdown": False},
            {"id": "acc1::GigabitEthernet0/0", "device": "acc1",
             "name": "GigabitEthernet0/0", "ip": "192.168.50.2/24",
             "vlan": None, "description": None, "shutdown": False},
            {"id": "acc2::GigabitEthernet0/0", "device": "acc2",
             "name": "GigabitEthernet0/0", "ip": "192.168.50.3/24",
             "vlan": None, "description": None, "shutdown": False},
        ],
        "links": [],
        "segments": [
            {
                "id": "seg-192_168_50_0_24",
                "subnet": "192.168.50.0/24",
                "members": [
                    "acc1::GigabitEthernet0/0",
                    "acc2::GigabitEthernet0/0",
                    "core1::GigabitEthernet0/2",
                ],
                "ospf_area": "1",
                "ospf_network": "192.168.50.0/24",
            }
        ],
        "routing": {
            "bgp": [],
            "ospf": [
                {"device": "core1", "process": 1, "network": "192.168.50.0/24", "area": "1"},
                {"device": "acc1", "process": 1, "network": "192.168.50.0/24", "area": "1"},
                {"device": "acc2", "process": 1, "network": "192.168.50.0/24", "area": "1"},
            ],
            "static": [],
        },
    }


@pytest.mark.unit
def test_segment_ospf_area_roundtrip(tmp_path):
    """segments[].ospf_area が dump → load で保持される（round-trip）。"""
    topo = _make_segment_topology_with_ospf()

    out_dir = str(tmp_path / "seg_ospf_rt")
    dump_topology(topo, out_dir)
    loaded = load_topology(out_dir)

    assert loaded["segments"] == topo["segments"], \
        f"segments の round-trip が一致しない:\n期待: {topo['segments']}\n実際: {loaded['segments']}"


@pytest.mark.unit
def test_segment_ospf_area_field_preserved(tmp_path):
    """segments[].ospf_area の値 '1' が round-trip 後も '1' のまま。"""
    topo = _make_segment_topology_with_ospf()

    out_dir = str(tmp_path / "seg_ospf_val")
    dump_topology(topo, out_dir)
    loaded = load_topology(out_dir)

    seg = loaded["segments"][0]
    assert seg.get("ospf_area") == "1", \
        f"ospf_area='1' が round-trip 後に変化した: {seg}"


@pytest.mark.unit
def test_segment_ospf_network_field_preserved(tmp_path):
    """segments[].ospf_network の値が round-trip 後も保持される。"""
    topo = _make_segment_topology_with_ospf()

    out_dir = str(tmp_path / "seg_ospf_net")
    dump_topology(topo, out_dir)
    loaded = load_topology(out_dir)

    seg = loaded["segments"][0]
    assert seg.get("ospf_network") == "192.168.50.0/24", \
        f"ospf_network が round-trip 後に変化した: {seg}"


@pytest.mark.unit
def test_segment_without_ospf_area_roundtrip(tmp_path):
    """ospf_area なしのセグメントは round-trip 後も ospf_area を持たない（後方互換）。"""
    import copy
    topo = _make_segment_topology_with_ospf()
    # ospf_area を除去
    topo = copy.deepcopy(topo)
    del topo["segments"][0]["ospf_area"]
    del topo["segments"][0]["ospf_network"]

    out_dir = str(tmp_path / "seg_no_ospf")
    dump_topology(topo, out_dir)
    loaded = load_topology(out_dir)

    seg = loaded["segments"][0]
    assert "ospf_area" not in seg, \
        f"ospf_area がないセグメントに round-trip 後 ospf_area が付いた: {seg}"


@pytest.mark.unit
def test_segment_ospf_area_reference_integrity_preserved(tmp_path):
    """ospf_area 付きセグメントの dump → load で参照整合チェックが通る（壊さない）。"""
    topo = _make_segment_topology_with_ospf()

    out_dir = str(tmp_path / "seg_ospf_integrity")
    dump_topology(topo, out_dir)
    # 例外なく load できること
    loaded = load_topology(out_dir)
    assert loaded is not None
