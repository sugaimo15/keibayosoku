from pathlib import Path

from keibayosoku.scraper.race_card import parse_race_card

FIXTURE = Path(__file__).parent / "fixtures" / "race_card_sample.html"


def test_parse_race_card():
    html = FIXTURE.read_text(encoding="utf-8")
    card = parse_race_card("202506050812", html)

    assert card.race_name == "サンプルステークス"
    assert card.surface == "ダート"
    assert card.distance_m == 1200
    assert len(card.entries) == 3

    first = card.entries[0]
    assert first["horse_name"] == "サンプルホース"
    assert first["horse_id"] == "2021104567"
    assert first["jockey_id"] == "01234"
    assert first["horse_weight"] == "492(+2)"
