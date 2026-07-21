"""過去にバックフィル済みのレース結果を使い、データリークを除去した状態で
scoring.pyの予測モデルの的中率・回収率を検証する。

「リークを除去した」とは、各レースをスコアリングする際に、そのレースの
日付より前の履歴だけを使う(そのレース自身やそれ以降のレース結果は一切
見ない)という意味。過去にjockey×horse相性・展開(隊列・ペース)の2つの
新機能を実データで検証した際、65レースという小サンプルでは極端に高い
回収率が出た条件が、900レース規模の大規模データで再検証すると軒並み
平均的な水準まで下がる、という経験をしたため、このモジュールを常設の
検証ツールとして用意した。今後スコアリングを変更するたびに
`keibayosoku backtest` で同じ基準で検証できるようにする。

score_race_card() (scoring.py) は呼ぶたびに build_horse_stats/build_jockey_stats
で履歴全体をgroupbyするため、レースごとに異なる日付カットオフで数百〜数千回
呼び出すと非常に遅い。ここでは対象レースに登場する馬・騎手だけに絞ってから
集計する高速版(score_card_fast)を使う。
"""
from __future__ import annotations

import sys
from itertools import combinations, permutations
from pathlib import Path

import pandas as pd

from .. import storage
from .scoring import (
    RECENT_N,
    WEIGHTS,
    _aptitude_score,
    _normalize,
    _parse_odds,
    _parse_weight_change,
    _to_numeric_finish,
    _track_condition_score,
)

# 単勝/複勝は1位予測のみ購入、他は上位TOP_N頭のボックス買いを想定する
# (これまでのユーザー向け回収率検証で使ってきた基準と揃えている)。
TOP_N = 5
STRAIGHT_BET_TYPES = ["単勝", "複勝"]
BOX_BET_SIZES = {"馬連": 2, "ワイド": 2, "馬単": 2, "三連複": 3, "三連単": 3}
ORDERED_BET_TYPES = {"馬単", "三連単"}
ALL_BET_TYPES = STRAIGHT_BET_TYPES + list(BOX_BET_SIZES)


def _avg_finish_recent_fast(hist_before: pd.DataFrame, horse_id) -> float | None:
    g = hist_before[hist_before["horse_id"] == horse_id]
    finishes = g["finish_num"].dropna().tail(RECENT_N)
    return float(finishes.mean()) if len(finishes) else None


def _jockey_win_rate_fast(hist_before: pd.DataFrame, jockey_id) -> float | None:
    g = hist_before[hist_before["jockey_id"] == jockey_id]
    finishes = g["finish_num"].dropna()
    if len(finishes) == 0:
        return None
    return float((finishes == 1).sum() / len(finishes))


def score_card_fast(
    card_df: pd.DataFrame,
    hist_before: pd.DataFrame,
    distance_m: float | None = None,
    surface: str | None = None,
    track_condition: str | None = None,
) -> pd.DataFrame:
    """score_race_card()と同じ重み付けで、対象レースの馬・騎手だけに絞って
    高速にスコアリングする(バックテストで大量レースを処理するための最適化版)。
    """
    df = card_df.copy()
    df["_avg_finish_recent"] = df["horse_id"].apply(lambda hid: _avg_finish_recent_fast(hist_before, hid))
    df["_jockey_win_rate"] = df["jockey_id"].apply(lambda jid: _jockey_win_rate_fast(hist_before, jid))
    df["_aptitude"] = df["horse_id"].apply(lambda hid: _aptitude_score(hist_before, hid, distance_m, surface))
    df["_track_condition"] = df["horse_id"].apply(
        lambda hid: _track_condition_score(hist_before, hid, track_condition)
    )
    weight_change = df.get("horse_weight", pd.Series(dtype=object)).apply(_parse_weight_change)
    df["_weight_change"] = pd.to_numeric(weight_change, errors="coerce").abs()
    df["_odds"] = df.get("win_odds", pd.Series(dtype=object)).apply(_parse_odds)

    recent_form_score = _normalize(df["_avg_finish_recent"], invert=True)
    jockey_score = _normalize(df["_jockey_win_rate"], invert=False)
    aptitude_score = _normalize(df["_aptitude"], invert=True)
    track_condition_score = _normalize(df["_track_condition"], invert=True)
    weight_change_score = _normalize(df["_weight_change"], invert=True)
    odds_score = _normalize(df["_odds"], invert=True)

    df["score"] = (
        WEIGHTS["recent_form"] * recent_form_score
        + WEIGHTS["jockey"] * jockey_score
        + WEIGHTS["aptitude"] * aptitude_score
        + WEIGHTS["track_condition"] * track_condition_score
        + WEIGHTS["weight_change"] * weight_change_score
        + WEIGHTS["odds"] * odds_score
    )
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["predicted_rank"] = df.index + 1
    return df


def _payout_lookup(payouts: pd.DataFrame, bet_type: str, combo: str) -> int | None:
    if payouts.empty:
        return None
    rows = payouts[(payouts["bet_type"] == bet_type) & (payouts["combination"].astype(str) == combo)]
    if rows.empty:
        return None
    return int(rows["amount"].iloc[0])


def evaluate_race(scored: pd.DataFrame, payouts: pd.DataFrame) -> dict:
    """1レース分の的中判定・回収率計算に必要な指標を返す。

    scored: score_card_fast()の出力に実際の着順(finish_num列)を付与したもの。
    payouts: そのレースの払戻データ(無ければ空DataFrameでよい。回収率計算対象外になる)。
    """
    scored = scored.sort_values("predicted_rank").reset_index(drop=True)
    top1 = scored.iloc[0]
    top5 = scored.head(TOP_N)

    win_hit = bool(not pd.isna(top1.get("finish_num")) and top1["finish_num"] == 1)
    place_hit = bool(not pd.isna(top1.get("finish_num")) and top1["finish_num"] <= 3)

    bet_stats = {bt: {"stake": 0, "payout": 0, "hits": 0} for bt in ALL_BET_TYPES}

    hn = str(int(top1["horse_number"])) if not pd.isna(top1.get("horse_number")) else None
    for bt in STRAIGHT_BET_TYPES:
        bet_stats[bt]["stake"] += 100
        if hn:
            amt = _payout_lookup(payouts, bt, hn)
            if amt:
                bet_stats[bt]["payout"] += amt
                bet_stats[bt]["hits"] += 1

    nums = [str(int(row["horse_number"])) for _, row in top5.iterrows() if not pd.isna(row.get("horse_number"))]
    for bt, k in BOX_BET_SIZES.items():
        if len(nums) < k:
            continue
        if bt in ORDERED_BET_TYPES:
            combos = list(permutations(nums, k))
            bet_stats[bt]["stake"] += 100 * len(combos)
            for c in combos:
                amt = _payout_lookup(payouts, bt, "-".join(c))
                if amt:
                    bet_stats[bt]["payout"] += amt
                    bet_stats[bt]["hits"] += 1
        else:
            combos = list(combinations(nums, k))
            bet_stats[bt]["stake"] += 100 * len(combos)
            for c in combos:
                for perm in permutations(c):
                    amt = _payout_lookup(payouts, bt, "-".join(perm))
                    if amt:
                        bet_stats[bt]["payout"] += amt
                        bet_stats[bt]["hits"] += 1
                        break

    return {"win_hit": win_hit, "place_hit": place_hit, "has_payout": not payouts.empty, "bet_stats": bet_stats}


def run_backtest(
    race_files: list[Path] | None = None,
    full_history: pd.DataFrame | None = None,
    exclude_shinba: bool = True,
    progress_every: int | None = 100,
) -> dict:
    """バックフィル済みの過去レース全てについて、日付より前の履歴だけでスコアリングし、
    リークを除去した的中率・回収率を集計する。

    race_files省略時はdata/race_results配下の全CSVを対象にする。
    full_history省略時はstorage.load_all_race_results()/load_all_horse_historiesを結合して使う。
    """
    if race_files is None:
        race_files = sorted(storage.RACE_RESULTS_DIR.glob("*/*.csv"))
    if full_history is None:
        full_history = pd.concat(
            [storage.load_all_race_results(), storage.load_all_horse_histories()], ignore_index=True
        )
        full_history = full_history.drop_duplicates(subset=["race_id", "horse_id"], keep="first")
    full_history = full_history.copy()
    full_history["finish_num"] = _to_numeric_finish(full_history["finish_position"])
    full_history = full_history.sort_values("date").reset_index(drop=True)

    n_evaluated = 0
    n_skipped_shinba = 0
    n_skipped_other = 0
    win_hits = 0
    place_hits = 0
    bet_totals = {bt: {"stake": 0, "payout": 0, "hits": 0} for bt in ALL_BET_TYPES}
    n_with_payout = 0

    for i, f in enumerate(race_files):
        card_df = pd.read_csv(f)
        if card_df.empty or "horse_id" not in card_df.columns:
            n_skipped_other += 1
            continue

        race_name = str(card_df["race_name"].iloc[0]) if "race_name" in card_df.columns else ""
        if exclude_shinba and "新馬" in race_name:
            n_skipped_shinba += 1
            continue

        race_id = card_df["race_id"].iloc[0]
        race_date = card_df["date"].iloc[0] if "date" in card_df.columns else None
        if pd.isna(race_date):
            n_skipped_other += 1
            continue

        hist_before = full_history[full_history["date"] < race_date]
        if hist_before.empty:
            n_skipped_other += 1
            continue

        distance_m = card_df["distance_m"].iloc[0] if "distance_m" in card_df.columns else None
        surface = card_df["surface"].iloc[0] if "surface" in card_df.columns else None
        track_condition = card_df["track_condition"].iloc[0] if "track_condition" in card_df.columns else None
        if pd.isna(track_condition):
            track_condition = None

        scored = score_card_fast(card_df, hist_before, distance_m, surface, track_condition)
        scored["finish_num"] = _to_numeric_finish(scored["finish_position"])

        payout_path = storage.race_payout_path(race_id)
        payouts = pd.read_csv(payout_path) if payout_path.exists() else pd.DataFrame()

        result = evaluate_race(scored, payouts)
        n_evaluated += 1
        win_hits += int(result["win_hit"])
        place_hits += int(result["place_hit"])
        if result["has_payout"]:
            n_with_payout += 1
            for bt, s in result["bet_stats"].items():
                bet_totals[bt]["stake"] += s["stake"]
                bet_totals[bt]["payout"] += s["payout"]
                bet_totals[bt]["hits"] += s["hits"]

        if progress_every and (i + 1) % progress_every == 0:
            print(f"  [backtest] {i + 1}/{len(race_files)} 処理済み", file=sys.stderr)

    return {
        "n_race_files": len(race_files),
        "n_skipped_shinba": n_skipped_shinba,
        "n_skipped_other": n_skipped_other,
        "n_evaluated": n_evaluated,
        "n_with_payout": n_with_payout,
        "win_hits": win_hits,
        "place_hits": place_hits,
        "bet_totals": bet_totals,
    }


def format_report(result: dict) -> str:
    lines = []
    lines.append(f"対象レースファイル数: {result['n_race_files']}")
    lines.append(f"新馬戦除外: {result['n_skipped_shinba']}")
    lines.append(f"その他除外(履歴データ無し等): {result['n_skipped_other']}")
    lines.append(f"検証対象レース数: {result['n_evaluated']}")
    n = result["n_evaluated"]
    if n:
        lines.append("")
        lines.append(f"単勝的中率(1位予測が実際に1着): {result['win_hits']}/{n} = {result['win_hits']/n*100:.1f}%")
        lines.append(f"複勝的中率(1位予測が実際に3着以内): {result['place_hits']}/{n} = {result['place_hits']/n*100:.1f}%")

    lines.append("")
    lines.append(f"払戻データあり(回収率計算対象): {result['n_with_payout']}レース")
    for bt, s in result["bet_totals"].items():
        roi = s["payout"] / s["stake"] * 100 if s["stake"] else 0.0
        lines.append(f"  {bt}: stake={s['stake']} payout={s['payout']} hits={s['hits']} ROI={roi:.1f}%")

    return "\n".join(lines)
