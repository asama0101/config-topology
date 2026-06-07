"""
build_topology.py — 結線推論層

正規化済みの Device リストを受け取り、topology dict を返す。

公開 API:
    build(devices: list[Device], generated_from: list[str],
          title: str = "Network Topology (config-derived)") -> dict

CLI:
    python scripts/build_topology.py [paths...] [-o <出力ディレクトリ>]
        - paths 省略時は parse_configs.collect_inputs() で workspace/ から収集
        - parse_configs.parse_paths() で Device 群を得て build() し、
          topology_io.dump_topology() で -o（既定 topology/）へ層別 YAML 書き出し

設計判断:
    - ipaddress 標準モジュールのみ使用（外部依存なし）
    - 決定性を保証: 乱数・時刻に依存しない、全リストは安定ソート
    - link-inference.md および schema.md に厳密準拠
"""

from __future__ import annotations

import ipaddress
import os
import re
import sys
from collections import defaultdict

# スクリプトから直接実行された場合もインポートできるようにパスを追加
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)  # バンドルルート（scripts/ の1階層上）
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from lib.parsers.base import Device, sort_addresses as _sort_addresses_base, derive_ip_from_addresses as _derive_ip_base


# ================================================================
# Phase 3F: addresses ヘルパー（base.py 共通関数へ委譲）
# テストからの import 参照（_sort_addresses / _derive_ip_from_addresses）を維持する
# ================================================================

def _sort_addresses(addresses: list) -> list:
    """addresses リストを決定的にソートして返す（base.sort_addresses に委譲）。

    テスト・topology_io からの参照を維持するための再エクスポート関数。
    詳細は lib.parsers.base.sort_addresses を参照。

    Args:
        addresses: アドレス dict のリスト

    Returns:
        ソート済みの新しいリスト
    """
    return _sort_addresses_base(addresses)


def _derive_ip_from_addresses(addresses: list) -> str | None:
    """addresses リストから ip フィールド値（後方互換 CIDR）を導出する（base.derive_ip_from_addresses に委譲）。

    テスト・topology_io からの参照を維持するための再エクスポート関数。
    詳細は lib.parsers.base.derive_ip_from_addresses を参照。

    Args:
        addresses: アドレス dict のリスト（ソート済みを想定）

    Returns:
        "a.b.c.d/prefixlen" 形式の文字列、または None
    """
    return _derive_ip_base(addresses)


# ================================================================
# ID 採番
# ================================================================

def _make_device_id_base(hostname: str) -> str:
    """hostname を device id の基底文字列に変換する。

    - 小文字化
    - 英数字・ハイフン以外を '-' に置換
    - 空文字列の場合は 'device'
    """
    if not hostname:
        return "device"
    base = hostname.lower()
    base = re.sub(r"[^a-z0-9\-]", "-", base)
    return base


def _assign_device_ids(devices: list[Device]) -> list[str]:
    """Device リストに対して決定的な device id を採番する。

    重複時は -2, -3 ... を付与する。入力の順序を保持する。
    別 hostname が正規化後に既存 ID と衝突する場合も、
    発行済み ID セットと衝突しないサフィックスまでカウントを繰り上げる。
    """
    issued: set[str] = set()
    counter: dict[str, int] = {}
    ids: list[str] = []

    for device in devices:
        base = _make_device_id_base(device.hostname)
        count = counter.get(base, 0) + 1

        if count == 1:
            candidate = base
        else:
            candidate = f"{base}-{count}"

        # 衝突が解消されるまでカウントを繰り上げる
        while candidate in issued:
            count += 1
            candidate = f"{base}-{count}"

        counter[base] = count
        issued.add(candidate)
        ids.append(candidate)

    return ids


# ================================================================
# build() メイン関数
# ================================================================

def build(
    devices: list[Device],
    generated_from: list[str],
    title: str = "Network Topology (config-derived)",
) -> dict:
    """Device リストから topology dict（schema.md 準拠・レイヤー別 YAML 正本）を組み立てる。

    Args:
        devices: 正規化済み Device のリスト（パーサ層出力）
        generated_from: 元になった config ファイル名（読み込み順）
        title: 図のタイトル

    Returns:
        topology dict（schema.md 準拠・レイヤー別 YAML 正本と互換）
    """
    # --- generated_from を basename に正規化（フルパスが渡されても情報漏洩しない） ---
    generated_from = [os.path.basename(p) for p in generated_from]

    # --- device id 採番 ---
    device_ids = _assign_device_ids(devices)

    # --- devices セクション ---
    devices_out: list[dict] = []
    for dev, dev_id in zip(devices, device_ids):
        devices_out.append({
            "id": dev_id,
            "hostname": dev.hostname,
            "vendor": dev.vendor,
            "as": dev.asn,
            # Phase 4 (router-id): addition-only（既存キー不変）
            "ospf_router_id": getattr(dev, "ospf_router_id", None),
            "bgp_router_id": getattr(dev, "bgp_router_id", None),
            "sections": [],
        })

    # --- interfaces セクション (device 順 × config 出現順) ---
    interfaces_out: list[dict] = []
    for dev, dev_id in zip(devices, device_ids):
        for iface in dev.interfaces:
            # Phase 3F: addresses をソートして出力（決定的）
            sorted_addrs = _sort_addresses(getattr(iface, "addresses", []))
            # ip は addresses から派生（後方互換: addresses がなければ iface.ip を信頼）
            derived_ip = _derive_ip_from_addresses(sorted_addrs) if sorted_addrs else iface.ip
            interfaces_out.append({
                "id": f"{dev_id}::{iface.name}",
                "device": dev_id,
                "name": iface.name,
                "ip": derived_ip,
                "vlan": iface.vlan,
                "description": iface.description,
                "shutdown": iface.shutdown,
                # Phase 2D: IF属性拡充（admin_status はパーサ計算結果をそのまま信頼する）
                "admin_status": iface.admin_status,
                "oper_status": iface.oper_status,
                "mtu": iface.mtu,
                "speed": iface.speed,
                "duplex": iface.duplex,
                "l2_l3": iface.l2_l3,
                "switchport": iface.switchport,
                "encapsulation": iface.encapsulation,
                "source": iface.source,
                # Phase 3F: dual-stack アドレス正本
                "addresses": sorted_addrs,
            })

    # --- リンク推論 ---
    links_out, segments_out = _infer_links_and_segments(devices, device_ids)

    # --- OSPF area 逆引き: links に ospf_area / ospf_network を付与 ---
    _annotate_links_with_ospf_area(links_out, devices, device_ids)

    # --- OSPF area 逆引き: segments に ospf_area / ospf_network を付与 ---
    _annotate_segments_with_ospf_area(segments_out, devices, device_ids)

    # --- BGP 解決 ---
    bgp_out = _build_bgp(devices, device_ids)

    # --- OSPF ---
    # Phase 3I [HIGH1a]: area を _normalize_ospf_area で正規化（"0.0.0.0" → "0" 等）
    # Phase 3I [HIGH1b]: network が非CIDR(IF名)の場合、device の IF addresses から CIDR を導出
    ospf_out: list[dict] = []
    for dev, dev_id in zip(devices, device_ids):
        for entry in dev.ospf:
            # HIGH1a: area 正規化
            normalized_area = _normalize_ospf_area(entry.area) if entry.area else entry.area

            # HIGH1b: network が非CIDR(IF名)のとき addresses から CIDR を解決
            resolved_network = _resolve_ospf_network_to_cidr(dev, entry.network, entry.af)

            ospf_out.append({
                "device": dev_id,
                "process": entry.process,
                "network": resolved_network,
                "area": normalized_area,
                "af": entry.af,  # Phase 3G: af フィールド（base.py デフォルト "v4"）
            })

    # --- Static ---
    static_out: list[dict] = []
    for dev, dev_id in zip(devices, device_ids):
        for entry in dev.static:
            static_out.append({
                "device": dev_id,
                "prefix": entry.prefix,
                "next_hop": entry.next_hop,
                "af": entry.af,  # Phase 3G: af フィールド（base.py デフォルト "v4"）
            })

    return {
        "title": title,
        "generated_from": generated_from,
        "devices": devices_out,
        "interfaces": interfaces_out,
        "links": links_out,
        "segments": segments_out,
        "routing": {
            "bgp": bgp_out,
            "ospf": ospf_out,
            "static": static_out,
        },
    }


# ================================================================
# リンク推論
# ================================================================

def _infer_links_and_segments(
    devices: list[Device],
    device_ids: list[str],
) -> tuple[list[dict], list[dict]]:
    """サブネットによる結線推論を行い links と segments を返す。

    Rules (link-inference.md 準拠, Phase 3F 拡張):
    - shutdown=False の IF のみ対象
    - Phase 3F: addresses リストの各アドレスごとにネットワークを算出してグルーピング
      - addresses が空の場合は従来の ip フィールドにフォールバック（後方互換）
      - link-local（fe80::/10 = is_link_local）は結線推論から除外
      - 同一 IF が同一 network に複数アドレスで属しても members に IF を1回のみ登録
    - ネットワーク（ip_interface.network）でグルーピング
      - メンバー 2 かつ別機器ペアが存在 → links に 1 本
      - メンバー >= 3 → segments に 1 ノード
      - メンバー 1 → スタブ（何もしない）
    - 同一機器内の同一サブネット: 自己ループ link を作らない

    後方互換保証:
      IPv4-only config（addresses なし or v4 のみ）では links/segments が従来と完全一致する。
    """
    # (network_str) → list of (dev_id, if_name)
    # 同一 IF が同一 network に重複登録されないよう set で管理
    subnet_to_members: dict[str, list[tuple[str, str]]] = defaultdict(list)
    # 重複除去用: (network_str, dev_id, if_name) の集合
    seen_entries: set[tuple[str, str, str]] = set()

    for dev, dev_id in zip(devices, device_ids):
        for iface in dev.interfaces:
            if iface.shutdown:
                continue

            addresses = getattr(iface, "addresses", [])

            if addresses:
                # Phase 3F: addresses から各アドレスをグルーピングに追加
                for addr in addresses:
                    ip_str = addr.get("ip", "")
                    prefix = addr.get("prefix", 0)
                    if not ip_str:
                        continue
                    cidr = f"{ip_str}/{prefix}"
                    try:
                        net = ipaddress.ip_interface(cidr).network
                    except ValueError:
                        continue
                    # link-local を除外（fe80::/10 = is_link_local）
                    if net.is_link_local:
                        continue
                    network_str = str(net)
                    key = (network_str, dev_id, iface.name)
                    if key not in seen_entries:
                        seen_entries.add(key)
                        subnet_to_members[network_str].append((dev_id, iface.name))
            else:
                # フォールバック: 旧形式（ip フィールドのみ）
                if iface.ip is None:
                    continue
                try:
                    network = str(ipaddress.ip_interface(iface.ip).network)
                except ValueError:
                    continue
                key = (network, dev_id, iface.name)
                if key not in seen_entries:
                    seen_entries.add(key)
                    subnet_to_members[network].append((dev_id, iface.name))

    links_out: list[dict] = []
    segments_out: list[dict] = []

    for network_str, members in sorted(subnet_to_members.items()):
        count = len(members)

        if count == 1:
            # スタブ: 何もしない
            continue

        if count == 2:
            # メンバー 2: link 候補
            (dev_a, if_a), (dev_b, if_b) = members
            if dev_a == dev_b:
                # 同一機器 → 自己ループを作らない
                continue
            # a < b で安定化
            if dev_a > dev_b:
                dev_a, if_a, dev_b, if_b = dev_b, if_b, dev_a, if_a
            links_out.append({
                "a_device": dev_a,
                "a_if": if_a,
                "b_device": dev_b,
                "b_if": if_b,
                "subnet": network_str,
                "kind": "inferred-subnet",
            })

        else:
            # メンバー >= 3: segment
            seg_id = "seg-" + network_str.replace(".", "_").replace("/", "_")
            member_ids = sorted(
                f"{dev_id}::{if_name}" for dev_id, if_name in members
            )
            segments_out.append({
                "id": seg_id,
                "subnet": network_str,
                "members": member_ids,
            })

    # links は (a_device, a_if) 昇順でソート
    links_out.sort(key=lambda l: (l["a_device"], l["a_if"]))
    # segments は id 昇順
    segments_out.sort(key=lambda s: s["id"])

    return links_out, segments_out


# ================================================================
# 共通ヘルパー
# ================================================================

def _make_id_to_device(
    devices: list[Device],
    device_ids: list[str],
) -> dict[str, Device]:
    """device_id → Device の逆引き辞書を返す（複数箇所で共通利用）。"""
    return {dev_id: dev for dev, dev_id in zip(devices, device_ids)}


# ================================================================
# OSPF area 正規化
# ================================================================

def _normalize_ospf_area(area: str) -> str:
    """OSPF area 表現を正規化して数値文字列（または元の文字列）で返す。

    IOS は "area 0" を area="0" として保存し、
    JunOS は "area 0.0.0.0" を area="0.0.0.0" として保存する。
    両者は同一エリアを指すため、dotted-decimal 表現を整数文字列に変換して統一する。

    変換ルール:
    - "0.0.0.0" → "0"  (0 * 2^24 + 0 * 2^16 + 0 * 2^8 + 0 = 0)
    - "0.0.0.1" → "1"
    - "0.0.1.0" → "256"
    - "0.0.0.0" 形式でないもの（例 "0", "1", "backbone"）はそのまま返す

    Args:
        area: OSPF area 文字列（例 "0", "0.0.0.0", "1", "backbone"）

    Returns:
        正規化した area 文字列。パース不能な場合は元の文字列をそのまま返す。
    """
    if not area:
        return area

    # 既に純粋な数値なら変換不要
    if area.isdigit():
        return area

    # dotted-decimal パターン: "a.b.c.d" を整数変換
    parts = area.split(".")
    if len(parts) == 4:
        try:
            octets = [int(p) for p in parts]
            # 各オクテットが 0-255 の範囲内であること
            if all(0 <= o <= 255 for o in octets):
                value = (octets[0] << 24) | (octets[1] << 16) | (octets[2] << 8) | octets[3]
                return str(value)
        except (ValueError, OverflowError):
            pass

    # パース不能: 元の文字列を返す（クラッシュしない）
    return area


def _resolve_ospf_network_to_cidr(
    dev: "Device",
    network: str,
    af: str,
) -> str:
    """OSPF エントリの network が非CIDR(IF名)の場合、addresses から CIDR を導出して返す。

    Phase 3I [HIGH1b]: JunOS ospf3 は IF名（例 "ge-0/0/0.0"）を network として記録する。
    _build_ospf_marking_map は CIDR を期待するため、IF名のままでは ospf_id が解決できない。

    解決ルール:
    - network が有効な CIDR（ip_network でパース可能）なら変更しない（IOS等 既にCIDR）
    - network が非CIDR（IF名）の場合:
        - ユニット表記（ge-0/0/0.0）はドット前のベース名（ge-0/0/0）で IF を特定
        - dev の interfaces から name が一致する IF を探す
        - af が "v6" なら addresses の先頭 v6 GUA（scope != link-local）から ip_interface.network を取得
        - af が "v4" なら IF の ip フィールドから ip_interface.network を取得
        - 解決できた場合はネットワークアドレス CIDR を返す
        - 解決できない場合は元の文字列を返す（クラッシュしない）

    Args:
        dev:     Device オブジェクト（interfaces を参照）
        network: OSPF エントリの network フィールド（CIDR または IF名）
        af:      アドレスファミリ（"v4" or "v6"）

    Returns:
        CIDR 文字列（解決済み）または元の文字列（変更不能時）
    """
    if not network:
        return network

    # CIDR として解析可能なら変更不要
    try:
        ipaddress.ip_network(network, strict=False)
        return network  # 既に CIDR
    except ValueError:
        pass

    # 非CIDR: IF名として解釈（ユニット表記 ge-0/0/0.0 → ベース ge-0/0/0）
    base_if = network.split(".")[0]

    for iface in dev.interfaces:
        if iface.name != base_if:
            continue
        if iface.shutdown:
            continue  # shutdown IF は参照しない

        if af == "v6":
            # v6: addresses リストから先頭 GUA を取得
            for addr in getattr(iface, "addresses", []):
                if addr.get("af") != "v6":
                    continue
                if addr.get("scope") == "link-local":
                    continue
                ip_str = addr.get("ip", "")
                prefix = addr.get("prefix", 0)
                if not ip_str:
                    continue
                try:
                    net = ipaddress.ip_interface(f"{ip_str}/{prefix}").network
                    return str(net)
                except ValueError:
                    continue
        else:
            # v4: iface.ip フィールドから
            if iface.ip is not None:
                try:
                    net = ipaddress.ip_interface(iface.ip).network
                    return str(net)
                except ValueError:
                    pass

    # 解決不能: 元の文字列を返す
    return network


# ================================================================
# OSPF area 逆引き
# ================================================================

def _resolve_ospf_area_for_device(
    dev: Device,
    subnet_network: ipaddress.IPv4Network | ipaddress.IPv6Network,
) -> str | None:
    """device の OSPF エントリから subnet_network をカバーする area を返す。

    - IOS（e.network が CIDR）: e.network をパースして subnet_network と比較。
      subnet_network == e.network またはサブネットとして包含される場合に一致。
      IPv4/IPv6 バージョン不一致の場合はスキップ（TypeError 回避）。
    - JunOS（e.network が IF 名）: device の interface で name が一致するものを探し、
      その IP から算出した network が subnet_network と一致するか判定。
      IF 名のユニット表記（ge-0/0/0.0 等）はベース部分（ge-0/0/0）で突き合わせる。
      IF の network と subnet_network のバージョン不一致の場合はスキップ。

    一致した最初の area を返す。一致しない場合は None。
    """
    # device の IF 名 → network の逆引きテーブルを構築
    # JunOS 解決に必要（IF 名からサブネットを算出するため）
    # IPv4/IPv6 混在対応: バージョンが一致する IF のみ登録
    # Phase 3G: addresses リストの v6 エントリも登録（OSPFv3 の JunOS 解決に必要）
    if_name_to_network: dict[str, ipaddress.IPv4Network | ipaddress.IPv6Network] = {}
    for iface in dev.interfaces:
        if iface.shutdown:
            continue
        # v4: ip フィールドから（後方互換）
        if iface.ip is not None:
            try:
                iface_network = ipaddress.ip_interface(iface.ip).network
                if iface_network.version == subnet_network.version:
                    if_name_to_network[iface.name] = iface_network
            except ValueError:
                pass
        # Phase 3G: addresses から v6 エントリも登録（OSPFv3 向け）
        for addr in getattr(iface, "addresses", []):
            if addr.get("af") != "v6":
                continue
            ip_str = addr.get("ip", "")
            prefix = addr.get("prefix", 0)
            if not ip_str:
                continue
            # link-local は除外（OSPFv3 は GUA のみ対象）
            if addr.get("scope") == "link-local":
                continue
            try:
                v6_network = ipaddress.ip_interface(f"{ip_str}/{prefix}").network
                if v6_network.version == subnet_network.version:
                    # v4 登録済みかつ今回 v6 なら版不一致のため v6 で上書き
                    # v6 のみの場合も登録（v4 IF のない IF に対応）
                    if iface.name not in if_name_to_network:
                        if_name_to_network[iface.name] = v6_network
                    elif if_name_to_network[iface.name].version != v6_network.version:
                        if_name_to_network[iface.name] = v6_network
            except ValueError:
                continue

    # クエリ subnet の af を判定（af ガード比較に使用）
    subnet_af = "v6" if subnet_network.version == 6 else "v4"

    for entry in dev.ospf:
        net_str = entry.network
        area = entry.area

        # af ガード: entry の af とクエリ subnet の af を突き合わせ、不一致はスキップ。
        # OspfNetwork.af はパーサーが常に設定する（既定 "v4"）ため entry_af is None は
        # 実際には発生しない。is not None チェックは念のための防御的ガード。
        # 通常は af 一致判定のみが機能し、
        # OSPFv3(af=v6) は v4 subnet に、OSPFv2(af=v4) は v6 subnet にマッチしない。
        entry_af = getattr(entry, "af", None)
        if entry_af is not None and entry_af != subnet_af:
            continue

        # IOS パス: CIDR として解釈を試みる
        try:
            entry_network = ipaddress.ip_network(net_str, strict=False)
            # IPv4/IPv6 バージョン不一致の場合はスキップ（TypeError 回避）
            if entry_network.version != subnet_network.version:
                continue
            # subnet_network が entry_network と一致するかサブネットであれば採用
            if subnet_network == entry_network or subnet_network.subnet_of(entry_network):
                return area
            continue
        except ValueError:
            pass

        # JunOS パス: IF 名として解釈（CIDR パース失敗）
        # ユニット表記（ge-0/0/0.0）のドット以降を除去してベース IF 名を得る
        base_if = net_str.split(".")[0]
        # dev の interfaces から name が base_if に一致するものを探す
        # af ガードで entry_af == subnet_af が保証済みのため版不一致は発生しない
        resolved_network = if_name_to_network.get(base_if)
        if resolved_network is not None and resolved_network == subnet_network:
            return area

    return None


def _annotate_links_with_ospf_area(
    links: list[dict],
    devices: list[Device],
    device_ids: list[str],
) -> None:
    """links リストを in-place で更新し、各 link に ospf_area / ospf_network を付与する。

    付与条件:
    - 少なくとも片端の device が OSPF で subnet をカバーしている場合
    - 両端が OSPF 参加かつ area が同一 → ospf_area = 単一 area 文字列（例 "0"）
    - 両端が OSPF 参加かつ area が異なる → ospf_area = 昇順スラッシュ区切り（例 "0/1"）
    - 片端のみ OSPF 参加 → その端の area を ospf_area に設定
    - OSPF 非参加リンクには ospf_area / ospf_network を付けない

    Args:
        links: _infer_links_and_segments() が生成した links リスト（in-place 更新）
        devices: Device リスト
        device_ids: devices に対応する device id リスト
    """
    # device_id → Device の逆引き
    id_to_device = _make_id_to_device(devices, device_ids)

    for link in links:
        try:
            subnet_network = ipaddress.ip_network(link["subnet"], strict=False)
        except ValueError:
            continue

        a_dev_id = link["a_device"]
        b_dev_id = link["b_device"]

        a_device = id_to_device.get(a_dev_id)
        b_device = id_to_device.get(b_dev_id)

        area_a: str | None = None
        area_b: str | None = None

        if a_device is not None:
            area_a = _resolve_ospf_area_for_device(a_device, subnet_network)
        if b_device is not None:
            area_b = _resolve_ospf_area_for_device(b_device, subnet_network)

        # 少なくとも片端が OSPF 参加の場合のみ付与
        if area_a is None and area_b is None:
            # OSPF 非参加: フィールドを付けない
            continue

        # area を集約（決定的: 数値ソート → 数値でない混在なら lex ソート）
        # Phase 3H: 集約前に各 area を正規化（"0.0.0.0" → "0" 等）
        areas_set = {_normalize_ospf_area(a) for a in {area_a, area_b} if a is not None}
        if all(a.isdigit() for a in areas_set):
            areas = sorted(areas_set, key=int)
        else:
            areas = sorted(areas_set)
        if len(areas) == 1:
            ospf_area_val = areas[0]
        else:
            ospf_area_val = "/".join(areas)

        link["ospf_area"] = ospf_area_val
        link["ospf_network"] = link["subnet"]


def _annotate_segments_with_ospf_area(
    segments: list[dict],
    devices: list[Device],
    device_ids: list[str],
) -> None:
    """segments リストを in-place で更新し、各 segment に ospf_area / ospf_network を付与する。

    付与条件:
    - 少なくとも1機器が OSPF で subnet をカバーしている場合
    - 参加機器全員の area が同一 → ospf_area = 単一 area 文字列（例 "1"）
    - 参加機器間で area が異なる → ospf_area = 昇順スラッシュ区切り（例 "0/1"）
    - OSPF 非参加セグメントには ospf_area / ospf_network を付けない

    _annotate_links_with_ospf_area と同一ロジック（segments 版）。

    Args:
        segments: _infer_links_and_segments() が生成した segments リスト（in-place 更新）
        devices: Device リスト
        device_ids: devices に対応する device id リスト
    """
    # device_id → Device の逆引き
    id_to_device = _make_id_to_device(devices, device_ids)
    # interface id → device id の逆引き（segment members 解決用）
    iface_id_to_device_id: dict[str, str] = {}
    for dev, dev_id in zip(devices, device_ids):
        for iface in dev.interfaces:
            iface_id = f"{dev_id}::{iface.name}"
            iface_id_to_device_id[iface_id] = dev_id

    for seg in segments:
        try:
            subnet_network = ipaddress.ip_network(seg["subnet"], strict=False)
        except ValueError:
            continue

        # メンバー interface id からユニークな device id を収集
        member_device_ids: set[str] = set()
        for member_iface_id in seg.get("members", []):
            dev_id = iface_id_to_device_id.get(member_iface_id)
            if dev_id:
                member_device_ids.add(dev_id)

        # 各メンバー機器の OSPF area を解決
        areas_set: set[str] = set()
        for dev_id in sorted(member_device_ids):  # 決定的処理のためソート
            device = id_to_device.get(dev_id)
            if device is not None:
                area = _resolve_ospf_area_for_device(device, subnet_network)
                if area is not None:
                    areas_set.add(area)

        # OSPF 非参加セグメントには付けない
        if not areas_set:
            continue

        # Phase 3H: 集約前に各 area を正規化（"0.0.0.0" → "0" 等）
        areas_set = {_normalize_ospf_area(a) for a in areas_set}

        # area を集約（決定的: 数値ソート → 数値でない混在なら lex ソート）
        if all(a.isdigit() for a in areas_set):
            areas = sorted(areas_set, key=int)
        else:
            areas = sorted(areas_set)

        if len(areas) == 1:
            ospf_area_val = areas[0]
        else:
            ospf_area_val = "/".join(areas)

        seg["ospf_area"] = ospf_area_val
        seg["ospf_network"] = seg["subnet"]


# ================================================================
# BGP 解決
# ================================================================

def _build_bgp(
    devices: list[Device],
    device_ids: list[str],
) -> list[dict]:
    """BGP エントリを組み立てる。

    - local_ip: neighbor_ip と同一サブネットにある自機 IF の IP（ホスト部）
    - type: ebgp / ibgp / unknown
    """
    bgp_out: list[dict] = []

    for dev, dev_id in zip(devices, device_ids):
        for neighbor in dev.bgp:
            local_ip = _resolve_local_ip(dev, neighbor.neighbor_ip)
            bgp_type = _determine_bgp_type(dev.asn, neighbor.peer_as)

            bgp_out.append({
                "device": dev_id,
                "local_as": dev.asn,
                "local_ip": local_ip,
                "neighbor_ip": neighbor.neighbor_ip,
                "peer_as": neighbor.peer_as,
                "type": bgp_type,
                "af": neighbor.af,  # Phase 3G: af フィールド（base.py デフォルト "v4"）
            })

    return bgp_out


def _resolve_local_ip(dev: Device, neighbor_ip: str) -> str | None:
    """neighbor_ip と同一サブネットにある自機 IF の IP（ホスト部のみ）を返す。

    同一サブネットの IF が見つからなければ None を返す。

    Phase 3G 拡張:
    - neighbor_ip の IP バージョン（v4/v6）を判定し、一致する版の IF アドレスを検索する。
    - v4 の場合: Interface.ip（CIDR）を参照（従来通り）。
    - v6 の場合: Interface.addresses リストの v6 エントリを参照し、
      同一サブネットにある自 IF の v6 アドレス（ホスト部のみ）を返す。
    """
    try:
        neighbor_addr = ipaddress.ip_address(neighbor_ip)
    except ValueError:
        return None

    if neighbor_addr.version == 4:
        # v4: 従来通り Interface.ip（CIDR）を参照
        for iface in dev.interfaces:
            if iface.ip is None:
                continue
            try:
                iface_net = ipaddress.ip_interface(iface.ip)
            except ValueError:
                continue
            if neighbor_addr in iface_net.network:
                return str(iface_net.ip)
    else:
        # v6: addresses リストの v6 エントリを参照
        for iface in dev.interfaces:
            addresses = getattr(iface, "addresses", [])
            for addr in addresses:
                if addr.get("af") != "v6":
                    continue
                ip_str = addr.get("ip", "")
                prefix = addr.get("prefix", 0)
                if not ip_str:
                    continue
                try:
                    iface_net = ipaddress.ip_interface(f"{ip_str}/{prefix}")
                    if neighbor_addr in iface_net.network:
                        return str(iface_net.ip)
                except ValueError:
                    continue

    return None


def _determine_bgp_type(local_as: int | None, peer_as: int | None) -> str:
    """BGP タイプを判定する。

    - peer_as 不明または local_as 不明 → unknown
    - local_as == peer_as → ibgp
    - それ以外（両方既知かつ異なる）→ ebgp
    """
    if peer_as is None or local_as is None:
        return "unknown"
    if local_as == peer_as:
        return "ibgp"
    return "ebgp"


# ================================================================
# CLI
# ================================================================

def main() -> None:
    """CLI エントリポイント。"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Build layer-split YAML topology from network config files."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Config file paths. If omitted, collects from workspace/.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="topology",
        help="Output directory for layer-split YAML files (default: topology)",
    )
    args = parser.parse_args()

    from scripts.parse_configs import collect_inputs, parse_paths
    from lib.topology_io import dump_topology

    if args.paths:
        paths: list[str] = []
        for arg in args.paths:
            paths.extend(collect_inputs(arg))
    else:
        paths = collect_inputs()

    devices = parse_paths(paths)
    generated_from = [os.path.basename(p) for p in paths]
    topology = build(devices, generated_from=generated_from)

    dump_topology(topology, args.output)

    print(f"[INFO] Written: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
