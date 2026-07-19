"""過去のレース結果データから馬・騎手の成績を集計し、
出馬表(これから走るレース)の各馬をルールベースでスコアリングして着順を予測する。

スコアの内訳(重みは経験則による初期値。data/predictions蓄積後にチューニングする想定):
  - 直近成績スコア (過去5走の平均着順)          : 40%
  - 騎手勝率スコア (騎手全体の通算勝率)         : 25%
  - 同条件(距離帯・馬場種別)適性スコア           : 20%
  - 馬体重増減ペナルティ                        : 10%
  - オッズ/人気スコア (発表されていれば)         : 5%

(補足) 騎手×馬の組み合わせ相性(build_horse_jockey_stats)も試したが、07/18・07/19の
実データでリークを除去した上でバックテストしたところ、単勝的中率29.2%→26.2%、
単勝回収率123.5%→73.4%など全指標で悪化したため、score_race_cardへの組み込みは
見送っている(組み合わせ自体のレース数が少なく勝率のノイズが大きいことが原因と推測)。
関数自体は将来の改善(最低レース数によるフィルタ等)のために残してある。
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

WEIGHTS = {
    "recent_form": 0.40,
    "jockey": 0.25,
    "aptitude": 0.20,
    "weight_change": 0.10,
    "odds": 0.05,
}

RECENT_N = 5
DISTANCE_TOLERANCE_M = 400


def _to_numeric_finish(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def build_horse_stats(history: pd.DataFrame) -> pd.DataFrame:
    """horse_id別に成績を集計する。history が空の場合は空DataFrameを返す。"""
    if history.empty or "horse_id" not in history.columns:
        return pd.DataFrame(
            columns=["horse_id", "races", "win_rate", "place_rate", "avg_finish", "avg_finish_recent"]
        ).set_index("horse_id")

    df = history.copy()
    df["finish_num"] = _to_numeric_finish(df["finish_position"])
    df = df.sort_values("date")

    records = []
    for horse_id, g in df.groupby("horse_id"):
        finishes = g["finish_num"].dropna()
        races = len(g)
        wins = (finishes == 1).sum()
        places = (finishes <= 3).sum()
        recent = finishes.tail(RECENT_N)
        records.append(
            {
                "horse_id": horse_id,
                "races": races,
                "win_rate": wins / races if races else 0.0,
                "place_rate": places / races if races else 0.0,
                "avg_finish": finishes.mean() if len(finishes) else np.nan,
                "avg_finish_recent": recent.mean() if len(recent) else np.nan,
            }
        )
    return pd.DataFrame(records).set_index("horse_id")


def build_jockey_stats(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty or "jockey_id" not in history.columns:
        return pd.DataFrame(columns=["jockey_id", "races", "win_rate", "place_rate"]).set_index("jockey_id")

    df = history.copy()
    df["finish_num"] = _to_numeric_finish(df["finish_position"])

    records = []
    for jockey_id, g in df.groupby("jockey_id"):
        finishes = g["finish_num"].dropna()
        races = len(g)
        wins = (finishes == 1).sum()
        places = (finishes <= 3).sum()
        records.append(
            {
                "jockey_id": jockey_id,
                "races": races,
                "win_rate": wins / races if races else 0.0,
                "place_rate": places / races if races else 0.0,
            }
        )
    return pd.DataFrame(records).set_index("jockey_id")


def build_horse_jockey_stats(history: pd.DataFrame) -> pd.DataFrame:
    """(horse_id, jockey_id)の組み合わせ別に成績を集計する。

    同じ馬に同じ騎手が乗り続けている場合の相性を見るためのもの。組み合わせ自体の
    レース数が少ないことが多いため、勝率のノイズが大きい点には注意(_normalizeの
    NaN埋めにより、組み合わせ実績が無い馬は他馬の平均的なスコアになる)。
    """
    if history.empty or "horse_id" not in history.columns or "jockey_id" not in history.columns:
        return pd.DataFrame(columns=["horse_id", "jockey_id", "races", "win_rate", "place_rate"]).set_index(
            ["horse_id", "jockey_id"]
        )

    df = history.copy()
    df["finish_num"] = _to_numeric_finish(df["finish_position"])

    records = []
    for (horse_id, jockey_id), g in df.groupby(["horse_id", "jockey_id"]):
        finishes = g["finish_num"].dropna()
        races = len(g)
        wins = (finishes == 1).sum()
        places = (finishes <= 3).sum()
        records.append(
            {
                "horse_id": horse_id,
                "jockey_id": jockey_id,
                "races": races,
                "win_rate": wins / races if races else 0.0,
                "place_rate": places / races if races else 0.0,
            }
        )
    return pd.DataFrame(records).set_index(["horse_id", "jockey_id"])


def _aptitude_score(history: pd.DataFrame, horse_id: str, distance_m: float | None, surface: str | None) -> float | None:
    if history.empty or distance_m is None or "horse_id" not in history.columns:
        return None
    g = history[history["horse_id"] == horse_id].copy()
    if surface:
        g = g[g["surface"] == surface]
    if "distance_m" in g.columns:
        g = g[(g["distance_m"] - distance_m).abs() <= DISTANCE_TOLERANCE_M]
    if g.empty:
        return None
    finishes = _to_numeric_finish(g["finish_position"]).dropna()
    if finishes.empty:
        return None
    return float(finishes.mean())


def _parse_weight_change(horse_weight: str) -> float | None:
    if not isinstance(horse_weight, str):
        return None
    m = re.search(r"\(([+-]?\d+)\)", horse_weight)
    return float(m.group(1)) if m else None


def _parse_odds(win_odds) -> float | None:
    try:
        v = float(win_odds)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _normalize(series: pd.Series, invert: bool = False) -> pd.Series:
    """0〜1に正規化する。値が全て同じ/欠損のみの場合は0.5で埋める。"""
    s = series.astype(float)
    if s.notna().sum() == 0:
        return pd.Series(0.5, index=s.index)
    filled = s.fillna(s.mean())
    lo, hi = filled.min(), filled.max()
    if hi - lo < 1e-9:
        return pd.Series(0.5, index=s.index)
    norm = (filled - lo) / (hi - lo)
    return 1 - norm if invert else norm


def score_race_card(
    card_df: pd.DataFrame,
    history: pd.DataFrame,
    distance_m: float | None = None,
    surface: str | None = None,
) -> pd.DataFrame:
    """出馬表DataFrameに予測スコアと予測着順を付与して返す。

    card_dfは scraper.race_card.RaceCard.entries から作ったDataFrameを想定。
    historyは storage.load_all_race_results() で読み込んだ過去結果。
    """
    df = card_df.copy()
    horse_stats = build_horse_stats(history)
    jockey_stats = build_jockey_stats(history)

    df["_avg_finish_recent"] = df.get("horse_id", pd.Series(dtype=object)).map(
        horse_stats["avg_finish_recent"] if "avg_finish_recent" in horse_stats.columns else {}
    )
    df["_jockey_win_rate"] = df.get("jockey_id", pd.Series(dtype=object)).map(
        jockey_stats["win_rate"] if "win_rate" in jockey_stats.columns else {}
    )
    df["_aptitude"] = df.get("horse_id", pd.Series(dtype=object)).apply(
        lambda hid: _aptitude_score(history, hid, distance_m, surface) if pd.notna(hid) else None
    )
    weight_change = df.get("horse_weight", pd.Series(dtype=object)).apply(_parse_weight_change)
    df["_weight_change"] = pd.to_numeric(weight_change, errors="coerce").abs()
    df["_odds"] = df.get("win_odds", pd.Series(dtype=object)).apply(_parse_odds)

    recent_form_score = _normalize(df["_avg_finish_recent"], invert=True)
    jockey_score = _normalize(df["_jockey_win_rate"], invert=False)
    aptitude_score = _normalize(df["_aptitude"], invert=True)
    weight_change_score = _normalize(df["_weight_change"], invert=True)
    odds_score = _normalize(df["_odds"], invert=True)

    df["score"] = (
        WEIGHTS["recent_form"] * recent_form_score
        + WEIGHTS["jockey"] * jockey_score
        + WEIGHTS["aptitude"] * aptitude_score
        + WEIGHTS["weight_change"] * weight_change_score
        + WEIGHTS["odds"] * odds_score
    )

    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df["predicted_rank"] = df.index + 1

    drop_cols = [c for c in df.columns if c.startswith("_")]
    return df.drop(columns=drop_cols)
