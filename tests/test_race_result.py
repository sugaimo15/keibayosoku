from pathlib import Path

from keibayosoku.scraper.race_result import parse_race_result

FIXTURE = Path(__file__).parent / "fixtures" / "race_result_sample.html"


def test_parse_race_result_info():
    html = FIXTURE.read_text(encoding="utf-8")
    result = parse_race_result("202506050812", html)

    assert result.race_name == "サンプルステークス"
    assert result.date == "2025-12-28"
    assert result.surface == "芝"
    assert result.distance_m == 2000
    assert result.direction == "右"
    assert result.weather == "晴"
    assert result.track_condition == "良"


def test_parse_race_result_entries():
    html = FIXTURE.read_text(encoding="utf-8")
    result = parse_race_result("202506050812", html)

    assert len(result.entries) == 3
    first = result.entries[0]
    assert first["finish_position"] == "1"
    assert first["horse_name"] == "サンプルホース"
    assert first["horse_id"] == "2021104567"
    assert first["jockey_id"] == "01234"
    assert first["trainer_id"] == "01111"
    assert first["horse_weight"] == "492(+2)"
