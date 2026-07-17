from pathlib import Path

from keibayosoku.scraper.horse_history import parse_horse_history

FIXTURE = Path(__file__).parent / "fixtures" / "horse_history_sample.html"


def test_parse_horse_history():
    html = FIXTURE.read_text(encoding="utf-8")
    history = parse_horse_history("2021104567", html)

    assert history.horse_name == "サンプルホース"
    assert len(history.races) == 2

    first = history.races[0]
    assert first["date"] == "2026/05/10"
    assert first["race_name"] == "テストステークス"
    assert first["race_id"] == "202605050811"
    assert first["finish_position"] == "1"
    assert first["jockey_id"] == "01234"
    assert first["surface"] == "芝"
    assert first["distance_m"] == 1800

    second = history.races[1]
    assert second["surface"] == "ダート"
    assert second["distance_m"] == 1600
    assert second["track_condition"] == "稍重"
