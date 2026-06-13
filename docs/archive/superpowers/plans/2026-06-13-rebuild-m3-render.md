# M3: HTML レンダリング Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** M2 が生成する層別 YAML を読み込み、**単一・自己完結・決定的な HTML（SVG + バニラ JS）** を生成する `render_topology.py` CLI とレンダリング層を TDD で実装する。確定 UI 挙動は `docs/design-sample.html`（要件書 §8.5/§8.7 が正本指定）。

**Architecture:** 旧実装は Python が SVG 文字列を組み立てていたが、**確定サンプルは JS が DATA から SVG を描く**。よって M3 の Python 側責務は ①`topology dict → DATA`（denormalize・id 採番・extPeers/bgpEdges 導出）、②**決定的 POS レイアウト**（force-directed 相当・乱数/時刻不使用）、③CSS/JS（design-sample.html から移植・適応した静的アセット）＋ DATA/POS JSON を埋め込む HTML テンプレ組立、の3点に集約される。インタラクション（クリック/hover/選択/検索/表/注釈）の実体はバニラ JS で、ブラウザ実行＝§11.5 手動チェックリストで検証する。

**Tech Stack:** Python 3（pure Python）／ 依存は **PyYAML のみ**（load_topology 経由。M3 の新規コードは標準 `json`/`math`/`re`/`html`/`argparse` + PyYAML）／ JS/CSS はバニラ（フレームワーク禁止・外部アセット禁止）／ テストは pytest（`unit`/`integration`/`e2e`）＋ `node --check`（あれば）。

**仕様正本:** `docs/requirements.md` v2.1 §8（HTML 機能要件）・§10.1/§10.2（CLI）・§11.5（ブラウザ目視）・§3.3/§9.1（決定性）。確定挙動の正は `docs/design-sample.html`。進め方は `docs/implementation-instructions.md`（M3 = §8）。

**前提:** M1（パーサ）・M2（推論・層別 YAML）完了。ブランチ `rebuild-m1-parser` 上に `rebuild/` 配下で追加実装する。`rebuild/lib/topology_io.py::load_topology(dir)` が層別 YAML → topology dict を返す。

---

## 確定した方針（計画着手前の意思決定・確定済み）

1. **アドレス保持**: DATA の `ifs[]` に **`addrs[]`（全アドレス: af/ip/prefix/secondary/scope）** を持たせる。`ip`/`ip6`（主 v4 / 最初の GUA）は表示用に併存。検索コーパス・ADDRESSES/INTERFACES 表は `addrs[]` を使い、secondary・複数 GUA・link-local も対象にする（§8.5 検索仕様・§8.7 IPAM）。
2. **レイアウト**: **Python で決定的に POS を計算**し HTML に埋め込む（ビュー間ノード同一座標を保証・バイト決定性をテスト可能）。
3. **テスト戦略**: データ変換ユニット＋HTML 構造アサート＋決定性（同一 YAML → バイト一致）＋ `node --check`（あれば）を自動化。インタラクションは §11.5 手動チェックリスト。**HTML 全体のバイトゴールデンは持たない**（JS/CSS 改変で脆くなる）。構造アサート＋埋め込み DATA 一致＋再現バイト一致で担保。
4. **history 退避（§10.3）は M4** に属するため M3 CLI には入れない（M3 は生成＋上書き＋機密注意行のみ）。
5. **generic-proto ビュー（§9.3）は v1 ではスキップ**（dict に bgp/ospf/static しか無い）。タブ生成は将来拡張可能な形にする。
6. **外部ピア副ラベル**は素の `neighbor_ip`（description 補強はしない）。
7. **statusbar の skip 警告は出さない**（render は YAML しか読まず skip 情報を持たない。skip 通知は build の §10.4＝M4）。

## 横断制約（全タスク共通・違反禁止）

1. **実装先は `rebuild/` 配下のみ**。`.claude/skills/config-topology/` には書き込まない。旧 `lib/rendering/`（`layout.py`/`svg.py` 等）は**理解のための読み取りのみ可・コピー禁止**。特に旧 svg.py の **IF チップ描画は §8.4.1 で廃止**なので踏襲しない。
2. **単一・自己完結 HTML（§8.1）**: 外部 CSS/JS/画像参照なし（`http(s)://` の script/link/img なし、`<script src>`/`<link rel=stylesheet>` なし）。`file://` で開ける。
3. **決定性（§8.3/§9.1）**: 乱数・時刻・cwd 絶対パス不使用。同一層別 YAML → 同一 HTML（バイト一致）。POS は ID 昇順初期配置＋決定的反復。浮動小数は丸め（座標 `round(x,1)`）で plat 差を排除。
4. **依存追加禁止**: PyYAML 以外のサードパーティ禁止。
5. **IF チップ・選択●マーカーを描かない（§8.4.1/§8.5）**: 旧表現の誤移植を構造テストで弾く。

---

## DATA 契約（topology dict → この形に変換。JS が消費する正本形）

design-sample.html の JS が読むフィールド一式（architect 分析 + 方針1 の `addrs[]` 拡張）。data_transform はこの形を**厳密に**出力し、JS（assets）はこの形を読む。

```
DATA = {
  meta: { generated_from: [<basename>...] },
  devices: {                                  # id キーのオブジェクト
    "<id>": {
      hostname, vendor, as, ospf_rid, bgp_rid,
      ifs: [ { n, ip, ip6, d, st, mtu, sp,
               addrs: [ {af, ip, prefix, secondary?, scope?} ] } ],  # 方針1: 全アドレス
      bgp: [ { nb, pas, type, af, lip, link } ],   # link = bgpEdge id
      ospf:[ { net, area, proc } ],
      static:[ { p, nh } ],
    }, ...
  },
  links: [ { id, a, ai, aip, b, bi, bip, subnet, dual?, aip6?, bip6?, area?, admin_down? } ],
  segments: [ { id, subnet, area?, members:[ {dev, ifn, ip} ] } ],
  extPeers: [ { id, label, sub, as, from, link } ],
  bgpEdges: [
    { id, kind:"over-link", link, type, peerAs } |
    { id, kind:"loopback",  a, b, aip, bip, type, label } |
    { id, kind:"external",  a, ext, aip, bip, srcIf, type, peerAs }
  ],
}
POS = { "<nodeId>": {x, y} }    # 全 device id + segment id + ext id を網羅。座標は round(.,1)
VIEWS = ["physical", ("bgp"?), ("ospf"?), "addr", "ifs"]   # tabs.py が生成（§8.2）
```

フィールド派生規則（要点。詳細は各タスク）:
- `ifs[].ip` = 主 v4（最初の非 secondary v4）`"ip/prefix"` or null（= dict の interface.ip）。`ip6` = 最初の GUA（`scope!=link-local`）`"ip/prefix"` or null。`st` = interface.admin_status。`addrs[]` = 全 addresses（順序は §4.1 並び）。`role`/`note` は**出さない**（§8.7.3 ブラウザ永続・localStorage）。
- `links`: dict は link id 無し＋ dual-stack を v4/v6 別行で出す。**端点ペアでグルーピングして 1 本に統合**し、決定的 id を付与。`aip`/`bip` は各端点 IF の当該 subnet 内ホストアドレス。`dual`=v6 subnet、`aip6`/`bip6`=v6 ホスト。`area`=ospf_area、`admin_down`=presence-only。
- `segments[].members`: dict は iface_id 配列 → interfaces map で `{dev, ifn, ip}`（ip は subnet 内ホスト）。
- `extPeers`: `routing.bgp` で `neighbor_ip` が**どの機器 IF IP にも一致しない**もの。id=`"ext:"+neighbor_ip`、dedup・neighbor_ip 昇順。
- `bgpEdges`: 各セッションを over-link / loopback / external に分類。`bgp[].link` と `extPeers[].link` がこの id を参照。

---

## File Structure（`rebuild/lib/rendering/`）

| ファイル | 責務 |
|---------|------|
| `lib/rendering/__init__.py` | パッケージ marker |
| `lib/rendering/data_transform.py` | **topology dict → DATA**（pure・最大のテスト価値）。devices/ifs/routing/links/segments/extPeers/bgpEdges |
| `lib/rendering/layout.py` | 決定的 force-directed → POS、segment/ext 配置、キャンバス算出、座標丸め |
| `lib/rendering/tabs.py` | routing キーから タブ集合＋キー番号生成（§8.2） |
| `lib/rendering/assets.py` | `_CSS` / `_JS` 文字列定数（design-sample.html から移植・適応） |
| `lib/rendering/template.py` | HTML 組立（head+CSS + body skeleton + 埋め込み DATA/POS/VIEWS JSON + JS） |
| `scripts/render_topology.py` | CLI③（load_topology → transform → layout → template → write。機密注意行。history は M4） |
| `dev/tests/test_render_*.py` | 各層テスト |

---

## Task 1: data_transform — devices + ifs（DATA.devices の機器・IF 部）

**Files:** Create `rebuild/lib/rendering/__init__.py`（空）, `rebuild/lib/rendering/data_transform.py`; Test `rebuild/dev/tests/test_render_devices.py`

- [ ] **Step 1: 雛形**
```bash
mkdir -p rebuild/lib/rendering
: > rebuild/lib/rendering/__init__.py
```

- [ ] **Step 2: 失敗するテスト** — `rebuild/dev/tests/test_render_devices.py`:

```python
"""DATA.devices（機器・ifs・addrs[]）変換のテスト（§8.4/§8.5/§8.7・方針1）。"""
import pytest

from lib.rendering.data_transform import build_devices

pytestmark = pytest.mark.unit


def _topo(devices, interfaces, bgp=None, ospf=None, static=None):
    return {"meta": {}, "devices": devices, "interfaces": interfaces,
            "links": [], "segments": [],
            "routing": {"bgp": bgp or [], "ospf": ospf or [], "static": static or []}}


def _dev(id, hostname="H", vendor="cisco_ios", as_=None, ospf_rid=None, bgp_rid=None):
    return {"id": id, "hostname": hostname, "vendor": vendor, "as": as_,
            "ospf_router_id": ospf_rid, "bgp_router_id": bgp_rid, "sections": []}


def _if(device, name, addresses, ip=None, **kw):
    base = {"id": "%s::%s" % (device, name), "device": device, "name": name,
            "ip": ip, "vlan": None, "description": None, "shutdown": False,
            "admin_status": "up", "oper_status": None, "mtu": None, "speed": None,
            "duplex": None, "l2_l3": None, "switchport": None, "encapsulation": None,
            "source": "parsed", "addresses": addresses}
    base.update(kw)
    return base


def test_device_basic_fields():
    topo = _topo([_dev("r1", "R1", "cisco_ios", as_=65001, ospf_rid="1.1.1.1", bgp_rid="9.9.9.9")],
                 [])
    d = build_devices(topo)["r1"]
    assert d["hostname"] == "R1" and d["vendor"] == "cisco_ios" and d["as"] == 65001
    assert d["ospf_rid"] == "1.1.1.1" and d["bgp_rid"] == "9.9.9.9"
    assert d["ifs"] == [] and d["bgp"] == [] and d["ospf"] == [] and d["static"] == []


def test_if_primary_v4_and_gua_and_addrs():
    addrs = [{"af": "v4", "ip": "10.0.0.1", "prefix": 30},
             {"af": "v4", "ip": "10.0.0.9", "prefix": 30, "secondary": True},
             {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
             {"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"}]
    topo = _topo([_dev("r1")], [_if("r1", "Gi0", addrs, ip="10.0.0.1/30",
                                    description="to-R2", mtu=1500, speed="1000")])
    itf = build_devices(topo)["r1"]["ifs"][0]
    assert itf["n"] == "Gi0"
    assert itf["ip"] == "10.0.0.1/30"          # 主 v4（非 secondary）
    assert itf["ip6"] == "2001:db8::1/64"      # 最初の GUA（link-local 除外）
    assert itf["d"] == "to-R2" and itf["st"] == "up" and itf["mtu"] == 1500 and itf["sp"] == "1000"
    # addrs[] は全アドレス（secondary・link-local 含む）
    assert itf["addrs"] == addrs
    # role/note は出さない（§8.7.3 ブラウザ永続）
    assert "role" not in itf and "note" not in itf


def test_if_v6_only_has_null_v4():
    topo = _topo([_dev("r1")], [_if("r1", "lo0",
                  [{"af": "v6", "ip": "2001:db8::9", "prefix": 128}], ip=None)])
    itf = build_devices(topo)["r1"]["ifs"][0]
    assert itf["ip"] is None and itf["ip6"] == "2001:db8::9/128"


def test_if_link_local_only_has_null_v6():
    topo = _topo([_dev("r1")], [_if("r1", "Gi0",
                  [{"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"}])])
    itf = build_devices(topo)["r1"]["ifs"][0]
    assert itf["ip6"] is None                  # GUA が無ければ null
    assert len(itf["addrs"]) == 1              # ただし addrs[] には link-local 保持


def test_ifs_in_config_order():
    topo = _topo([_dev("r1")],
                 [_if("r1", "Gi0", []), _if("r1", "Gi1", []), _if("r1", "lo0", [])])
    assert [i["n"] for i in build_devices(topo)["r1"]["ifs"]] == ["Gi0", "Gi1", "lo0"]
```

- [ ] **Step 3:** `cd rebuild/dev && python3 -m pytest tests/test_render_devices.py -q` → FAIL。

- [ ] **Step 4: 実装** `rebuild/lib/rendering/data_transform.py`:

```python
"""topology dict → DATA（JS が消費する形）。pure・決定的。"""


def _primary_ip6(addresses):
    for a in addresses:
        if a["af"] == "v6" and a.get("scope") != "link-local":
            return "%s/%s" % (a["ip"], a["prefix"])
    return None


def _build_if(itf):
    return {
        "n": itf["name"], "ip": itf["ip"], "ip6": _primary_ip6(itf["addresses"]),
        "d": itf["description"], "st": itf["admin_status"],
        "mtu": itf["mtu"], "sp": itf["speed"],
        "addrs": itf["addresses"],          # 全アドレス（方針1）
    }


def build_devices(topo):
    """DATA.devices（id キーのオブジェクト）を構築。ifs は config 順。routing は device 別。"""
    by_dev_if = {}
    for itf in topo["interfaces"]:
        by_dev_if.setdefault(itf["device"], []).append(itf)

    bgp_by_dev, ospf_by_dev, static_by_dev = {}, {}, {}
    for e in topo["routing"].get("bgp", []):
        bgp_by_dev.setdefault(e["device"], []).append(
            {"nb": e["neighbor_ip"], "pas": e["peer_as"], "type": e["type"],
             "af": e["af"], "lip": e["local_ip"], "link": None})   # link は Task5 で埋める
    for e in topo["routing"].get("ospf", []):
        ospf_by_dev.setdefault(e["device"], []).append(
            {"net": e["network"], "area": e["area"], "proc": e["process"]})
    for e in topo["routing"].get("static", []):
        static_by_dev.setdefault(e["device"], []).append(
            {"p": e["prefix"], "nh": e["next_hop"]})

    out = {}
    for d in topo["devices"]:
        out[d["id"]] = {
            "hostname": d["hostname"], "vendor": d["vendor"], "as": d["as"],
            "ospf_rid": d["ospf_router_id"], "bgp_rid": d["bgp_router_id"],
            "ifs": [_build_if(i) for i in by_dev_if.get(d["id"], [])],
            "bgp": bgp_by_dev.get(d["id"], []),
            "ospf": ospf_by_dev.get(d["id"], []),
            "static": static_by_dev.get(d["id"], []),
        }
    return out
```

- [ ] **Step 5:** PASS を確認。**Step 6: Commit**
```bash
git add rebuild/lib/rendering/__init__.py rebuild/lib/rendering/data_transform.py rebuild/dev/tests/test_render_devices.py
git commit -m "feat(rebuild): render data_transform devices/ifs with full addrs[] (§8.4/§8.5)"
```

> 注: `bgp[].link`（bgpEdge id 参照）は Task 5 で `build_bgp_edges` が確定後に埋める。本タスクでは `link=None` のプレースホルダ。

---

## Task 2: data_transform — links + dual-stack 統合（DATA.links）

**Files:** Modify `rebuild/lib/rendering/data_transform.py`; Test `rebuild/dev/tests/test_render_links.py`

- [ ] **Step 1: 失敗するテスト** — `rebuild/dev/tests/test_render_links.py`:

```python
"""DATA.links（端点ペア統合・dual-stack マージ・決定的 id）のテスト（§8.4）。"""
import pytest

from lib.rendering.data_transform import build_links, link_id

pytestmark = pytest.mark.unit


def _topo(interfaces, links):
    return {"meta": {}, "devices": [], "interfaces": interfaces,
            "links": links, "segments": [], "routing": {"bgp": [], "ospf": [], "static": []}}


def _if(device, name, addresses):
    return {"id": "%s::%s" % (device, name), "device": device, "name": name,
            "addresses": addresses}


def _link(a_dev, a_if, b_dev, b_if, subnet, **kw):
    d = {"a_device": a_dev, "a_if": a_if, "b_device": b_dev, "b_if": b_if,
         "subnet": subnet, "kind": "inferred-subnet"}
    d.update(kw)
    return d


def test_link_id_symmetric_deterministic():
    a = link_id("r1", "Gi0", "r2", "ge0")
    b = link_id("r2", "ge0", "r1", "Gi0")
    assert a == b and isinstance(a, str)


def test_single_stack_link():
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
           _if("r2", "ge0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}])]
    links = [_link("r1", "Gi0", "r2", "ge0", "10.0.0.0/30")]
    out = build_links(_topo(ifs, links))
    assert len(out) == 1
    l = out[0]
    assert l["a"] == "r1" and l["ai"] == "Gi0" and l["aip"] == "10.0.0.1"
    assert l["b"] == "r2" and l["bi"] == "ge0" and l["bip"] == "10.0.0.2"
    assert l["subnet"] == "10.0.0.0/30"
    assert "dual" not in l and "admin_down" not in l and "area" not in l


def test_dual_stack_merge():
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                             {"af": "v6", "ip": "2001:db8::1", "prefix": 127}]),
           _if("r2", "ge0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30},
                             {"af": "v6", "ip": "2001:db8::2", "prefix": 127}])]
    links = [_link("r1", "Gi0", "r2", "ge0", "10.0.0.0/30"),
             _link("r1", "Gi0", "r2", "ge0", "2001:db8::/127")]
    out = build_links(_topo(ifs, links))
    assert len(out) == 1                       # v4+v6 を 1 本に統合
    l = out[0]
    assert l["subnet"] == "10.0.0.0/30" and l["aip"] == "10.0.0.1" and l["bip"] == "10.0.0.2"
    assert l["dual"] == "2001:db8::/127"
    assert l["aip6"] == "2001:db8::1" and l["bip6"] == "2001:db8::2"


def test_admin_down_and_area_projected():
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
           _if("r2", "ge0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}])]
    links = [_link("r1", "Gi0", "r2", "ge0", "10.0.0.0/30",
                   admin_down=True, ospf_area="0", ospf_network="10.0.0.0/30")]
    l = build_links(_topo(ifs, links))[0]
    assert l["admin_down"] is True and l["area"] == "0"
```

- [ ] **Step 2:** FAIL を確認。

- [ ] **Step 3: 実装** — `data_transform.py` に追記:

```python
import ipaddress


def link_id(a_dev, a_if, b_dev, b_if):
    """端点ペアから対称・決定的なリンク id を作る。"""
    ends = sorted(["%s::%s" % (a_dev, a_if), "%s::%s" % (b_dev, b_if)])
    return "lnk:" + "|".join(ends)


def _host_in_subnet(interfaces_index, device, ifname, subnet):
    """device::ifname の addresses から subnet に属するホストアドレス（prefix なし）を返す。"""
    net = ipaddress.ip_network(subnet, strict=False)
    itf = interfaces_index.get("%s::%s" % (device, ifname))
    if not itf:
        return None
    for a in itf["addresses"]:
        try:
            if ipaddress.ip_address(a["ip"]) in net:
                return a["ip"]
        except ValueError:
            continue
    return None


def build_links(topo):
    """dict links（v4/v6 別行）を端点ペアで 1 本に統合し DATA.links を構築（§8.4）。"""
    idx = {i["id"]: i for i in topo["interfaces"]}
    merged = {}   # link_id -> DATA link（出現順保持）
    order = []
    for ln in topo["links"]:
        lid = link_id(ln["a_device"], ln["a_if"], ln["b_device"], ln["b_if"])
        is_v6 = ipaddress.ip_network(ln["subnet"], strict=False).version == 6
        if lid not in merged:
            merged[lid] = {"id": lid, "a": ln["a_device"], "ai": ln["a_if"],
                           "b": ln["b_device"], "bi": ln["b_if"]}
            order.append(lid)
        m = merged[lid]
        aip = _host_in_subnet(idx, ln["a_device"], ln["a_if"], ln["subnet"])
        bip = _host_in_subnet(idx, ln["b_device"], ln["b_if"], ln["subnet"])
        if is_v6:
            m["dual"] = ln["subnet"]
            m["aip6"], m["bip6"] = aip, bip
        else:
            m["subnet"] = ln["subnet"]
            m["aip"], m["bip"] = aip, bip
        if ln.get("admin_down"):
            m["admin_down"] = True
        if ln.get("ospf_area") is not None:
            m["area"] = ln["ospf_area"]
    return [merged[lid] for lid in order]
```

- [ ] **Step 4:** PASS。**Step 5: Commit**
```bash
git add rebuild/lib/rendering/data_transform.py rebuild/dev/tests/test_render_links.py
git commit -m "feat(rebuild): render data_transform links + dual-stack merge (§8.4)"
```

> 注: `_host_in_subnet` は v6-only リンク（subnet が v6 のみ）でも v4 キー `subnet`/`aip`/`bip` が欠ける場合がある。JS 側は `l.subnet` の有無で v4 描画を分岐する想定（Task 8 アセット適応で確認）。v6-only リンクは `subnet` 無し＋`dual` ありになる。この形を許容する（テストは dual-stack と single-v4 を主対象）。

---

## Task 3: data_transform — segments（DATA.segments）

**Files:** Modify `data_transform.py`; Test `rebuild/dev/tests/test_render_segments.py`

- [ ] **Step 1: 失敗するテスト**:

```python
"""DATA.segments（members iface_id → {dev,ifn,ip}）のテスト（§8.4）。"""
import pytest

from lib.rendering.data_transform import build_segments

pytestmark = pytest.mark.unit


def _topo(interfaces, segments):
    return {"meta": {}, "devices": [], "interfaces": interfaces,
            "links": [], "segments": segments, "routing": {"bgp": [], "ospf": [], "static": []}}


def _if(device, name, addresses):
    return {"id": "%s::%s" % (device, name), "device": device, "name": name,
            "addresses": addresses}


def test_segment_members_resolved():
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "192.168.1.1", "prefix": 24}]),
           _if("r2", "Gi0", [{"af": "v4", "ip": "192.168.1.2", "prefix": 24}]),
           _if("r3", "Gi0", [{"af": "v4", "ip": "192.168.1.3", "prefix": 24}])]
    segs = [{"id": "seg-192_168_1_0_24", "subnet": "192.168.1.0/24",
             "members": ["r1::Gi0", "r2::Gi0", "r3::Gi0"]}]
    out = build_segments(_topo(ifs, segs))
    assert len(out) == 1
    s = out[0]
    assert s["id"] == "seg-192_168_1_0_24" and s["subnet"] == "192.168.1.0/24"
    assert s["members"] == [{"dev": "r1", "ifn": "Gi0", "ip": "192.168.1.1"},
                            {"dev": "r2", "ifn": "Gi0", "ip": "192.168.1.2"},
                            {"dev": "r3", "ifn": "Gi0", "ip": "192.168.1.3"}]
    assert "area" not in s


def test_segment_area_projected():
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 24}]),
           _if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 24}]),
           _if("r3", "Gi0", [{"af": "v4", "ip": "10.0.0.3", "prefix": 24}])]
    segs = [{"id": "seg-x", "subnet": "10.0.0.0/24",
             "members": ["r1::Gi0", "r2::Gi0", "r3::Gi0"], "ospf_area": "0/1"}]
    assert build_segments(_topo(ifs, segs))[0]["area"] == "0/1"
```

- [ ] **Step 2:** FAIL。**Step 3: 実装** — `data_transform.py` に追記:

```python
def build_segments(topo):
    """dict segments の members(iface_id) を {dev,ifn,ip} へ解決し DATA.segments を構築（§8.4）。"""
    idx = {i["id"]: i for i in topo["interfaces"]}
    out = []
    for seg in topo["segments"]:
        members = []
        for mid in seg["members"]:
            itf = idx.get(mid)
            if not itf:
                continue
            ip = _host_in_subnet(idx, itf["device"], itf["name"], seg["subnet"])
            members.append({"dev": itf["device"], "ifn": itf["name"], "ip": ip})
        s = {"id": seg["id"], "subnet": seg["subnet"], "members": members}
        if seg.get("ospf_area") is not None:
            s["area"] = seg["ospf_area"]
        out.append(s)
    return out
```

- [ ] **Step 4:** PASS。**Step 5: Commit**
```bash
git add rebuild/lib/rendering/data_transform.py rebuild/dev/tests/test_render_segments.py
git commit -m "feat(rebuild): render data_transform segments (§8.4)"
```

---

## Task 4: data_transform — extPeers + bgpEdges + bgp[].link 連結（§7.3/§8.4）

最難関の正確性面。BGP セッションを over-link / loopback / external に分類し、`bgp[].link`・`extPeers[].link` を edge id に紐付ける。

**Files:** Modify `data_transform.py`; Test `rebuild/dev/tests/test_render_bgp_edges.py`

- [ ] **Step 1: 失敗するテスト** — `rebuild/dev/tests/test_render_bgp_edges.py`:

```python
"""DATA.extPeers / bgpEdges と bgp[].link 連結のテスト（§7.3/§8.4）。"""
import pytest

from lib.rendering.data_transform import build_bgp_topology

pytestmark = pytest.mark.unit


def _topo(interfaces, links, bgp):
    return {"meta": {}, "devices": [], "interfaces": interfaces,
            "links": links, "segments": [], "routing": {"bgp": bgp, "ospf": [], "static": []}}


def _if(device, name, addresses):
    return {"id": "%s::%s" % (device, name), "device": device, "name": name,
            "addresses": addresses}


def _bgp(device, local_ip, neighbor_ip, peer_as, type_, af="v4", local_as=None):
    return {"device": device, "local_as": local_as, "local_ip": local_ip,
            "neighbor_ip": neighbor_ip, "peer_as": peer_as, "type": type_, "af": af}


def test_over_link_edge():
    # 10.0.0.0/30 リンク上の eBGP（双方向 2 エントリ → 1 over-link エッジ）
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
           _if("r2", "ge0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}])]
    links = [{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "ge0",
              "subnet": "10.0.0.0/30", "kind": "inferred-subnet"}]
    bgp = [_bgp("r1", "10.0.0.1", "10.0.0.2", 65002, "ebgp"),
           _bgp("r2", "10.0.0.2", "10.0.0.1", 65001, "ebgp")]
    res = build_bgp_topology(_topo(ifs, links, bgp))
    overs = [e for e in res["bgpEdges"] if e["kind"] == "over-link"]
    assert len(overs) == 1 and overs[0]["type"] == "ebgp"
    # 2 つの bgp エントリが同じ edge id を link に持つ
    links_ref = {(e["device"], e["nb"]): e["link"] for e in res["bgp_rows"]}
    assert links_ref[("r1", "10.0.0.2")] == overs[0]["id"]
    assert links_ref[("r2", "10.0.0.1")] == overs[0]["id"]
    assert res["extPeers"] == []


def test_external_peer_and_edge():
    # 対向 config 不在 → external
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "203.0.113.1", "prefix": 30}])]
    bgp = [_bgp("r1", "203.0.113.1", "203.0.113.2", 65100, "ebgp")]
    res = build_bgp_topology(_topo(ifs, [], bgp))
    assert len(res["extPeers"]) == 1
    ext = res["extPeers"][0]
    assert ext["id"] == "ext:203.0.113.2" and ext["as"] == 65100 and ext["from"] == "r1"
    assert ext["sub"] == "203.0.113.2"
    exts = [e for e in res["bgpEdges"] if e["kind"] == "external"]
    assert len(exts) == 1 and exts[0]["ext"] == "ext:203.0.113.2" and exts[0]["a"] == "r1"
    assert exts[0]["srcIf"] == "Gi0"
    assert ext["link"] == exts[0]["id"]


def test_loopback_ibgp_edge():
    # loopback 間 iBGP（同一サブネット物理リンク無し）
    ifs = [_if("r1", "lo0", [{"af": "v4", "ip": "1.1.1.1", "prefix": 32}]),
           _if("r2", "lo0", [{"af": "v4", "ip": "2.2.2.2", "prefix": 32}])]
    bgp = [_bgp("r1", "1.1.1.1", "2.2.2.2", 65001, "ibgp", local_as=65001),
           _bgp("r2", "2.2.2.2", "1.1.1.1", 65001, "ibgp", local_as=65001)]
    res = build_bgp_topology(_topo(ifs, [], bgp))
    lbs = [e for e in res["bgpEdges"] if e["kind"] == "loopback"]
    assert len(lbs) == 1 and lbs[0]["type"] == "ibgp"
    assert {lbs[0]["a"], lbs[0]["b"]} == {"r1", "r2"}


def test_extpeers_deduped_and_sorted():
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 24}])]
    bgp = [_bgp("r1", "10.0.0.1", "10.0.0.9", 65100, "ebgp"),
           _bgp("r1", "10.0.0.1", "10.0.0.5", 65101, "ebgp")]
    res = build_bgp_topology(_topo(ifs, [], bgp))
    assert [e["id"] for e in res["extPeers"]] == ["ext:10.0.0.5", "ext:10.0.0.9"]  # neighbor 昇順
```

- [ ] **Step 2:** FAIL。

- [ ] **Step 3: 実装** — `data_transform.py` に追記:

```python
def _ip_to_device(topo):
    """機器 IF の全ホストアドレス → device id の索引（link-local 含む）。"""
    m = {}
    for itf in topo["interfaces"]:
        for a in itf["addresses"]:
            m.setdefault(a["ip"], itf["device"])
    return m


def _ip_owner_if(topo, ip):
    for itf in topo["interfaces"]:
        for a in itf["addresses"]:
            if a["ip"] == ip:
                return itf["device"], itf["name"]
    return None, None


def _link_id_for_pair(topo, ip_a, ip_b):
    """ip_a と ip_b が同一物理リンク（subnet 共有）に乗るなら、その link_id を返す。"""
    for ln in topo["links"]:
        net = ipaddress.ip_network(ln["subnet"], strict=False)
        try:
            if ipaddress.ip_address(ip_a) in net and ipaddress.ip_address(ip_b) in net:
                return link_id(ln["a_device"], ln["a_if"], ln["b_device"], ln["b_if"])
        except ValueError:
            continue
    return None


def build_bgp_topology(topo):
    """extPeers / bgpEdges を導出し、各 bgp 行に edge id(link) を紐付ける（§7.3/§8.4）。

    返り値: {"extPeers":[...], "bgpEdges":[...], "bgp_rows":[{device, nb, link}, ...]}
      bgp_rows は build_devices が device 別 bgp[] の link を埋めるための索引。
    """
    ip2dev = _ip_to_device(topo)
    edges = {}        # edge id -> edge dict
    edge_order = []
    ext_peers = {}    # ext id -> ext dict
    bgp_rows = []     # {device, nb, link}

    # external ピアは neighbor_ip 昇順で決定的 id 採番のため、まず収集
    sessions = topo["routing"].get("bgp", [])

    def _ensure_edge(eid, factory):
        if eid not in edges:
            edges[eid] = factory()
            edge_order.append(eid)
        return eid

    for e in sessions:
        dev, lip, nb = e["device"], e["local_ip"], e["neighbor_ip"]
        peer_dev = ip2dev.get(nb)
        if peer_dev is None:
            # external
            eid = "be:ext:%s:%s" % (dev, nb)
            srcd, srcif = _ip_owner_if(topo, lip) if lip else (dev, None)
            _ensure_edge(eid, lambda dev=dev, nb=nb, lip=lip, srcif=srcif, e=e: {
                "id": eid, "kind": "external", "a": dev, "ext": "ext:" + nb,
                "aip": lip, "bip": nb, "srcIf": srcif, "type": e["type"], "peerAs": e["peer_as"]})
            ext_peers.setdefault(nb, {"id": "ext:" + nb, "label": "AS %s" % e["peer_as"],
                                      "sub": nb, "as": e["peer_as"], "from": dev, "link": eid})
            bgp_rows.append({"device": dev, "nb": nb, "link": eid})
            continue
        # 対向が機器 → over-link か loopback
        lk = _link_id_for_pair(topo, lip, nb) if lip else None
        if lk is not None:
            eid = "be:ol:%s" % lk
            _ensure_edge(eid, lambda lk=lk, e=e: {
                "id": eid, "kind": "over-link", "link": lk,
                "type": e["type"], "peerAs": e["peer_as"]})
        else:
            pair = tuple(sorted([dev, peer_dev]))
            eid = "be:lb:%s:%s" % pair
            _ensure_edge(eid, lambda dev=dev, peer_dev=peer_dev, lip=lip, nb=nb, e=e: {
                "id": eid, "kind": "loopback", "a": pair[0], "b": pair[1],
                "aip": lip, "bip": nb, "type": e["type"],
                "label": "iBGP" if e["type"] == "ibgp" else "BGP"})
        bgp_rows.append({"device": dev, "nb": nb, "link": eid})

    ext_list = [ext_peers[k] for k in sorted(ext_peers)]
    return {"extPeers": ext_list,
            "bgpEdges": [edges[k] for k in edge_order],
            "bgp_rows": bgp_rows}
```

- [ ] **Step 4:** PASS。**Step 5: Commit**
```bash
git add rebuild/lib/rendering/data_transform.py rebuild/dev/tests/test_render_bgp_edges.py
git commit -m "feat(rebuild): render extPeers/bgpEdges + bgp link linkage (§7.3/§8.4)"
```

> 注: edge id（`be:ol:` 等）は内部 id。bgp_rows の link をたどって build_devices の `bgp[].link` を埋める（Task 6 の build_data で結線）。over-link は link id 1 つに集約され、v4/v6 双方の bgp 行が同 edge を指す。

---

## Task 5: data_transform — build_data 統合（DATA 全体組立 + bgp link 結線）

**Files:** Modify `data_transform.py`; Test `rebuild/dev/tests/test_render_build_data.py`

- [ ] **Step 1: 失敗するテスト** — ゴールデン topology（B.3）をロードして DATA を組み立て、主要件を検証:

```python
"""DATA 全体組立（build_data）— 附録 B.3 トポロジーでの統合テスト。"""
import pytest

from lib.topology_io import load_topology
from lib.rendering.data_transform import build_data
from pathlib import Path

pytestmark = pytest.mark.integration

GOLDEN = Path(__file__).resolve().parents[1] / "examples" / "topology"


def test_build_data_from_golden():
    topo = load_topology(str(GOLDEN))
    data = build_data(topo)
    # devices
    assert set(data["devices"]) == {"r1", "r2"}
    assert data["devices"]["r1"]["hostname"] == "R1"
    # links: 10.0.0.0/30 が 1 本
    assert len(data["links"]) == 1 and data["links"][0]["subnet"] == "10.0.0.0/30"
    assert data["segments"] == []
    # extPeers なし（両端とも config 内）、bgpEdges は over-link 1 本
    assert data["extPeers"] == []
    overs = [e for e in data["bgpEdges"] if e["kind"] == "over-link"]
    assert len(overs) == 1
    # bgp[].link が edge を指す（None でない）
    for dev in ("r1", "r2"):
        for row in data["devices"][dev]["bgp"]:
            assert row["link"] == overs[0]["id"]
    # meta
    assert data["meta"]["generated_from"] == ["sample-ios-r1.cfg", "sample-junos-r2.conf"]


def test_build_data_deterministic():
    topo = load_topology(str(GOLDEN))
    import json
    a = json.dumps(build_data(topo), sort_keys=True)
    b = json.dumps(build_data(topo), sort_keys=True)
    assert a == b
```

- [ ] **Step 2:** FAIL。**Step 3: 実装** — `data_transform.py` に追記:

```python
def build_data(topo):
    """topology dict → DATA（devices/links/segments/extPeers/bgpEdges/meta）。決定的。"""
    devices = build_devices(topo)
    links = build_links(topo)
    segments = build_segments(topo)
    bgp_topo = build_bgp_topology(topo)

    # bgp[].link を bgp_rows で埋める（device, nb で対応）
    link_by = {}
    for r in bgp_topo["bgp_rows"]:
        link_by[(r["device"], r["nb"])] = r["link"]
    for dev_id, dev in devices.items():
        for row in dev["bgp"]:
            row["link"] = link_by.get((dev_id, row["nb"]))

    return {
        "meta": {"generated_from": topo["meta"].get("generated_from", [])},
        "devices": devices, "links": links, "segments": segments,
        "extPeers": bgp_topo["extPeers"], "bgpEdges": bgp_topo["bgpEdges"],
    }
```

- [ ] **Step 4:** PASS。**Step 5:** `python3 -m pytest -m unit -q`（リグレッションなし）。**Step 6: Commit**
```bash
git add rebuild/lib/rendering/data_transform.py rebuild/dev/tests/test_render_build_data.py
git commit -m "feat(rebuild): assemble full DATA + bgp link wiring (§8)"
```

---

## Task 6: layout — 決定的 POS（§8.3）

**Files:** Create `rebuild/lib/rendering/layout.py`; Test `rebuild/dev/tests/test_render_layout.py`

- [ ] **Step 1: 失敗するテスト** — `rebuild/dev/tests/test_render_layout.py`:

```python
"""§8.3 決定的レイアウト（POS）のテスト。"""
import pytest

from lib.rendering.layout import compute_positions

pytestmark = pytest.mark.unit


def _data(dev_ids, seg_ids=(), ext_ids=()):
    return {
        "devices": {d: {} for d in dev_ids},
        "segments": [{"id": s, "members": []} for s in seg_ids],
        "extPeers": [{"id": e} for e in ext_ids],
        "links": [],
    }


def test_all_node_ids_present():
    pos = compute_positions(_data(["r1", "r2", "r3"], seg_ids=["seg-a"], ext_ids=["ext:x"]))
    assert set(pos) == {"r1", "r2", "r3", "seg-a", "ext:x"}
    for p in pos.values():
        assert set(p) == {"x", "y"} and isinstance(p["x"], float) and isinstance(p["y"], float)


def test_deterministic_two_runs():
    d = _data(["r1", "r2", "r3", "r4"], seg_ids=["s1"], ext_ids=["e1"])
    assert compute_positions(d) == compute_positions(d)


def test_coords_rounded_one_decimal():
    pos = compute_positions(_data(["r1", "r2"]))
    for p in pos.values():
        assert round(p["x"], 1) == p["x"] and round(p["y"], 1) == p["y"]


def test_independent_of_dict_input_order():
    a = compute_positions(_data(["r1", "r2", "r3"]))
    b = compute_positions(_data(["r3", "r1", "r2"]))   # 入力順違い → 同一結果（id 昇順初期化）
    assert a == b
```

- [ ] **Step 2:** FAIL。

- [ ] **Step 3: 実装** `rebuild/lib/rendering/layout.py`（旧 layout.py を参考に再実装・コピー禁止。乱数/時刻不使用）:

```python
"""決定的 force-directed レイアウト（要件書 §8.3）。乱数・時刻不使用。"""
import math

NODE_W, NODE_H = 148.0, 56.0
_ITER = 200
_AREA = 1_000_000.0     # キャンバス面積の目安（ノード数でスケール）


def _initial_circle(node_ids):
    """機器 ID 昇順で円周上に決定的初期配置（§8.3）。"""
    n = max(len(node_ids), 1)
    radius = 60.0 * math.sqrt(n) + 120.0
    pos = {}
    for i, nid in enumerate(sorted(node_ids)):
        ang = 2.0 * math.pi * i / n
        pos[nid] = [radius * math.cos(ang), radius * math.sin(ang)]
    return pos


def compute_positions(data):
    """全ノード（device + segment + ext）の決定的 POS を返す（座標は round(.,1)）。"""
    dev_ids = list(data["devices"].keys())
    seg_ids = [s["id"] for s in data.get("segments", [])]
    ext_ids = [e["id"] for e in data.get("extPeers", [])]
    node_ids = dev_ids + seg_ids + ext_ids

    pos = _initial_circle(node_ids)
    k = math.sqrt(_AREA / max(len(node_ids), 1))      # 理想距離

    # 隣接（links の端点）— 引力対象
    edges = []
    for ln in data.get("links", []):
        if ln.get("a") in pos and ln.get("b") in pos:
            edges.append((ln["a"], ln["b"]))

    ids_sorted = sorted(node_ids)                     # 反復も決定的順序で
    for it in range(_ITER):
        disp = {nid: [0.0, 0.0] for nid in ids_sorted}
        # 斥力（全ペア）
        for i in range(len(ids_sorted)):
            for j in range(i + 1, len(ids_sorted)):
                a, b = ids_sorted[i], ids_sorted[j]
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                dist = math.hypot(dx, dy) or 0.01
                rep = k * k / dist
                ux, uy = dx / dist, dy / dist
                disp[a][0] += ux * rep; disp[a][1] += uy * rep
                disp[b][0] -= ux * rep; disp[b][1] -= uy * rep
        # 引力（隣接）
        for a, b in edges:
            dx = pos[a][0] - pos[b][0]
            dy = pos[a][1] - pos[b][1]
            dist = math.hypot(dx, dy) or 0.01
            att = dist * dist / k
            ux, uy = dx / dist, dy / dist
            disp[a][0] -= ux * att; disp[a][1] -= uy * att
            disp[b][0] += ux * att; disp[b][1] += uy * att
        # 温度（決定的に減衰）
        temp = k * (1.0 - it / _ITER)
        for nid in ids_sorted:
            d = disp[nid]
            dl = math.hypot(d[0], d[1]) or 0.01
            step = min(dl, temp)
            pos[nid][0] += d[0] / dl * step
            pos[nid][1] += d[1] / dl * step

    return {nid: {"x": round(p[0], 1), "y": round(p[1], 1)} for nid, p in pos.items()}
```

- [ ] **Step 4:** PASS。**Step 5: Commit**
```bash
git add rebuild/lib/rendering/layout.py rebuild/dev/tests/test_render_layout.py
git commit -m "feat(rebuild): deterministic force-directed layout (POS) (§8.3)"
```

> 注: §8.3 の「重なり分離」「外部ピアを機器群と重ならない領域へ」「ビュー間共通配置」は、本実装では全ノードを 1 つの POS に決定的配置することで満たす（ビュー共通＝同一 POS 参照）。視覚的品質（重なりの少なさ）は §11.5 目視で確認。O(N²) 反復は §8.3 の目安 150 台で実用範囲（性能は §11.5/必要なら M4 FU）。

---

## Task 7: tabs — タブ集合＋キー番号生成（§8.2）

**Files:** Create `rebuild/lib/rendering/tabs.py`; Test `rebuild/dev/tests/test_render_tabs.py`

- [ ] **Step 1: 失敗するテスト**:

```python
"""§8.2 タブ生成（図ビュー動的・表ビュー常設・static 除外・キー連番）のテスト。"""
import pytest

from lib.rendering.tabs import build_tabs

pytestmark = pytest.mark.unit


def _routing(bgp=False, ospf=False, static=False):
    return {"bgp": [1] if bgp else [], "ospf": [1] if ospf else [],
            "static": [1] if static else []}


def test_physical_and_tables_always():
    tabs = build_tabs(_routing())
    assert [t["view"] for t in tabs] == ["physical", "addr", "ifs"]


def test_bgp_ospf_conditional():
    tabs = build_tabs(_routing(bgp=True, ospf=True))
    assert [t["view"] for t in tabs] == ["physical", "bgp", "ospf", "addr", "ifs"]


def test_only_bgp():
    assert [t["view"] for t in build_tabs(_routing(bgp=True))] == \
        ["physical", "bgp", "addr", "ifs"]


def test_static_never_a_tab():
    assert "static" not in [t["view"] for t in build_tabs(_routing(static=True))]


def test_key_numbers_sequential():
    tabs = build_tabs(_routing(bgp=True))   # physical,bgp,addr,ifs
    assert [t["key"] for t in tabs] == [1, 2, 3, 4]
    # 汎用ビューが増えると表ビューのキーが後ろにずれる（§8.2）— bgp 有無で addr の key が変わる
    no_bgp = build_tabs(_routing())
    assert next(t["key"] for t in no_bgp if t["view"] == "addr") == 2
    assert next(t["key"] for t in tabs if t["view"] == "addr") == 3
```

- [ ] **Step 2:** FAIL。**Step 3: 実装** `rebuild/lib/rendering/tabs.py`:

```python
"""タブ（ビュー）生成（要件書 §8.2）。図ビューは routing から動的・表ビューは常設・static 除外。"""

_LABELS = {"physical": "PHYSICAL", "bgp": "BGP", "ospf": "OSPF",
           "addr": "ADDRESSES", "ifs": "INTERFACES"}


def build_tabs(routing):
    """[{view, label, key}] を返す。図ビュー（physical→bgp?→ospf?→generic?）→ 表ビュー（addr,ifs）。"""
    views = ["physical"]
    if routing.get("bgp"):
        views.append("bgp")
    if routing.get("ospf"):
        views.append("ospf")
    # generic proto（bgp/ospf/static 以外）は v1 ではスキップ（§9.3 拡張余地。方針5）
    views += ["addr", "ifs"]
    return [{"view": v, "label": _LABELS.get(v, v.upper()), "key": i + 1}
            for i, v in enumerate(views)]
```

- [ ] **Step 4:** PASS。**Step 5: Commit**
```bash
git add rebuild/lib/rendering/tabs.py rebuild/dev/tests/test_render_tabs.py
git commit -m "feat(rebuild): data-driven tab generation (§8.2)"
```

---

## Task 8: assets — CSS/JS の移植・適応（§8.1/§8.4-8.7）

design-sample.html の `<style>`/`<script>` を `assets.py` の `_CSS`/`_JS` 定数へ移植し、確定挙動を保ったまま **実データ対応**へ適応する。**これはコード生成ではなく移植＋限定編集タスク**。JS の振る舞いは §11.5 で目視検証。

**Files:** Create `rebuild/lib/rendering/assets.py`; Test `rebuild/dev/tests/test_render_assets.py`

- [ ] **Step 1: `docs/design-sample.html` を読み**、`<style>...</style>` の内容を `_CSS`、`<script>...</script>`（DATA/POS リテラル定義を除く）を `_JS` として `assets.py` に文字列定数で格納する。

- [ ] **Step 2: 以下の適応編集を行う**（確定挙動は変えない）:
  1. **ダミー DATA/POS の除去**: サンプル冒頭の `const DATA = {...}` / `const POS = {...}` リテラルは `_JS` に含めない（template が実データ JSON を `DATA`/`POS`/`VIEWS` として注入する。`_JS` は `DATA`/`POS`/`VIEWS` がグローバルに既出である前提のコードにする）。
  2. **「DUMMY DATA」リボン/バナー等のサンプル用 UI** を除去（`#ribbon` 等）。
  3. **検索コーパスの全アドレス対応（方針1）**: 検索（自由文字列・`ip:` 演算子）が `i.ip`/`i.ip6` だけでなく **`i.addrs[]` の全 ip（secondary/link-local 含む）** を走査するよう適応（§8.5「全 IP アドレス（v4・v6、secondary・link-local 含む）」）。
  4. **ADDRESSES / INTERFACES 表の全アドレス対応**: 行生成・使用率算出・重複 IP 判定が `addrs[]` を参照するよう適応（§8.7）。IPv4/IPv6 セルは主アドレス＋追加分を提示。
  5. **role/note の seed 依存除去**: `i.role`/`i.note` を初期 seed として読む箇所は、無い前提（localStorage のみ）に統一（§8.7.3）。
  6. **VIEWS 連動**: タブの妥当性判定・キー番号を、注入される `VIEWS`（Task 7 出力）に基づくよう適応（ハードコードのビュー一覧を VIEWS 参照に）。
  7. **外部参照ゼロの確認**: `http(s)://`・`<script src>`・`<link rel=stylesheet>`・外部 `@import`・外部 `url()` を含まないこと。

- [ ] **Step 3: テスト** — `rebuild/dev/tests/test_render_assets.py`:

```python
"""アセット（CSS/JS）の自己完結性・適応の構造テスト。"""
import re

import pytest

from lib.rendering import assets

pytestmark = pytest.mark.unit


def test_no_external_references():
    blob = assets._CSS + "\n" + assets._JS
    assert "http://" not in blob and "https://" not in blob
    assert "<script src" not in blob.lower()
    assert "@import" not in blob


def test_js_has_no_dummy_data_literal():
    # 実データは template が注入。アセット側に DATA/POS のリテラル定義を残さない
    assert not re.search(r"const\s+DATA\s*=\s*\{", assets._JS)
    assert not re.search(r"const\s+POS\s*=\s*\{", assets._JS)


def test_js_references_addrs_for_search():
    # 全アドレス検索（方針1）への適応が入っていること
    assert "addrs" in assets._JS


def test_node_check_syntax():
    # node があれば JS 構文チェック（無ければ skip）
    import shutil, subprocess, tempfile, os
    node = shutil.which("node")
    if not node:
        pytest.skip("node 不在のため構文チェックをスキップ")
    # DATA/POS/VIEWS を最小スタブで前置し、構文（実行ではなく parse）を検査
    stub = "const DATA={devices:{},links:[],segments:[],extPeers:[],bgpEdges:[],meta:{generated_from:[]}};" \
           "const POS={};const VIEWS=['physical','addr','ifs'];\n"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(stub + assets._JS)
        path = f.name
    try:
        r = subprocess.run([node, "--check", path], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    finally:
        os.unlink(path)
```

- [ ] **Step 4:** `cd rebuild/dev && python3 -m pytest tests/test_render_assets.py -q` → PASS（node 不在環境では `test_node_check_syntax` は skip）。node がある場合は `--check` 通過まで確認。
- [ ] **Step 5: Commit**
```bash
git add rebuild/lib/rendering/assets.py rebuild/dev/tests/test_render_assets.py
git commit -m "feat(rebuild): port+adapt CSS/JS assets from design-sample (addrs[], VIEWS, no dummy) (§8.1/§8.5/§8.7)"
```

> 重要: `_JS` 内の DATA/links/segments/extPeers/bgpEdges/devices.ifs の**フィールド名は本計画の DATA 契約と完全一致**させること（data_transform 出力と JS 読取りの不一致は §11.5 で初めて顕在化するため、Task 9 の埋め込み DATA 構造テスト＋Task 11 の手動チェックで検証）。サンプル JS が `i.role`/`i.note`/`l.dual`/`e.kind` 等を読む箇所のフィールド名を契約に合わせる。

---

## Task 9: template — HTML 組立 + DATA/POS/VIEWS 埋め込み（§8.1）

**Files:** Create `rebuild/lib/rendering/template.py`; Test `rebuild/dev/tests/test_render_template.py`

- [ ] **Step 1: 失敗するテスト** — `rebuild/dev/tests/test_render_template.py`:

```python
"""HTML 組立・埋め込み DATA 一致・自己完結・IF チップ/●不在の構造テスト（§8.1/§8.4.1）。"""
import json
import re
from pathlib import Path

import pytest

from lib.topology_io import load_topology
from lib.rendering.template import render_html

pytestmark = pytest.mark.integration

GOLDEN = Path(__file__).resolve().parents[1] / "examples" / "topology"


def _html():
    return render_html(load_topology(str(GOLDEN)))


def _embedded_data(html):
    m = re.search(r"const DATA\s*=\s*(\{.*?\});", html, re.DOTALL)
    assert m, "埋め込み DATA が見つからない"
    return json.loads(m.group(1))


def test_self_contained_no_external():
    html = _html()
    assert "http://" not in html and "https://" not in html
    assert "<script src" not in html.lower()
    assert "<link rel=\"stylesheet\"" not in html.lower() and "<link rel='stylesheet'" not in html.lower()


def test_single_file_has_inline_style_and_script():
    html = _html()
    assert "<style>" in html and "<script>" in html
    assert html.lstrip().lower().startswith("<!doctype html")


def test_embedded_data_matches_topology():
    html = _html()
    data = _embedded_data(html)
    assert set(data["devices"]) == {"r1", "r2"}
    assert len(data["links"]) == 1
    assert data["meta"]["generated_from"] == ["sample-ios-r1.cfg", "sample-junos-r2.conf"]


def test_tab_rules():
    html = _html()
    assert 'data-view="physical"' in html
    assert 'data-view="addr"' in html and 'data-view="ifs"' in html
    assert 'data-view="bgp"' in html       # golden に bgp あり
    assert 'data-view="ospf"' in html      # golden に ospf あり
    assert 'data-view="static"' not in html


def test_no_if_chip_or_select_marker():
    html = _html()
    # §8.4.1 IF チップ廃止 / 選択 ● マーカー廃止 の回帰ガード
    assert "selglyph" not in html
    assert "if-chip" not in html and "ifchip" not in html


def test_deterministic_same_input():
    a = _html()
    b = _html()
    assert a == b
```

- [ ] **Step 2:** FAIL。

- [ ] **Step 3: 実装** `rebuild/lib/rendering/template.py`:

```python
"""HTML 組立（要件書 §8.1）。CSS/JS アセット + 埋め込み DATA/POS/VIEWS で自己完結 HTML を生成。"""
import json

from .assets import _CSS, _JS
from .data_transform import build_data
from .layout import compute_positions
from .tabs import build_tabs


def _json(obj):
    # 決定的・コンパクト・非 ASCII はそのまま（UTF-8 で出力）
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _tabs_html(tabs):
    btns = []
    for t in tabs:
        btns.append('<button data-view="%s">%s<span class="k">%d</span></button>'
                    % (t["view"], t["label"], t["key"]))
    return "".join(btns)


def render_html(topo):
    """topology dict → 自己完結 HTML 文字列（決定的）。"""
    data = build_data(topo)
    pos = compute_positions(data)
    tabs = build_tabs(topo["routing"])
    views = [t["view"] for t in tabs]

    head = ("<!doctype html>\n<html lang=\"ja\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>Network Topology</title><style>%s</style></head><body>" % _CSS)
    # body skeleton（タブ・ツールバー・キャンバス・パネル等のコンテナ。詳細マークアップは _JS が描画/前提）
    body = ('<nav id="tabs">%s</nav>'
            '<div id="app"></div>') % _tabs_html(tabs)
    data_script = ("<script>const DATA=%s;const POS=%s;const VIEWS=%s;</script>"
                   % (_json(data), _json(pos), _json(views)))
    js = "<script>%s</script>" % _JS
    return head + body + data_script + js + "</body></html>"
```

> 注: body skeleton の正確なコンテナ構造（`#tabs`/`#canvas`/`#details`/`#tableview`/ツールバー等）は design-sample.html の `<body>` に合わせる。`_JS` がどの DOM を前提にするかに依存するため、**Task 8 で `_JS` を移植する際に必要な静的 DOM を洗い出し、本 template の body に含める**（サンプルの body マークアップを移植）。上記 `body` は最小形であり、実装時に design-sample.html の body 構造へ拡張すること。`const DATA=` の正規表現が Task 9 テストで使われるので、`data_script` の表記（`const DATA=` に続けて JSON）を保つ。

- [ ] **Step 4:** PASS。**Step 5:** `python3 -m pytest -q`。**Step 6: Commit**
```bash
git add rebuild/lib/rendering/template.py rebuild/dev/tests/test_render_template.py
git commit -m "feat(rebuild): assemble self-contained HTML with embedded DATA/POS/VIEWS (§8.1)"
```

---

## Task 10: CLI `render_topology.py`（§10.1/§10.2。history は M4）

**Files:** Create `rebuild/scripts/render_topology.py`; Test `rebuild/dev/tests/test_render_cli.py`

- [ ] **Step 1: 失敗するテスト**:

```python
"""§10.1/§10.2 render_topology.py CLI のテスト。"""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REBUILD_ROOT = Path(__file__).resolve().parents[2]
GOLDEN = REBUILD_ROOT / "dev" / "examples" / "topology"
CLI = REBUILD_ROOT / "scripts" / "render_topology.py"


def _run(args, cwd=None):
    return subprocess.run([sys.executable, str(CLI)] + args, capture_output=True,
                          text=True, cwd=cwd)


def test_generates_html_default_output(tmp_path):
    # -o 省略時は cwd 直下 ./topology.html
    proc = _run([str(GOLDEN)], cwd=str(tmp_path))
    assert proc.returncode == 0
    out = tmp_path / "topology.html"
    assert out.exists()
    assert out.read_text(encoding="utf-8").lstrip().lower().startswith("<!doctype html")
    assert "Generated" in proc.stdout
    # §10.2 機密注意行を stderr に出す
    assert "description" in proc.stderr or "確認" in proc.stderr


def test_explicit_output(tmp_path):
    out = tmp_path / "x.html"
    proc = _run([str(GOLDEN), "-o", str(out)])
    assert proc.returncode == 0 and out.exists()


def test_dangling_ref_exits_1(tmp_path):
    # 参照整合エラー（§5.6）→ exit 1・stderr
    bad = tmp_path / "topo"
    bad.mkdir()
    (bad / "_meta.yaml").write_text("generated_from: []\nschema_version: '1.0'\ntitle: T\n", encoding="utf-8")
    (bad / "devices.yaml").write_text(
        "devices: []\ninterfaces:\n- {id: 'rX::Gi0', device: rX, name: Gi0, ip: null, vlan: null,"
        " description: null, shutdown: false, admin_status: up, oper_status: null, mtu: null,"
        " speed: null, duplex: null, l2_l3: null, switchport: null, encapsulation: null,"
        " source: parsed, addresses: []}\n", encoding="utf-8")
    (bad / "physical.yaml").write_text("links: []\nsegments: []\n", encoding="utf-8")
    proc = _run([str(bad)])
    assert proc.returncode == 1
    assert "rX" in proc.stderr        # ファイル名・フィールド・値を含むエラー（§5.6/§10.2）
```

- [ ] **Step 2:** FAIL。**Step 3: 実装** `rebuild/scripts/render_topology.py`:

```python
#!/usr/bin/env python3
"""CLI③: 層別 YAML から自己完結 HTML を生成（要件書 §10.1・§10.2）。

history 退避（§10.3）は M4 で追加する（本 CLI には未実装）。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # rebuild/ を import パスへ

from lib.topology_io import load_topology      # noqa: E402
from lib.rendering.template import render_html  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description="Render layered topology YAML to a self-contained HTML.")
    p.add_argument("topology_dir", help="層別 YAML のディレクトリ")
    p.add_argument("-o", "--output", default="./topology.html",
                   help="出力 HTML（既定 ./topology.html）")
    args = p.parse_args(argv)

    try:
        topo = load_topology(args.topology_dir)      # 参照整合違反は ValueError（§5.6）
    except ValueError as e:
        print("[ERROR] 参照整合エラー: %s" % e, file=sys.stderr)
        return 1
    except OSError as e:
        print("[ERROR] 読込失敗: %s (%s)" % (args.topology_dir, e), file=sys.stderr)
        return 1

    html = render_html(topo)
    try:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(html)
    except OSError as e:
        print("[ERROR] 出力失敗: %s (%s)" % (args.output, e), file=sys.stderr)
        return 1

    print("Generated: %s" % args.output)
    # §10.2 機密注意（生成物に config 由来の自由記述がそのまま含まれる）
    print("[WARN] 生成物には config 由来の自由記述（description 等）がそのまま含まれます。"
          "共有前に内容を確認してください。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4:** PASS。**Step 5:** `python3 -m pytest -q`。**Step 6: Commit**
```bash
git add rebuild/scripts/render_topology.py rebuild/dev/tests/test_render_cli.py
git commit -m "feat(rebuild): add render_topology.py CLI (§10.1/§10.2)"
```

---

## Task 11: 決定性 + パイプライン E2E（§8.3/§9.1/§11.3）

**Files:** Test `rebuild/dev/tests/test_render_e2e.py`

- [ ] **Step 1: テスト** — config → YAML → HTML 通し＋決定性:

```python
"""§11.3 決定性・通しパイプライン E2E（config → 層別 YAML → HTML）。"""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REBUILD_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REBUILD_ROOT / "dev" / "examples" / "configs"
BUILD = REBUILD_ROOT / "scripts" / "build_topology.py"
RENDER = REBUILD_ROOT / "scripts" / "render_topology.py"


def _build(out):
    r = subprocess.run([sys.executable, str(BUILD),
                        str(CONFIG_DIR / "sample-ios-r1.cfg"),
                        str(CONFIG_DIR / "sample-junos-r2.conf"), "-o", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _render(topo_dir, out):
    r = subprocess.run([sys.executable, str(RENDER), str(topo_dir), "-o", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_full_pipeline_and_html_determinism(tmp_path):
    topo = tmp_path / "topology"
    _build(topo)
    h1 = tmp_path / "a.html"; h2 = tmp_path / "b.html"
    _render(topo, h1)
    _render(topo, h2)
    assert h1.read_bytes() == h2.read_bytes()        # 同一 YAML → バイト一致（§11.3）
    assert b"<!doctype html" in h1.read_bytes()[:64].lower()


def test_render_deterministic_independent_of_build(tmp_path):
    # 2 回 build した YAML から render しても HTML がバイト一致（パイプライン全体の決定性）
    t1 = tmp_path / "t1"; t2 = tmp_path / "t2"
    _build(t1); _build(t2)
    h1 = tmp_path / "h1.html"; h2 = tmp_path / "h2.html"
    _render(t1, h1); _render(t2, h2)
    assert h1.read_bytes() == h2.read_bytes()
```

- [ ] **Step 2:** PASS を確認（render の決定性が崩れる場合、POS の float 丸め・JSON sort_keys・dict 順を点検）。
- [ ] **Step 3:** 全テスト `cd rebuild/dev && python3 -m pytest -q`（unit + integration + e2e 全 green）。
- [ ] **Step 4: Commit**
```bash
git add rebuild/dev/tests/test_render_e2e.py
git commit -m "test(rebuild): render determinism + full pipeline e2e (§11.3)"
```

---

## Task 12: §11.5 ブラウザ目視チェック（手動・成果物＝チェックリスト）

自動化不能なインタラクションをブラウザで確認する。**コードではなく、消し込み済みチェックリストが成果物**。

- [ ] **Step 1:** サンプル config から HTML 生成:
```bash
python3 rebuild/scripts/build_topology.py \
  rebuild/dev/examples/configs/sample-ios-r1.cfg \
  rebuild/dev/examples/configs/sample-junos-r2.conf -o /tmp/m3-topology
python3 rebuild/scripts/render_topology.py /tmp/m3-topology -o /tmp/m3-topology.html
```
- [ ] **Step 2:** `/tmp/m3-topology.html` を**ブラウザ（file://）で開き**、要件書 §11.5 のチェックリストを 1 項目ずつ確認（タブ切替で座標維持・表ビューで図ツールバー非表示／ノードドラッグ追従・リロードで初期化／クリック選択トグル・ダブルクリック/Esc 全解除／hover プレビュー＋ライン hover 同色・ツールチップ無し／ライン選択の端点自動選択＋図⇄パネル連動・dual-stack v4/v6 連動／IF/IP 縦積みラベル／検索 自由文字列・演算子・ドロップダウン・Ctrl+F・0件警告色・Enter 次マッチ／表示ノードパネル・接続先のみ・種別フィルタ／BGP セッション行⇄線・対向ノード強調・外部ピア点線ノード／admin_down 破線淡色／テーマ・ミニマップ・凡例クリック・SVG/PNG エクスポート・ズーム/パン/fit/ショートカット／ADDRESSES グループ化・使用率・折りたたみ・重複IP・ソート・TSV／INTERFACES グループ化・ポート集計・対向ジャンプ・未使用・種別フィルタ・予約/使用不可/備考の永続）。
- [ ] **Step 3:** ブラウザ不可環境の場合は CLAUDE.md に従い静的代替（`node --check` ＋ JS ロジック机上追跡）で可能範囲を確認し、**ブラウザ目視は未実施として明示報告**する（合格を詐称しない）。結果（各項目 OK/NG/未確認）を報告する。

---

## M3 Done 条件（実装指示書 §4 M3 と対応）

- [ ] e2e: サンプル config → 層別 YAML → HTML 生成が通しでエラーなし（Task 11）。
- [ ] 決定性: 同一層別 YAML から 2 回生成した HTML がバイト一致（Task 11）。
- [ ] HTML 構造テスト（機械）: 外部リソース参照なし／Physical 常在・`routing.bgp` 時のみ BGP タブ・`routing.ospf` 時のみ OSPF タブ・`static` はタブ無し／IF チップ要素・選択●が無い（Task 9）。
- [ ] ブラウザ目視チェック（§11.5）を 1 項目ずつ確認し結果報告（Task 12。ブラウザ不可なら静的代替＋未確認明示）。

---

## Self-Review（計画作成者・実施済み）

- **Spec coverage:** §8.1 自己完結（Task8/9）・§8.2 タブ（Task7/9）・§8.3 決定的レイアウト（Task6）・§8.4 可視化＋§8.4.1 チップ廃止（Task8/9 構造ガード）・§8.5 操作/検索（Task8 移植＋§11.5）・§8.6 色（Task8 JS）・§8.7 表ビュー＋アノテーション（Task8/§11.5）・§10.1/10.2 CLI（Task10）・§11.3/11.5 受け入れ（Task11/12）を割当。
- **データ変換が自動テストの主戦場**（Task1-5・layout Task6・tabs Task7）。JS 振る舞いは §11.5 手動（自動不能を正直に扱う）。
- **確定方針を反映:** addrs[] 全アドレス（方針1）／Python POS（方針2）／構造＋決定性テスト・バイトゴールデン無し（方針3）／history は M4（方針4）／generic-proto スキップ（方針5）／ext 副ラベルは素の IP（方針6）／skip 警告なし（方針7）。
- **スコープ外（M4）:** history 退避（§10.3）・実行サマリー（§10.4）は本計画に含めない。
- **Type consistency:** DATA 契約を冒頭で固定し、data_transform 出力（Task1-5）と JS 読取り（Task8）と template 埋め込み（Task9）が同一フィールド名を共有。`bgp[].link` は Task5/build_data で結線。
- **既知リスク（実装時注意）:** ① assets 移植時の **JS フィールド名と DATA 契約の一致**（不一致は §11.5 で初顕在化）。Task8 注記＋Task9 埋め込み構造テストで早期検知。② body skeleton は design-sample.html の `<body>` 構造を移植して `_JS` の DOM 前提を満たす（Task9 注記）。③ レイアウト性能 O(N²)（150 台目安）は §11.5/必要時 M4 FU。
