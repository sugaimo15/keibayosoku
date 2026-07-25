from pathlib import Path

from keibayosoku.scraper.race_card import _is_abroad_race_id, parse_odds_response, parse_race_card

FIXTURE = Path(__file__).parent / "fixtures" / "race_card_sample.html"
ODDS_RESULT_FIXTURE = Path(__file__).parent / "fixtures" / "odds_api_result_sample.json"
ABROAD_FIXTURE = Path(__file__).parent / "fixtures" / "race_card_abroad_sample.html"


def test_parse_race_card():
    html = FIXTURE.read_text(encoding="utf-8")
    card = parse_race_card("202506050812", html)

    assert card.race_name == "サンプルステークス"
    assert card.surface == "ダート"
    assert card.distance_m == 1200
    assert card.track_condition == "稍重"
    assert len(card.entries) == 3

    first = card.entries[0]
    assert first["waku"] == "1"
    assert first["horse_number"] == "1"
    assert first["horse_name"] == "サンプルホース"
    assert first["horse_id"] == "2021104567"
    assert first["weight_carried"] == "58.0"
    assert first["jockey_id"] == "01234"
    assert first["trainer_id"] == "01111"
    assert first["horse_weight"] == "492(+2)"

    second = card.entries[1]
    assert second["waku"] == "2"
    assert second["horse_number"] == "2"
    assert second["weight_carried"] == "56.0"
    assert second["jockey_id"] == "05678"
    assert second["trainer_id"] == "02222"


def test_parse_race_card_missing_track_condition():
    """発走当日の朝より前など、馬場状態がまだ発表されていない場合はNoneになること。"""
    html = """
    <div class="RaceName">サンプルステークス</div>
    <div class="RaceData01">15:35発走 / ダ1200m (右)</div>
    <table class="Shutuba_Table"></table>
    """
    card = parse_race_card("202506050812", html)
    assert card.track_condition is None


def test_is_abroad_race_id():
    assert _is_abroad_race_id("2026A0010105") is True
    assert _is_abroad_race_id("202601010107") is False


def test_parse_race_card_abroad_race():
    """海外レース(shutuba_abroad.html)は国内版とテーブルのクラス名が共通なので、
    parse_race_card()をそのまま流用できることの回帰テスト(実データ: 2026年
    キングジョージ, race_id=2026A0010105)。日本調教馬・海外調教馬が混在し、
    horse_id/jockey_idの形式も数値/16進数文字列が混在する。
    """
    html = ABROAD_FIXTURE.read_text(encoding="utf-8")
    card = parse_race_card("2026A0010105", html)

    assert card.race_name == "キングジョージ"
    assert card.surface == "芝"
    assert card.distance_m == 2390
    assert len(card.entries) == 9

    # 海外調教馬(16進数のhorse_id、馬体重列自体が無いのでhorse_weightは空)
    foreign = next(e for e in card.entries if e["horse_name"] == "ミニーホーク")
    assert foreign["horse_id"] == "000a029d4f"
    assert foreign["jockey_id"] == "a02c7"
    assert foreign["win_odds"] == "20.0"
    assert foreign["horse_weight"] == ""

    # 日本調教馬(通常の数値ID)も同じレースに混在する
    japan_trained = next(e for e in card.entries if e["horse_name"] == "マスカレードボール")
    assert japan_trained["horse_id"] == "2022105519"
    assert japan_trained["jockey"] == "ルメール"


def test_parse_odds_response_real_data():
    """実データ(2026/07/25 札幌1R、発走直後に取得したレスポンス)でのパース確認。

    出馬表ページの静的HTMLには単勝オッズが"---.-"のプレースホルダーしか
    無く、実際の値は非同期API(api_get_jra_odds.html)から取得する必要がある
    ことが実データ調査で判明したため、そのレスポンス形式に対するパーサー。
    """
    json_text = ODDS_RESULT_FIXTURE.read_text(encoding="utf-8")
    odds = parse_odds_response(json_text)

    assert odds[3]["win_odds"] == 2.3
    assert odds[3]["popularity"] == 1
    assert odds[3]["place_odds_min"] == 1.1
    assert odds[3]["place_odds_max"] == 1.1

    assert odds[8]["win_odds"] == 42.0
    assert odds[8]["popularity"] == 8
    assert len(odds) == 8


def test_parse_odds_response_not_yet_available():
    """馬券発売前は{"status":"middle","data":"",...}が返る(エラーではない)。"""
    json_text = '{"status":"middle","data":"","update_count":"0","reason":"result odds empty"}'
    assert parse_odds_response(json_text) == {}


def test_parse_odds_response_invalid_json():
    assert parse_odds_response("not json") == {}
