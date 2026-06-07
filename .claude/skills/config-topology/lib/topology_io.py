"""
topology_io.py — レイヤー別 YAML I/O 層（Stage1）

topology dict（schema.md 準拠）をレイヤー別 YAML ファイルに分割して書き出し・読み込みする。

公開 API:
    dump_topology(topology: dict, out_dir: str) -> None
        topology dict を out_dir 以下のレイヤー別 YAML に書き出す。

    load_topology(in_dir: str) -> dict
        レイヤー別 YAML を読み込み、従来の topology dict に再組み立てして返す。

ファイルレイアウト:
    out_dir/
      _meta.yaml            # {schema_version, title, generated_from}
      devices.yaml          # {devices, interfaces}
      physical.yaml         # {links, segments}
      routing.<key>.yaml    # {<key>: [...]}  ← 非空の routing キーのみ生成（汎用）

設計判断:
    - yaml.safe_dump / yaml.safe_load のみ使用（任意 Python オブジェクト復元禁止）
    - sort_keys=True, default_flow_style=False, allow_unicode=True で決定的出力
    - 参照整合チェック: dangling 参照を ValueError で送出（ファイル名・フィールド・値を明示）
    - schema_version メジャーが未知（1 以外）なら stderr 警告（前方互換、例外にしない）
    - out_dir が存在しない場合は makedirs で自動作成
    - routing キーは ^[a-z0-9_-]+$ のみ許可。不正キーは stderr 警告＋スキップ
    - 各 YAML ファイルの内容が dict でない場合 ValueError（ファイル名明示）
    - 参照整合エラーメッセージは os.path.basename のみ使用（絶対パス非露出）
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any

import yaml

SCHEMA_VERSION = "1.0"

# routing キーの許可パターン（CSS/HTML クラス名として安全な文字のみ）
_ROUTING_KEY_RE = re.compile(r'^[a-z0-9_-]+$')

# ================================================================
# ユーティリティ
# ================================================================


def _safe_dump_file(path: str, data: Any) -> None:
    """data を YAML ファイルに決定的に書き出す。"""
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            sort_keys=True,
            default_flow_style=False,
            allow_unicode=True,
        )


def _safe_load_file(path: str) -> Any:
    """YAML ファイルを safe_load で読み込む。

    Raises:
        FileNotFoundError: ファイルが存在しない場合
        yaml.YAMLError: YAML パースエラー（危険タグ含む）
    """
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ================================================================
# dump_topology
# ================================================================


def dump_topology(topology: dict, out_dir: str) -> None:
    """topology dict をレイヤー別 YAML として out_dir に書き出す。

    Args:
        topology: schema.md 準拠の topology dict
        out_dir:  出力先ディレクトリ（存在しない場合は自動作成）
    """
    os.makedirs(out_dir, exist_ok=True)

    routing = topology.get("routing", {})

    # _meta.yaml
    _safe_dump_file(
        os.path.join(out_dir, "_meta.yaml"),
        {
            "generated_from": topology.get("generated_from", []),
            "schema_version": SCHEMA_VERSION,
            "title": topology.get("title", ""),
        },
    )

    # devices.yaml（devices が空でも常に書く）
    _safe_dump_file(
        os.path.join(out_dir, "devices.yaml"),
        {
            "devices": topology.get("devices", []),
            "interfaces": topology.get("interfaces", []),
        },
    )

    # physical.yaml（常に書く）
    _safe_dump_file(
        os.path.join(out_dir, "physical.yaml"),
        {
            "links": topology.get("links", []),
            "segments": topology.get("segments", []),
        },
    )

    # routing.*.yaml（非空のみ書く、任意キー汎用対応）
    for key in sorted(routing.keys()):
        if not _ROUTING_KEY_RE.match(key):
            print(
                f"[WARNING] topology_io: routing キー '{key}' は無効な形式です "
                f"(^[a-z0-9_-]+$ のみ許可)。スキップします。",
                file=sys.stderr,
            )
            continue
        entries = routing.get(key, [])
        if entries:
            _safe_dump_file(
                os.path.join(out_dir, f"routing.{key}.yaml"),
                {key: entries},
            )


# ================================================================
# load_topology
# ================================================================


def _synthesize_addresses_from_ip(ip_cidr: str | None) -> list:
    """旧形式の ip フィールド（CIDR）から addresses リストを合成する（後方互換吸収用）。

    Phase 3F: addresses キーが存在しない旧 YAML を読み込む際に使用する。
    ip="a.b.c.d/prefix" → [{"af": "v4", "ip": "a.b.c.d", "prefix": n}]
    ip が None または不正な場合は空リストを返す。

    注意: この関数は base.derive_ip_from_addresses の**逆写像**（逆変換）である。
    derive_ip_from_addresses(addresses) → ip_cidr という正方向に対して、
    _synthesize_addresses_from_ip(ip_cidr) → addresses[0] の逆変換を担う。

    Args:
        ip_cidr: "a.b.c.d/prefixlen" 形式の文字列、または None

    Returns:
        addresses リスト（0 または 1 エントリ）
    """
    import ipaddress as _ip
    if not ip_cidr:
        return []
    try:
        iface = _ip.ip_interface(ip_cidr)
        af = "v4" if iface.version == 4 else "v6"
        return [{"af": af, "ip": str(iface.ip), "prefix": iface.network.prefixlen}]
    except ValueError:
        return []


def load_topology(in_dir: str) -> dict:
    """レイヤー別 YAML を読み込み従来の topology dict を返す。

    Args:
        in_dir: レイヤー別 YAML が置かれているディレクトリ

    Returns:
        schema.md 準拠の topology dict

    Raises:
        FileNotFoundError: in_dir が存在しない、または必須ファイルが欠落
        ValueError: 参照整合エラー（dangling 参照）
        yaml.YAMLError: 危険な YAML タグを含む場合
    """
    if not os.path.isdir(in_dir):
        raise FileNotFoundError(f"ディレクトリが存在しません: {in_dir}")

    # --- 必須ファイルの読み込み ---
    meta = _load_required(in_dir, "_meta.yaml")
    dev_data = _load_required(in_dir, "devices.yaml")
    phys_data = _load_required(in_dir, "physical.yaml")

    # --- dict 型チェック（list/スカラー/None → ValueError） ---
    _assert_dict(meta, "_meta.yaml")
    _assert_dict(dev_data, "devices.yaml")
    _assert_dict(phys_data, "physical.yaml")

    # --- schema_version チェック ---
    schema_version = str(meta.get("schema_version", "1.0"))
    major = schema_version.split(".")[0]
    if major != "1":
        print(
            f"[WARNING] topology_io: 未知の schema_version '{schema_version}' "
            f"(サポート: 1.x)。読み込みを継続します。",
            file=sys.stderr,
        )

    # --- routing.*.yaml（ディレクトリ内を全スキャンして汎用読み込み） ---
    # まず bgp/ospf/static のデフォルトキーを保証する
    routing: dict[str, list] = {"bgp": [], "ospf": [], "static": []}
    # ディレクトリ内の routing.*.yaml を全て読み込む
    for fname in sorted(os.listdir(in_dir)):
        if not fname.startswith("routing.") or not fname.endswith(".yaml"):
            continue
        # routing.<key>.yaml からキーを導出
        key = fname[len("routing."):-len(".yaml")]
        if not _ROUTING_KEY_RE.match(key):
            print(
                f"[WARNING] topology_io: ファイル '{fname}' のキー '{key}' は無効な形式です "
                f"(^[a-z0-9_-]+$ のみ許可)。スキップします。",
                file=sys.stderr,
            )
            continue
        path = os.path.join(in_dir, fname)
        data = _safe_load_file(path)
        if data is not None:
            _assert_dict(data, fname)
            routing[key] = data.get(key, [])
        else:
            routing[key] = []

    interfaces = dev_data.get("interfaces", [])

    # Phase 3F: 旧形式（addresses キーなし）の interfaces を吸収する
    # addresses が欠如している interface に ip フィールドから合成した addresses を付与する
    for iface in interfaces:
        if "addresses" not in iface:
            iface["addresses"] = _synthesize_addresses_from_ip(iface.get("ip"))

    topology: dict = {
        "title": meta.get("title", ""),
        "generated_from": meta.get("generated_from", []),
        "devices": dev_data.get("devices", []),
        "interfaces": interfaces,
        "links": phys_data.get("links", []),
        "segments": phys_data.get("segments", []),
        "routing": routing,
    }

    # --- 参照整合の検証 ---
    _validate_references(topology, in_dir)

    return topology


def _load_required(in_dir: str, filename: str) -> Any:
    """必須 YAML ファイルを読み込む。欠落は FileNotFoundError を送出。"""
    path = os.path.join(in_dir, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"必須ファイルが存在しません: {os.path.basename(path)}")
    data = _safe_load_file(path)
    return data if data is not None else {}


def _assert_dict(data: Any, filename: str) -> None:
    """data が dict でない場合 ValueError を送出する（filename は basename のみ）。"""
    if not isinstance(data, dict):
        basename = os.path.basename(filename)
        raise ValueError(
            f"ファイル '{basename}' の内容が dict 形式でありません: "
            f"{type(data).__name__} が得られました。"
        )


# ================================================================
# 参照整合チェック
# ================================================================


def _validate_references(topology: dict, in_dir: str) -> None:
    """topology dict 内の参照整合を検証する。

    dangling 参照（存在しない device id・interface id への参照）を検出し、
    ValueError でファイル名（basename のみ）・フィールド名・不正値を明示して送出する。

    チェック対象:
      1. interfaces[].device  → device id 集合
      2. links[].a_device     → device id 集合
      3. links[].b_device     → device id 集合
      4. links[].a_if         → a_device の IF 名集合
      5. links[].b_if         → b_device の IF 名集合
      6. segments[].members   → interface id 集合
      7. routing.*[].device   → device id 集合（全キー汎用）
    """
    devices: list[dict] = topology.get("devices", [])
    interfaces: list[dict] = topology.get("interfaces", [])
    links: list[dict] = topology.get("links", [])
    segments: list[dict] = topology.get("segments", [])
    routing: dict = topology.get("routing", {})

    # インデックス構築
    device_ids: set[str] = {d["id"] for d in devices}
    interface_ids: set[str] = {i["id"] for i in interfaces}
    # device_id → IF 名集合
    device_if_names: dict[str, set[str]] = {}
    for iface in interfaces:
        dev_id = iface.get("device", "")
        device_if_names.setdefault(dev_id, set()).add(iface.get("name", ""))

    # 1. interfaces[].device（basename のみ使用）
    dev_yaml = "devices.yaml"
    for iface in interfaces:
        val = iface.get("device")
        if val not in device_ids:
            raise ValueError(
                f"参照整合エラー [{dev_yaml}] "
                f"interfaces[id={iface.get('id')!r}].device={val!r} は "
                f"存在しない device id です。"
            )

    # 2-5. links[].a_device, b_device, a_if, b_if（basename のみ使用）
    phys_yaml = "physical.yaml"
    for link in links:
        a_dev = link.get("a_device")
        b_dev = link.get("b_device")
        a_if = link.get("a_if")
        b_if = link.get("b_if")

        if a_dev not in device_ids:
            raise ValueError(
                f"参照整合エラー [{phys_yaml}] "
                f"links[subnet={link.get('subnet')!r}].a_device={a_dev!r} は "
                f"存在しない device id です。"
            )
        if b_dev not in device_ids:
            raise ValueError(
                f"参照整合エラー [{phys_yaml}] "
                f"links[subnet={link.get('subnet')!r}].b_device={b_dev!r} は "
                f"存在しない device id です。"
            )
        # a_if は a_device の IF 名に存在するか
        if a_if not in device_if_names.get(a_dev, set()):
            raise ValueError(
                f"参照整合エラー [{phys_yaml}] "
                f"links[subnet={link.get('subnet')!r}].a_if={a_if!r} は "
                f"device {a_dev!r} に存在しない interface 名です。"
            )
        # b_if は b_device の IF 名に存在するか
        if b_if not in device_if_names.get(b_dev, set()):
            raise ValueError(
                f"参照整合エラー [{phys_yaml}] "
                f"links[subnet={link.get('subnet')!r}].b_if={b_if!r} は "
                f"device {b_dev!r} に存在しない interface 名です。"
            )

    # 6. segments[].members → interface id 集合
    for seg in segments:
        for member in seg.get("members", []):
            if member not in interface_ids:
                raise ValueError(
                    f"参照整合エラー [{phys_yaml}] "
                    f"segments[id={seg.get('id')!r}].members に "
                    f"存在しない interface id {member!r} が含まれています。"
                )

    # 7. routing.*[].device → device id 集合（全キー汎用）
    for key in routing.keys():
        _check_routing_device_refs(routing.get(key, []), key, device_ids)


def _check_routing_device_refs(
    entries: list[dict],
    proto: str,
    device_ids: set[str],
) -> None:
    """routing.*[].device の参照整合チェック（basename のみ使用）。"""
    filename = f"routing.{proto}.yaml"
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        val = entry.get("device")
        if val not in device_ids:
            raise ValueError(
                f"参照整合エラー [{filename}] "
                f"routing.{proto}[device={val!r}].device={val!r} は "
                f"存在しない device id です。"
            )
