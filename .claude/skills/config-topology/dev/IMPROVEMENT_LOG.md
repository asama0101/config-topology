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
### 計画 6 項目（C4b/C1b/A3/D2c/D4/B5）完了。残バックログ: A1b（要設計・見送り）/ B2（要差別化）。**B が最少（3）**。B2 表ビュー列フィルタ（既存検索 vendor:/as: と差別化＝INTERFACES の種別チップ拡張や STATS/CHECKS の絞り込みチップ・要差別化設計）/ B5 キーボードショートカット拡充（選択コピー等・テスト容易性要確認）/ C4b BGP timers/community（parser強TDD・pending増殖注意）/ D2c CHECKS ルール追加（OSPF area0 接続性・iBGP full-mesh）。観点B 補強なら B2（差別化設計を明確化）、強TDD・高価値なら D2c（design 検証の更なる拡充）。推奨は D2c（build_checks 強TDD・設計レビュー価値）か B2。
推奨順序の残り目安: D2c or B2 → C4b → A3 → A1b(要設計) → 残り。
