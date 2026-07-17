from pathlib import Path

from keibayosoku.scraper.race_result import parse_race_result

FIXTURE = Path(__file__).parent / "fixtures" / "race_result_sample.html"
HURDLE_FIXTURE = Path(__file__).parent / "fixtures" / "race_result_hurdle_sample.html"


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


def test_parse_race_result_hurdle_track_condition_label():
    """障害レースは "馬場: 良" ではなく "芝: 良" のように馬場種別自体がラベルになる。

    実データ(backfillテスト)で発見した回帰: jockey/trainer detail link が
    /jockey/result/recent/{id}/ 形式である点、着差が空欄の点も併せて検証する。
    """
    html = HURDLE_FIXTURE.read_text(encoding="utf-8")
    result = parse_race_result("202603020501", html)

    assert result.surface == "芝"
    assert result.distance_m == 3380
    assert result.track_condition == "良"

    first = result.entries[0]
    assert first["jockey_id"] == "01101"
    assert first["trainer_id"] == "01166"
