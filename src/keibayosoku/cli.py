"""keibayosoku CLI.

サブコマンド:
  scrape-results --date YYYYMMDD   指定日に開催されたレースの結果を取得してdata/race_resultsに保存
  scrape-card     --date YYYYMMDD  指定日に開催されるレースの出馬表を取得してdata/race_cardsに保存
  predict         --date YYYYMMDD  保存済みの出馬表と過去結果から予測しdata/predictionsに保存
  daily           --date YYYYMMDD  上記を一括実行 (GitHub Actionsから呼び出す想定)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

import pandas as pd

from . import storage
from .scraper.http import NetkeibaClient, RobotsDisallowedError
from pathlib import Path

from .scraper.race_card import fetch_race_card
from .scraper.race_list import fetch_race_ids, fetch_race_list_html
from .scraper.race_result import fetch_race_result
from .predict.predict_race import predict

DEBUG_DIR = Path(__file__).resolve().parents[2] / "debug"


def _today_str() -> str:
    return date.today().strftime("%Y%m%d")


def _yesterday_str(base: str) -> str:
    d = date.fromisoformat(f"{base[0:4]}-{base[4:6]}-{base[6:8]}")
    return (d - timedelta(days=1)).strftime("%Y%m%d")


def cmd_scrape_results(args: argparse.Namespace) -> None:
    client = NetkeibaClient(min_interval_sec=args.interval)
    race_ids = args.race_ids or [item.race_id for item in _safe_fetch_race_ids(client, args.date)]
    if not race_ids:
        print(f"[scrape-results] {args.date}: 開催レースが見つかりませんでした。", file=sys.stderr)
        return

    for race_id in race_ids:
        try:
            result = fetch_race_result(client, race_id)
        except RobotsDisallowedError as exc:
            print(f"[scrape-results] {race_id}: スキップ ({exc})", file=sys.stderr)
            continue
        if not result.entries:
            print(f"[scrape-results] {race_id}: 結果テーブルが見つかりませんでした(未確定の可能性)。", file=sys.stderr)
            continue
        path = storage.save_race_result(result)
        print(f"[scrape-results] {race_id}: {len(result.entries)}頭分を保存 -> {path}")


def cmd_scrape_card(args: argparse.Namespace) -> None:
    client = NetkeibaClient(min_interval_sec=args.interval)
    race_ids = args.race_ids or [item.race_id for item in _safe_fetch_race_ids(client, args.date)]
    if not race_ids:
        print(f"[scrape-card] {args.date}: 開催レースが見つかりませんでした。", file=sys.stderr)
        return

    for race_id in race_ids:
        try:
            card = fetch_race_card(client, race_id)
        except RobotsDisallowedError as exc:
            print(f"[scrape-card] {race_id}: スキップ ({exc})", file=sys.stderr)
            continue
        if not card.entries:
            print(f"[scrape-card] {race_id}: 出馬表が見つかりませんでした。", file=sys.stderr)
            continue
        path = storage.save_race_card(card, args.date)
        print(f"[scrape-card] {race_id}: {len(card.entries)}頭分を保存 -> {path}")


def cmd_predict(args: argparse.Namespace) -> None:
    history = storage.load_all_race_results()
    if history.empty:
        print("[predict] 過去データがまだありません。scrape-resultsを先に実行してください。", file=sys.stderr)

    card_dir = storage.RACE_CARDS_DIR / args.date
    if not card_dir.exists():
        print(f"[predict] {args.date}の出馬表がありません。先にscrape-cardを実行してください。", file=sys.stderr)
        return

    for csv_path in sorted(card_dir.glob("*.csv")):
        race_id = csv_path.stem
        card_df = pd.read_csv(csv_path)
        if card_df.empty:
            continue
        distance_m = card_df["distance_m"].iloc[0] if "distance_m" in card_df.columns else None
        surface = card_df["surface"].iloc[0] if "surface" in card_df.columns else None

        from .predict.scoring import score_race_card

        scored = score_race_card(card_df, history, distance_m=distance_m, surface=surface)
        path = storage.save_predictions(scored, args.date, race_id)

        top = scored[["predicted_rank", "horse_number", "horse_name", "score"]].head(3)
        print(f"[predict] {race_id} ({card_df['race_name'].iloc[0] if 'race_name' in card_df.columns else ''})")
        print(top.to_string(index=False))
        print(f"  -> 保存: {path}")


def _dump_debug_html(client: NetkeibaClient, date_str: str) -> None:
    """race_idが1件も見つからない場合に、原因調査用に生HTMLを保存する。

    (JS描画/ブロック/セレクタずれ等の切り分け用。debug/はコミットしない一時出力)
    """
    try:
        html = fetch_race_list_html(client, date_str)
    except Exception as exc:  # noqa: BLE001 - デバッグ用途なので握りつぶして継続
        print(f"[debug] race_list.html取得にも失敗: {exc}", file=sys.stderr)
        return

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    path = DEBUG_DIR / f"race_list_{date_str}.html"
    path.write_text(html, encoding="utf-8")

    has_race_id = "race_id=" in html
    has_racelist = "RaceList" in html
    print(
        f"[debug] {date_str}: race_idが0件のため生HTMLを保存 -> {path} "
        f"(len={len(html)}, 'race_id='含む={has_race_id}, 'RaceList'含む={has_racelist})",
        file=sys.stderr,
    )
    if len(html) <= 4000:
        print(f"[debug] {date_str}: 応答本文(短いため全文出力) --->\n{html}\n<--- [debug] 応答本文ここまで", file=sys.stderr)


def _safe_fetch_race_ids(client: NetkeibaClient, date_str: str):
    try:
        items = fetch_race_ids(client, date_str)
    except RobotsDisallowedError as exc:
        print(f"robots.txtにより拒否されました: {exc}", file=sys.stderr)
        return []

    if not items:
        _dump_debug_html(client, date_str)
    return items


def cmd_daily(args: argparse.Namespace) -> None:
    results_ns = argparse.Namespace(date=args.results_date, race_ids=None, interval=args.interval)
    cmd_scrape_results(results_ns)

    card_ns = argparse.Namespace(date=args.date, race_ids=None, interval=args.interval)
    cmd_scrape_card(card_ns)

    predict_ns = argparse.Namespace(date=args.date)
    cmd_predict(predict_ns)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keibayosoku")
    sub = parser.add_subparsers(dest="command", required=True)

    common_args = dict(interval=2.0)

    p_results = sub.add_parser("scrape-results", help="過去レース結果を取得して保存")
    p_results.add_argument("--date", default=_yesterday_str(_today_str()), help="YYYYMMDD (デフォルト: 前日)")
    p_results.add_argument("--race-id", dest="race_ids", action="append", help="race_idを直接指定(複数可)")
    p_results.add_argument("--interval", type=float, default=common_args["interval"])
    p_results.set_defaults(func=cmd_scrape_results)

    p_card = sub.add_parser("scrape-card", help="出馬表を取得して保存")
    p_card.add_argument("--date", default=_today_str(), help="YYYYMMDD (デフォルト: 当日)")
    p_card.add_argument("--race-id", dest="race_ids", action="append", help="race_idを直接指定(複数可)")
    p_card.add_argument("--interval", type=float, default=common_args["interval"])
    p_card.set_defaults(func=cmd_scrape_card)

    p_predict = sub.add_parser("predict", help="保存済みデータから予測")
    p_predict.add_argument("--date", default=_today_str(), help="YYYYMMDD (デフォルト: 当日)")
    p_predict.set_defaults(func=cmd_predict)

    p_daily = sub.add_parser("daily", help="結果取得+出馬表取得+予測を一括実行")
    p_daily.add_argument("--date", default=_today_str(), help="YYYYMMDD (デフォルト: 当日、出馬表取得/予測対象)")
    p_daily.add_argument("--results-date", default=None, help="YYYYMMDD (デフォルト: --dateの前日、結果取得対象)")
    p_daily.add_argument("--interval", type=float, default=common_args["interval"])
    p_daily.set_defaults(func=cmd_daily)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "daily" and args.results_date is None:
        args.results_date = _yesterday_str(args.date)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
