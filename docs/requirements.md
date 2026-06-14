# config-topology システム要件定義書

**版** 2.1 | **作成日** 2026-06-12 | **改訂日** 2026-06-13

## 本書の位置づけ

本書は、**config-topology システムの全面刷新に向けた要件定義書**である。振る舞い（外部から観測可能な入出力契約）のみを規定し、内部実装は刷新側の自由とする。本書の要件を満たす実装なら、利用者にとって既存システムと同等以上のシステムを構築できる精度を目指す。

- 本書（v2.1）が**刷新の唯一の仕様正本**である。既存実装・既存ドキュメント・既存ゴールデン出力と本書が食い違う場合は本書を優先する。
- 文書の版（2.1）は本書自体の版であり、対象システムは刷新の初版（v1 スコープ）である。
- **v2.1 改訂（2026-06-13）**: §8（HTML 構成図機能要件）を、インタラクティブ仕様確定後の挙動（ライン選択・hover・表ビュー〔ADDRESSES / INTERFACES〕・運用アノテーション・検索 UI 等）に合わせて全面改訂した。確定挙動はデザインモック `docs/design-sample.html` を正とし、本章はそれを機能仕様化したもの（px 値・力学式・配色値は引き続き実装裁量）。
- 本書は参照性と保守性のため単一 Markdown ファイルで統一し、ドキュメント生成・コード生成・テスト設計の正本として機能する。

---

## 目次
1. [システム概要と目的](#1-システム概要と目的)
2. [入力要件](#2-入力要件)
3. [出力要件](#3-出力要件)
4. [データモデル要件](#4-データモデル要件)
5. [中間表現スキーマ要件](#5-中間表現スキーマ要件)
6. [パース要件（ベンダー別 config 構文マッピング）](#6-パース要件ベンダー別-config-構文マッピング)
7. [結線推論・ルーティング解析要件](#7-結線推論ルーティング解析要件)
8. [HTML 構成図機能要件](#8-html-構成図機能要件)
9. [振る舞い上の制約](#9-振る舞い上の制約)
10. [運用・CLI 要件](#10-運用cli-要件)
11. [受け入れ基準・テスト要件](#11-受け入れ基準テスト要件)
- [附録 A: 用語定義](#附録-a-用語定義)
- [附録 B: サンプル config と期待出力（ゴールデン）](#附録-b-サンプル-config-と期待出力ゴールデン)

---

## 1. システム概要と目的

### 1.1 機能概要

**config-topology** は、ネットワーク機器の running-config（テキスト形式）を入力に、以下の出力を生成するシステムである：

1. **中間表現（レイヤー別 YAML）** — ベンダー中立で、人手編集可能な層別ファイル群。IP/サブネット一致による結線・ルーティングを含む。
2. **HTML 構成図** — 単一の自己完結 HTML ファイル。`file://` URL でブラウザから直接開け、ズーム・パン・検索・レイヤー切替などのインタラクティブ機能を備える。

### 1.2 入出力の契約

```
入力: 複数の config ファイル（IOS/JunOS 混在可）
  ↓
  パース：ベンダー自動判定 → 正規化
  ↓
  推論：IP/サブネット一致 → リンク・セグメント・ルーティング解析
  ↓
出力①: ./topology/ （層別 YAML）
出力②: ./topology.html （自己完結 HTML）
```

### 1.3 スコープと制限

| 対象 | 対応状況 | 備考 |
|------|--------|------|
| **対応ベンダー** | Cisco IOS / IOS-XE / Juniper JunOS（set 形式） | 自動判定；未知ベンダーはスキップ（クラッシュしない） |
| **抽出対象** | 機器・インターフェース・IP（IPv4/IPv6）・説明・管理状態・ルーティング（BGP/OSPF/static） | 初版スコープ |
| **結線推論** | IP/サブネット一致のみ（CDP/LLDP 非使用） | 対向が無い外部 AS も片側オーバーレイで残す |
| **L2・VLAN・LAG・HSRP** | 初版では非対応 | 将来拡張。L2 判定フィールドは層別 YAML に保持 |
| **追加ベンダー** | 初版では未対応（NX-OS / Arista 等） | 拡張手順は要件定義の対象外 |

### 1.4 機密情報の取り扱い

- **interface description** 等の自由記述テキストは、そのまま層別 YAML と HTML に出力される（サニタイズは行わない）。
- **password / secret / snmp community 行** はパースしない（これらのキーワード行自体は読み込まない）。
- **`generated_from` に記録する入力ファイル情報はファイル名（basename）のみ**とし、ディレクトリパスは記録しない（パスに含まれる環境情報の漏洩防止）。
- **生成物（層別 YAML・HTML）の共有時は、利用者が機密情報や個人情報の漏洩を事前に確認する責任を持つ**。

---

## 2. 入力要件

### 2.1 対応ファイル形式

| ベンダー | 形式 | 判定方法 |
|--------|------|--------|
| **Cisco IOS / IOS-XE** | running-config（行指向、`!` で区切られた設定ブロック） | `hostname`・`interface ...Ethernet`・`!` 等の IOS 特徴行の存在で判定（`set ` 行が過半を占めるときは JunOS とみなし除外） |
| **Juniper JunOS** | set 形式（全行 `set ...` で始まる） | 非空行のうち `set ` で始まる行が過半（50% 超） |

### 2.2 入力ファイル収集

- **対象拡張子**: `*.cfg`, `*.conf`, `*.txt`
- **既定の走査ディレクトリ**: `./workspace/`（ホストプロジェクト cwd からの相対）
- **走査ルール**:
  - `./workspace/` に対象ファイルがあれば使用。
  - ユーザーがファイル・ディレクトリ・glob パターンを明示指定した場合はそれを対象にする。
  - 指定パスの複数ファイルは **名前順でソート**。
  - **重複排除**: 同一ファイルパスは 1 回だけ処理。
- **処理順序の保持**: ファイルの読み込み順を `generated_from` フィールドに**ファイル名（basename）で**記録し、再現性を確保する（§1.4）。

### 2.3 ベンダー自動判定

**判定の振る舞い**（特異度の高い順に試行する）:

1. **JunOS 判定**: 非空行のうち `set ` で始まる行が **過半（50% 超）** を占めれば JunOS と確定。
2. **IOS 判定**: `hostname`・`interface ...Ethernet`・`!` 等の IOS 特徴行が存在すれば IOS と確定。ただし `set ` 行が **40% を超える** config は（IOS 特徴行があっても）JunOS とみなして IOS 判定から除外する。
3. **未知ベンダー**: いずれにも該当しないファイルはスキップする（警告を出力し、処理は継続する）。

**特徴**:
- どのベンダーにも一致しなかったファイルはスキップするが、パイプライン全体はクラッシュせず継続する。
- 判定の閾値（JunOS 50% / IOS 側ガード 40%）が非対称なのは、IOS 特徴行を持たない純粋な set 形式を確実に JunOS 側へ寄せるための安全マージンである。

---

## 3. 出力要件

### 3.1 出力物の成果物

| 出力 | 形式 | 内容 | 備考 |
|-----|------|------|------|
| **出力①**: `./topology/` | ディレクトリ（複数 YAML） | 層別 YAML 正本（中間表現） | 人手編集可・参照整合検証 |
| **出力②**: `./topology.html` | 単一 HTML | 自己完結構成図 | 外部依存なし・`file://` 対応 |

### 3.2 層別 YAML ファイル構成

`./topology/` に生成されるファイル一覧:

| ファイル | 内容 | 条件 |
|---------|------|------|
| `_meta.yaml` | schema_version / title / generated_from | 必ず生成 |
| `devices.yaml` | devices[] / interfaces[] | 必ず生成 |
| `physical.yaml` | links[] / segments[] | 必ず生成（links/segments が空でも空配列として出力） |
| `routing.bgp.yaml` | bgp[] | BGP エントリが存在する場合のみ生成 |
| `routing.ospf.yaml` | ospf[] | OSPF エントリが存在する場合のみ生成 |
| `routing.static.yaml` | static[] | static route エントリが存在する場合のみ生成 |
| `routing.redistribute.yaml` | redistribute[] | redistribute エントリが存在する場合のみ生成（§C5） |

空の routing プロトコルはファイルを書き出さない（読込時は欠落＝空リスト扱い）。

**YAML 仕様**:
- 直列化: マッピングのキーを辞書式（ASCII コード順）昇順でソートし、フロースタイルを使わないブロック表記で出力すること。同一入力に対して同一バイト列の YAML を生成する（決定的順序）。
- 表記の確定（附録 B のゴールデンとバイト一致させるための規定）:
  - null 値は `null` と表記する（`~` は使わない）。
  - インデントは 2 スペース。
  - ドキュメント開始行 `---` は出力しない。
  - （参考: PyYAML の `yaml.safe_dump(data, sort_keys=True, default_flow_style=False, allow_unicode=True)` がこの表記を満たす）
- 安全な読込/書込のみを行い、任意のオブジェクト復元を伴う機能は使用しないこと。
- エンコーディング: UTF-8（非 ASCII 文字はそのまま出力）。

### 3.3 HTML 構成図の特性

- **単一ファイル**: 外部 CSS / JavaScript / 画像依存なし。`file://` URL で直接ブラウザから開ける。
- **SVG ベース**: ベクトルグラフィックス（スケーラブル）。
- **バニラ JavaScript**: フレームワーク依存なし。
- **決定的レイアウト**: 同一の層別 YAML → 同一の HTML 出力（乱数・時刻に依存しない）。

---

## 4. データモデル要件

### 4.1 抽出される論理データ項目（ベンダー中立）

パーサが config テキストから抽出・正規化すべきデータ項目（以下「属性」と呼ぶ）:

#### 機器

| 属性 | 型 | 説明 | 備考 |
|------|-----|------|------|
| `hostname` | string | ホスト名（config 上の表記） | 空文字列は許容（ID 採番で `device` に） |
| `vendor` | string | ベンダー識別子 | `"cisco_ios"` / `"juniper_junos"` |
| `as` | int \| null | ローカル AS 番号（BGP/autonomous-system 宣言由来） | BGP がなければ null |
| `ospf_router_id` | string \| null | OSPF router-id | config に記載があれば格納 |
| `bgp_router_id` | string \| null | BGP router-id | config に記載があれば格納 |

#### インターフェース

| 属性 | 型 | 説明 | 備考 |
|------|-----|------|------|
| `name` | string | インターフェース名（config 上の表記） | 例: `GigabitEthernet0/0`, `ge-0/0/0` |
| `addresses` | object[] | IP アドレス群（dual-stack 正本） | 本節後述「アドレス（dual-stack）」で形式指定 |
| `ip` | string \| null | 後方互換の単一 IP（`addresses` 中の最初の非 secondary v4 から派生） | 形式 `"a.b.c.d/prefixlen"`。v6-only / IP 未設定は null |
| `description` | string \| null | description テキスト | 自由記述；サニタイズなし |
| `shutdown` | bool | 管理停止状態 | `true` = shutdown、`false` = no shutdown |
| `admin_status` | string \| null | 管理状態文字列 | `"up"` / `"down"` |
| `oper_status` | string \| null | 運用状態（現行常に null） | config からは取得不可（将来 SNMP 連携） |
| `mtu` | int \| null | MTU 値（バイト） | config に記載がなければ null |
| `speed` | string \| null | インターフェース速度 | ベンダー表記のまま（`"1000"`, `"1g"` など） |
| `duplex` | string \| null | duplex 設定 | `"full"` / `"half"` / null（IOS のみ） |
| `l2_l3` | string \| null | レイヤー種別 | `"l2"` / `"l3"` / null |
| `switchport` | object \| null | switchport 情報（IOS 専用） | §5.2.2 で形式指定 |
| `encapsulation` | string \| null | カプセル化種別 | 例: `"dot1q"`, `"flexible-ethernet-services"` |

#### アドレス（dual-stack）

各アドレス項目は以下の構造:
```
{
  af: "v4" | "v6"           # アドレスファミリ
  ip: "a.b.c.d"             # ホストアドレス（プレフィックス長なし・正規化済み）
  prefix: int               # プレフィックス長
  secondary?: true          # IOS secondary フラグ（省略＝非secondary）
  scope?: "link-local"      # link-local 標識（省略＝グローバル）
}
```

**並び順**: af 順（v4 < v6） → ip 昇順 → prefix 昇順。

#### ルーティング

**BGP ネイバー**:
| 属性 | 型 | 説明 |
|------|-----|------|
| `neighbor_ip` | string | ネイバー IP（v4 または v6） |
| `peer_as` | int \| null | ピア AS 番号（不明なら null） |
| `af` | string | アドレスファミリ（`"v4"` / `"v6"`） |

**OSPF network 宣言**:
| 属性 | 型 | 説明 |
|------|-----|------|
| `process` | int \| null | プロセス ID（JunOS では null 可） |
| `network` | string | CIDR またはインターフェース名 |
| `area` | string | エリア番号（正規化済み文字列。§6.3「OSPF area 正規化」参照。例: `"0"`, `"16909060"`） |
| `af` | string | アドレスファミリ（`"v4"` = OSPFv2 / `"v6"` = OSPFv3） |

**static route**:
| 属性 | 型 | 説明 |
|------|-----|------|
| `prefix` | string | 宛先 CIDR（例: `"0.0.0.0/0"`, `"::/0"`） |
| `next_hop` | string | ネクストホップ IP（v4 または v6） |
| `af` | string | アドレスファミリ（`"v4"` / `"v6"`） |

### 4.2 設計原則

1. **IP はインターフェースに帰属する** — 機器は直接 IP を持たない（実機の構造と一致）。
2. **物理層と論理層の分離** — 機器・インターフェース・リンク・セグメント（物理） と BGP・OSPF・static（論理）を分離。レンダラーはレイヤートグルで重ねる。
3. **dual-stack 正本性** — `addresses` が正本。単一 `ip` フィールドは後方互換派生。
4. **ベンダー中立な正規化** — パーサが IOS/JunOS の構文差異を吸収。以降のパイプラインはこの正規化モデルのみを見る。

---

## 5. 中間表現スキーマ要件

### 5.1 層別 YAML とトップレベル構造

層別 YAML は以下の 6 種ファイルで構成される（ファイル間の参照整合を検証する）。

トップレベル (`_meta.yaml`)：
| フィールド | 型 | 説明 |
|------------|-----|------|
| `schema_version` | string | スキーマバージョン（現行 `"1.0"`） |
| `title` | string | 図のタイトル（既定 `"Network Topology (config-derived)"`) |
| `generated_from` | string[] | 元になった config の**ファイル名（basename）**一覧（読込順）。ディレクトリパスは含めない |

### 5.2 devices.yaml スキーマ

**トップレベル**:
```
devices: [...]
interfaces: [...]
```

#### devices[] フィールド

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `id` | string | ✓ | 機器 ID（[ID 採番規則](#55-id-採番規則) に準拠） |
| `hostname` | string | ✓ | config 上のホスト名 |
| `vendor` | string | ✓ | `"cisco_ios"` / `"juniper_junos"` |
| `as` | int \| null | ✓ | ローカル AS（null 可） |
| `ospf_router_id` | string \| null | ✓ | OSPF router-id（§5.2.1）。未設定時は null を出力 |
| `bgp_router_id` | string \| null | ✓ | BGP router-id（§5.2.1）。未設定時は null を出力 |
| `sections` | object[] | ✓ | 拡張枠（初版は常に `[]`）。形式: `[{title: "...", rows: [...]}]` |

##### 特記: ospf_router_id / bgp_router_id（§5.2.1）

- **OSPF router-id**: OSPF 設定由来の router-id（IOS は `router ospf` 配下の `router-id`、JunOS は OSPF プロトコル配下の router-id。JunOS で OSPF 専用 router-id が無くグローバル `routing-options router-id` がある場合はそれをフォールバックとして用いる）。
- **BGP router-id**: BGP 設定由来の router-id（IOS は `router bgp` 配下の `bgp router-id`、JunOS はグローバル `routing-options router-id` を含む）。
- 両フィールドは独立であり、競合しない（一方が他方を上書きすることはない）。
- いずれも **常に出力する**。設定に該当 router-id が無い場合は `null` を出力する（フィールド自体は省略しない）。

#### interfaces[] フィールド

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `id` | string | ✓ | `"<device_id>::<name>"` |
| `device` | string | ✓ | 所属機器 ID（devices[].id への参照） |
| `name` | string | ✓ | インターフェース名（config 上の表記） |
| `ip` | string \| null | ✓ | 後方互換フィールド。形式 `"a.b.c.d/prefixlen"`（CIDR 正規化済み。`addresses` 中の最初の非 secondary v4 から派生）。v6-only / IP 未設定の IF は null |
| `vlan` | int \| null | ✗ | VLAN（初版では基本 null。L2 は将来拡張） |
| `description` | string \| null | ✗ | インターフェース description |
| `shutdown` | bool | ✓ | 管理停止状態（true/false） |
| `admin_status` | string \| null | ✗ | `"up"` / `"down"` (shutdown 由来) |
| `oper_status` | string \| null | ✗ | 運用状態（現行常に null。将来 SNMP 連携用の予約フィールド） |
| `mtu` | int \| null | ✗ | MTU 値（バイト） |
| `speed` | string \| null | ✗ | インターフェース速度（ベンダー表記） |
| `duplex` | string \| null | ✗ | duplex 設定（IOS のみ） |
| `l2_l3` | string \| null | ✗ | `"l2"` / `"l3"` / null |
| `switchport` | object \| null | ✗ | IOS switchport 情報（§5.2.2） |
| `encapsulation` | string \| null | ✗ | カプセル化種別 |
| `ospf` | object | ✗ | OSPF interface パラメータ（サブキー `cost`/`network_type`/`passive`、存在するもののみ格納）。**設定があるときのみ出力する条件付き省略フィールド**（§6.1/§6.2）。null も空 object も出力せずキー自体を省く |
| `source` | string | ✓ | データソース（常に `"parsed"`） |
| `addresses` | object[] | ✓ | IP アドレス群（§5.2.2）。empty[] なら IP なし |

**出力規約（重要）**: `devices[]`・`interfaces[]` の各要素は、**表中の全フィールドをキーとして常に出力する**（該当値が無い場合は `null`、`addresses`/`sections` は `[]`）。表の「必須」列は ✓＝値が常に意味を持つ、✗＝値が null になり得る、の区別であり、**キーの省略を許すものではない**（附録 B のゴールデンと一致させるため）。フィールドキーの条件付き省略を行うのは links/segments の `admin_down` / `ospf_area` / `ospf_network`（§5.3）、および interfaces の `ospf`（加算的拡張。設定不在の IF では既存ゴールデンと byte 一致を保つためキーを省く）のみ。

##### switchport 構造（§5.2.2）

```
{
  mode: "access" | "trunk"        # 必須
  access_vlan?: int               # mode="access" 時に指定
  trunk_vlans?: string            # mode="trunk" 時に指定（範囲文字列）
}
```

**JunOS では常に null**（IOS 専用フィールド）。

##### addresses[] 構造

各要素:
```
{
  af: "v4" | "v6"           # 必須
  ip: string                # ホストアドレス（プレフィックス長なし）
  prefix: int               # プレフィックス長（1-32 for v4、1-128 for v6）
  secondary?: true          # 省略は false 相当（IOS secondary フラグ）
  scope?: "link-local"      # 省略はグローバルアドレス
}
```

**並び順** (必須):
1. af 順（`"v4"` < `"v6"`）
2. ip 昇順（正規化後のアドレス数値による比較）
3. prefix 昇順

**ソート例**: `[{af:"v4",ip:"10.0.0.1",prefix:24}, {af:"v4",ip:"192.168.1.1",prefix:24}, {af:"v6",ip:"2001:db8::1",prefix:64}]`

**特記**:
- link-local（fe80::/10）も addresses に保持（ただし結線推論から除外）。
- addresses が空配列なら、`ip` フィールドは null。

### 5.3 physical.yaml スキーマ

**トップレベル**:
```
links: [...]
segments: [...]
```

#### links[] フィールド

2 機器のちょうど 2 つのインターフェースが同一サブネットを共有するとき生成。

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `a_device` | string | ✓ | 端点機器 ID（`a` < `b` で辞書式安定ソート） |
| `b_device` | string | ✓ | 端点機器 ID |
| `a_if` | string | ✓ | 端点インターフェース名 |
| `b_if` | string | ✓ | 端点インターフェース名 |
| `subnet` | string | ✓ | 共有サブネット CIDR（例: `"10.0.0.0/30"`, `"2001:db8:1::/127"`） |
| `kind` | string | ✓ | 結線の由来（初版は常に `"inferred-subnet"`） |
| `admin_down` | bool | ✗ | 片端/両端が shutdown の場合 `true`（視覚的に破線表示）。両端 up ならフィールド省略 |
| `ospf_area` | string \| null | ✗ | OSPF 参加リンクの area（§5.3.1）。非参加なら省略 |
| `ospf_network` | string \| null | ✗ | OSPF network CIDR（`ospf_area` 付与時のみ）。非参加なら省略 |

**`links` には `id` を設けない** — `(subnet, a_device, a_if, b_device, b_if)` の複合キーで一意に定まるため。

##### admin_down と ospf_area の関係

- **`admin_down=true` の場合**: `ospf_area` / `ospf_network` は **付与しない**（shutdown IF は OSPF 隣接を張れない）。
- **`admin_down` が false または省略の場合**: `ospf_area` / `ospf_network` を付与可（OSPF 対応リンク）。

##### ospf_area 値の形式（§5.3.1）

area 値は **正規化済み文字列**（§6.3「OSPF area 正規化」適用後）で格納する。

- **両端同一 area**: 単一値（例: `"0"`、`"1"`、`"16909060"`）。
- **両端異なる area**: 昇順スラッシュ区切り（例: `"0/1"`）。連結順は、正規化後の全要素が数値文字列なら**数値昇順**、数値でない要素が混在するなら**辞書式昇順**。

#### segments[] フィールド

同一サブネットに 3 つ以上のインターフェースが属するとき生成。

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `id` | string | ✓ | `"seg-<subnet>"`（`/` と `.` は `_` に置換。例: `seg-192_168_1_0_24`） |
| `subnet` | string | ✓ | サブネット CIDR（例: `"192.168.1.0/24"`） |
| `members` | string[] | ✓ | 接続インターフェース ID の配列（安定ソート） |
| `ospf_area` | string \| null | ✗ | OSPF 参加セグメントの area（§5.3.1）。非参加なら省略 |
| `ospf_network` | string \| null | ✗ | OSPF network CIDR（`ospf_area` 付与時のみ）。非参加なら省略 |

**members の並び順** (必須): インターフェース ID を辞書式昇順でソート。

**ospf_area 値**: links と同じルール（§5.3.1）。全メンバーの area を正規化後に集約する。

### 5.4 routing.*.yaml スキーマ

ルーティングプロトコル別のファイル。空プロトコルは書き出さない。

#### routing.bgp.yaml

```
bgp: [...]
```

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `device` | string | ✓ | 機器 ID（devices[].id への参照） |
| `local_as` | int | ✓ | ローカル AS 番号 |
| `local_ip` | string \| null | ✓ | neighbor と同一サブネットにある自機 IP（解決不能なら null）。update_source フォールバックが成功した場合も非 null になる |
| `neighbor_ip` | string | ✓ | ネイバー IP（v4 または v6） |
| `peer_as` | int \| null | ✓ | ピア AS（不明なら null） |
| `type` | string | ✓ | `"ebgp"` / `"ibgp"` / `"unknown"` |
| `af` | string | ✓ | `"v4"` / `"v6"` |
| `update_source` | string \| null | ✗ | **任意・設定時のみ出力**。IOS の `update-source <ifname>` または JunOS の `local-address <ip>`。未設定の場合はキー自体を省略する |
| `route_reflector_client` | bool | ✗ | **任意・True 時のみ出力**。IOS `neighbor route-reflector-client` / JunOS `group cluster`。False はキー省略 |
| `next_hop_self` | bool | ✗ | **任意・True 時のみ出力**。IOS `neighbor next-hop-self`。JunOS はポリシーベースで常に False（キー省略） |
| `timers` | object \| null | ✗ | **任意・設定時のみ出力**。IOS `timers <ka> <hold>` → `{keepalive, holdtime}`。JunOS 非対応 |
| `send_community` | string \| null | ✗ | **任意・設定時のみ出力**。IOS `send-community [both\|standard\|extended]`（無印=standard）。large 等の未対応キーワードはスキップ。JunOS 非対応 |
| `peer_group` | string \| null | ✗ | **任意・設定時のみ出力**。IOS peer-group 名（属性は group 定義から継承・個別指定が優先）。JunOS は group を peer_group にマッピングしない（非出力） |

**local_ip 解決ルール**:
- neighbor_ip と同一サブネットにある自機のインターフェース IP を検索（一次解決）。
- v4 neighbor に対しては v4 local_ip、v6 neighbor に対しては v6 local_ip を返す。
- 一次解決が null かつ `update_source` が設定されている場合にフォールバック:
  - `update_source` が有効な IP アドレスなら、AF が一致する場合のみその IP を local_ip として採用（JunOS local-address）。
  - IP でなければ（インターフェース名）、dev.interfaces から name が一致する IF の AF 一致アドレス（v6 は link-local 除外）を返す（IOS update-source）。
- 解決できなければ null。
- config に対向が存在しない外部 AS でも BGP エントリは片側オーバーレイとして残す。

**type 判定ルール**:
- `local_as == peer_as` → `"ibgp"`
- `local_as != peer_as`（両者既知） → `"ebgp"`
- `peer_as` が null → `"unknown"`

#### routing.ospf.yaml

```
ospf: [...]
```

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `device` | string | ✓ | 機器 ID（devices[].id への参照） |
| `process` | int \| null | ✓ | プロセス ID（JunOS では null 可） |
| `network` | string | ✓ | CIDR またはインターフェース名 |
| `area` | string | ✓ | エリア（**正規化済み文字列**。§6.3「OSPF area 正規化」。例: `"0"`, `"1"`, `"16909060"`） |
| `af` | string | ✓ | `"v4"` / `"v6"` |

**network の形式**:
- **CIDR**: IP マスク（IOS）または prefix/length（JunOS）を CIDR に正規化（例: `"10.0.0.0/24"`）。
- **インターフェース名**: CIDR 算出不能の場合（JunOS fallback）、インターフェース名を格納（例: `"ge-0/0/0"`）。

#### routing.static.yaml

```
static: [...]
```

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `device` | string | ✓ | 機器 ID（devices[].id への参照） |
| `prefix` | string | ✓ | 宛先 CIDR（例: `"0.0.0.0/0"`, `"::/0"`） |
| `next_hop` | string | ✓ | ネクストホップ IP（v4 または v6） |
| `af` | string | ✓ | `"v4"` / `"v6"` |

#### routing.redistribute.yaml（§C5）

ルーティングプロトコル間の再配布設定。**IOS のみ対応**。非空時のみ生成。

```
redistribute: [...]
```

| フィールド | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `device` | string | ✓ | 機器 ID（devices[].id への参照） |
| `into` | string | ✓ | 再配布先プロトコル（`"bgp"` / `"ospf"`）= config の文脈（router bgp / router ospf ブロック） |
| `source` | string | ✓ | 再配布元プロトコル（`connected` / `static` / `ospf` / `bgp` / `rip` / `eigrp` / `isis` 等） |
| `metric` | int | ✗ | 設定時のみ出力（`metric <n>`）。未設定時はキー省略 |
| `route_map` | string | ✗ | 設定時のみ出力（`route-map <name>`）。未設定時はキー省略 |

JunOS はルート再配布をポリシーベース（export policy 経由）で制御するため、set 形式 config では非対応（エントリは常に空）。

### 5.5 ID 採番規則

#### device_id

1. hostname を小文字化。
2. 英数字とハイフン以外を `-` に置換。
3. 入力ファイルの処理順（`generated_from` の順序）で先に出現した機器が短いサフィックスを取る。最初の出現はサフィックスなし、2 番目は `-2`、3 番目は `-3` ...
4. **衝突回避**: 採番した ID が既出の ID と**テキスト一致**する場合のみ、候補に `-2`, `-3` … を付与して一意化する（slug に対する単純な重複回避。サフィックスの解釈やファントム予約はしない）。衝突しない素の slug（他に同名 ID が無い場合）はそのまま採用する。
5. **空 hostname**: `device`, `device-2`, `device-3` ...

**例**:
- hostname `r1`, `r1`, `r2` → device_id `r1`, `r1-2`, `r2`
- hostname `R1`, `R1`, `R1-2` → device_id `r1`, `r1-2`, `r1-2-2`（2 台目 `R1` が `r1-2`、3 台目 `R1-2`〔slug `r1-2`〕はそれと衝突するため `-2` を付与して `r1-2-2`）

#### interface_id

```
"<device_id>::<name>"
```

例: `"r1::GigabitEthernet0/0"`, `"r2::ge-0/0/0"`

#### segment_id

```
"seg-<subnet_CIDR_with_substitution>"
```

CIDR の `.` と `/` を `_` に置換。

**例**: `"seg-192_168_1_0_24"`, `"seg-2001_db8_1__64"`

### 5.6 参照整合検証

層別 YAML の読込処理は、以下の参照整合を検証すること。違反（人手編集による dangling 参照等）を検出した場合は、**違反したファイル名・フィールド・値を示すエラーで処理を停止する**：

| 参照元 | 参照先集合 | チェック |
|--------|----------|--------|
| `interfaces[].device` | `devices[].id` | すべての interface が既知の device を参照 |
| `links[].a_device` / `links[].b_device` | `devices[].id` | すべての link 端点機器が既知 |
| `links[].a_if` / `links[].b_if` | `interfaces[].name` （各device内） | 指定 device のインターフェース名が存在 |
| `segments[].members[*]` | `interfaces[].id` | すべてのメンバー IF が既知 |
| `routing.bgp[].device` etc. | `devices[].id` | すべてのルーティングエントリが既知の device を参照 |

**手編集ノート**: 層別 YAML は人手編集を想定する（§3.1）。リンクを手で追加する場合の最小フィールドは links[] の必須✓列（`a_device` / `b_device` / `a_if` / `b_if` / `subnet` / `kind`）であり、`admin_down` / `ospf_area` / `ospf_network` は省略してよい。編集後の検証はこの §5.6 のチェックで行われ、違反時のエラーメッセージから修正箇所を特定できる（§10.2）。

### 5.7 スキーマ進化方針

- **フィールド追加（addition-only）**: `schema_version` を据え置く。（例：`af` の追加は version `"1.0"` のまま）
- **型変更・フィールド廃止**: `schema_version` をバンプ（例: `"1.1"` → `"2.0"`）。
- **未知メジャーバージョンの読込**: 警告を出しつつ forward-compatible に読込（フィールド省略時は既定値で補完）。

---

## 6. パース要件（ベンダー別 config 構文マッピング）

### 6.1 Cisco IOS / IOS-XE

#### 判定基準

- `hostname `, `interface ...Ethernet`, `!` などの IOS 特徴行の存在で判定する（JunOS 判定の後に試行する）。
- ただし `set ` で始まる行が **40% を超える** config は、IOS 特徴行があっても JunOS とみなし IOS 判定から除外する（純粋な set 形式を確実に JunOS へ寄せるためのガード。閾値の非対称性の意図は §2.3 参照）。

#### 構文 → データマッピング

| 構文 | 抽出先 | マッピング | 備考 |
|------|--------|-----------|------|
| `hostname <name>` | 機器 | `hostname = <name>` | 最初の 1 行のみ採用 |
| `interface <name>` | インターフェース | `name = <name>`、ブロック内の属性を解析 | GigabitEthernet / FastEthernet など |
| `ip address <ip> <mask>` | IF.addresses | `{af:"v4", ip:<host>, prefix:<from_mask>}` | マスクを CIDR prefix に変換 |
| `ip address <ip> <mask> secondary` | IF.addresses | `{af:"v4", ip:<host>, prefix:<from_mask>, secondary:true}` | secondary フラグを付与 |
| `ipv6 address <prefix/len>` | IF.addresses | `{af:"v6", ip:<host>, prefix:<len>}` | v6 短縮形に正規化（§6.3 参照） |
| `ipv6 address <prefix/len> link-local` | IF.addresses | `{af:"v6", ip:<host>, prefix:<len>, scope:"link-local"}` | scope フィールド付与 |
| `description <text>` | IF | `description = <text>` | クォートは除去 |
| `shutdown` | IF | `shutdown = true`, `admin_status = "down"` | `no shutdown` で false |
| `mtu <val>` | IF | `mtu = <val>` (int) | 数値 parse；エラーは無視 |
| `speed <val>` | IF | `speed = <val>` (string) | ベンダー表記のまま |
| `duplex <val>` | IF | `duplex = <val>` | `"full"`, `"half"` など |
| `switchport mode access\|trunk` | IF.switchport | `mode = "access" \| "trunk"` | |
| `switchport access vlan <id>` | IF.switchport | `access_vlan = <id>` (int) | mode="access" 時 |
| `switchport trunk allowed vlan <range>` | IF.switchport | `trunk_vlans = <range>` (string) | mode="trunk" 時 |
| `no switchport` | IF | `l2_l3 = "l3"` | L3 判定フラグ |
| `encapsulation dot1Q <vlan>` | IF | `encapsulation = "dot1q"` | IGNORECASE |
| `router bgp <asn>` | 機器 | `as = <asn>`, BGP ブロック開始 | |
| `neighbor <ip> remote-as <peer>` | BGP neighbor | `neighbor_ip = <ip>`, `peer_as = <peer>`, `af = "v4"` | グローバル登録 |
| `neighbor <ip> update-source <ifname>` | BGP neighbor | `update_source = <ifname>`（インターフェース名）| remote-as と順不同可。address-family 配下も対応 |
| `neighbor <ip> route-reflector-client` | BGP neighbor | `route_reflector_client = true`（True 時のみ YAML 出力）| remote-as と順不同可。address-family 配下も対応。他 neighbor に影響しない |
| `neighbor <ip> next-hop-self` | BGP neighbor | `next_hop_self = true`（True 時のみ YAML 出力）| remote-as と順不同可。address-family 配下も対応。他 neighbor に影響しない |
| `neighbor <ip> timers <ka> <hold>` | BGP neighbor | `timers = {keepalive, holdtime}`（設定時のみ YAML 出力）| remote-as と順不同可。address-family 配下も対応 |
| `neighbor <ip> send-community [both\|standard\|extended]` | BGP neighbor | `send_community = <値>`（無印=standard・設定時のみ YAML 出力）| large 等の未対応キーワードはスキップ。remote-as と順不同可。address-family 配下も対応 |
| `neighbor <name> remote-as/update-source/...`（name が IP でない）| peer-group 定義 | group 属性を集約（pg_template） | name は norm 失敗で peer-group 名と判定 |
| `neighbor <ip> peer-group <name>` | BGP neighbor | `peer_group = <name>` ＋ group 属性を欠落分だけ継承（**個別指定が優先**・設定時のみ YAML 出力）| 個別 remote-as 無しメンバーは末尾解決で生成。未定義 group 参照は neighbor 非生成（ゾンビ防止） |
| `address-family ipv6` | BGP AF | neighbor に `activate` で `af = "v6"` に変更 | v6 neighbor のみ |
| `neighbor <v6ip> activate` (under address-family ipv6) | BGP AF | `af = "v6"` に変更（当該 neighbor） | activate されていない v4 neighbor は af="v4" 確定 |
| `router ospf <pid>` | OSPF process | process ID = <pid> | |
| `network <addr> <wildcard> area <a>` | OSPF network | `network = <CIDR>` (wildcard を逆マスク化), `area = <正規化済み a>`, `af = "v4"` | area は §6.3 で正規化 |
| `ipv6 router ospf <pid>` | OSPF v3 | process ID 宣言のみ（interface 内で確定） | |
| `ipv6 ospf <pid> area <a>` (in interface block) | OSPF v3 | `network = <v6_subnet_of_IF_or_IF_name>`, `area = <正規化済み a>`, `af = "v6"` | v6 アドレスが無ければ IF 名 |
| `ip ospf cost <n>` (in interface block) | OSPF if param | `interfaces[].ospf.cost = int(n)` | 加算フィールド |
| `ip ospf network <type>` (in interface block) | OSPF if param | `interfaces[].ospf.network_type = <type>` | point-to-point / broadcast 等 |
| `passive-interface <if>` (under router ospf) | OSPF if param | 該当 `interfaces[].ospf.passive = true` | 明示名のみ対応（`default` / `no passive-interface` は非対応） |
| `area <a> stub` (under router ospf) | OSPF area type | 同一 `(process, area)`・af="v4" の OspfNetwork に `area_type = "stub"` を設定（末尾一括適用。別プロセス・OSPFv3 には漏れない） | network 宣言と順不同可 |
| `area <a> stub no-summary` (under router ospf) | OSPF area type | `area_type = "totally-stubby"` | no-summary は ABR でのみ有意 |
| `area <a> nssa` (under router ospf) | OSPF area type | `area_type = "nssa"` | |
| `area <a> nssa no-summary` (under router ospf) | OSPF area type | `area_type = "totally-nssa"` | |
| `ip route <prefix> <mask> <next_hop>` | static | `prefix = <CIDR>`, `next_hop = <next_hop>`, `af = "v4"` | `0.0.0.0 0.0.0.0` → `"0.0.0.0/0"` |
| `ipv6 route <prefix/len> <nexthop>` | static | `prefix = <正規化済み CIDR>`, `next_hop = <v6 短縮形正規化済み>`, `af = "v6"` | §6.3 参照 |
| `redistribute <source> [<pid/AS>] [metric <n>] [route-map <name>] [subnets ...]` (router bgp / router ospf 内、§C5) | redistribute | `into = <"bgp"/"ospf">`, `source = <直後のトークン>`, `metric`/`route_map` は値ありのみ出力。プロセス ID・AS 番号・`subnets` 等の付加引数は無視。`no redistribute ...` は対象外 | connected / static / ospf / bgp / rip / eigrp / isis 等に対応 |

#### L2/L3 判定ルール（IOS）

| 条件 | l2_l3 判定 |
|------|-----------|
| `ip address` あり または `no switchport` あり | `"l3"` |
| `ipv6 address` あり | `"l3"` |
| `switchport` あり | `"l2"` |
| いずれもなし | null |

**優先順**: `ip`/`ipv6`/`no switchport` が `switchport` より先に評価（L3 優先）。

#### admin_status 導出

- `shutdown = true` → `admin_status = "down"`
- `shutdown = false` → `admin_status = "up"`

### 6.2 Juniper JunOS（set 形式）

#### 判定基準

非空行のうち `set ` で始まる行が **過半（50% 超）** → JunOS に確定。

#### 構文 → データマッピング

| 構文 | 抽出先 | マッピング | 備考 |
|------|--------|-----------|------|
| `set system host-name <name>` | 機器 | `hostname = <name>` | クォート除去 |
| `set interfaces <if> description <text>` | IF | `description = <text>` | クォート除去 |
| `set interfaces <if> unit <n> family inet address <prefix/len>` | IF.addresses | `{af:"v4", ip:<host>, prefix:<len>}` | unit を集約（IF 名に含めず） |
| `set interfaces <if> unit <n> family inet6 address <prefix/len>` | IF.addresses | `{af:"v6", ip:<短縮形正規化済み>, prefix:<len>}` | v6 アドレス全収集 |
| `set interfaces <if> unit <n> family inet6 address <fe80::.../len>` | IF.addresses | `{af:"v6", ip:<短縮形正規化済み>, prefix:<len>, scope:"link-local"}` | `fe80::/10` に該当するものに scope を付与 |
| `set interfaces <if> disable` | IF | `shutdown = true`, `admin_status = "down"` | 反対: 行がなければ false |
| `set interfaces <if> mtu <val>` | IF | `mtu = <val>` (int) | |
| `set interfaces <if> speed <val>` | IF | `speed = <val>` (string) | `"1g"`, `"10g"` など |
| `set interfaces <if> encapsulation <val>` | IF | `encapsulation = <val>` | ベンダー表記のまま |
| `set interfaces <if> unit <n> family ethernet-switching` | IF | `l2_l3 = "l2"` | L2 フラグ |
| `set interfaces <if> unit <n> family inet` (address あり) | IF | `l2_l3 = "l3"` | L3 判定 |
| `set interfaces <if> unit <n> family inet6` (address あり) | IF | `l2_l3 = "l3"` | L3 判定 |
| `set routing-options autonomous-system <asn>` | 機器 | `as = <asn>` | |
| `set routing-options router-id <id>` | 機器 | `bgp_router_id = <id>`（OSPF 専用 router-id 未設定時は `ospf_router_id` のフォールバックにも使用） | §5.2.1 |
| `set protocols bgp group <g> neighbor <ip> peer-as <peer>` | BGP neighbor | `neighbor_ip = <ip>`, `peer_as = <peer>` | neighbor_ip が v4 なら `af="v4"` |
| `set protocols bgp group <g> neighbor <ip> local-address <localip>` | BGP neighbor | `update_source = <localip>`（ローカル IP 文字列）| peer-as と順不同可 |
| `set protocols bgp group <g> cluster <id>` | BGP neighbor | cluster を持つ group の全 neighbor に `route_reflector_client = true`（末尾一括適用・True 時のみ YAML 出力）| JunOS の RR 表現。cluster のない group の neighbor は False（影響なし） |
| `set protocols bgp group <g> peer-as <peer>`（neighbor 無し）| BGP neighbor | group の peer_as 未設定 neighbor に `peer_as` を継承（末尾一括適用・個別 peer-as が優先）| peer_group フィールドは出力しない（golden 維持の非対称） |
| JunOS next_hop_self | BGP neighbor | **非対応（常に False・YAML 出力なし）**。JunOS は next-hop-self をポリシー（export policy）ベースで制御するため set 形式 config から直接抽出できない | |
| neighbor_ip が v6 アドレス | BGP neighbor | `af = "v6"`（neighbor_ip を v6 短縮形に正規化して格納） | |
| `set protocols ospf area <a> interface <if>` | OSPF network | `area = <正規化済み a>`, `network = <CIDR_or_IF_name>`, `af = "v4"` | IF の v4 サブネットから CIDR；不能なら IF 名 |
| `set protocols ospf3 area <a> interface <if>` | OSPF v3 | `area = <正規化済み a>`, `network = <IF_base_name>`, `af = "v6"`, `process = null` | ドット除去（unit 除去） |
| `… ospf[3] area <a> interface <if> metric <n>` | OSPF if param | `interfaces[].ospf.cost = int(n)` | 加算フィールド |
| `… ospf[3] area <a> interface <if> interface-type <t>` | OSPF if param | `interfaces[].ospf.network_type = <t>` | p2p 等 |
| `… ospf[3] area <a> interface <if> passive` | OSPF if param | `interfaces[].ospf.passive = true` | |
| `set protocols ospf area <a> stub` | OSPF area type | 同一 area・af="v4" の OspfNetwork に `area_type = "stub"` を設定（末尾一括適用） | |
| `set protocols ospf area <a> stub no-summaries` | OSPF area type | `area_type = "totally-stubby"` | JunOS は no-summaries |
| `set protocols ospf area <a> nssa` | OSPF area type | `area_type = "nssa"` | |
| `set protocols ospf area <a> nssa no-summaries` | OSPF area type | `area_type = "totally-nssa"` | |
| `set protocols ospf3 area <a> stub` | OSPF area type | af="v6" の OspfNetwork に `area_type = "stub"` | |
| `set protocols ospf3 area <a> stub no-summaries` | OSPF area type | `area_type = "totally-stubby"`（af="v6"） | |
| `set protocols ospf3 area <a> nssa` | OSPF area type | af="v6" の OspfNetwork に `area_type = "nssa"` | |
| `set protocols ospf3 area <a> nssa no-summaries` | OSPF area type | `area_type = "totally-nssa"`（af="v6"） | |
| `set routing-options static route <prefix> next-hop <ip>` | static | `prefix = <CIDR>`, `next_hop = <ip>`, `af = "v4"` | |
| `set routing-options rib inet6.0 static route <prefix> next-hop <ip>` | static | `prefix = <正規化済み CIDR>`, `next_hop = <v6 短縮形正規化済み>`, `af = "v6"` | ホストビット除去；無効 prefix は skip |

#### L2/L3 判定ルール（JunOS）

| 条件 | l2_l3 判定 |
|------|-----------|
| `family ethernet-switching` あり | `"l2"` |
| `family inet` または `family inet6` に **address 行あり** | `"l3"` |
| いずれもなし（family 宣言のみで address 行が無い場合を含む） | null |

**優先順**: `ethernet-switching` が `inet`/`inet6` より先に評価（L2 優先）。

#### admin_status 導出

- `disable` 行あり → `admin_status = "down"`
- `disable` 行なし → `admin_status = "up"`

#### switchport フィールド

**JunOS では常に null**（IOS 専用）。

### 6.3 共通規則

#### IP アドレス正規化

すべてのパーサが以下の正規化を実施すること（観測される出力表記の規定）：
- IPv4 アドレス: 先行ゼロを除去した標準ドット 10 進表記に正規化する。
- IPv6 アドレス: 短縮形（RFC 5952）に正規化する。
- CIDR: ホストビットを除去したネットワークアドレス表記に正規化する。

#### OSPF area 正規化

OSPF area は IOS では数値（`area 0`）、JunOS では dotted-decimal（`area 0.0.0.0`）で書かれることが多く、**両者は同一エリアを指す**。層別 YAML への出力時に以下のルールで**整数文字列へ正規化して統一する**：

| 入力 area 表記 | 正規化結果 | 説明 |
|---------------|-----------|------|
| 純数値（`"0"`, `"1"`, `"100"`） | そのまま（`"0"`, `"1"`, `"100"`） | 変換不要 |
| dotted-decimal `"a.b.c.d"`（各オクテット 0-255） | `str(a×2^24 + b×2^16 + c×2^8 + d)` | 例: `"0.0.0.0"`→`"0"`、`"0.0.0.1"`→`"1"`、`"0.0.1.0"`→`"256"`、`"1.2.3.4"`→`"16909060"` |
| 上記いずれでもない（例 `"backbone"`、不正値） | 原文のまま | クラッシュしない |

この正規化は `routing.ospf[].area` と、link/segment への `ospf_area` 注釈（§5.3.1、§7.4）の両方に適用される。

#### 複数値の収集

- **IOS ip address**: `ip address` コマンドが複数行ある場合、すべてを addresses に追加。
- **JunOS interfaces**: unit が複数ある場合、すべてのアドレスを収集（unit 集約）。

#### エラーハンドリング

- **パース失敗**: 個別行のパースエラーは握りつぶして警告ログを出力し、パイプラインは継続する（クラッシュしない）。
- **未知ベンダー**: 判定に失敗したファイルはスキップする（警告を出力）。
- **警告の可視化**: スキップ・警告は実行サマリー（§10.4）に集約し、利用者が結果の不完全性に気づけるようにする。

---

## 7. 結線推論・ルーティング解析要件

### 7.1 サブネット一致による結線推論

#### アルゴリズム

1. **IP 抽出**: 全インターフェースから `addresses`（IP アドレス群）を取得。`addresses` が空の場合は後方互換の `ip` フィールドにフォールバックする。IP を持たない IF はスキップ。
2. **ネットワーク算出**: 各アドレスの `{ip, prefix}` から所属ネットワーク CIDR を算出する。
3. **グルーピング**: ネットワーク CIDR ごとにインターフェースをグループ化。
4. **結線 / セグメント判定**:
   - **メンバー = 2**（異機器）→ `links` に 1 本（point-to-point）。`a_device` < `b_device` で辞書式安定化。
   - **メンバー ≥ 3** → `segments` に 1 ノード。`members` 配列（安定ソート）にすべての IF ID を登録。
   - **メンバー = 1** → スタブ（リンク化しない）。loopback（`/32`）や LAN 側 IF に該当。

#### 特別な考慮

| 状況 | 扱い |
|------|------|
| **同一機器内同一サブネット複数 IF** | メンバー数に含める。links では `a_device != b_device` ペアのみ採用（自己ループ回避） |
| **IP 重複（同一サブネット同一 IP）** | members に含める；警告は呼び出し側 log に委ねる（初版はクラッシュしない） |
| **shutdown IF** | 結線推論に含める（admin_down フラグで視覚的区別） |
| **link-local（fe80::/10）** | addresses には保持；結線推論から除外 |
| **同一 IF が同一ネットワークに複数アドレス** | members には IF ID を 1 回のみ登録（重複除去） |

#### マスク長の扱い

- `/30`, `/31` は典型的な P2P だが、判定は **メンバー数のみで統一**（マスク長に特別扱いなし）。
- `/32`（IPv4）/ `/128`（IPv6）は単独メンバーになり、スタブ扱い。

### 7.2 admin_down フラグの付与

**link に対する `admin_down` フラグ**:

- **片端 shutdown && 対向 up** → `admin_down = true`
- **両端 shutdown** → `admin_down = true`
- **両端 up** → `admin_down` フィールド省略（付与しない）。**`admin_down: false` という出力は行わない**（`true` か省略の二値）
- **segment には `admin_down` フラグを付与しない**（メンバー IF の shutdown 状態は詳細パネルで確認する）

**視覚効果**: `admin_down = true` リンクは HTML で破線・淡色表示。

**OSPF area 非付与**: `admin_down = true` のリンクには `ospf_area` / `ospf_network` を付けない（shutdown IF は OSPF 隣接を張れない）。

### 7.3 BGP 対向解決

#### ローカル IP 解決

1. 各 BGP neighbor の `neighbor_ip` を、全機器のすべてのインターフェース IP と突合。
2. 突合した IF が見つかれば、その機器の AS を参照。
3. `local_ip` = 「neighbor_ip と同一サブネットにある自機のインターフェース IP」を採用（無ければ null）。
4. **v6 neighbor に対しては v6 local_ip を返す**（af ファミリ一致）。

#### type 判定

| 条件 | type | 備考 |
|------|------|------|
| `local_as == peer_as` | `"ibgp"` | iBGP（内部） |
| `local_as != peer_as`（両者既知） | `"ebgp"` | eBGP（外部） |
| `peer_as` が null | `"unknown"` | 対向 AS 不明 |

#### 片側オーバーレイ

- 対向機器が config に存在しない外部 AS でも、BGP エントリは残す（外部隣接の可視化）。

### 7.4 OSPF area 注釈

#### link / segment への area 付与条件

- link / segment が対応する subnet について、OSPF network エントリが存在するか検索。
- 存在する場合、`ospf_area` / `ospf_network` を付与。
- `admin_down = true` のリンクには付与しない（§7.2）。

#### area 値の決定

各端点（メンバー）の area を §6.3 のルールで**正規化したうえで**集約する：

| メンバー OSPF area 構成 | ospf_area 値 |
|--------|-----------|
| 両端/全メンバー同一 area（正規化後） | 単一値（例: `"0"`, `"16909060"`） |
| 異なる area が混在（正規化後） | 昇順スラッシュ区切り（例: `"0/1"`）。全要素が数値文字列なら数値昇順、非数値が混在するなら辞書式昇順で連結 |

### 7.5 出力の決定性

**前提**: 同一入力 → 同一の層別 YAML → 同一 HTML。

- **すべてのリスト**（devices / interfaces / links / segments / routing.*）は決定的順序で出力。
- **乱数・時刻に依存しない**。テスト・diff・再現可能な eval がこの前提に依存。
- リスト要素の内部順序:
  - `devices`: device_id 昇順
  - `interfaces`: device の出現順（`generated_from` の処理順）× 各 device 内は **config 記述順**
  - `links`: `(a_device, a_if, b_device, b_if, subnet)` 昇順
  - `segments`: `id` 昇順
  - `routing.*`: device_id 昇順 → その他フィールド昇順

---

## 8. HTML 構成図機能要件

本章は**機能仕様と主要規則**を規定する。座標値・フォント・色値・力学パラメータ等の実装詳細は刷新側の裁量とする（見た目は既存実装と異なってよい）。ただし**決定性（§8.3）と本章の機能・操作仕様**は必須要件である。

### 8.1 出力形式と依存性

- **単一 HTML ファイル**: 外部 CSS / JavaScript / 画像なし。`file://` URL で直接開ける。
- **SVG ベース**: スケーラブルなベクトルグラフィックス。
- **バニラ JavaScript**: フレームワーク（jQuery/React 等）非使用。
- **決定的出力**: 同一の層別 YAML → 同一の HTML（§8.3、§9.1）。
- **運用アノテーションの永続化**: ポートの予約 / 使用不可 / 備考（§8.7.3）は**ブラウザ側ストレージに永続化**する（生成 HTML 自体は不変＝決定的。ストレージ不可環境ではセッション内のみ動作に縮退）。これは生成物の外部ファイル依存ではなく、決定性契約（§9.1）の対象外。

### 8.2 ビュー（タブ）

ビューはタブで切替可能。**図ビュー**（SVG トポロジー）と**表ビュー**（一覧表）の2系統からなる。

**図ビュー**:

| ビュー名 | 表示内容 | 生成条件 |
|---------|--------|---------|
| **Physical** | 物理層（devices + links + segments） | 常に生成 |
| **BGP** | AS グループ枠・BGP ピアリング・外部ピア | routing.bgp[] が存在時 |
| **OSPF** | OSPF area 色分け・area/network 注釈 | routing.ospf[] が存在時 |
| **汎用プロトコルビュー** | 物理トポロジー＋当該プロトコルのオーバーレイ | bgp / ospf / static **以外**の `routing.<proto>` キーが存在時に自動生成 |

**表ビュー**（§8.7 で詳細規定）:

| ビュー名 | 表示内容 | 生成条件 |
|---------|--------|---------|
| **ADDRESSES** | サブネット単位にグループ化したアドレス一覧（IPAM 風・使用率付き。1 行 = 1 IF の **IP 個別一覧**） | 常に生成 |
| **INTERFACES** | 機器単位にグループ化した IF 一覧（対向・種別・使用ポート集計） | 常に生成 |
| **SUBNETS** | v4 サブネット使用率の**集約**ビュー（D4）。1 行 = 1 サブネット（subnet / usable / used / free / util% / status）。使用率（util）降順 → subnet 昇順。util ≥ 80% は exhausted として強調。`/32`（ホスト/ループバック）と link-local は除外。ADDRESSES（IP 個別一覧）との差別化＝サブネット集約・枯渇監視。値は render 層で `DATA.subnet_usage` として導出（層別 YAML 外） | 常に生成 |
| **CHECKS** | 設計検証パネル。topology dict を走査して検出した設計上の注意点を severity / kind / message / refs でリスト表示。0 件のときは「問題は検出されませんでした」メッセージを表示。検出ルール: (1) duplicate_ip（error）同一ホスト IP が複数 IF に重複 / (2) duplicate_ospf_router_id（error）同一 ospf_router_id を 2 台以上の機器が持つ場合（None は無視、router-id ごとに 1 件） / (3) duplicate_bgp_router_id（error）同一 bgp_router_id を 2 台以上の機器が持つ場合（同様） / (4) mtu_mismatch（warning）同一リンク両端の MTU 不一致 / (5) bgp_unresolved_local_ip（warning）BGP の local_ip が未解決 / (6) static_dangling_next_hop（warning）static の next_hop がトポロジー内のどの IF サブネット・ホスト IP にも存在しない（静的チェック。デフォルトルートや 0.0.0.0/:: 等の特殊 next_hop、Null0 等の IF 名 next_hop はスキップ） / (7) ospf_area0_disconnected（warning）area 0 を持つ機器が存在する混在環境で、OSPF area を持つが area 0 を持たない機器（config 保有 area で近似・ABR は対象外・area0 不在環境では非発火） / (8) ibgp_fullmesh_incomplete（warning）RR 不在の AS 内 iBGP で full-mesh が崩れたピア対（neighbor_ip を IF ホスト IP で解決・解決不能を含むペアと RR 構成 AS はスキップ＝偽陽性抑制）。検出結果は severity→kind→refs の安定ソートで決定的 | 常に生成 |
| **DIFF** | トポロジー差分ビュー。`render_topology.py --diff-against <prev_dir>` 指定時のみ生成。前回（prev_dir）との差分を `diff_topology()` で計算し、devices / interfaces / links / segments / routing_bgp / routing_ospf / routing_static の固定順で added(+) / removed(-) / changed(~) を件数サマリと一覧表で表示。全体で差分0件のときは「差分なし」を明示。config 由来文字列は esc() でエスケープ。決定的（同一 (topo, prev) → 同一 HTML） | `--diff-against` 指定時のみ |

- **static はビューを生成しない**。static route の情報は Device Details パネル（§8.5）で表示する。
- CHECKS / SUBNETS の値は render 層で `DATA.checks` / `DATA.subnet_usage` として導出する**加算的拡張**であり、層別 YAML スキーマ（§4）には含めない。
- 図ビューは `routing` のキーから動的に決まり、新プロトコル層を追加すると自動的にビューが増える（static のみ除外）。表ビュー（ADDRESSES / INTERFACES / CHECKS / SUBNETS）は常設。DIFF ビューは `--diff-against` 指定時のみ表ビュー群の先頭（CHECKS の前）に追加される。
- タブ切替はクリックおよびキーボード `1`〜`N`（図ビュー＝若番、表ビュー＝続く番号）で行う。汎用プロトコルビューが増えると表ビュー（ADDRESSES / INTERFACES / CHECKS / SUBNETS 等）のキー番号は後ろにずれる（タブ並び順に連番）。
- **図ビュー専用のツールバー操作**（ズーム・凡例・ミニマップ・ノード種別フィルタ・表示ノード指定・エクスポート等）は、表ビュー表示中は隠す。検索ボックスとテーマ切替・タブは全ビュー共通で残す。
- 表ビュー表示中はキャンバス（図）を覆い、図のホバー/クリック処理は発火しない。

#### ノード配置のビュー間共通化（v2.0 必須）

- 複数の図ビューに登場する**同一機器のノードは、全図ビューで同一座標**に描画する。タブを切り替えても機器の位置が飛ばないこと。
- ビュー固有の追加ノード（BGP 外部ピア、セグメントノード等）は、共通配置を変更しない位置に**決定的に**配置する。

### 8.3 レイアウト（決定的）

- **自動レイアウト**: force-directed 相当のアルゴリズムでノードを自動配置する。方式・力学式・反復回数は実装裁量。
- **決定性の保証（必須）**: 乱数・時刻を一切使用しない。初期配置は機器 ID 昇順に基づく決定的配置を基本とし、以降の計算も決定的に進める。同一の層別 YAML → 同一の配置。
  - **AS クラスタリング初期配置**: 同一 AS に 2 台以上の機器が属する場合は、初期円周配置を AS 番号昇順 →（同一 AS 内）機器 ID 昇順の順に並べ、同一 AS の機器を隣接配置する（視認性向上）。これにより同一 AS 群が空間的にまとまる。2 台以上の AS グループが無い場合（AS 未設定・全 singleton）は従来の機器 ID 昇順配置に一致（no-op）。順序規則は完全に決定的。
- **重なり分離**: 機器ノード同士の重なりは自動分離する（分離処理も決定的）。BGP ビューの AS 枠同士の重なりも決定的に分離する。
- **外部ピアの配置**: config に対向が存在しない BGP neighbor（外部ピア）は、機器ノード群と重ならない領域に決定的に配置する。
- **キャンバスサイズの動的調整**: 機器数に応じて描画領域を拡大する（目安 150 台程度まで実用）。

#### 8.3.3 階層レイアウトモード（A3）

`render_topology.py --layout hierarchical` 指定時、force-directed に代えて**決定的な階層グリッド配置**を用いる（既定は `--layout force`＝従来の force-directed・§8.3 本文）。

- **列(x)**: 機器を AS でグループ化し、AS 番号昇順（未設定 AS は末尾）に列を割り当てる。segment・ext（外部ピア）はその後ろの専用列に置く。
- **段(y)**: 各列内を degree 降順 →（同値は）機器 ID 昇順に縦積みする（要所を上段に）。segment/ext 列は ID 昇順。
- **間隔**: 列間 240px・段間 120px（ノード矩形 148×56 と重ならない中心間距離）。
- **決定性（§9.1 維持）**: 乱数・時刻不使用。座標は round(.,1) で確定し、同一入力 → 同一配置。
- **不正な mode 値**は `ValueError`。既定省略時は force で従来の生成物と byte 完全一致（加算的拡張）。

#### 8.3.1 degree 連動ノードサイズ（A4）

接続数（degree: 隣接する相異なるデバイス数）の多い機器ほどノード矩形をやや大きく描画し、構成の要所（ハブ・コア機器）を視認しやすくする。

- **拡大のみ・縮小しない**: degree ≤ 1 の機器は基準サイズ（NODE_W=148, NODE_H=56）。degree > 1 で単調非減少に拡大。
- **上限あり**: CAP=6 を超える degree はサイズ頭打ち（最大 196×68 程度）。ラベル溢れと過剰な重なりを防ぐ。
- **座標は点ベースを維持**: layout.py による座標計算は変更しない。ノードサイズは視覚的目安であり、多少の重なりは許容する。
- **決定的**: degree 算出も nodeScale もノードサイズも乱数・時刻非依存。同一入力 → 同一 HTML（§9.1 維持）。
- **実装**: degree は `DATA.devices[id].degree`（render 層派生・YAML 非収録）。ノード描画は `nodeScale(d.degree||0)` が返す `{w, h}` を使用。ext ノード・AS 枠は基準サイズのまま（スコープは device ノードに限定）。**AS 枠の境界計算は NODE_W/NODE_H 固定値ベースのため、degree 拡大したハブ機器が AS 枠から多少はみ出す場合がある（許容範囲・座標の点ベース維持を優先）。**
- **layer YAML 非影響**: degree は render 層 DATA の派生値であり、層別 YAML スキーマ（§4）には含まれない。

#### 8.3.2 長いホスト名ラベルの省略表示（A5）

ノード幅に対して長いホスト名（例 `core-router-dc1-rack5-unit12`）は、ノード矩形からはみ出し視認性が低下する。

- **省略**: device ノード・ext ノードの hostname/label ラベルは、ノード幅 `w` に基づく概算最大文字数（`nodeLabelMaxChars(w)`）で省略し、末尾に「…」（U+2026）を付加する。副ラベル（ビュー別: 物理=vendor / OSPF=`rid <ospf_rid>` / BGP=`rid <bgp_rid>`）も同じ `maxChars` で省略する。外部ピアノードの主ラベルは neighbor IP。
- **full text ホバー表示**: 各ノード `<g>` の最初の子として `<title>${esc(hostname)}</title>` を追加する。ブラウザネイティブの SVG ツールチップで full hostname がホバー時に表示される。
- **省略は表示テキストのみ**: 検索 corpus・data-id・選択判定・クリック/ホバー判定等の内部ロジックは full 値のまま変更しない。検索が省略形に影響されないこと。
- **純関数・決定的**: `nodeLabelMaxChars(w)` と `truncateLabel(text, maxChars)` は DOM 非依存の純関数。同一入力 → 同一出力（§9.1 の決定性維持）。
- **実装式**: `nodeLabelMaxChars(w) = Math.max(1, Math.floor((w - 22) / 8))`（左16+右パディング ≈22px、14px bold で約8px/文字）。`truncateLabel(text, maxChars)` は `text.length <= maxChars` なら原文、超過なら先頭 `(maxChars-1)` 文字 + "…"。`maxChars<=0` は空文字を返す（`nodeLabelMaxChars` が常に1以上を返すため実用上未到達）。対象は ASCII のホスト名識別子を想定（slice は UTF-16 単位）。

### 8.4 要素の可視化

| 要素 | 可視化要件 |
|------|----------|
| **機器** | ノード（矩形等）+ hostname ラベル + 副ラベル（ビュー別: 物理=vendor / OSPF=`rid <ospf_router_id>` / BGP=`rid <bgp_router_id>`）。**BGP ビューは AS 番号を副ラベルに出さない**（AS の識別は §8.4 の AS 枠ラベル「AS xxx」と枠/ノードの色が担う）。**インターフェースチップは描画しない**（§8.4.1） |
| **リンク** | 実線。選択・ライン選択・ライン hover 時に**線端の IF 名 / IPv4 / IPv6（GUA＋link-local を淡色併記）を改行で縦積み**表示し、中央に subnet（dual-stack は v4・v6 を併記）を表示（§8.5）。subnet ラベルはエッジの**法線方向**に決定的オフセット（`edgeNormalOffset`）を加えて配置し、エッジの角度によらず線との重なりを避ける（A2） |
| **admin_down リンク** | 破線・淡色で区別 |
| **dual-stack リンク** | 線種は分けない（通常の1本線）。v6 は IF 端ラベル・subnet ラベルに v4 と同形式で併記する |
| **セグメント** | 中央ノード（楕円等）＋メンバー IF への放射状接続（spoke）。subnet ラベル。spoke にも IF 名 / IP ラベルを併記（選択・hover 時） |
| **OSPF area** | OSPF ビューで area ごとの色分けと area / network（subnet・dual-stack は v6 も）注釈 |
| **BGP セッション** | 種別（eBGP / iBGP）で**固定2色**に着色（ピア AS では着色しない。AS の識別は AS 枠の色が担う）。iBGP（loopback ピア）は破線等で区別。over-link（物理リンク上のセッション）は対応リンクと同じ端点で、loopback/external は対向ノードまで、それぞれ曲線等で描く |
| **BGP AS** | AS 番号付きグループ枠。AS 間ピアリング線。**外部ピア（config 非存在の対向）は機器と同じノード描画＋点線枠で区別**し、凡例も機器とは別項目にする。外部ピアノードの**主ラベルは neighbor IP**（AS 番号は枠ラベル・枠の色・ホバー `<title>` で識別）|
| **凡例** | 現在のビューで使用中の記号・色の凡例パネル（表示/非表示切替可）。色付き線・破線の凡例項目は**クリックで該当要素を強調**（再クリックで解除）できる。凡例項目は**データ駆動**で生成する: OSPF ビューは**実在する area** を数値昇順で列挙（ハードコードしない）、BGP ビューは**実在する AS** を数値昇順で列挙し AS 別一括強調（`as:<n>` 強調）を提供する。area/AS 強調はビュー切替時にリセットする |

#### 8.4.1 IF チップの廃止（v2.0）

旧実装の「機器ノード上にインターフェースを小円（チップ）で並べる」表現は**廃止する**。インターフェース情報の提示先は以下に集約する：

1. **Device Details パネル**の Interfaces 表（§8.5）
2. **リンクのホバー表示**（両端の機器名 / IF 名 / IP / subnet）
3. **選択モデル**による IF 情報表示（§8.5、複数選択時）

これに伴い、旧実装の「BGP セッション ⇄ IF チップ」のハイライト連動は「BGP セッション ⇄ リンク・対向ノード」のハイライト連動（§8.5）に置き換える。

### 8.5 インタラクティブ機能（図ビュー）

#### ズーム・パン

- **マウスホイール**: ズームイン / ズームアウト（カーソル位置中心）。
- **キャンバス空白部のドラッグ**: パン（移動）。
- **ツールバー**: zoom in / zoom out / reset / fit（全体表示）ボタン。
- **キーボードショートカット**:
  - `F` = 全体表示（fit）
  - `Esc` = 表示リセット（zoom=1, pan=0,0）＋選択・ライン選択・凡例強調の全解除＋ショートカット一覧オーバーレイを閉じる
  - `1`〜`N` = ビュー（タブ）切替
  - `/` または **`Ctrl+F`（`⌘F`）** = 検索ボックスへフォーカス（既存テキストは全選択。ブラウザ既定のページ内検索は抑止）
  - `G` = 接続先のみ表示 / `H` = フォーカス / `M` = ミニマップ / `L` = 凡例（B5・図ビュー専用。表ビュー中は無効。各トグルボタンと同等）
  - `?` = ショートカット一覧オーバーレイの表示/非表示（背景クリックまたは `Esc` で閉じる。`?` は US 配列の Shift+/ 前提）
  - いずれも検索/入力欄フォーカス中は発火しない（入力欄ガード）

#### ノード選択・hover（v2.1 確定）

- **クリック＝選択トグル**: ノードをクリックすると選択に追加、同じノードを再クリックで解除（修飾キー不要・複数選択可）。**ノード上のダブルクリックによる個別解除は廃止**。ただしセグメントの楕円はノード選択ではなく「ライン選択」として扱う（下記）。
- **キャンバス空白部のダブルクリック**: 全解除（選択・ライン選択・凡例強調をすべてクリア。`Esc` でも全解除）。
- **hover はハイライトのみ**: ノードにカーソルを乗せると、選択時と同じ強調を**プレビュー**表示する（仮選択）。ただし**複数選択モードの判定は確定選択のみ**で行い、hover で表示が増えることはあっても減らない。
- **単一選択時**: 選択ノードと接続リンクを強調し、リンク端に IF 名 / IPv4 / IPv6 ラベルを表示する。
- **複数選択時**: 選択ノード同士を結ぶリンク（および同一セグメント上の経路）を強調し、その両端 IF ラベルを表示する。
- **選択マーカーは描かない**: 選択状態はノード枠の色（§8.6）のみで示す（旧 ● マーカーは廃止）。

#### ライン選択（図 ⇄ 表 連動）（v2.1 確定）

- **リンク / セグメント spoke / セグメント楕円のクリック＝「ライン選択」**: 当該 subnet を選択状態（subnet 単位のライン選択）にする。**dual-stack は v4/v6 を同一ラインとして扱う**（v6 側の操作・行でも対の v4 が連動）。
- **BGP セッション線のクリック＝「セッション選択」**（BGP セッション単位のライン選択）。BGP ビューでは over-link 物理リンクのクリックも対応する BGP セッション選択に流す。
- ライン選択時は**端点ノードを自動選択**する。自動選択分は手動選択と区別して追跡し、ライン選択を解除しても手動選択ノードは巻き込まない。非表示ノード（§表示ノード指定）は自動選択に含めない。
- **図 ⇄ 表の双方向ハイライト連動**: ライン選択は、Device Details パネルの該当 IF 行 / OSPF Networks 行 / BGP Sessions 行 / 選択リンクカードと相互に強調連動する。現在のビューで線として描画されない subnet の表行は連動クリック対象にしない。

#### ライン hover（v2.1 確定）

- リンク / セグメント spoke / BGP セッション線にカーソルを乗せると、**線自体をノード hover と同色（選択色）で強調**し、線端の IF / IP ラベルを表示する。
- **hover 時の説明ツールチップ（フローティング）は表示しない**（IF/IP ラベルで情報提示は足りるため、重複する説明表示は廃止）。

#### ノードドラッグ（v2.0 新設）

- 機器ノードをマウスドラッグで移動できる。**接続リンクは必ず追従**する。グループ枠（AS 枠等）・注釈の追従は近似でよい。
- 移動は**ブラウザセッション内のみ**有効。リロードすると決定的初期配置（§8.3）に戻る（永続化しない）。
- ドラッグとクリック（選択）は区別する（一定距離以上の移動でドラッグと判定。ドラッグ終端の click は選択しない）。

#### 検索

- **検索対象フィールド（確定列挙）**: hostname / 全 IP アドレス（v4・v6、secondary・link-local 含む）/ description / AS 番号 / vendor / IF 名 / 接続サブネット（net）。
- **自由文字列検索**: 上記フィールドを横断して部分一致（大文字小文字無視）。マッチノードを強調、不一致は淡色化（削除・非表示にしない）。
- **フィールド指定検索**: 2通りを提供し**いずれも機能する**:
  1. テキストの演算子記法 `host:` / `ip:` / `desc:` / `as:` / `vendor:` / `net:`（例 `as:65001`）。
  2. 検索ボックス横の**ドロップダウン**で対象フィールドを選択（記法を書かずに絞り込み）。テキスト記法を書いた場合はそちらを優先。
- **0 件警告**: ヒット 0 件のとき検索ボックスを警告色にする（演算子の値が未入力の間は警告しない）。
- **次マッチ移動**: `Enter` で次のマッチへ移動（図ビューは該当ノードへパン。非表示ノードは巡回スキップ）。
- 表ビューでは同じ検索が**行フィルタ**として働き、件数は表示行数で表示する（§8.7）。

#### フィルタ・表示制御

- **ノード種別フィルタ**: セグメント / 外部ピアの表示 ON/OFF（機器の一括 ON/OFF・選択反転・プロトコル重畳トグルは提供しない）。
- **表示ノード指定パネル**: 機器 / セグメント / 外部ピアを**個別に**表示/非表示指定できる。非表示ノードは選択・自動選択・AS 枠計算からも除外する。
- **「接続先のみ」フィルタ**: 選択ノードと、それに現在のビューで接続するノードのみを表示する絞り込み。
- **隣接フォーカスモード**: 「フォーカス」ボタンで ON/OFF をトグルする（既定 OFF、図ビュー専用）。ON かつノード選択中のとき、選択ノードから N-hop（既定 1-hop）以内に到達できるサブグラフ以外のノード・ラインを**淡色化（dim）**する（非表示にはしない＝文脈を残す）。「接続先のみ」フィルタが非隣接を**非表示**にするのと対比し、フォーカスモードは**淡色化**で差別化する。adjacency() のビュー対応（physical/bgp/ospf）がそのまま適用されるため、ビュー切替と組み合わせ可能。

#### BGP 連動ハイライト

- **Device Details パネルの BGP Sessions 行** と、図上の**対応 BGP セッション線・対向ノード**を双方向に強調連動する。
- 対応の解決: `local_ip` / `neighbor_ip` が乗る物理リンク（over-link）、または loopback 間ピアリング（iBGP 等）。対向が外部ピアの場合は外部ピアノードを連動対象とする。
- **アドレス・IF ラベルの表示条件**: ライン hover、またはライン/セッション選択中の一致セッション、または端点ノードの確定選択時（複数選択時は両端が選択されたセッションのみ）。端点を共有するだけの無関係セッションは表示しない。
- **対象 AF**: v4 および v6 GUA。link-local は対象外。

#### Device Details パネル

- 機器/セグメント/外部ピアの選択で表示。複数選択時は先頭に「選択リンク」一覧（選択ノード間リンク・セグメントの両端 IF 情報）を表示。
- 機器カード:
  - ヘッダ: hostname / vendor / AS 番号 / **router-id バッジ（OSPF・BGP は機器内で同一のため `rid` として1つに統合**。設定時のみ）
  - **Interfaces** 表: Name / IPv4 / IPv6（GUA＋link-local を淡色併記）/ Description / Status
  - **BGP Sessions** 表: neighbor / peer_as / type / **af** / **src**（update-source/local-address 由来の local_ip ソース。未設定は `—`）/ **attr**（`RR`=route-reflector-client・`NHS`=next-hop-self のバッジ。未設定は `—`）
  - **OSPF Networks** 表: network / area
  - **Static Routes** 表: prefix / next_hop
  - **REDISTRIBUTE** 表: into（bgp/ospf）/ source / metric / route-map（device に redistribute がある場合のみ表示。IOS のみ・未設定の metric/route-map は `—`）
  - **Sections**: `devices[].sections` の汎用表示（初版は常に空）
- パネルは**幅をドラッグでリサイズ**、および**最小化**できる。

#### テーマ・補助表示・エクスポート

- **ライト / ダークテーマ**: ツールバーで切替可能。
- **ミニマップ**: 全体俯瞰と現在のビューポート枠（表示/非表示切替可）。
- **SVG / PNG エクスポート**: 現在の図の表示状態（ドラッグ後の配置・ハイライト込み）を SVG / PNG で保存（外部依存なし。PNG は高解像度で書き出す）。

#### URL ハッシュによるビュー・選択状態の保存/復元（B3）

- 現在の**ビュー（タブ）と選択ノード id の集合**を URL ハッシュ（`location.hash`）に自動的にエンコードして保存する。
  - フォーマット: `#v=<view>&n=<id1>,<id2>,...`（例 `#v=bgp&n=r1,r2`）。選択なしのときは `n=` を付けない（例 `#v=physical`）。
  - ノード id は `encodeURIComponent` でエンコードする（`:` や `/` を含む id に対応）。
  - sel（選択ノード）は昇順ソートして決定的なハッシュ文字列を生成する。
- URL をコピーして共有・ブックマークすると、開いた側で同じビューと選択状態が復元される。
  - `applyStateFromHash()` が boot 時（初期描画の前）に呼ばれ、ハッシュ中の view が有効なビュー名（`VIEWS` に含まれる）なら適用、sel の各 id が実在ノード（devices/segments/extPeers）であれば選択状態に復元する（不正 id は無視）。
  - 更新は `history.replaceState` で行い、履歴スタックを汚染しない。
- **生成 HTML には焼き込まない**: ハッシュはブラウザ実行時にクライアント側で読み書きされるものであり、生成 HTML ファイル自体には含まれない。同一入力 → 同一バイトの決定性を維持する。
- 対象は **view + sel** のみ。ズーム・パン・フォーカスモード等の他状態は対象外（将来拡張余地）。

### 8.6 色規則（決定的）

- **AS 色**: 固定パレットを `asn % パレット数` で循環割当する。
- **OSPF area 色**: 固定パレットを循環割当する。複合 area（例 `"0/1"`）は**先頭の area** で決色する。数値 area は整数値、非数値 area は決定的なハッシュ（文字コード和等）でパレットインデックスを決める。
- **BGP セッション色**: eBGP / iBGP の**種別ごとに固定色**（ピア AS では着色しない）。
- **状態色の意味づけ**（インタラクションの色は役割で区別する。具体的色値は実装裁量だが互いに区別できること）:
  - **選択 / ノード hover / ライン hover** … 同一の「選択色」（1 色）。hover は選択のプレビューであり選択と同系色で示す。
  - **ライン選択（図 ⇄ 表 連動）** … 選択色とは別の「連動色」。
  - 検索ヒット、admin_down、予約 / 使用不可（§8.7）等もそれぞれ区別可能な色で示す。
- パレットの色数・色値は実装裁量。ただし**同一入力 → 同一配色**（決定的）であること。

### 8.7 表ビュー（ADDRESSES / INTERFACES）（v2.1 確定）

両表に共通する基盤:
- **検索連動**: §8.5 の検索（自由文字列・フィールド演算子・ドロップダウン）を**行フィルタ**として適用し、件数は表示行数で出す。
- **列ソート**: 列ヘッダクリックで昇順 → 降順 → 解除の 3 状態。空値（未設定）は昇順・降順いずれでも末尾固定。アドレス列は数値順、IF 名列は自然順（`Gi0/2 < Gi0/10`）。
- **グループ折りたたみ**: グループ見出しクリックで折りたたみ、「全展開 / 全折りたたみ」ボタンも提供。
- **TSV コピー**: 表示中（フィルタ・ソート適用後・折りたたみ中の行も含む）を TSV でクリップボードへコピー（Excel 台帳貼り付け用）。
- **整合性の強調**: 重複 IP（複数機器に同一アドレス）・リンク両端の MTU / 速度不一致（速度は表記ゆれを正規化して比較）を警告色で強調し、説明を補助表示する。description 未設定セルも区別色で示す。

#### 8.7.1 ADDRESSES（サブネット管理）

- **1 行 = 1 IF**（IPv4 / IPv6 を併記）。列: Device / Interface / IPv4 / IPv6 / Description / Status。**v6 link-local（fe80::）は除外**（結線推論除外〔§7.1〕と同様、IPAM ノイズ・重複 IP 誤検出を避けるため）。
- **サブネット単位にグループ化**（IPAM 風）。グループ見出しに subnet（dual-stack は v4・v6 を 1 行に統合）と**使用率**を表示。使用率＝使用アドレス数 / 収容数で、収容数は v4 prefix から算出する（`/31`＝2、`/32`＝1、それ以外＝`2^(32−prefix)−2`）。v6-only・推論外グループは使用アドレス数（IF 数）のみ表示。使用率は**検索フィルタに依存せず全グループメンバーから算出**する（フィルタで行が減っても分母・使用数は不変）。グループ順は v4 ネットワークアドレス昇順 → v6-only → サブネット推論外（loopback 等）で決定的。
- **所属サブネットの導出**: 結線推論（links/segments 由来）を優先し、無ければ当該 IF の prefix 長から導出する（対外スタブ /30 等も管理対象に載せる）。/32（host route）は推論外グループへ。

#### 8.7.2 INTERFACES（IF 一覧・ポート管理）

- **機器単位にグループ化**。グループ見出しに**物理ポートの使用ポート集計**（状態別: 使用 / 予約 / 使用不可 / 空き）と**ラインカード別内訳**を表示する。ラインカードは IF 名のスロット表記（例 `GigabitEthernet1/0/x` → カード `GigabitEthernet1/0`）から決定し、仮想 IF（loopback / SVI 等）は物理ポート集計から除外する。
- 行の列: Interface / Connected to / IPv4 / IPv6（GUA＋link-local を淡色併記）/ Description / Status（種別バッジ付）/ MTU / Speed / 指定 / 備考。
- **対向情報（Connected to）**: リンクは対向機器・IF、セグメントはメンバー一覧、外部 BGP は対向 AS を表示。リンク対向はクリックで**対向 IF 行へジャンプ**（折りたたみ中なら展開してスクロール＋一時強調）。
- **IF 種別**: 接続（結線あり）/ スタブ（IP ありだが対向なし）/ **未使用（IPv4 / IPv6 いずれのアドレスも description も無し）** / loopback。種別フィルタチップ（ALL / 接続 / スタブ / 未使用 / 予約 / 使用不可 / down）で絞り込む。

#### 8.7.3 運用アノテーション（予約 / 使用不可 / 備考）（v2.1 確定）

- INTERFACES のポートに対し、**予約 / 使用不可**の運用状態と、**備考（メモ）**を**手動で指定**できる（予約理由などの記入用）。
- これらは**config 由来データではなく運用アノテーション**であり、**config・層別 YAML・決定的 HTML 出力とは分離**して保持する（ブラウザ側に永続化。図・層別 YAML の決定性〔§9.1〕には影響しない）。
- 使用ポート集計（§8.7.2）は予約 / 使用不可を状態カテゴリに反映する。

---

## 9. 振る舞い上の制約

### 9.1 決定性（必須）

**要件**: 同一の config 入力群 → 同一の層別 YAML → 同一の HTML 出力。

**制約**:
- ファイル処理順序を記録・再現する（`generated_from`）。
- すべてのリスト出力を決定的順序（ID 昇順等）でソートする。
- **乱数・時刻に一切依存しない**（レイアウトの初期配置も決定的：機器 ID 昇順を基本とし、同一 AS に 2 台以上あれば AS 昇順→ID 昇順のクラスタリング配置。§8.3）。
- テスト・diff・再現可能な eval がこの前提に依存する。

**決定性の適用範囲**: 決定性は**成果物（層別 YAML・HTML）の内容**に適用する。以下は対象外：
- history 退避ディレクトリ名（実行時刻ベース。§10.3）
- 実行サマリー等の stderr 出力（§10.4）
- ブラウザ上の操作（ノードドラッグ・選択等）による表示状態

### 9.2 機密情報の扱い

- **出力に含まれるテキスト**: 
  - `interface description` 等の自由記述はそのまま層別 YAML・HTML に出力される。
  - `password` / `secret` / `snmp community` 等のキーワード行はパースしない（これらの行自体を読み込まない）。
  - **description フィールドはサニタイズしない**（機密情報や個人情報の混入を排除しない設計）。
  - `generated_from` はファイル名（basename）のみ記録する（§1.4）。
  
- **生成物の取り扱い責任**:
  - エンドユーザー（管理者）が生成物を共有・保存する前に、機密情報の漏洩を確認する責任を持つ。
  - 本システムはこれを強制しない（config をそのまま反映する設計）。

### 9.3 拡張性

| 拡張ポイント | 拡張方法 | スキーマ影響 |
|------------|--------|-----------|
| **新ベンダー追加** | パーサ実装 + registry 登録（正規化モデル統一） | なし |
| **新プロトコル（VRRP 等）** | `routing.<proto>.yaml` 層追加 | なし（加算）。ビューも自動生成（§8.2） |
| **機器固有情報** | `devices[].sections` に append | なし（加算） |
| **新結線由来（LLDP 等）** | `links[].kind` に新値 | なし（加算） |

---

## 10. 運用・CLI 要件

### 10.1 コマンド構成

パイプラインの各層に対応する 3 つの CLI と、独立した差分ツール（パイプライン外）の計 4 つの CLI を提供する：

| コマンド | 役割 | 引数 |
|---------|------|------|
| `parse_configs.py` | 正規化 Device リストの JSON 出力（デバッグ・ベンダー判定確認用） | `[paths...]` |
| `build_topology.py` | パース＋推論を実行し層別 YAML を生成 | `[paths...] [-o DIR]` |
| `render_topology.py` | 層別 YAML から HTML を生成 | `<topology_dir> [-o FILE] [--diff-against PREV_DIR] [--diff-against-history] [--layout {force,hierarchical}]` |
| `diff_topology.py` | 2 つの層別 YAML を比較し差分レポート（Markdown）を生成（§10.4・パイプライン外の独立ツール） | `<old_dir> <new_dir> [-o FILE]` |

**共通の入力解決**（parse / build）:
- `paths` はファイル・ディレクトリ・glob パターンを受け付ける。ディレクトリは `*.cfg *.conf *.txt` を名前順で走査。重複パスは 1 回のみ処理。
- `paths` 省略時は `./workspace/` を走査する（§2.2）。

**デフォルト値**:
- `build_topology.py -o` の既定値: `topology`（カレント配下 `./topology/`）。
- `render_topology.py -o` 省略時: `./topology.html`（カレント直下。§1.2・§3.1 の出力②と一致させる）。
- `render_topology.py --diff-against` 省略時: DIFF ビューなし（従来通り・加算的拡張）。指定時は `load_topology(PREV_DIR)` で前回トポロジーを読み、`diff_topology(prev, topo)` を計算して HTML に DIFF タブを追加する。PREV_DIR の読込失敗（OSError / ValueError / yaml.YAMLError）は終了コード 1。
- `render_topology.py --diff-against-history`: 直近 history スナップショットとの差分を自動表示する（§10.6）。
- `render_topology.py --layout`: `force`（既定・従来の force-directed）/ `hierarchical`（AS 列グリッド・§8.3.3）。省略時は force で従来の生成物と byte 一致。

### 10.2 終了コード・出力規約

| 事象 | 終了コード | 出力 |
|------|----------|------|
| 正常終了 | 0 | 成果物パスを明示出力（例: `Generated: ./topology.html`） |
| 入出力エラー（出力先に書けない等） | 1 | エラー内容を stderr |
| 参照整合エラー（render 時の層別 YAML 検証違反） | 1 | ファイル名・フィールド・値を含むエラーを stderr（§5.6） |
| 個別行のパース失敗・未知ベンダースキップ | **0（継続）** | `[WARN]` を stderr に出力し処理継続（§6.3） |

- 警告・進捗（`[INFO]` / `[WARN]`）は **stderr** に出力する。
- `parse_configs.py` の JSON は **stdout** に出力する（パイプ処理可能）。
- `render_topology.py` の正常終了時、成果物パスに続けて「生成物には config 由来の自由記述（description 等）がそのまま含まれるため、共有前に内容を確認すること」という趣旨の注意行を stderr に出力する（§9.2 の利用者責任を促すトリガー）。
- 参照整合エラー（§5.6）のメッセージは、利用者がエラー中の**ファイル名・フィールド・値**を手掛かりに該当 YAML を自力修正できることを意図している（正しい参照先 ID は `devices.yaml` の `id` / `interfaces[].id` を確認する）。

### 10.3 history 退避（v2.0 新設・自動化）

再生成時に過去の成果物を自動退避する：

- **build_topology.py**: 出力先ディレクトリ（既定 `./topology/`）に既存の層別 YAML があるとき、生成前にそれを `./history/<YYYY-MM-DD_HHMM>/topology/` へ移動する。既定パス運用時、`./topology.html` が存在すればそれも同じ退避ディレクトリへ一緒に移動する（成果物ペアの整合維持）。
- **render_topology.py**: 出力先 HTML が既存のとき、生成前に `./history/<YYYY-MM-DD_HHMM>/` へ移動する。
- タイムスタンプは**実行時のローカル時刻**。同名の退避ディレクトリが既に存在する場合は `_2`, `_3`… の連番サフィックスで衝突回避する。
- 退避を行った場合は、退避先パスを stderr に出力する。
- 決定性不変条件（§9.1）は成果物の内容に適用され、退避ディレクトリ名は対象外。

### 10.4 diff CLI（diff_topology.py）

2 つの層別 YAML ディレクトリを比較し、Markdown 差分レポートを出力する独立ツール。
既存パイプライン（parse / build / render）に変更を加えない加算的拡張。

| 項目 | 仕様 |
|------|------|
| 入力 | `old_dir`, `new_dir`（層別 YAML ディレクトリ。`load_topology` で読込・参照整合検証付き） |
| 出力 | Markdown レポート（stdout または `-o FILE`） |
| 終了コード | 常に 0（差分あり/なし問わず。エラー時のみ 1） |
| 決定性 | 時刻・乱数に依存しない。同一入力→同一レポート（§9.1 決定性不変条件と同様） |

**セクション別比較**:

| セクション | 自然キー | changed 比較フィールド |
|---|---|---|
| `devices` | `id` | `hostname`, `vendor`, `as`, `ospf_router_id`, `bgp_router_id` |
| `interfaces` | `id` | `description`, `shutdown`, `mtu`, `speed`, `addresses`, `ospf` |
| `links` | `(subnet, a_device, a_if, b_device, b_if)` | added/removed のみ |
| `segments` | `id` | `members`（集合比較） |
| `routing_bgp` | `(device, neighbor_ip, af)` | `peer_as`, `type`, `local_ip`, `update_source`, `route_reflector_client`, `next_hop_self`, `timers`, `send_community`, `peer_group` |
| `routing_ospf` | `(device, network, af)` | `process`, `area`, `area_type` |
| `routing_static` | `(device, prefix, af)` | `next_hop` |

diff dict のセクションキーはアンダースコア区切り（`routing_bgp`/`routing_ospf`/`routing_static`）。自然キーは一意前提（重複時は先勝ち）。

差分ゼロ時は「差分なし」を明示。全リストはキー昇順ソートで決定的。

### 10.5 実行サマリー（v2.0 新設）

`build_topology.py` は処理完了時、以下のサマリーを stderr に出力する：

1. **入力ファイルごとの判定結果**: ファイル名と判定ベンダー（`cisco_ios` / `juniper_junos` / `skipped (unknown vendor)`）。
2. **警告件数**: パース警告の総数（0 でない場合は代表例を併記）。
3. **生成数**: devices / interfaces / links / segments / 各 routing.* のエントリ数。
4. **注意喚起**: スキップまたは警告が 1 件以上ある場合、サマリー末尾に「結果が不完全な可能性がある」旨の注意行を出力する。

目的: 未知ベンダーのサイレントスキップや多数の警告に利用者が気づき、生成結果の信頼性を判断できるようにする。

### 10.6 render_topology.py --diff-against-history（D3c）

直近 history スナップショットとの差分を自動表示するオプション。パスを手動指定する `--diff-against` を補完する利便性フラグ。

**フラグ**: `--diff-against-history`（store_true・省略可）

**解決順（優先度）**:
1. `--diff-against <dir>` が明示されている場合は **そちらを優先**（`--diff-against-history` は無視）。
2. `--diff-against` が未指定かつ `--diff-against-history` が指定されている場合:
   - `lib/history.latest_history_topology()` を呼び、直近 history の層別 YAML inner ディレクトリを取得する。
   - 見つかれば `--diff-against <inner_dir>` を指定した場合と同等の DIFF 描画を行う。
   - 見つからなければ `[INFO] 比較対象の history が見つかりません（差分なしで描画）` を stderr に出力し、差分なし（従来通り）で描画する。終了コードは 0（正常）。

**`latest_history_topology()` の選択ルール**:
- `history/` 直下の各 `<ts>` サブディレクトリを**名前の降順**（lexical sort）で走査する。タイムスタンプ文字列は ISO 風（`YYYY-MM-DD_HHMM`）のため、新しいものが辞書順で大きい。衝突連番（`_2`/`_3` 等）は base の後にソートされ、最新の衝突が選ばれる。
- 各 `<ts>/` の直下サブディレクトリに `_meta.yaml` を持つものがあれば、その inner ディレクトリの Path を返す。
- `render_only` 退避（`topology.html` のみ、`_meta.yaml` なし）はスキップする。
- `history/` 不在・空・層別 YAML を含む history が無い場合は `None` を返す。
- **決定性**: ファイルシステム状態が同一であれば常に同一の inner dir を返す（§9.1 の範囲内）。なお history 退避ディレクトリ名のタイムスタンプ自体は実行時刻依存（§9.1 の既存例外）。

**prev の load_topology 失敗時**: `--diff-against` 指定時と同じ例外処理（OSError / ValueError / yaml.YAMLError）を行い、終了コード 1。

---

## 11. 受け入れ基準・テスト要件

### 11.1 ゴールデン受け入れ（必須）

- **附録 B のサンプル config 2 件**を `build_topology.py` に入力した出力が、**附録 B の期待層別 YAML と完全一致（バイト一致）**すること。
- この期待出力（ゴールデン）は本書 §2〜§7 の規定のみから導出可能であり、刷新実装のリポジトリにテストフィクスチャとして収載すること。
- **注意**: 旧実装のゴールデン（`dev/examples/topology/`）は古いスキーマ（`addresses` 欠落）のため**期待出力として使用しないこと**。

### 11.2 テスト階層

pytest マーカーで階層を分離する：

| マーカー | 対象 | 例 |
|---------|------|-----|
| `unit` | 単一関数・クラス | ベンダー判定閾値、IP/area 正規化、ID 採番、L2/L3 判定、結線推論の境界（メンバー 1/2/3） |
| `integration` | CLI・ファイル I/O | CLI 引数解決、層別 YAML の書込/読込往復、参照整合エラー（dangling 参照で ValueError）、history 退避、実行サマリー |
| `e2e` | パイプライン全体 | サンプル config → 層別 YAML → HTML 生成まで通し実行 |

### 11.3 決定性テスト（必須）

- 同一入力で 2 回実行し、層別 YAML 全ファイルと HTML が**バイト一致**することを確認するテストを設けること。

### 11.4 カバレッジ

- テストカバレッジ **80% 以上**を目標とする。

### 11.5 E2E 機能確認項目（ブラウザ目視）

生成 HTML をブラウザで開き、以下を確認すること：

- [ ] 図/表のタブ切替で共通機器ノードの座標が変わらず、表ビュー時は図専用ツールバーが隠れる（§8.2）
- [ ] 機器ノード上に IF チップ・選択 ● マーカーが描画されていない（§8.4.1 / §8.5）
- [ ] ノードドラッグでリンク・枠が追従し、リロードで初期配置に戻る（§8.5）
- [ ] クリックで選択トグル（再クリック解除・複数可）、空白ダブルクリック / Esc で全解除。ノード上ダブルクリックでの個別解除は無い（§8.5）
- [ ] ノード hover で選択と同じ強調がプレビューされ、ライン hover で線が選択色で強調される。hover 時に説明ツールチップは出ない（§8.5）
- [ ] リンク/セグメント/BGP 線のクリックで端点ノードが自動選択され、図 ⇄ 詳細パネル該当行が双方向ハイライトする（dual-stack は v4/v6 連動）（§8.5）
- [ ] リンク端に IF 名 / IPv4 / IPv6 が縦積み表示される（§8.4 / §8.5）
- [ ] 検索: 自由文字列・演算子（`as:` 等）・ドロップダウン・`/`/`Ctrl+F` フォーカス・0 件警告色・Enter 次マッチが機能する（§8.5）
- [ ] 表示ノード指定パネル・「接続先のみ」・ノード種別フィルタが機能する（機器一括/選択反転/重畳トグルは無い）（§8.5）
- [ ] BGP セッション行 ⇄ セッション線/対向ノードの双方向ハイライト、外部ピアが点線枠ノードで表示される（§8.4 / §8.5）
- [ ] admin_down リンクが破線・淡色で表示される（shutdown を含む config で確認）（§8.4）
- [ ] ライト/ダークテーマ・ミニマップ・凡例クリック強調・SVG/PNG エクスポート・ズーム/パン/fit・キーボードショートカットが機能する（§8.5）
- [ ] ADDRESSES: サブネットグループ化・使用率・折りたたみ・重複 IP 強調・列ソート・TSV コピーが機能する（§8.7.1）
- [ ] INTERFACES: 機器グループ化・使用ポート集計（ラインカード別・状態別）・対向ジャンプ・未使用 IF 可視化・種別フィルタ・予約/使用不可/備考の指定と再読込後の保持が機能する（§8.7.2 / §8.7.3）
- [ ] 100 台規模の合成 config（テスト用に機械生成してよい）でも、初期表示・ズーム/パン・検索が実用的な応答性で動作し、ノードラベルが判読可能（§8.3 の「150 台目安」の実効性確認。定量基準は運用で調整）

---

## 附録 A: 用語定義

| 用語 | 定義 |
|------|------|
| **中間表現** | 層別 YAML（ベンダー中立・人手編集可・参照整合検証済み） |
| **正規化モデル** | パーサが出力するベンダー中立なデータ表現。IOS/JunOS の構文差異を吸収し、以降のパイプラインはこのモデルのみを参照する |
| **admin_down** | shutdown IF による非稼働リンク。視覚的に破線・淡色表示 |
| **addresses** | IF の IP アドレス群（dual-stack 正本）。複数アドレス・IPv4/IPv6 共存に対応 |
| **link** | 2 機器が同一サブネットで接続（point-to-point） |
| **segment** | 3 つ以上の IF が同一サブネットで接続（L2 セグメント相当） |
| **スタブ** | 単独 IF のサブネット（結線なし。loopback など） |
| **eBGP / iBGP** | BGP ピアリング種別。`local_as != peer_as` → eBGP / `==` → iBGP |
| **OSPF area** | OSPF 管理領域。正規化済み文字列（§6.3）で保持し、link/segment に area 注釈を付与 |
| **外部ピア** | config に対向機器が存在しない BGP neighbor。BGP ビューに片側オーバーレイとして描画 |
| **ビュー / オーバーレイ** | ビュー＝タブで切り替える表示単位。オーバーレイ＝物理トポロジーに重ねるルーティング情報の表示層 |
| **選択** | クリックによるノードのマーク状態。ハイライトと詳細パネル表示の起点（§8.5） |
| **力指向（force-directed）レイアウト** | ノード間の引力・斥力をシミュレートして配置する方式。乱数を用いず、決定的初期配置（機器 ID 昇順を基本、同一 AS が 2 台以上なら AS クラスタリング配置。§8.3）により再現可能 |

---

## 附録 B: サンプル config と期待出力（ゴールデン）

受け入れ基準 §11.1 で用いる入力と期待出力。期待出力は本書 §2〜§7 の規定から導出されたものである。

### B.1 入力 1: `sample-ios-r1.cfg`（Cisco IOS）

```
!
! Cisco IOS / IOS-XE running-config (sample)
!
hostname R1
!
interface GigabitEthernet0/0
 description to-R2
 ip address 10.0.0.1 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description LAN
 ip address 192.168.1.1 255.255.255.0
!
interface Loopback0
 ip address 1.1.1.1 255.255.255.255
!
router bgp 65001
 neighbor 10.0.0.2 remote-as 65002
!
router ospf 1
 network 192.168.1.0 0.0.0.255 area 0
!
ip route 0.0.0.0 0.0.0.0 10.0.0.2
!
end
```

### B.2 入力 2: `sample-junos-r2.conf`（Juniper JunOS set 形式）

```
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
```

### B.3 期待出力（層別 YAML、入力順: B.1 → B.2）

#### `_meta.yaml`

```yaml
generated_from:
- sample-ios-r1.cfg
- sample-junos-r2.conf
schema_version: '1.0'
title: Network Topology (config-derived)
```

#### `devices.yaml`

```yaml
devices:
- as: 65001
  bgp_router_id: null
  hostname: R1
  id: r1
  ospf_router_id: null
  sections: []
  vendor: cisco_ios
- as: 65002
  bgp_router_id: null
  hostname: R2
  id: r2
  ospf_router_id: null
  sections: []
  vendor: juniper_junos
interfaces:
- addresses:
  - af: v4
    ip: 10.0.0.1
    prefix: 30
  admin_status: up
  description: to-R2
  device: r1
  duplex: null
  encapsulation: null
  id: r1::GigabitEthernet0/0
  ip: 10.0.0.1/30
  l2_l3: l3
  mtu: null
  name: GigabitEthernet0/0
  oper_status: null
  shutdown: false
  source: parsed
  speed: null
  switchport: null
  vlan: null
- addresses:
  - af: v4
    ip: 192.168.1.1
    prefix: 24
  admin_status: up
  description: LAN
  device: r1
  duplex: null
  encapsulation: null
  id: r1::GigabitEthernet0/1
  ip: 192.168.1.1/24
  l2_l3: l3
  mtu: null
  name: GigabitEthernet0/1
  oper_status: null
  shutdown: false
  source: parsed
  speed: null
  switchport: null
  vlan: null
- addresses:
  - af: v4
    ip: 1.1.1.1
    prefix: 32
  admin_status: up
  description: null
  device: r1
  duplex: null
  encapsulation: null
  id: r1::Loopback0
  ip: 1.1.1.1/32
  l2_l3: l3
  mtu: null
  name: Loopback0
  oper_status: null
  shutdown: false
  source: parsed
  speed: null
  switchport: null
  vlan: null
- addresses:
  - af: v4
    ip: 10.0.0.2
    prefix: 30
  admin_status: up
  description: to-R1
  device: r2
  duplex: null
  encapsulation: null
  id: r2::ge-0/0/0
  ip: 10.0.0.2/30
  l2_l3: l3
  mtu: null
  name: ge-0/0/0
  oper_status: null
  shutdown: false
  source: parsed
  speed: null
  switchport: null
  vlan: null
- addresses:
  - af: v4
    ip: 192.168.2.1
    prefix: 24
  admin_status: up
  description: LAN2
  device: r2
  duplex: null
  encapsulation: null
  id: r2::ge-0/0/1
  ip: 192.168.2.1/24
  l2_l3: l3
  mtu: null
  name: ge-0/0/1
  oper_status: null
  shutdown: false
  source: parsed
  speed: null
  switchport: null
  vlan: null
- addresses:
  - af: v4
    ip: 2.2.2.2
    prefix: 32
  admin_status: up
  description: null
  device: r2
  duplex: null
  encapsulation: null
  id: r2::lo0
  ip: 2.2.2.2/32
  l2_l3: l3
  mtu: null
  name: lo0
  oper_status: null
  shutdown: false
  source: parsed
  speed: null
  switchport: null
  vlan: null
```

#### `physical.yaml`

```yaml
links:
- a_device: r1
  a_if: GigabitEthernet0/0
  b_device: r2
  b_if: ge-0/0/0
  kind: inferred-subnet
  subnet: 10.0.0.0/30
segments: []
```

#### `routing.bgp.yaml`

```yaml
bgp:
- af: v4
  device: r1
  local_as: 65001
  local_ip: 10.0.0.1
  neighbor_ip: 10.0.0.2
  peer_as: 65002
  type: ebgp
- af: v4
  device: r2
  local_as: 65002
  local_ip: 10.0.0.2
  neighbor_ip: 10.0.0.1
  peer_as: 65001
  type: ebgp
```

#### `routing.ospf.yaml`

```yaml
ospf:
- af: v4
  area: '0'
  device: r1
  network: 192.168.1.0/24
  process: 1
```

#### `routing.static.yaml`

```yaml
static:
- af: v4
  device: r1
  next_hop: 10.0.0.2
  prefix: 0.0.0.0/0
- af: v4
  device: r2
  next_hop: 10.0.0.1
  prefix: 0.0.0.0/0
```

### B.4 期待される図の読み取り（参考）

- R1 (AS 65001) と R2 (AS 65002) が `10.0.0.0/30` の point-to-point リンクで接続。
- `192.168.1.0/24`・`192.168.2.0/24`・loopback `/32` はメンバー 1 のスタブ（リンク・セグメントなし）。
- BGP ビューに eBGP ピアリング（65001 ⇄ 65002）が双方向エントリで表示される。
- OSPF は R1 のみ（area "0"、192.168.1.0/24）。リンク 10.0.0.0/30 は OSPF 非参加のため `ospf_area` 注釈なし。

---

**本要件定義書の版履歴**

| 版 | 日付 | 変更内容 |
|---|--------|--------|
| 1.0 | 2026-06-12 | 初版 |
| 2.0 | 2026-06-13 | OSPF area 正規化の誤記修正（整数文字列化を明記）／generated_from の basename 記録を明記／L3/Static ビューを削除（static は詳細パネル表示のみ）／§8 を機能仕様レベルで全面改訂（IF チップ廃止・ビュー間配置共通化・ノードドラッグ・選択モデルを新設、ミニマップ・各種フィルタ・キーボード操作・詳細パネル仕様を明文化）／§10 運用・CLI 要件（CLI 契約・history 退避自動化・実行サマリー）新設／§11 受け入れ基準・テスト要件新設／附録 B（サンプル config と期待出力）追加 |
| 2.1 | 2026-06-13 | §8 をインタラクティブ仕様確定後の挙動に合わせ全面改訂。表ビュー（ADDRESSES / INTERFACES）と §8.7 を新設／選択トグル・hover プレビュー・ライン選択（図⇄表連動・端点自動選択）・ライン hover（選択色・ツールチップ廃止）・選択 ● マーカー廃止／検索（演算子＋フィールド ドロップダウン＋`Ctrl+F`＋0 件警告色）／表示ノード指定パネル・外部ピアのノード化・BGP 種別2色・dual-stack 同一ライン連動・SVG/PNG エクスポート／運用アノテーション（予約・使用不可・備考）を §8.7.3 に新設。確定挙動の正は `docs/design-sample.html` |
