from pathlib import Path

from keibayosoku.scraper.race_list import parse_race_list

FIXTURE = Path(__file__).parent / "fixtures" / "race_list_fragment_sample.html"


def test_parse_race_list():
    html = FIXTURE.read_text(encoding="utf-8")
    items = parse_race_list(html)

    assert len(items) == 2
    assert items[0].race_id == "202605010101"
    assert items[0].race_name == "2歳未勝利"
    assert items[1].race_id == "202605010102"
    assert items[1].race_name == "3歳未勝利"
