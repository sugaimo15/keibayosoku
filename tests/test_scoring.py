import pandas as pd

from keibayosoku.predict.scoring import score_race_card


def _history_df():
    rows = [
        # horse A: 好成績が続いている
        {"horse_id": "A", "jockey_id": "J1", "date": "2025-01-01", "finish_position": "1", "surface": "芝", "distance_m": 2000},
        {"horse_id": "A", "jockey_id": "J1", "date": "2025-03-01", "finish_position": "2", "surface": "芝", "distance_m": 1800},
        {"horse_id": "A", "jockey_id": "J1", "date": "2025-05-01", "finish_position": "1", "surface": "芝", "distance_m": 2000},
        # horse B: 不振
        {"horse_id": "B", "jockey_id": "J2", "date": "2025-01-01", "finish_position": "10", "surface": "芝", "distance_m": 2000},
        {"horse_id": "B", "jockey_id": "J2", "date": "2025-03-01", "finish_position": "12", "surface": "芝", "distance_m": 2000},
    ]
    return pd.DataFrame(rows)


def test_score_race_card_ranks_better_horse_higher():
    history = _history_df()
    card = pd.DataFrame(
        [
            {"horse_id": "A", "jockey_id": "J1", "horse_name": "Horse A", "horse_weight": "480(0)", "win_odds": "2.0"},
            {"horse_id": "B", "jockey_id": "J2", "horse_name": "Horse B", "horse_weight": "480(0)", "win_odds": "20.0"},
        ]
    )

    scored = score_race_card(card, history, distance_m=2000, surface="芝")

    assert list(scored["horse_name"]) == ["Horse A", "Horse B"]
    assert list(scored["predicted_rank"]) == [1, 2]


def test_score_race_card_handles_empty_history():
    card = pd.DataFrame(
        [
            {"horse_id": "A", "jockey_id": "J1", "horse_name": "Horse A", "horse_weight": "480(0)", "win_odds": "2.0"},
        ]
    )
    scored = score_race_card(card, pd.DataFrame(), distance_m=2000, surface="芝")
    assert len(scored) == 1
    assert scored["predicted_rank"].iloc[0] == 1
