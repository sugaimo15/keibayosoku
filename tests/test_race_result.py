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


def test_parse_race_result_payouts():
    html = FIXTURE.read_text(encoding="utf-8")
    result = parse_race_result("202506050812", html)

    payouts = {(p["bet_type"], p["combination"]): p for p in result.payouts}
    assert payouts[("単勝", "5")]["amount"] == 210
    assert payouts[("単勝", "5")]["popularity"] == 1

    fuku = [p for p in result.payouts if p["bet_type"] == "複勝"]
    assert len(fuku) == 3
    assert {p["combination"] for p in fuku} == {"5", "2", "8"}
    assert payouts[("複勝", "8")]["amount"] == 340

    assert payouts[("枠連", "1-3")]["amount"] == 480
    assert payouts[("馬連", "2-5")]["amount"] == 560

    wide = [p for p in result.payouts if p["bet_type"] == "ワイド"]
    assert len(wide) == 3
    assert payouts[("ワイド", "5-8")]["amount"] == 420

    # 馬単・三連単は"→"区切りだが、他の組番と表記を揃えるため"-"に正規化する。
    assert payouts[("馬単", "5-2")]["amount"] == 1020
    assert payouts[("三連複", "2-5-8")]["amount"] == 3140
    assert payouts[("三連単", "5-2-8")]["amount"] == 12600
    assert payouts[("三連単", "5-2-8")]["popularity"] == 27


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
