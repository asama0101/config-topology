# config-topology シナリオ集（examples/）

`config-topology` スキルの機能を実証する独立シナリオ集。各シナリオは別々の機器群の config から、3層パイプライン（`build_topology.py` → `render_topology.py`）で**層別 YAML** と**自己完結 HTML** を生成したもの。`<scenario>/topology.html` をブラウザで開くと構成図と各ビューを確認できる。

> 生成はパーサ実機対応強化（#1-#10）を含むブランチ `parser-realworld-hardening` 上で実施。STATIC discard/reject・VRF・入力診断などはそのブランチの機能に依存する。ソースコード（`lib/` 等）は一切変更していない。

## 各シナリオフォルダの構成
```
<scenario>/
  configs/      入力 config（IOS .cfg / JunOS .conf）
  topology/     build 出力（層別 YAML 正本 + raw_config.yaml）
  topology.html render 出力（SVG + vanilla JS の自己完結 HTML）
```

## シナリオ一覧

| # | シナリオ | 実証内容 | 主なビュー / CHECKS |
|---|---------|---------|-------------------|
| 01 | **core-mixed** | IOS+JunOS 混在 4 台。OSPF area 0 ＋ iBGP/eBGP、loopback、3 台同一サブネットの **segment**、**dual-stack**(v4+v6 リンク) | PHYSICAL / OSPF / BGP / CONFIG / CHECKS |
| 02 | **static-forwarding** | static 経路の全形態: 通常 next-hop / exit-interface(IF形) / IF+NH 併記(IP優先) / **Null0・discard・reject**(blackhole) / AD・name 付き / **qualified-next-hop**(ECMP) | **STATIC**（経路トレース・blackhole 表現） |
| 03 | **vrf** | IOS `address-family vrf`/`ip vrf forwarding`/`ip route vrf`、JunOS `routing-instances`。**同一 IP を別 VRF** に置き duplicate_ip が**誤発火しない**ことを実証 | PHYSICAL / BGP / STATIC / CHECKS（duplicate_ip 無し） |
| 04 | **diagnostics** | 入力形式の問題検知。JunOS **波括弧形式**(`junos_brace_format`)・**apply-groups 多用**(`junos_apply_groups_unexpanded`)・**asdot ASN**(`1.0`→65536)・OSPF `interface all` 展開 | CHECKS（診断 2 種）／`diagnostics.yaml` |
| 05 | **ospf-multiarea** | 4 area（0/1/2/3）、area type **stub/nssa/totally-stubby**、passive・cost・network-type。1 リンクで area 不一致 → **`ospf_area_mismatch`** | OSPF / CHECKS |
| 06 | **bgp-rr-peergroup** | **route-reflector(RR) 正常構成**。R1=RR・R2/R3/R4=RRC。peer-group 継承・update-source loopback・send-community・timers。BGP ビューで **RR=金リング＋"RR"バッジ / RRC=中空リング＋"RRC"バッジ / RR→client の reflects-to 矢印** を表示（RR があるため `ibgp_fullmesh_incomplete` は出ない＝正常） | BGP（RR/RRC 可視化）/ CHECKS |
| 07 | **datacenter-scale** | 10 台・3 AS（spine/leaf/core）。**force** と **hierarchical** の 2 種 HTML で AS クラスタリング・degree 連動ノードサイズを実証 | PHYSICAL / BGP（`topology.html` ＋ `topology-hierarchical.html`） |
| 08 | **diff-before-after** | 変更前後 2 スナップショット。新規リンク・dual-stack 化・BGP/OSPF 変更を `--diff-against` で差分表示 → **DIFF** タブ | DIFF（追加/変更マーカー） |

## 再生成コマンド
プロジェクトルートから `python3` で実行（`SKILL=.claude/skills/config-topology`）。
```bash
# 標準（01〜06）
python3 $SKILL/scripts/build_topology.py  examples/<scenario>/configs  -o examples/<scenario>/topology
python3 $SKILL/scripts/render_topology.py examples/<scenario>/topology -o examples/<scenario>/topology.html

# 07 は hierarchical も
python3 $SKILL/scripts/render_topology.py examples/07-datacenter-scale/topology --layout hierarchical \
  -o examples/07-datacenter-scale/topology-hierarchical.html

# 08 は prev を先に build し、--diff-against で render
python3 $SKILL/scripts/build_topology.py  examples/08-diff-before-after/configs-prev -o examples/08-diff-before-after/prev_topology
python3 $SKILL/scripts/build_topology.py  examples/08-diff-before-after/configs      -o examples/08-diff-before-after/topology
python3 $SKILL/scripts/render_topology.py examples/08-diff-before-after/topology \
  --diff-against examples/08-diff-before-after/prev_topology -o examples/08-diff-before-after/topology.html
```
出力先が空ディレクトリなら history 退避は発生しない。層別 YAML・HTML の出力は決定的（同一入力→同一出力）。
