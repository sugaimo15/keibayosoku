# keibayosoku

netkeiba.com から競馬の過去レース結果・当日出馬表をスクレイピングして本リポジトリの `data/` 配下に蓄積し、
蓄積したデータをもとにルールベースのスコアリングで着順を予測するツールです。

## 構成

```
src/keibayosoku/
  scraper/
    http.py        # robots.txt尊重・レート制限付きHTTPクライアント
    race_id.py      # race_id (12桁) のパース
    race_list.py     # 指定日の開催レースID一覧取得
    race_result.py    # 過去レース結果ページのパース
    race_card.py      # 出馬表(レース前)ページのパース
  storage.py          # data/ へのCSV保存・読込
  predict/
    scoring.py         # ルールベーススコアリング
    predict_race.py     # 1レース分の予測オーケストレーション
  cli.py                # コマンドラインエントリーポイント

data/
  race_results/{year}/{race_id}.csv   # 過去レース結果 (蓄積データ = 学習元)
  race_cards/{date}/{race_id}.csv     # 出馬表
  predictions/{date}/{race_id}.csv    # 予測結果

.github/workflows/
  daily.yml   # 毎日自動でスクレイピング→予測→data/へコミット
  test.yml    # オフラインの単体テストをCIで実行
```

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 使い方 (CLI)

```bash
# 指定日に開催されたレースの結果を取得してdata/race_resultsに保存 (過去データの蓄積)
keibayosoku scrape-results --date 20260101

# 指定日に開催されるレースの出馬表を取得してdata/race_cardsに保存
keibayosoku scrape-card --date 20260117

# 保存済みの出馬表 + 過去結果から予測してdata/predictionsに保存
keibayosoku predict --date 20260117

# 上記を一括実行 (GitHub Actionsから毎日呼び出される)
keibayosoku daily --date 20260117
```

いずれのコマンドも `--interval` でリクエスト間隔(秒, デフォルト2秒)を調整できます。

## 自動化 (GitHub Actions)

`.github/workflows/daily.yml` が毎日 08:00 JST (23:00 UTC) にスケジュール実行され、
前日のレース結果取得 → 当日の出馬表取得 → 予測 → `data/` への差分コミット を自動で行います。
`workflow_dispatch` で日付を指定した手動実行も可能です。

## 予測ロジック (ルールベース、初期版)

`src/keibayosoku/predict/scoring.py` で以下を加重合算してスコア化し、降順に並べたものを予測着順とします。

| 要素 | 重み | 内容 |
|---|---|---|
| 直近成績 | 40% | 過去5走の平均着順 |
| 騎手成績 | 25% | 騎手の通算勝率 |
| 適性 | 20% | 同一馬場種別・近い距離帯での平均着順 |
| 馬体重増減 | 10% | 前走比の増減幅が小さいほど加点 |
| オッズ | 5% | 単勝オッズが発表されていれば低いほど加点 |

データが蓄積されるほど精度は上がる想定です。重みは経験則による初期値なので、
`data/predictions/` と実際の結果を突き合わせて調整していくことを想定しています。

## スクレイピングに関する注意

- `NetkeibaClient` はリクエスト毎に対象サイトの `robots.txt` を取得し、許可されていないURLへはアクセスしません
  (取得自体に失敗した場合も安全側に倒してアクセスを中止します)。
- リクエスト間隔はデフォルト2秒空けており、対象サーバーに過度な負荷をかけないようにしています。
- 本ツールは個人の研究・分析目的での利用を想定しています。利用にあたっては対象サイトの利用規約を
  必ず確認し、規約に反する形での利用は行わないでください。
- HTML構造はサイト側の変更で容易に変わりうるため、パーサーが正しく動作しない場合は
  `src/keibayosoku/scraper/` 内のセレクタ(クラス名など)を実際のページに合わせて調整してください。
  `tests/` にはオフラインで動作確認できるサンプルHTMLとテストを用意しています。

## テスト

```bash
pytest tests/ -v
```

ネットワークアクセスなしで、`tests/fixtures/` のサンプルHTMLを使ってパーサー/スコアリングロジックを検証します。
