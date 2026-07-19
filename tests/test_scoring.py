import pandas as pd

from keibayosoku.predict.scoring import build_horse_jockey_stats, score_race_card, _track_condition_score


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


def test_build_horse_jockey_stats_computes_combo_win_rate():
    history = _history_df()
    stats = build_horse_jockey_stats(history)

    assert stats.loc[("A", "J1"), "races"] == 3
    assert stats.loc[("A", "J1"), "win_rate"] == 2 / 3
    assert stats.loc[("B", "J2"), "win_rate"] == 0.0


def test_track_condition_score_prefers_matching_bucket():
    history = pd.DataFrame(
        [
            # horse C: 良馬場は不振、道悪(稍重/不良)は好走 = 道悪巧者
            {"horse_id": "C", "finish_position": "10", "track_condition": "良"},
            {"horse_id": "C", "finish_position": "9", "track_condition": "良"},
            {"horse_id": "C", "finish_position": "1", "track_condition": "不良"},
            {"horse_id": "C", "finish_position": "2", "track_condition": "稍重"},
        ]
    )
    good_score = _track_condition_score(history, "C", "良")
    off_score = _track_condition_score(history, "C", "不良")
    assert good_score == 9.5
    assert off_score == 1.5


def test_track_condition_score_none_when_not_announced():
    history = pd.DataFrame([{"horse_id": "C", "finish_position": "1", "track_condition": "良"}])
    assert _track_condition_score(history, "C", None) is None


def test_score_race_card_uses_track_condition_when_available():
    history = pd.DataFrame(
        [
            # 道悪巧者(不良で好走、良で不振)
            {"horse_id": "A", "jockey_id": "J1", "date": "2025-01-01", "finish_position": "8", "track_condition": "良"},
            {"horse_id": "A", "jockey_id": "J1", "date": "2025-02-01", "finish_position": "1", "track_condition": "不良"},
            # 良馬場巧者(良で好走、不良で不振)
            {"horse_id": "B", "jockey_id": "J2", "date": "2025-01-01", "finish_position": "1", "track_condition": "良"},
            {"horse_id": "B", "jockey_id": "J2", "date": "2025-02-01", "finish_position": "8", "track_condition": "不良"},
        ]
    )
    card = pd.DataFrame(
        [
            {"horse_id": "A", "jockey_id": "J1", "horse_name": "Horse A", "horse_weight": "480(0)", "win_odds": "5.0"},
            {"horse_id": "B", "jockey_id": "J2", "horse_name": "Horse B", "horse_weight": "480(0)", "win_odds": "5.0"},
        ]
    )
    scored = score_race_card(card, history, track_condition="不良")
    assert scored.loc[scored["horse_name"] == "Horse A", "predicted_rank"].iloc[0] == 1


def test_score_race_card_handles_unparseable_horse_weight():
    """馬体重が「計不」等で(+n)形式に一致しない場合でもクラッシュしないこと。

    実データで score_race_card(...).abs() が TypeError: bad operand type for
    abs(): 'NoneType' で落ちたことがあるための回帰テスト。
    """
    card = pd.DataFrame(
        [
            {"horse_id": "A", "jockey_id": "J1", "horse_name": "Horse A", "horse_weight": "計不", "win_odds": "2.0"},
            {"horse_id": "B", "jockey_id": "J2", "horse_name": "Horse B", "horse_weight": "480(+2)", "win_odds": "5.0"},
        ]
    )
    scored = score_race_card(card, pd.DataFrame(), distance_m=2000, surface="芝")
    assert len(scored) == 2
