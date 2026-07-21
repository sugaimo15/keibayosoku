import numpy as np
import pandas as pd

from keibayosoku.predict.ml_model import (
    FEATURES,
    _prepare_history,
    build_horse_features,
    load_model,
    predict_win_probabilities,
    save_model,
    train_model,
)


def _history_df():
    rows = []
    # horse A: 直近好調・上がりも速い / horse B: 不振
    for i, (fin, l3f) in enumerate([("1", "34.0"), ("2", "34.5"), ("1", "33.8")]):
        rows.append(
            {"horse_id": "A", "jockey_id": "J1", "date": f"2025-0{i+1}-01",
             "finish_position": fin, "last_3f": l3f, "surface": "芝", "distance_m": 2000,
             "track_condition": "良"}
        )
    for i, (fin, l3f) in enumerate([("10", "37.0"), ("12", "37.5")]):
        rows.append(
            {"horse_id": "B", "jockey_id": "J2", "date": f"2025-0{i+1}-01",
             "finish_position": fin, "last_3f": l3f, "surface": "芝", "distance_m": 2000,
             "track_condition": "良"}
        )
    return pd.DataFrame(rows)


def _card_df():
    return pd.DataFrame(
        [
            {"horse_id": "A", "jockey_id": "J1", "horse_name": "Horse A", "horse_weight": "480(0)",
             "win_odds": "2.0", "popularity": "1", "weight_carried": "57"},
            {"horse_id": "B", "jockey_id": "J2", "horse_name": "Horse B", "horse_weight": "470(-2)",
             "win_odds": "20.0", "popularity": "8", "weight_carried": "55"},
        ]
    )


def test_build_horse_features_produces_all_feature_columns():
    hist = _prepare_history(_history_df())
    feats = build_horse_features(_card_df(), hist, distance_m=2000, surface="芝", race_date="2025-06-01")
    assert len(feats) == 2
    for col in FEATURES:
        assert col in feats.columns
    a = feats[feats["horse_id"] == "A"].iloc[0]
    assert a["win_rate"] == 2 / 3
    assert a["no_history"] == 0.0
    assert a["days_since_last"] == 92  # 2025-03-01 -> 2025-06-01


def test_build_horse_features_handles_first_time_starter():
    hist = _prepare_history(_history_df())
    card = pd.DataFrame([{"horse_id": "NEW", "jockey_id": "J9", "horse_name": "New Horse"}])
    feats = build_horse_features(card, hist, race_date="2025-06-01")
    row = feats.iloc[0]
    assert row["no_history"] == 1.0
    assert pd.isna(row["win_rate"])
    assert pd.isna(row["log_odds"])


def _training_df(n_races=30):
    """学習可能な最小限の合成データ: オッズが低い馬が勝ちやすい構造にする。"""
    rng = np.random.default_rng(0)
    rows = []
    for r in range(n_races):
        n_horses = 6
        winner = rng.integers(0, 2)  # 低オッズ側の2頭のどちらかが勝つ
        for h in range(n_horses):
            feat = {f: rng.normal() for f in FEATURES}
            feat["log_odds"] = np.log(2.0 + h * 3)
            feat.update(
                {"race_id": f"R{r}", "date": f"2026-05-{r % 28 + 1:02d}",
                 "horse_id": f"{r}-{h}", "win": 1 if h == winner else 0}
            )
            rows.append(feat)
    return pd.DataFrame(rows)


def test_train_save_load_predict_roundtrip(tmp_path):
    artifact = train_model(_training_df())
    assert len(artifact["coef"]) == len(FEATURES)

    path = save_model(artifact, tmp_path / "model.json")
    loaded = load_model(path)
    assert loaded["coef"] == artifact["coef"]

    hist = _history_df()
    out = predict_win_probabilities(
        _card_df(), hist, loaded, distance_m=2000, surface="芝", race_date="2025-06-01"
    )
    assert len(out) == 2
    assert abs(out["ml_win_prob"].sum() - 1.0) < 1e-9
    assert set(out["ml_rank"]) == {1, 2}
    # EV = 勝率×オッズ
    a = out[out["horse_id"] == "A"].iloc[0]
    assert abs(a["ml_ev"] - a["ml_win_prob"] * 2.0) < 1e-9


def test_load_model_returns_none_when_missing(tmp_path):
    assert load_model(tmp_path / "nope.json") is None
