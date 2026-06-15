# 継続改善ループ ログ (improvement-loop-20260613)

30分間隔の自動ループ。各サイクル: 立案 → TDD実装 → ゴールデン再生成（必要時）→ run-reviewers → doc更新 → 1コミット。

## 不変条件（厳守）
- 決定性: 乱数・時刻非依存。同一入力→同一YAML→同一HTML。
- 加算的拡張: 既存フィールドの意味/型を変えない。新規はキー/フィールド追加で吸収。変える時のみ `_meta.yaml` schema_version をバンプ。
- 参照整合: `topology_io.load_topology` の検証を通す。
- 依存は PyYAML のみ（pure Python, safe_load/safe_dump）。python3。

## 運用方針（QA確定 2026-06-13）
- スコープ: 自律判断。原則は既存(BGP/OSPF/render)の深掘り、基盤が揃えば新領域へ。
- 順序: 自律判断。提案順を基本に、触るファイルが衝突しない順で交互に。
- 品質ゲート: **TDD必須＋毎回 run-reviewers**。
- ブランチ: improvement-loop-20260613、各サイクル1コミット。

## バックログ（優先度順・適宜更新）

### A. レイアウト視認性
- [x] A1 AS でのノードクラスタリング（layout.py 初期円周配置を AS グループ順に）— M ✅反復5完了
- [ ] A1b area でのノードクラスタリング（device 単位 area 集約が必要・cluster_order 拡張）— M
- [x] A2 リンクラベル重なり回避（決定的法線オフセット）— M ✅反復15完了
- [x] A4 ノードサイズの degree 連動（拡大のみ・上限・決定的）— S ✅反復11完了
- [x] A5 長いホスト名ラベルの省略表示（truncateLabel＋<title> full）— S ✅反復17完了
- [x] A3 階層/直交レイアウトモード切替 — L（A1後）✅反復21完了

### B. UI操作性
- [x] B1 隣接フォーカスモード（選択ノードの N hop 隣接以外を淡色化）— S ✅反復6完了
- [ ] B2 表ビューの列フィルタ/絞り込みチップ（vendor/area/AS）— M
- [x] B3 URLハッシュ状態の保存/復元（ビュー＋選択ノードを #v=&n= にエンコード）— M ✅反復10完了
- [x] B4 データ駆動凡例（実在 OSPF area / BGP AS の一括強調・ハードコード撤廃）— S ✅反復14完了
- [x] B5 キーボードショートカット拡充（g/h/m/l/?・図ビュー専用＋ヘルプ overlay）— S ✅反復24完了

### C. BGP/OSPF 設定管理（parse→build→schema→render の加算フィールド）
- [x] C1 BGP update-source 抽出 → local_ip 解決フォールバック — M ✅反復4完了（peer-group は C1b に分割・未着手）
- [x] C1b BGP peer-group のメンバー継承（remote-as/update-source をグループから継承）— M ✅反復20完了
- [x] C2 OSPF interface cost / passive / network-type（interfaces[].ospf 加算）— M ✅反復2完了
- [x] C3 OSPF area type (stub/nssa/totally)（routing.ospf[].area_type）— M ✅反復7完了
- [x] C4 BGP route-reflector-client / next-hop-self（routing.bgp[].rr/nhs）— M ✅反復9完了
- [x] C4b BGP timers / community（routing.bgp[].timers/send_community）— M ✅反復19完了
- [x] C5 redistribute 抽出（新 routing.redistribute 層・IOS）— L ✅反復13完了

### D. 業務支援機能
- [x] D1 構成統計ダッシュボード（機器/IF/AS別/area別/リンク種別/dual-stack率/BGP/OSPF集計の新ビュー）— M ✅反復1完了
- [x] D2 設計検証警告の集約パネル（重複IP・MTU不一致・未解決BGP local_ip・dangling next_hop）— M ✅反復3完了
- [x] D2b 設計検証ルール拡張（OSPF/BGP router-id 重複検出）— S ✅反復18完了
- [x] D3 トポロジー差分レポート（コア: lib/diff.py + scripts/diff_topology.py）— M ✅反復8完了（HTML表示は D3b に分割）
- [x] D3b 差分の HTML 表示（render --diff-against で DIFF ビュー）— M ✅反復12完了
- [x] D3c history 自動連携（--diff-against-history で直近 history との差分を自動ビュー化）— S ✅反復16完了
- [x] D2c 設計検証ルール拡張（OSPF area0 非接続・iBGP full-mesh 欠落）— M ✅反復22完了
- [x] D4 IPアドレス計画/サブネット使用率ビュー（SUBNETS 集約ビュー）— M ✅反復23完了（ユーザー承認で見送り撤回）

## 推奨順序
D1 → B1 → C2 → A1 → C1 → D2 → B2 → C3 → C4 → A2 → D3 → 残り

## 進捗

### 反復1: D1 構成統計ダッシュボード — ✅完了（2026-06-13）
- `build_stats(topo, links=None, bgp_edges=None)` を data_transform.py に新設、`build_data()` に `DATA.stats` 加算。
- tabs.py に常設 STATS タブ、assets.py に `renderStatsView()`＋CSS。
- 12項目集計（機器/IF/links/segments/by_vendor/by_as/by_area/link_kinds/dualstack_ifs/bgp_sessions/ospf_networks/static_routes）。
- レビュー対応: by_as/by_area を数値ソート（Python・JS両側）、build_links 二重呼び出し解消、bgp_sessions=重複排除済みセッション数（golden=1）、stub 実値検証（golden=4）。
- doc: requirements.md §8.2 / SKILL.md / .claude/CLAUDE.md に STATS を反映。
- テスト 257 passed（+28）。render層のみ・層別YAMLゴールデン不変。
- 見送り(LOW・既存事象): esc() のシングルクォート未対応、norm_ospf_area フォールスルー、tbl のモジュール化、_BODY 静的nav、pytestmark分割。

### 反復2: C2 OSPF interface パラメータ抽出 — ✅完了（2026-06-14）
- Interface に `ospf: Optional[dict]`（cost/network_type/passive）追加。None/空dict は to_dict・build で省略（golden byte 不変）。
- IOS: `ip ospf cost`/`ip ospf network`/`passive-interface <if>` 抽出。JunOS: metric/interface-type/passive（ospf/ospf3）。
- build 透過・data_transform._build_if 公開・assets.py INTERFACES 表に OSPF バッジ表示。
- レビュー対応: バッジ title の二重エスケープ修正、`_ensure_ospf`→base.ensure_ospf に DRY 集約、空dict防御（`if self.ospf:`）、passive-interface default ネガティブテスト、junos 正規表現 `(.*)?$`→`(.*)$`。
- doc: requirements.md §5.2 出力規約に interfaces[].ospf を条件付き省略の例外として加筆＋§6.1/§6.2 マッピング行、schema.md 整形、vendor-parsing.md・.claude/CLAUDE.md にフィールド/マッピング反映。
- テスト 287 passed（+30）。golden byte 不変・render 決定性維持。
- 非対応（明記済み）: `passive-interface default`・`no passive-interface`。
- 見送り(LOW): `_build_if` private import、IOS/JunOS 拡張パス非対称(YAGNI)、pytestmark分割。

### 反復3: D2 設計検証パネル（CHECKS ビュー）— ✅完了（2026-06-14）
- `build_checks(topo, links=None)` を data_transform.py に新設、`build_data` に `DATA.checks` 加算。4ルール: duplicate_ip(error)/mtu_mismatch/bgp_unresolved_local_ip/static_dangling_next_hop(warning)。severity→kind→refs 安定ソート。
- 新規 CHECKS 表ビュー（tabs.py / assets.py renderChecksView）。0件時は肯定メッセージ。
- レビュー対応: link-local 偽陽性除外（duplicate_ip・static_dangling、最重要）、mtu_mismatch を build_links 統合済みリンク基準にして dual-stack 重複解消、bgp local_ip キー欠如ガード、template `_json` の `</script>` エスケープ（XSS ハードニング）、`_SPECIAL_NH` モジュール定数化、テスト堅牢化（ソート3段検証・重複テスト除去）。
- doc: schema.md DATA.checks ルール表、requirements.md §8.2（「到達不可」→正確表現）、SKILL.md、.claude/CLAUDE.md render層索引に build_checks/renderChecksView 反映。
- テスト 336 passed（+48）。golden byte 不変・render 決定性維持。
- 見送り(LOW): duplicate_ip refs の list→set 微最適化、型ヒント（build_stats と様式統一で無し）。

### 反復4: C1 BGP update-source 抽出＋local_ip 解決フォールバック — ✅完了（2026-06-14）
- BgpNeighbor に update_source 追加（IOS=update-source IF名 / JunOS=local-address IP、omit-when-None）。
- build._resolve_local_ip にフォールバック: サブネット一致 None 時、IP直指定(AF一致・link-local除外) or IF名解決(config順・v6 link-local除外)。サブネット一致成功時は挙動不変。
- iBGP over loopback の local_ip 解決 → D2 の bgp_unresolved_local_ip 警告が消える相乗効果。render の BGP SESSIONS 表に src 列。
- レビュー対応: IP直指定ブランチの link-local 除外、YAMLラウンドトリップテスト、v6/AF-ipv6配下のupdate-sourceテスト、src列render テスト、孤立 pending ドロップを意図的と docstring 明記。
- doc: schema.md/vendor-parsing.md/requirements.md §6・§8.5/link-inference.md §2 を同期。
- テスト 366 passed（+30）。golden byte 不変・render 決定性維持。
- 見送り(LOW): pending dict命名非対称、フィールドdocstringスタイル、型ヒント具体化。

### 反復5: A1 AS ノードクラスタリング初期配置 — ✅完了（2026-06-14）
- layout.py に `cluster_order()` 追加。初期円周配置を AS 昇順→同一AS内 id 昇順に並べ同一 AS を隣接配置。force 本体は無変更。
- 発動ガード: 2台以上の AS グループがある時のみ発動。AS 未設定・全 singleton・1台は現行 ID 昇順に厳密 no-op（既存テスト・golden 不変）。
- `_initial_circle` は `_initial_circle_ordered(sorted())` のラッパーに一本化（DRY）。AS ソートは `(asn is None, asn)` タプルキーで型安全・数値昇順。
- レビュー対応(ブロッカー含む): 近接テストが stub で確実にREDになるよう fixture を sorted≠cluster＋links無しに作り直し実証、AS型ロバスト性、docstring修正、A1b 拡張コメント。
- doc: requirements.md §8.3/§9.1/用語集の「機器 ID 昇順」を AS クラスタリング反映に更新、CLAUDE.md 索引に cluster_order。
- テスト 366→385 passed（+19）。golden byte 不変・render 決定性維持。観点A(視認性)に初進出。

### 反復6: B1 隣接フォーカスモード — ✅完了（2026-06-14）
- assets.py に純関数 `nHopNeighbors(adj, seeds, hops)`（BFS・DOM非依存）、`S.focusMode/focusHops`、`#btn-focus`、applyVisibility の dim 統合を追加。観点B(操作性)に初進出。
- 選択ノードの N-hop 隣接サブグラフ以外を淡色化（dim）。connectedOnly(非表示)と差別化。既定OFF・図ビュー専用(gonly)・ビュー対応(adjacency 経由)。
- テスト: node 実行で nHopNeighbors の BFS を実検証（壊すと赤になることを実証）。
- レビュー対応: 弱いテスト3件を厳密集合一致に強化(A1教訓)、gonly検証、focusActive で二重ガード集約、focusHops コメント、title文言、import整理。
- doc: SKILL.md・requirements.md §8.5・CLAUDE.md 索引を同期。
- テスト 385→398 passed（+13）。golden byte 不変・render 決定性維持。

### 反復7: C3 OSPF area type (stub/nssa/totally) — ✅完了（2026-06-14）
- OspfNetwork に area_type（"stub"/"totally-stubby"/"nssa"/"totally-nssa"、omit-when-None）追加。IOS `area <a> stub|nssa [no-summary]` / JunOS `protocols ospf[3] area <a> stub|nssa [no-summaries]` を area→type map で収集し末尾適用。build 透過・render で `area N (stub)` 表示。
- レビュー対応(実バグ2件): 正規表現を語境界化(`stub-default-metric`等の誤マッチ防止)、IOS area_types を (process,area) キー化＋v4スコープ化(マルチプロセス汚染・v6漏れ防止)。JunOS 型アノテ修正。ospf3/順不同/後勝ち/非汚染テスト追加。
- doc: schema.md・vendor-parsing.md・requirements.md §6.1/§6.2 を同期（IOS v4スコープ・ospf3 totally系反映）。
- テスト 398→435 passed（+37）。golden byte 不変・render 決定性維持。

### 反復8: D3 トポロジー差分レポート（コア）— ✅完了（2026-06-14）
- 新規 `lib/diff.py`（純粋 diff エンジン `diff_topology`/`format_diff_report`）＋ `scripts/diff_topology.py`（決定的 Markdown レポート CLI、4本目）。既存コード無変更・パイプライン外の独立ツール。
- 7セクション（devices/interfaces/links/segments/routing_bgp/ospf/static）の added/removed/changed。時刻・乱数非依存で本文決定的。
- レビュー対応: CLI の YAMLError 捕捉、_diff_devices 死蔵コード除去＋first-wins ヘルパ DRY、addresses 順序 false-positive 排除、重複キー決定化、意図的スキップの docstring＋ネガティブテスト、弱アサーション強化、機密注意 WARN。
- doc: SKILL.md・schema.md・requirements.md §10.1/§10.4・CLAUDE.md（開発コマンド/独立ツール注記）を同期。
- テスト 435→512 passed（+77）。golden/既存 e2e 無影響。
- 注: D4(サブネット使用率)は既存 ADDRESSES 表(IPAM風・使用率付き)と重複するため見送り、高価値・重複なしの D3 を優先した。

### 反復9: C4 BGP route-reflector-client / next-hop-self — ✅完了（2026-06-14）
- BgpNeighbor に route_reflector_client/next_hop_self（bool, omit-when-False）追加。IOS per-neighbor（pending_rr/pending_nhs で順不同）、JunOS は group cluster→rr_client（next_hop_self はポリシーベースで非対応）。build 透過・render に RR/NHS バッジ（attr 列）。
- レビュー対応: pending 引数を必須化、**lib/diff.py の COMPARE に rr/nhs 追加（D3 差分ツールが RR/NHS 変更を検出）**、nhs の AF配下テスト・attr 列テスト追加、コメント整備。
- doc: schema.md・vendor-parsing.md（モデル表含む）・requirements.md §6.1/§8.5/§10.4 を同期。
- テスト 512→551 passed（+39）。golden byte 不変・render 決定性維持。test レビュアーが「誤適用検出テストは今回有効」と確認（A1/B1/C3 の弱テスト教訓が定着）。

### 反復10: B3 URLハッシュ状態保存/復元 — ✅完了（2026-06-14）
- assets.py に純関数 `encodeState(view, selIds)`/`decodeState(hashStr)`（`#v=&n=` 形式・selIds 昇順・encodeURIComponent）＋ boot 連携 `applyStateFromHash`（VIEWS/実在ノード検証・view 固有クリーンアップ）/`syncHashToState`（history.replaceState・同値抑止）。共有可能なビュー（観点B）。
- 生成 HTML にハッシュを焼かず実行時のみ＝決定性維持。B2(列フィルタ)は既存 vendor:/as: 検索と重複のため見送り、重複なしの B3 を選択。
- テスト: encode/decode を node 実行で検証（ラウンドトリップ・特殊文字・不正入力・ソート・プロトタイプ汚染・上限）。壊すと赤を実証。
- レビュー対応: Object.create(null) でプロト汚染防御、view 固有クリーンアップ、決定性テストの空振り修正、sel 上限ガード、テスト補強。
- doc: SKILL.md・requirements.md §8.5・CLAUDE.md 索引を同期。
- テスト 551→575 passed（+24）。golden byte 不変・render 決定性維持。

### 反復11: A4 degree 連動ノードサイズ — ✅完了（2026-06-14）
- data_transform に `_compute_degrees(topo)`（物理接続数=隣接相異なるデバイス数・set 重複排除・dual-stack 1計上）→ DATA.devices[id].degree（Python 強TDD）。
- assets に純関数 `nodeScale(degree)`（degree≤1 基準148×56・拡大のみ・CAP6・STEP_W8/H2・最大196×68）。device ノードを per-node サイズ化。ext/AS枠・layout は据え置き。
- レビュー対応: JSDoc 式修正、hybrid(link+segment) degree テスト、CAP マジックナンバーコメント、単調性テスト精度。AS枠はみ出し許容を §8.3.1 明記。
- doc: schema.md（DATA.devices[].degree）・requirements.md §8.3.1・CLAUDE.md 索引を同期。
- テスト 575→594 passed（+19）。golden byte 不変・render 決定性維持。correctness/test 承認。

### 反復12: D3b 差分の HTML 表示（DIFF ビュー）— ✅完了（2026-06-14）
- `render_html(topo, diff=None)`＋`build_tabs(routing, has_diff=False)`＋`const DIFF` 埋め込み＋`render_topology.py --diff-against <prev_dir>`（load_topology→diff_topology→render）＋`renderDiffView`。テスト済み D3 diff エンジン再利用。既存 render_html(topo) 後方互換。
- 条件付き DIFF 表ビュー（STATS/CHECKS と同機構）。7セクション固定順で added/removed/changed・0件は「差分なし」・esc 済み。
- レビュー対応: renderDiffView の XSS を node 実行で実証、テーブルヘッダ整合、links ラベルの Python/JS 統一、ゼロ/非ゼロ差分 CLI テスト、本体 topo load の YAMLError 対称化。
- doc: SKILL.md・requirements.md §8.2/§10.1・CLAUDE.md・tabs docstring を同期。
- テスト 594→634 passed（+40）。golden byte 不変・render 決定性維持。correctness/security 承認。

### 反復13: C5 redistribute 抽出（routing.redistribute 層）— ✅完了（2026-06-14）
- Redistribute dataclass（into/source/metric?/route_map?）＋Device.redistribute。IOS `redistribute <source> [metric][route-map][subnets]` を bgp/ospf 文脈で抽出（into=文脈・source=先頭トークン・付加引数無視・no redistribute スキップ）。JunOS 非対応。
- 新 routing.redistribute 層: build_redistribute＋topology_io の proto を `_ROUTING_PROTOS` 定数化（dump/load）。非空時のみ routing.redistribute.yaml 生成→golden byte 不変。参照整合は汎用走査で対応。
- 詳細パネルに REDISTRIBUTE 表（into/source/metric/route-map）。data_transform で DATA.devices[].redistribute 公開。
- レビュー対応: **画面表示の実装漏れ修正（最重要・データのみ→REDISTRIBUTE表追加）**、proto 定数化、docstring、AF配下/順序テスト、no ガード厳密化。
- doc: schema.md・vendor-parsing.md（モデル表含む）・requirements.md §6.1/§8.5・ファイルレイアウトを同期。
- テスト 634→717 passed（+83）。golden byte 不変・render 決定性維持。correctness 承認。

### 反復14: B4 データ駆動凡例 — ✅完了（2026-06-14）
- 純関数 `presentAreas(data)`（links非admin_down+segments の area・複合"0/1"分割・数値昇順・重複排除）/ `presentASes(data)`（devices+extPeers の as・null除外・数値昇順）を node 実検証。
- renderLegend を**データ駆動化**: OSPF の area:0/area:1 ハードコード撤廃→実在 area を列挙、BGP に AS 別 clk("as:N") を追加。applyVisibility に `as:` 一括強調分岐＋update でビュー切替リセット。
- レビュー対応: seglink as: 分岐の簡潔化（segment は AS 無し・BGP で非描画＝非到達コメント）、legend ハードコード撤廃テスト強化（area0/area1両方）、presentAreas と by_area の集計元差異コメント。
- doc: requirements.md §8.4 凡例・CLAUDE.md 索引を同期。
- テスト 717→738 passed（+21）。golden byte 不変・render 決定性維持。correctness 機能バグなし。

### 反復15: A2 リンクラベル法線オフセット — ✅完了（2026-06-14）
- 純関数 `edgeNormalOffset(ax,ay,bx,by,dist)`（方向ベクトルを左90°回転した単位法線×dist・小数1桁丸め・退化 a==b で{0,0}）を node 実検証（直交性=内積≈0で接線誤実装を確実に検出）。
- subnet ラベルを中点固定 `my+7`（エッジ角度依存で線上に乗る）→ 法線オフセット（LABEL_NORMAL_OFFSET=10）に置換。どの角度でも線から外れて可読性向上。IF ラベル/area バッジはスコープ外。
- レビュー: correctness 完全承認（直交性・退化・決定性・表示条件不変）。LABEL_NORMAL_OFFSET コメント・CLAUDE.md 索引・test docstring の行番号除去を対応。
- doc: requirements.md §8.4・CLAUDE.md を同期。
- テスト 738→749 passed（+11）。golden byte 不変・render 決定性維持。

### 反復16: D3c history 自動連携 — ✅完了（2026-06-14）
- lib/history.py に `latest_history_topology(history_root)`（history/<ts>/ を**連番数値対応の降順ソート**で走査し直下に _meta.yaml を持つ inner dir を返す・無ければ None。Python 強TDD）。
- render_topology.py に `--diff-against-history`（--diff-against 優先・無ければ直近 history を自動選択し diff・無ければ INFO＋diffなし）。D3b の diff 表示を再利用。
- レビュー対応: 連番 `_10`>`_9` の数値ソート修正（lexical 崩れ）、--diff-against 優先テストの識別力強化（内容で区別）、history-diff を実差分化、非ゼロ差分の決定性・_meta.yaml無しサブディレクトリ スキップ補強。
- doc: SKILL.md・requirements.md §10.1/§10.6（§10.5 誤参照修正）・CLAUDE.md を同期。
- テスト 749→771 passed（+22）。golden byte 不変・render 決定性維持。未指定時は従来挙動完全不変。

### 反復17: A5 長いホスト名ラベルの省略表示 — ✅完了（2026-06-14）
- 純関数 `truncateLabel(text, maxChars)`（≤maxChars はそのまま・超過は (maxChars-1)+"…"・境界/空/null 安全）/ `nodeLabelMaxChars(w)`（`max(1, floor((w-22)/8))`）を node 実検証。
- device/ext ノードの hostname/sub をノード幅基準で省略表示し、ノード `<g>` 最初の子に `<title>full</title>`（full hostname/label）でホバー表示。省略は表示のみ（検索 corpus/data-id は full 値・非影響をテストで担保）。
- レビュー対応: truncateLabel コメント整合（maxChars≤0 は ""・ASCII 注記）、maxChars=0 返り値検証、検索非影響テスト、extMaxc ループ外移動。correctness 承認。
- doc: requirements.md §8.3.2・CLAUDE.md 索引を同期。
- テスト 771→796 passed（+25）。golden byte 不変・render 決定性維持。

### 反復18: D2b 設計検証ルール拡張（router-id 重複）— ✅完了（2026-06-14）
- build_checks に duplicate_ospf_router_id / duplicate_bgp_router_id（error）を追加。同一 router-id を持つ2台以上の機器を検出（OSPF/BGP を壊す深刻な誤設定）。`_collect_rid_duplicates` ヘルパで ospf/bgp 共通化（DRY）。None 無視・機器内 ospf=bgp 共用は非対象。renderChecksView は汎用表示で render 変更不要。
- レビュー対応: build_checks docstring にルール5/6、DRY ヘルパ集約、BGP 対称テスト、schema.md ## devices 表に ospf/bgp_router_id（既存ギャップ補完）＋ DATA.checks の bgp refs 注記、SKILL.md CHECKS に router-id。correctness 承認。
- doc: schema.md・requirements.md §8.2・SKILL.md を同期。
- テスト 796→815 passed（+19）。golden byte 不変（sample router-id 全null→checks 不変）。render 決定性維持。

### 反復19: C4b BGP timers / send-community（＋pending dict 統合リファクタ）— ✅完了（2026-06-14）
- BgpNeighbor に timers（`{keepalive,holdtime}` dict 化）/ send_community（"standard"/"extended"/"both"・無印=standard）を omit-when-None 追加。IOS `neighbor timers <ka> <hold>` / `send-community [both|standard|extended]`。
- pending dict 3個（update_source/rr/nhs）を単一 `pending_attrs[nip]` に統合し `_parse_bgp_line` を8→6引数に縮小。lib/diff.py COMPARE に timers/send_community 追加。
- レビュー対応（実バグ）: `send-community large` の silent "standard" 誤登録を修正（未対応キーワードはスキップ）、test_diff.py の削除アサーション復元、`Optional[Tuple[int,int]]` 厳密化、address-family 配下テスト追加。
- doc: schema.md・vendor-parsing.md・requirements.md §5.4/§6.1/§10 を同期。テスト 815→855 passed（+40）。golden byte 不変。

### 反復20: C1b BGP peer-group 継承 — ✅完了（2026-06-14）
- グループテンプレート方式。IOS `neighbor <name> 属性`（name が IP でない）→ pg_template、`neighbor <ip> peer-group <name>` → メンバー継承（remote-as/update-source/rr/nhs/timers/send-community を欠落分だけ・**個別指定が優先**）。BgpNeighbor.peer_group（omit-when-None）。BGP パース状態を単一 `bgp` dict に統合（引数再肥大を回避）。
- JunOS は group レベル `peer-as` 継承のみ（peer_group は非出力＝golden 維持の非対称）。
- レビュー対応（実害）: 未定義 peer-group をメンバー行だけで参照した際の **ゾンビ neighbor（peer_as=None）を排除**（メンバー生成を末尾解決へ遅延・DRY 重複も解消）、diff.py COMPARE に peer_group 追加、override 逆順/属性 override/二重登録/IPv6 メンバーのテスト補強。
- doc: schema.md・vendor-parsing.md・requirements.md §5.4/§6.1/§6.2/§10 を同期。テスト 855→880 passed（+25）。golden byte 不変。

### 反復21: A3 階層/直交レイアウトモード — ✅完了（2026-06-14）
- `compute_positions(data, mode="force")` に分岐追加（既存 force 本体は無変更）。新 `_hierarchical_positions`: device を AS で列(x)・列内 degree 降順→id 昇順で段(y)・segment/ext 末尾列・座標 round(.,1)。COL_GAP=240/ROW_GAP=120。`render_html(...,layout=)`＋`render_topology.py --layout {force,hierarchical}`（既定 force）。
- レビュー対応: 不正 mode を ValueError 化（silent fallthrough 解消）、AS グループ化を `_group_by_asn` ヘルパに DRY 抽出（cluster_order と共通化・golden 不変厳守）、module/COL_GAP docstring 補足。
- doc: requirements.md §8.3.3/§10.1・CLAUDE.md 索引を同期。テスト 880→909 passed（+29）。**既定 force で golden HTML byte 完全不変**・hierarchical は opt-in。

### 反復22: D2c 設計検証ルール拡張（OSPF area0 非接続・iBGP full-mesh 欠落）— ✅完了（2026-06-14）
- build_checks に `_check_ospf_area0_connectivity`（ルール7 ospf_area0_disconnected）/`_check_ibgp_fullmesh`（ルール8 ibgp_fullmesh_incomplete）を追加。config 保有 area で近似・RR 構成と解決不能 neighbor は偽陽性抑制でスキップ。
- レビュー対応（防御）: local_as=None / area=None の TypeError ガード、area refs の数値優先ソート、2台 iBGP 完成ケース非発火テスト、`_ip_to_device` と host_ip_to_device の差分 docstring 明記、ネスト if フラット化。
- doc: schema.md DATA.checks 表・requirements.md §8 CHECKS・SKILL.md を同期。テスト 909→930 passed（+21）。golden byte 不変（sample 非発火）。

### 反復23: D4 サブネット使用率集約ビュー（SUBNETS）— ✅完了（2026-06-14）
- `build_subnet_usage(topo)`→`DATA.subnet_usage`（v4・非link-local・非/32 を ip_network 集約。usable/used/free/util/exhausted・util降順→subnet昇順）。tabs に SUBNETS 常設タブ、assets に `renderSubnetUsageView`（Python 確定値を表示のみ）。ADDRESSES(IP一覧)と差別化＝サブネット集約・枯渇監視。**反復2で見送った D4 をユーザー承認で実装**。
- レビュー対応: `_EXHAUSTED_THRESHOLD=0.8` 定数化、exhausted 境界値テスト（util==0.8→True）、0件メッセージ/util%表示/trow件数の node 実検証強化、tabs docstring 更新。
- doc: requirements.md §8.2（SUBNETS・ADDRESSES 差別化）・schema.md DATA.subnet_usage・SKILL.md・CLAUDE.md 索引を同期。テスト 930→967 passed（+37）。**層別 YAML 不変**（保存済み golden HTML は無く render 決定性は test_render_e2e で担保）。

### 反復24: B5 キーボードショートカット拡充 — ✅完了（2026-06-14）
- 純関数 `keyToAction(key)`（g→connected/h→focus/m→minimap/l→legend/?→shortcuts・未割当 null）を node 実検証。keydown ディスパッチは既存ボタン `.click()` 複製で状態ロジック非二重化。`?` でショートカット一覧オーバーレイ（_BODY 隠し DOM・toggleShortcutsOverlay・背景/Esc で閉じる）。入力欄ガード維持。
- レビュー対応: **表ビュー中はグラフ操作系(g/h/m/l)を `!isTableView()` でガード**（hidden ボタンの誤 .click() 反転を防止）、toggleShortcutsOverlay 簡約、overlay 既定非表示の display:none 実検証、Escape 閉じテストのマジックスライス除去。
- doc: requirements.md §8.5・SKILL.md・CLAUDE.md 索引を同期。テスト 967→990 passed（+23）。層別 YAML 不変（render のみ）。

### 観点カバレッジ: A=A1,A4,A2,A5,A3 / B=B1,B3,B4,B5 / C=C2,C1,C3,C4,C4b,C5,C1b / D=D1,D2,D2b,D2c,D3,D3b,D3c,D4。
### 計画 6 項目（C4b/C1b/A3/D2c/D4/B5）完了。残バックログ: A1b（要設計・見送り）/ B2（要差別化）。**B が最少（3）**。B2 表ビュー列フィルタ（既存検索 vendor:/as: と差別化＝INTERFACES の種別チップ拡張や CHECKS の絞り込みチップ・要差別化設計（STATS は削除済み））/ B5 キーボードショートカット拡充（選択コピー等・テスト容易性要確認）/ C4b BGP timers/community（parser強TDD・pending増殖注意）/ D2c CHECKS ルール追加（OSPF area0 接続性・iBGP full-mesh）。観点B 補強なら B2（差別化設計を明確化）、強TDD・高価値なら D2c（design 検証の更なる拡充）。推奨は D2c（build_checks 強TDD・設計レビュー価値）か B2。
推奨順序の残り目安: D2c or B2 → C4b → A3 → A1b(要設計) → 残り。

## UI 改修（HTML レビュー反映・2026-06-14）
demo2 HTML レビューの指摘に対応（render 層のみ・層別 YAML 不変）。
- UI③ #nodepanel スクロール対応（max-height + overflow-y）。✅
- UI⑦ INTERFACES Status 列の OSPF バッジ削除。✅ **注意（情報損失）**: IF レベル OSPF パラメータ（cost/network_type/passive）はこの ospfBadge が唯一の表示箇所だったため、削除後はどこにも表示されない（ユーザー要望で許容）。将来必要なら詳細パネルへ移設を検討。
- UI⑥ STATS タブ削除（build_stats/renderStatsView/DATA.stats/CSS 除去・tabs から stats 除外）。✅ DIFF→CHECKS→ADDRESSES→INTERFACES→SUBNETS にタブ番号繰り上げ（数字キー/URLハッシュは VIEWS ベースで自動追従）。doc（requirements §8.2・SKILL.md・CLAUDE.md）同期。1000→986 passed・層別 YAML 不変。
- UI① OSPF area 不一致 CHECK（`ospf_area_mismatch` warning）＋ OSPF ビューの area-badge を `area 0≠1`＋警告色に簡素化（areaBadge ヘルパに DRY）。golden 非発火。doc（schema/requirements/SKILL）同期。✅
- UI② ハイライト時のライン/エッジラベル（IF/IP/subnet・stackLabel・BGP subnet-tag）を labelParts に集約し全ノード後に統合＝ノード前面化（z-order のみ・生成 HTML 内容不変）。`.subnet-tag` に pointer-events:none。✅
- UI④ OSPF ビューで loopback をスタブ図形描画（`build_ospf_stubs`→`DATA.ospf_stubs`・最長プレフィックス一致で area 採用・OSPF 非参加スキップ・決定的扇状配置）。loopback 判定は JS ifKind と同一正規表現を Python に一元化。凡例 dim 連動は非対応（常設）。doc（schema/SKILL/CLAUDE）同期。✅
  - **再設計（ユーザー指摘で浮遊円を不採用）**: A) **IOS interface-level `ip ospf <pid> area <a>`（IPv4）パース追加**（pending_ospf・IF v4 サブネット由来 OspfNetwork・ドット 0.0.0.0 対応・network 文と重複排除）。B) loopback 描画を **segment 様式**（`.segnode` 点線楕円＋subnet＋area-badge＋`.lk` spoke）に置換、`build_ospf_stubs` に `net` 追加、旧 `.lpstub*` 削除、loopback segnode は cursor:default・非選択。1020→1048 passed・層別 YAML 不変。✅
  - **segment と完全同一化（ユーザー再指摘）**: loopback segnode から `<title>`（IF 名ホバー）を削除＝**IF 名非表示**、ellipse を segment と同寸法 `rx=62 ry=26` に、area-badge オフセット・fan-out R を調整。非選択は維持。subnet のみ表示で segment と見分け不能に。render のみ・層別 YAML 不変。✅
  - **ホバー IF 名＋選択可能へ反転（ユーザー再指摘・2026-06-14）**: loopback を「ホバーで IF 名表示・クリックで親デバイス選択」に。`<title>${ifn} ${ip}</title>` 復活、`data-dev`（親デバイス id）付与＋click/mousemove/dblclick に `g.segnode[data-dev]` 専用分岐（data-elem は付けず seg 用 hittest と非衝突）、`class="segnode${selected/hovered}"` で親デバイス選択状態に連動強調、CSS `cursor:default` 上書き削除（segnode pointer 継承）。選択は実在 device id を S.sel に流す＝hash 復元健全。常設 invariant 維持。レビュー対応: click トグル delete を lp 分岐 250字窓で固有検査、dblclick ガードテスト追加、click 分岐コメント・CSS コメント・CLAUDE.md 索引同期。doc（schema/SKILL/CLAUDE）同期。1048→1052 passed・層別 YAML 不変。✅

### stub/loopback を両ビュー segment 様式ノード化＋ハイライト統一（ユーザー再スコープ・2026-06-14）— ✅完了
- 要望: Physical/OSPF 両ビューで loopback と**スタブ**（単独 IF サブネット）を segment 様式表示。ハイライトは「楕円 hover=スポーク hover（IF/IP ラベル）／クリック=setHotNet subnet 連動／3種統一」。loopback の旧「親デバイス選択（data-dev）」は廃止。
- データ層: `build_ospf_stubs`→**`build_stub_nodes(topo)`**（link/segment 非所属の IF-サブネットを抽出。`{dev, ifn, ip, subnet, area, kind}`・area=None 許容・kind=loopback/stub）。build_data キー `stub_nodes`。**層別 YAML 不変・build/parser 非変更**。
- render 層: stub ブロックを `if (S.view !== "bgp")`（OSPF は area あり）で `data-elem="seg"`/`seglink`＋`.lk-hit`＋area-badge、色クラス `.lpnode`/`.stubnode`、IF/IP は `stackLabel`。`lpId`/`segById`/`STUB_BY_ID`(Map・O(1))、`netNodes` に stub 走査、mousemove は楕円 hover でも `want=s.id`（ラベル）、click は `segById→setHotNet`、renderNodePanel/renderLegend（clk loopback/stub）/lgNodes/validIds/view cleanup/legendHot 無効化に stub。CSS テーマ変数 `--lp-edge`/`--stub-edge`・凡例 `.sw.lp`/`.sw.stub2`・PNG SVG_VARS。
- **レビュー対応（reviewer 指摘）**: ① **mousedown クラッシュ修正**（stub は POS 非登録 → `g && POS[g.dataset.id]` ガードで pan フォールバック＝非ドラッグ）。② **security: data 属性 esc**（`esid`/`edev` で data-id/data-mem/data-deco/data-nid を esc・IF 名生値の属性ブレイク防止）。③ **perf: `STUB_BY_ID` Map** で segById を O(1)（hover/applyVisibility ホットパス）。④ test: ガードが stub ブロックを囲むことを位置検査・mousedown 非ドラッグ/dblclick/esc テスト追加。⑤ doc 全面同期（schema.md DATA.stub_nodes・link-inference.md・SKILL.md・CLAUDE.md 索引）。
- 1052→1054 passed・**層別 YAML 不変**・node --check OK。暫定: 色（紫=loopback/緑=stub）と凡例は HTML 確認後に調整可。許容副作用: stub 非ドラッグ・connectedOnly/検索中 dim（adj/corpus 非参加）。

### stub/loopback のカテゴリ全体トグル＋デモ config 作り直し（ユーザー要望・2026-06-14）— ✅完了
- **カテゴリトグル**: segment の `#f-seg`/`S.filters.seg` に倣い、ツールバーに `#f-lo`（loopback）/`#f-stub`（スタブ）チェックボックス追加。`S.filters.lo/stub`、ヘルパ `stubFiltered(id)`（STUB_BY_ID で kind 判定→`S.filters` 参照）を `visible()`/`selectable()` 両方で使用。onchange→render。個別（表示ノードパネル `S.hiddenNodes`）とカテゴリ（全体）が両立。
- **デモ config 作り直し**: `demo3/configs/`（core1/2/3/edge1）で **segment（core1/2/3 共有 LAN 10.0.0.0/24）・link（core1-edge1 P2P）・stub 2（core3/edge1 単独 LAN）・loopback 4・area0/1 混在・iBGP loopback peering** を1図で見分けられる構成。segment/stub/loopback の視覚的区別を確認できる。demo3/topology（層別YAML）生成。
- レビュー: correctness ✅・test ✅（既存 seg/ext フィルタと同粒度）・maintainability ⚠️→doc（schema/SKILL/CLAUDE）にカテゴリトグル1行追記で対応。1054→1055 passed・層別 YAML 不変・node --check OK。

### CONFIG タブ（生 running-config 閲覧→比較・編集ワークベンチ）（ユーザー要望・2026-06-14）— ✅完了
- **基盤**: parse 後に破棄していた生 config を中間表現 `raw_config.yaml`（device id キー・非空時のみ）に保持。`build_topology(...,raw_texts=)`→`topo["raw_configs"]`→`DATA.raw_configs`。CONFIG タブ（`has_config` 条件付き）で左=機器リスト＋検索/右=行番号付き本文。機密は原本のまま保持・警告バナー（ユーザー受容）。schema_version 据え置き。
- **parse 状態モード（突合の核心）**: `parse_ios`/`parse_junos` に opt-in `line_status` 追加（サブハンドラを bool 返しに）→各行 parsed/ignored/unparsed 記録（正規表現一致=parsed・機密/コメント/空行=ignored・fall-through=unparsed）。`topo["parse_status"]`→`raw_config.yaml` 同居→`DATA.parse_status`。CONFIG で3色分け＋「未対応のみ」抽出。**モデル出力不変**（既存ゴールデン byte 一致で回帰確認）。
- **ユーティリティ**: 全文コピー(`copyText`)・行折返し・検索一致行ナビ(`cfgHitIdx`)・grep。
- **2ペイン比較・編集**: `renderCfgSplit`・`lineDiff`(LCS)。source=`dev:`(原本)/`prev:`(`--diff-against` 前回)/`scratch:`(編集コピー)。`cfgTextOf` は scratch のみ編集バッファ・dev/prev は原本＝**原本保持で原本 vs 編集の比較成立**。「コピーして編集」(dev のみ)で scratch 生成。**リテラル全置換**(`split(f).join(repl)`)。編集スクラッチ localStorage 永続・生成 HTML には焼かない（決定性維持）。
- **refinement（ユーザー指示・同日）**: SUBNETS タブ完全削除（`build_subnet_usage`/`DATA.subnet_usage`/`renderSubnetUsageView`/`_EXHAUSTED_THRESHOLD`）／アウトライン・折りたたみ廃止（`cfgSections`/`configOutline`/`collapsedCfg`）／タブ順 `ADDRESSES INTERFACES [CONFIG] [DIFF] CHECKS`／編集モデルを scratch 独立 source 化／文字置換追加。
- レビュー（5本＋HTML敵対的・複数ラウンド）: CRITICAL/HIGH 動作バグなし。修正済=keydownガードに TEXTAREA／diff debounce／lineDiff境界／検索ナビ初回／コピーして編集を dev のみ（prev seed/衝突修正）／localStorage prototype 汚染ガード／node-check スタブ更新。doc（SKILL/schema/CLAUDE/vendor-parsing）同期。**1065 passed・層別 YAML（既存6ファイル）byte 不変・node --check OK**。未コミット。

### CONFIG タブ ノード駆動「編集」モード追加（ユーザー要望・2026-06-14）— ✅完了
- **目的**: 既存の「比較→source 選択→コピーして編集」の3段階を、「機器を選択→『編集』ボタン→編集前 vs 編集中」の1アクションに簡素化。自由比較「比較」は併存（render 層のみ・`DATA.raw_configs` 既存）。
- **実装**（`assets.py`）: `S.configEdit` 追加（split と排他）。toolbar に `data-cfgtoggle="edit"`。新 `renderCfgEdit(q,cur)`=左 `dev:<cur>`原本(読取専用)／右 `scratch:<cur>`(textarea＋全置換)・source ドロップダウンなし・各ペインに `data-cfgkey`。「edit」トグルで scratch を原本から生成（既存は温存）。編集対象 `cur` は検索フィルタ非依存（全機器ベース＝トグルと整合し機器すり替え防止）。
- **キー解決一元化**: select 不在の編集モードに対応するため、保存(input)/全置換/コピー/差分(`updateCfgSplitDiff`)の source キー解決を共通ヘルパ `cfgPaneKey(paneEl,ta)`（select 優先→`data-cfgkey` フォールバック）に集約。`lineDiff` に同一テキスト早道（O(n)）追加。
- レビュー（5本＋HTML敵対的）: CRITICAL/HIGH なし。修正済=lineDiff早道(perf)／キー解決一元化(correctness MEDIUM・maint)／編集対象が検索で勝手にすり替わる(adversarial M1)／差分省略表示の一貫性(M2)／behavioral テスト追加(cfgPaneKey×3・lineDiff同一・renderCfgEdit markup)。textarea の `esc()` は `</textarea>` ブレイクアウト防止で必須＝据え置き。doc（SKILL/CLAUDE）同期。**1074 passed・層別 YAML byte 不変・決定性OK・node --check OK**。未コミット。

### CONFIG 仕上げ＋図ビュー loopback/stub 4点修正（ユーザー要望・2026-06-15）— ✅完了
render 層のみ（`assets.py`）・`DATA` 既存・層別YAML/ゴールデン不変・決定性維持。
- **A 比較=読取専用化**: `renderCfgSplit` から textarea/find-replace/「コピーして編集」全廃・`data-cfgcopyedit` ボタン＋ハンドラ削除（dead code 清掃）。編集は「編集」モード一本化。
- **B 編集モードのライブ行整列**: 旧 `lineDiff`→`lineAlign`（順序付き ops・同一テキスト早道・`n*m>=4e6` 省略・DP は Int32Array）。`cfgLineHtml`/`cfgDiffCounts`/`cfgSymRows`（比較=対称整列・両ペイン同数＋空行ギャップ）/`cfgEditLeftRows`（編集左=右 textarea にアンカー整列・左行数==編集後行数・追加=`.cfgline.gap`・削除=行非消費の `.del-above[data-del]`/末尾 `.cfgdelmark`）。`renderCfgEdit` 左を整列生成・折返し除外・textarea `white-space:pre`。`updateCfgSplitDiff` は編集時のみ左ペイン再計算（debounce）。縦スクロール同期（capture・`_cfgScrollLock`）。
- **C ラベルにじみ抑制**: stub/loopback の `showIf` から親機器条件 `S.sel.has(st.dev)` 除去（自身選択/hover/hot のみ）。複数機器選択時・別 loopback 選択時の無関係ラベルを解消。
- **D DEVICE DETAILS から選択可能化**: `stubNetForDetail(dev,ifn)`（bgp→null・ospf は area 有のみ）で IF 行に `data-net` 付与→既存 `setHotNet`/`netNodes` でクリック選択連動。`IP2NET` は非変更（ADDRESSES グループへの副作用回避）。
- レビュー（5本＋HTML敵対的・16整列パターン node-eval）: CRITICAL/HIGH/MEDIUM 0。対応済=DP Int32Array(perf HIGH)／cfgLineHtml 非利用理由コメント(maint)／脆いテストを `_extract_fn`・空白非依存化(test)。LOW=2000行超で整列省略（バッジ明示・グレースフル）。doc（CLAUDE L44/45・SKILL L96）同期。**1081 passed・層別 YAML byte 不変・決定性OK・node --check OK**。未コミット。

### CONFIG 編集刷新: 編集(textarea+行番号ガター) + 統一差分プレビュー(読取専用 git 風)（2026-06-16）— ✅完了
- CONFIG 仕上げ以前の「編集前(左・原本/読取専用) vs 編集中(右・textarea)＋cfgEditLeftRows 行整列」から刷新。
- 左=編集 textarea＋行番号ガター（`cfgGutHtml`/`data-cfggut="E"`）、右=統一差分プレビュー（読取専用・`cfgUnifiedRows`〔行単位 same/del/add・変更カテゴリなし〕）の横並びに変更。
- 撤去: `cfgEditLeftRows` 関数・`.del-above`/`.cfgdelmark` CSS ピルマーカー。
- 追加: DL（`downloadText`/`cfgFileName`/`data-cfgdl`）・コピー（`data-cfgcopytext="E"`）・元に戻す（`data-cfgrevert`）・dirty バッジ（`cfgIsDirty`/`.cfgdirty`）・カーソル行ハイライト（`cfgEditHighlightCur`/`updateCfgEditDiff`）。
- COMPARE（読取専用比較・`cfgSymRows`）は不変。render 層のみ・golden YAML byte 不変・決定性維持。

### STATIC 図ビュー: スタティック経路フォワーディング・シミュレーション v1（ユーザー要望・2026-06-16）— ✅完了
「スタティックルートを図で解析・将来はダイナミックもシミュレーション」要望。render 層のみ・層別YAML(golden) byte 不変・決定性維持・将来 dynamic 拡張の土台。
- **FIB（protocol 非依存 RIB）**: `build_fib(topo,links)`→`DATA.fib`（connected＋static・plen降順＋同plen connected優先ソート）。`_resolve_next_hop`（特殊値/Null0/loopback→blackhole・host一致(自機除外)→device・サブネット内包→所有device・未解決→dangling・IF名 P2P→peer/不定→target=null）。`_build_host_ip_index`/`_build_subnet_index` を切り出し iBGP/dangling チェックと共用（無挙動変更リファクタ先行）。`link_idx` で over-link を O(1) 解決。
- **オーバーレイ**: `build_static_edges`→`DATA.static_edges`（幾何 dedup）/`build_static_stubs`→`DATA.static_stubs`（blackhole/dangling/viaif 終端・POS 非登録扇状）。
- **タブ**: `tabs.py` で `routing.static` 非空時に STATIC 図ビュー（physical の次）。
- **トレース（純関数）**: `evalNode`/`traceForward`/`ipInCidr`/`ip6ToBig`（LPM・verdict delivered/blackhole/unreachable-nexthop/no-route/loop・ECMP先頭・v6 BigInt・/999 クランプ）。
- **描画/UI**: 矢じり marker `#se-arrow`・方向線（default破線/ECMP太/blackhole赤/dangling橙/viaif青）・終端ノード・`.trace-hop`/`.trace-edge` ハイライト・`applyVisibility` 連動・トレース UI（`#trace-src`/`#trace-dst`/`runTrace`/`clearTrace`/`syncTraceControls`）・`S.trace`・`renderTraceResult`・verdict 許可リスト `safeVerdict`。
- レビュー6本（5＋HTML敵対的・node-eval 多数）: CRITICAL/HIGH 0。対応済=`_over_link` O(1)化(perf)・node-check スタブに新キー＋via-interface トレーステスト(test)・`seen=set()`(maint)・verdict 許可リスト/ipInCidr クランプ(sec)・viaif 独自色・`applyVisibility` で sedge/sstub の hidden/dim 伝播＋sedge hover ラベル(adversarial M1/M2)。doc（SKILL/CLAUDE/schema）同期。**1109 passed・層別 YAML byte 不変・決定性OK・node --check OK**。未コミット。
