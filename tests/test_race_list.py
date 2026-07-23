from pathlib import Path

from keibayosoku.scraper.race_list import find_sub_url_for_date, parse_db_race_list, parse_race_list

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


def test_parse_db_race_list_extracts_race_ids():
    """db.netkeiba.comの日付別レース一覧: /race/{12桁}/ 形式のリンクからrace_idを拾う。

    馬・騎手など他のリンクや、race_idでないリンクは無視されること。
    """
    html = """
    <html><body>
      <a href="/race/202301010101/">3歳未勝利</a>
      <a href="/race/202301010102/">サンプル特別</a>
      <a href="/race/202301010101/">重複リンク</a>
      <a href="/horse/2020104567/">馬リンク</a>
      <a href="/race/list/20230105/">別の日</a>
    </body></html>
    """
    items = parse_db_race_list(html)
    assert [i.race_id for i in items] == ["202301010101", "202301010102"]
    assert items[0].race_name == "3歳未勝利"


def test_parse_db_race_list_empty_when_no_races():
    items = parse_db_race_list("<html><body><p>該当するレースがありません</p></body></html>")
    assert items == []
