# config-topology rebuild

config テキストからネットワーク・トポロジー（層別 YAML / HTML）を生成するパイプラインの再実装。

仕様正本: `../docs/requirements.md` v2.1 ／ 進め方: `../docs/implementation-instructions.md`

## テスト
    cd rebuild/dev && python3 -m pytest -q

## CLI（M1 時点）
    python3 rebuild/scripts/parse_configs.py <paths...>   # 正規化 Device を JSON 出力
