import pandas as pd

from keibayosoku import storage


def test_load_all_horse_histories_normalizes_slash_dates(tmp_path):
    """horse_historiesの日付は"2026/05/03"形式で保存されており、race_resultsの
    "2026-07-18"形式と文字列比較すると常に大きい('/' > '-')と判定されてしまう。

    実データで、バックテストの日付カットオフ(date < cutoff)からhorse_histories側の
    5,800行超が丸ごと除外されていたバグの回帰テスト。読み込み時にISO形式へ
    正規化されることを確認する。
    """
    df = pd.DataFrame(
        [
            {"horse_id": "A", "date": "2026/05/03", "finish_position": "1"},
            {"horse_id": "A", "date": "2025/12/28", "finish_position": "2"},
        ]
    )
    df.to_csv(tmp_path / "A.csv", index=False, encoding="utf-8-sig")

    loaded = storage.load_all_horse_histories(base_dir=tmp_path)
    assert list(loaded["date"]) == ["2026-05-03", "2025-12-28"]
    # 正規化後はISO形式同士なので文字列比較が時系列比較として機能する
    assert (loaded["date"] < "2026-07-18").all()


def test_normalize_date_column_keeps_unparseable_values():
    df = pd.DataFrame({"date": ["2026-07-18", "不明", None]})
    normalized = storage._normalize_date_column(df)
    assert normalized["date"].iloc[0] == "2026-07-18"
    assert normalized["date"].iloc[1] == "不明"
