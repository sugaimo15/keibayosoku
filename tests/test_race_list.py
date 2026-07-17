from pathlib import Path

from keibayosoku.scraper.race_list import find_sub_url_for_date, parse_race_list

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_race_list():
    html = (FIXTURES / "race_list_fragment_sample.html").read_text(encoding="utf-8")
    items = parse_race_list(html)

    assert len(items) == 2
    assert items[0].race_id == "202605010101"
    assert items[0].race_name == "2歳未勝利"
    assert items[1].race_id == "202605010102"
    assert items[1].race_name == "3歳未勝利"


def test_find_sub_url_for_date_matches_active_day():
    html = (FIXTURES / "race_date_tabs_sample.html").read_text(encoding="utf-8")
    url = find_sub_url_for_date(html, "20260718")

    assert url == "https://race.netkeiba.com/top/race_list_sub.html?kaisai_date=20260718&current_group=1020260718"


def test_find_sub_url_for_date_matches_other_day_in_same_group():
    html = (FIXTURES / "race_date_tabs_sample.html").read_text(encoding="utf-8")
    url = find_sub_url_for_date(html, "20260719")

    assert url == "https://race.netkeiba.com/top/race_list_sub.html?kaisai_date=20260719&current_group=1020260718"


def test_find_sub_url_for_date_returns_none_when_no_races():
    html = (FIXTURES / "race_date_tabs_no_race_sample.html").read_text(encoding="utf-8")
    url = find_sub_url_for_date(html, "20260717")

    assert url is None
