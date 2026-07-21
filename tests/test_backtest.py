import pandas as pd

from keibayosoku.predict.backtest import evaluate_race, score_card_fast


def _history_df():
    rows = [
        {"horse_id": "A", "jockey_id": "J1", "date": "2025-01-01", "finish_position": "1", "surface": "芝", "distance_m": 2000},
        {"horse_id": "A", "jockey_id": "J1", "date": "2025-03-01", "finish_position": "2", "surface": "芝", "distance_m": 1800},
        {"horse_id": "B", "jockey_id": "J2", "date": "2025-01-01", "finish_position": "10", "surface": "芝", "distance_m": 2000},
        {"horse_id": "B", "jockey_id": "J2", "date": "2025-03-01", "finish_position": "12", "surface": "芝", "distance_m": 2000},
    ]
    df = pd.DataFrame(rows)
    df["finish_num"] = pd.to_numeric(df["finish_position"], errors="coerce")
    return df


def test_score_card_fast_ranks_better_horse_higher():
    history = _history_df()
    card = pd.DataFrame(
        [
            {"horse_id": "A", "jockey_id": "J1", "horse_name": "Horse A", "horse_weight": "480(0)", "win_odds": "2.0"},
            {"horse_id": "B", "jockey_id": "J2", "horse_name": "Horse B", "horse_weight": "480(0)", "win_odds": "20.0"},
        ]
    )
    scored = score_card_fast(card, history, distance_m=2000, surface="芝")
    assert list(scored.sort_values("predicted_rank")["horse_name"]) == ["Horse A", "Horse B"]


def _scored_df(finish_nums, horse_numbers):
    return pd.DataFrame(
        {
            "predicted_rank": range(1, len(finish_nums) + 1),
            "horse_number": horse_numbers,
            "finish_num": finish_nums,
        }
    )


def test_evaluate_race_win_and_place_hit():
    scored = _scored_df(finish_nums=[1, 2, 3, 4, 5], horse_numbers=[7, 3, 9, 1, 5])
    payouts = pd.DataFrame(
        [
            {"bet_type": "単勝", "combination": "7", "amount": 250},
            {"bet_type": "複勝", "combination": "7", "amount": 130},
        ]
    )
    result = evaluate_race(scored, payouts)
    assert result["win_hit"] is True
    assert result["place_hit"] is True
    assert result["has_payout"] is True
    assert result["bet_stats"]["単勝"] == {"stake": 100, "payout": 250, "hits": 1}
    assert result["bet_stats"]["複勝"] == {"stake": 100, "payout": 130, "hits": 1}


def test_evaluate_race_miss_when_top_pick_loses():
    scored = _scored_df(finish_nums=[5, 1, 2, 3, 4], horse_numbers=[7, 3, 9, 1, 5])
    payouts = pd.DataFrame([{"bet_type": "単勝", "combination": "3", "amount": 250}])
    result = evaluate_race(scored, payouts)
    assert result["win_hit"] is False
    assert result["place_hit"] is False
    assert result["bet_stats"]["単勝"] == {"stake": 100, "payout": 0, "hits": 0}


def test_evaluate_race_box_bet_hits_regardless_of_order():
    """三連単/三連単以外のボックス買いは、上位5頭のどの組み合わせが的中しても回収される。"""
    scored = _scored_df(finish_nums=[3, 1, 2, 4, 5], horse_numbers=[7, 3, 9, 1, 5])
    payouts = pd.DataFrame([{"bet_type": "三連複", "combination": "3-7-9", "amount": 5000}])
    result = evaluate_race(scored, payouts)
    assert result["bet_stats"]["三連複"]["hits"] == 1
    assert result["bet_stats"]["三連複"]["payout"] == 5000


def test_evaluate_race_no_payout_data():
    scored = _scored_df(finish_nums=[1], horse_numbers=[1])
    result = evaluate_race(scored, pd.DataFrame())
    assert result["has_payout"] is False
    assert result["bet_stats"]["単勝"]["payout"] == 0
