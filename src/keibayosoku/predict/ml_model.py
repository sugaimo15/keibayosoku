"""ロジスティック回帰による勝率モデルの学習・保存・推論。

ルールベースのスコアリング(scoring.py)と違い、勝率そのもの(確率)を出力する。
確率が出ると「期待値 = 勝率 × 単勝オッズ」が計算でき、期待値が1を超える
(=市場が過小評価しているとモデルが判断した)馬だけを買う期待値ベッティングが
可能になる。2026-07-01より前の712レースで学習し7月の193レースでテストした
時系列分割の検証では、1位予測の単勝的中率がルールベース18.7%に対して32.1%、
期待値1.0以上の馬のみ購入で回収率126.3%(169点)という結果だった
(ただし的中20件の小サンプルであり、継続検証が必要)。

学習はscikit-learnを使うが、推論(predict_win_probabilities)はnumpyだけで
動くよう、モデルは係数・標準化パラメータをJSONで保存する(pickleを使わない)。
特徴量は各レースの日付より前の履歴だけから計算する(リーク除去)。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .. import storage
from .scoring import (
    RECENT_N,
    _aptitude_score,
    _parse_weight_change,
    _to_numeric_finish,
    _track_condition_score,
)

MODEL_PATH = storage.DATA_DIR / "model" / "ml_model.json"

FEATURES = [
    "n_races_log", "win_rate", "place_rate", "avg_finish_recent", "avg_last3f_recent",
    "days_since_last", "no_history",
    "jockey_win_rate", "jockey_n_log",
    "aptitude", "track_cond",
    "weight_change_abs", "weight_carried", "field_size",
    "log_odds", "popularity",
]

# 休み明けの日数はこの値で頭打ちにする(数年ぶりの出走などの外れ値対策)
DAYS_SINCE_LAST_CAP = 365


def _prepare_history(history: pd.DataFrame) -> pd.DataFrame:
    """特徴量計算に使う派生列(数値着順・日付・上がり3F)を事前計算する。"""
    df = history.copy()
    df["finish_num"] = _to_numeric_finish(df["finish_position"]) if "finish_position" in df.columns else np.nan
    df["date_dt"] = pd.to_datetime(df["date"], errors="coerce") if "date" in df.columns else pd.NaT
    df["last_3f_num"] = pd.to_numeric(df.get("last_3f"), errors="coerce")
    return df


def build_horse_features(
    card_df: pd.DataFrame,
    hist_before: pd.DataFrame,
    distance_m: float | None = None,
    surface: str | None = None,
    track_condition: str | None = None,
    race_date: str | None = None,
) -> pd.DataFrame:
    """出馬表の各馬について、hist_before(そのレースより前の履歴)だけから
    特徴量を計算して返す。hist_beforeは_prepare_history()済みであること。
    """
    race_date_dt = pd.to_datetime(race_date) if race_date else pd.NaT
    field_size = len(card_df)

    rows = []
    for _, row in card_df.iterrows():
        horse_id = row.get("horse_id")
        jockey_id = row.get("jockey_id")
        win_odds = pd.to_numeric(row.get("win_odds"), errors="coerce")
        popularity = pd.to_numeric(row.get("popularity"), errors="coerce")

        g = hist_before[hist_before["horse_id"] == horse_id] if pd.notna(horse_id) else hist_before.iloc[0:0]
        finishes = g["finish_num"].dropna()
        recent = finishes.tail(RECENT_N)
        last3f_recent = g["last_3f_num"].dropna().tail(RECENT_N)
        last_date = g["date_dt"].max() if len(g) else pd.NaT
        days_since = (race_date_dt - last_date).days if pd.notna(race_date_dt) and pd.notna(last_date) else np.nan

        jg = hist_before[hist_before["jockey_id"] == jockey_id] if pd.notna(jockey_id) else hist_before.iloc[0:0]
        j_finishes = jg["finish_num"].dropna()

        rows.append(
            {
                "horse_id": horse_id,
                "n_races_log": np.log1p(len(g)),
                "win_rate": (finishes == 1).mean() if len(finishes) else np.nan,
                "place_rate": (finishes <= 3).mean() if len(finishes) else np.nan,
                "avg_finish_recent": recent.mean() if len(recent) else np.nan,
                "avg_last3f_recent": last3f_recent.mean() if len(last3f_recent) else np.nan,
                "days_since_last": min(days_since, DAYS_SINCE_LAST_CAP) if pd.notna(days_since) else np.nan,
                "no_history": 1.0 if len(g) == 0 else 0.0,
                "jockey_win_rate": (j_finishes == 1).mean() if len(j_finishes) else np.nan,
                "jockey_n_log": np.log1p(len(jg)),
                "aptitude": _aptitude_score(hist_before, horse_id, distance_m, surface) if pd.notna(horse_id) else None,
                "track_cond": _track_condition_score(hist_before, horse_id, track_condition) if pd.notna(horse_id) else None,
                "weight_change_abs": abs(w) if (w := _parse_weight_change(row.get("horse_weight"))) is not None else np.nan,
                "weight_carried": pd.to_numeric(row.get("weight_carried"), errors="coerce"),
                "field_size": field_size,
                "log_odds": np.log(win_odds) if pd.notna(win_odds) and win_odds > 0 else np.nan,
                "popularity": popularity,
            }
        )
    return pd.DataFrame(rows)


def build_training_data(
    race_files: list[Path] | None = None,
    full_history: pd.DataFrame | None = None,
    exclude_shinba: bool = True,
    progress_every: int | None = 100,
) -> pd.DataFrame:
    """バックフィル済みの全レースについて、リークを除去した特徴量+勝敗ラベルを作る。

    返り値はFEATURES列に加えて race_id/date/horse_id/win 列を含むDataFrame。
    """
    import sys

    if race_files is None:
        race_files = sorted(storage.RACE_RESULTS_DIR.glob("*/*.csv"))
    if full_history is None:
        full_history = pd.concat(
            [storage.load_all_race_results(), storage.load_all_horse_histories()], ignore_index=True
        )
        full_history = full_history.drop_duplicates(subset=["race_id", "horse_id"], keep="first")
    full_history = _prepare_history(full_history).sort_values("date").reset_index(drop=True)

    frames = []
    for i, f in enumerate(race_files):
        card_df = pd.read_csv(f)
        if card_df.empty or "horse_id" not in card_df.columns:
            continue
        race_name = str(card_df["race_name"].iloc[0]) if "race_name" in card_df.columns else ""
        if exclude_shinba and "新馬" in race_name:
            continue
        race_date = card_df["date"].iloc[0] if "date" in card_df.columns else None
        if pd.isna(race_date):
            continue
        hist_before = full_history[full_history["date"] < race_date]
        if hist_before.empty:
            continue

        distance_m = card_df["distance_m"].iloc[0] if "distance_m" in card_df.columns else None
        surface = card_df["surface"].iloc[0] if "surface" in card_df.columns else None
        track_condition = card_df["track_condition"].iloc[0] if "track_condition" in card_df.columns else None
        if pd.isna(track_condition):
            track_condition = None

        feats = build_horse_features(
            card_df, hist_before, distance_m, surface, track_condition, race_date=race_date
        )
        feats["race_id"] = card_df["race_id"].iloc[0]
        feats["date"] = race_date
        feats["win"] = (_to_numeric_finish(card_df["finish_position"]) == 1).astype(int).values
        frames.append(feats)

        if progress_every and (i + 1) % progress_every == 0:
            print(f"  [train-data] {i + 1}/{len(race_files)} 処理済み", file=sys.stderr)

    if not frames:
        return pd.DataFrame(columns=FEATURES + ["race_id", "date", "horse_id", "win"])
    return pd.concat(frames, ignore_index=True)


def train_model(training_df: pd.DataFrame) -> dict:
    """FEATURES+win列を持つDataFrameからロジスティック回帰を学習し、
    JSON保存可能なモデルアーティファクト(係数・標準化パラメータ・欠損埋め値)を返す。
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    X = training_df[FEATURES].astype(float)
    medians = X.median().fillna(0.0)
    X = X.fillna(medians)
    scaler = StandardScaler().fit(X)
    model = LogisticRegression(max_iter=2000, C=1.0)
    model.fit(scaler.transform(X), training_df["win"])

    return {
        "features": FEATURES,
        "medians": {k: float(v) for k, v in medians.items()},
        "scaler_mean": [float(v) for v in scaler.mean_],
        "scaler_scale": [float(v) for v in scaler.scale_],
        "coef": [float(v) for v in model.coef_[0]],
        "intercept": float(model.intercept_[0]),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_train_rows": int(len(training_df)),
        "n_train_races": int(training_df["race_id"].nunique()),
    }


def save_model(artifact: dict, path: Path = MODEL_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_model(path: Path = MODEL_PATH) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _predict_raw(features_df: pd.DataFrame, artifact: dict) -> np.ndarray:
    """保存済みアーティファクトからnumpyのみで勝率(正規化前)を計算する。"""
    X = features_df[artifact["features"]].astype(float)
    X = X.fillna(pd.Series(artifact["medians"]))
    mean = np.array(artifact["scaler_mean"])
    scale = np.array(artifact["scaler_scale"])
    Xs = (X.values - mean) / scale
    logits = Xs @ np.array(artifact["coef"]) + artifact["intercept"]
    return 1.0 / (1.0 + np.exp(-logits))


def predict_win_probabilities(
    card_df: pd.DataFrame,
    history: pd.DataFrame,
    artifact: dict,
    distance_m: float | None = None,
    surface: str | None = None,
    track_condition: str | None = None,
    race_date: str | None = None,
) -> pd.DataFrame:
    """出馬表の各馬の勝率(レース内で合計1に正規化)と期待値を計算して返す。

    推論はnumpyのみで行う(scikit-learn不要)。返り値はhorse_id, ml_win_prob,
    ml_ev(オッズがあれば), ml_rank の列を持つDataFrame。
    """
    hist = _prepare_history(history)
    feats = build_horse_features(
        card_df, hist, distance_m, surface, track_condition, race_date=race_date
    )
    p_raw = _predict_raw(feats, artifact)

    total = p_raw.sum()
    p_norm = p_raw / total if total > 0 else np.full_like(p_raw, 1.0 / max(len(p_raw), 1))

    out = pd.DataFrame({"horse_id": feats["horse_id"], "ml_win_prob": p_norm})
    win_odds = pd.to_numeric(card_df.get("win_odds"), errors="coerce")
    out["ml_ev"] = out["ml_win_prob"].values * win_odds.values
    out["ml_rank"] = out["ml_win_prob"].rank(ascending=False, method="first").astype(int)
    return out


EV_THRESHOLDS = [1.0, 1.1, 1.2, 1.3, 1.5]


def evaluate_time_split(training_df: pd.DataFrame, split_date: str) -> str:
    """時系列分割(split_dateより前で学習/以降でテスト)の評価レポートを返す。

    単勝の払戻は「確定オッズ×100円」と等価なので、payoutファイルを引かずに
    log_odds特徴量から復元したオッズで回収率を計算する。
    """
    train = training_df[training_df["date"] < split_date]
    test = training_df[training_df["date"] >= split_date].copy()
    if train.empty or test.empty:
        return f"学習またはテストデータが空です(split={split_date}, 学習{len(train)}行/テスト{len(test)}行)"

    artifact = train_model(train)
    test["p_raw"] = _predict_raw(test, artifact)
    test["p_norm"] = test.groupby("race_id")["p_raw"].transform(lambda s: s / s.sum())
    test["odds"] = np.exp(test["log_odds"])
    test["ev"] = test["p_norm"] * test["odds"]

    lines = []
    lines.append(
        f"学習: {train['race_id'].nunique()}レース {len(train)}行 / "
        f"テスト: {test['race_id'].nunique()}レース {len(test)}行 (split={split_date})"
    )

    top1 = test.loc[test.groupby("race_id")["p_norm"].idxmax()]
    n = len(top1)
    hits = int(top1["win"].sum())
    payout = (top1["win"] * top1["odds"] * 100).sum()
    roi = payout / (n * 100) * 100 if n else 0.0
    lines.append(f"ML1位予測: n={n} 的中={hits} ({hits/n*100:.1f}%) 単勝ROI={roi:.1f}%")

    lines.append("期待値ベッティング(単勝、しきい値別):")
    for th in EV_THRESHOLDS:
        sub = test[(test["ev"] >= th) & test["odds"].notna()]
        n = len(sub)
        hits = int(sub["win"].sum())
        payout = (sub["win"] * sub["odds"] * 100).sum()
        roi = payout / (n * 100) * 100 if n else 0.0
        hr = hits / n * 100 if n else 0.0
        lines.append(f"  EV>={th:.1f}: n={n} 的中={hits} ({hr:.1f}%) ROI={roi:.1f}%")

    return "\n".join(lines)
