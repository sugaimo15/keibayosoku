"""race.netkeiba.com の出馬表(当日/レース前)ページをパースする。

対象URL: https://race.netkeiba.com/race/shutuba.html?race_id={race_id}
出走前のため着順・タイム等は存在せず、枠番・馬番・馬名・斤量・騎手・厩舎・馬体重(前走比)・オッズ/人気(発表されていれば)を取得する。

実際のマークアップ(2026年7月時点で確認)の注意点:
  - 枠番/馬番のtdは class="Waku{N} Txt_C" / class="Umaban{N} Txt_C" のように
    馬番号が結合された動的クラス名になっており、固定の "Waku"/"Umaban" という
    クラス名では一致しない。
  - 斤量のtdには専用クラスが無く、性齢(class="Barei")の直後のtdという位置関係
    でしか特定できない。
  - 騎手/調教師の詳細ページへのリンクは https://db.netkeiba.com/jockey/result/recent/{id}/
    のように "result/recent/" を挟む形式で、末尾のセグメントがID。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from .http import NetkeibaClient

RACE_CARD_URL = "https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
ID_RE = re.compile(r"/(horse|jockey|trainer)/(?:result/recent/)?(\w+)/?(?:$|[?#])")

# 出馬表ページの単勝オッズ(<span id="odds-N_NN">)は静的HTMLの時点では"---.-"の
# プレースホルダーしか入っておらず、実際の値はページ読み込み後にJavaScriptが
# $.oddsUpdate({apiUrl:'.../api/api_get_jra_odds.html', raceId:...}) 経由で
# 非同期取得して埋め込んでいる。実データで確認したレスポンス形式:
#   {"status":"result","data":{"odds":{"1":{"01":["18.4","0.0","6"],...},
#                                      "2":{"01":["2.3","7.4","6"],...}}}, ...}
#   "1"=単勝([オッズ,"0.0",人気順位]), "2"=複勝([下限,上限,人気順位])。
# まだ馬券発売が始まっていないレースは {"status":"middle","data":"",...} を返す
# (エラーではなく、単に未発表という意味)。
ODDS_API_URL = "https://race.netkeiba.com/api/api_get_jra_odds.html?race_id={race_id}&type=1"


@dataclass
class RaceCard:
    race_id: str
    race_name: str | None = None
    distance_m: int | None = None
    surface: str | None = None
    track_condition: str | None = None
    entries: list[dict] = field(default_factory=list)


def _text(cell) -> str:
    return cell.get_text(strip=True) if cell else ""


def _extract_id(cell) -> str | None:
    if cell is None:
        return None
    a = cell.find("a", href=True)
    if not a:
        return None
    m = ID_RE.search(a["href"])
    return m.group(2) if m else None


def _find_by_class_prefix(row, prefix: str):
    return row.find("td", class_=lambda c: c and c.startswith(prefix))


def parse_race_card(race_id: str, html: str) -> RaceCard:
    soup = BeautifulSoup(html, "lxml")

    race_name = None
    name_tag = soup.find(class_="RaceName")
    if name_tag:
        race_name = name_tag.get_text(strip=True)

    distance_m = None
    surface = None
    track_condition = None
    data_tag = soup.find(class_=lambda c: c and "RaceData01" in c)
    if data_tag:
        detail_text = data_tag.get_text(" ", strip=True)
        surface_m = re.search(r"(芝|ダ)[右左内外]{0,2}(\d{3,4})m", detail_text)
        if surface_m:
            surface = "芝" if surface_m.group(1) == "芝" else "ダート"
            distance_m = int(surface_m.group(2))

        # 馬場状態はレース当日の朝以降に発表されるため、発表前は取得できない
        # (その場合はNoneのまま。predict側は距離・馬場種別と同様に欠損を許容する)。
        track_m = re.search(r"(?:馬場|芝|ダート)\s*[::]\s*(\S+?)(\s|/|$)", detail_text)
        if track_m:
            track_condition = track_m.group(1)

    table = soup.find(class_=lambda c: c and "Shutuba_Table" in c)
    entries: list[dict] = []
    if table is not None:
        rows = table.find_all("tr", class_=lambda c: c and "HorseList" in c)
        for row in rows:
            def cell(cls):
                return row.find(class_=cls)

            barei_cell = cell("Barei")
            weight_carried_cell = barei_cell.find_next_sibling("td") if barei_cell else None
            horse_info_cell = cell("HorseInfo") or cell("Horse_Name")

            entry = {
                "waku": _text(_find_by_class_prefix(row, "Waku")),
                "horse_number": _text(_find_by_class_prefix(row, "Umaban")),
                "horse_name": _text(horse_info_cell),
                "sex_age": _text(barei_cell),
                "weight_carried": _text(weight_carried_cell),
                "jockey": _text(cell("Jockey")),
                "trainer": _text(cell("Trainer")),
                "horse_weight": _text(cell("Weight")),
                "win_odds": _text(cell("Odds") or cell("Popular")),
            }
            horse_id = _extract_id(horse_info_cell)
            if horse_id:
                entry["horse_id"] = horse_id
            jockey_id = _extract_id(cell("Jockey"))
            if jockey_id:
                entry["jockey_id"] = jockey_id
            trainer_id = _extract_id(cell("Trainer"))
            if trainer_id:
                entry["trainer_id"] = trainer_id

            if entry["horse_name"]:
                entries.append(entry)

    return RaceCard(
        race_id=race_id,
        race_name=race_name,
        distance_m=distance_m,
        surface=surface,
        track_condition=track_condition,
        entries=entries,
    )


def fetch_race_card_html(client: NetkeibaClient, race_id: str) -> str:
    """デバッグ用: 出馬表ページの生HTMLを返す。"""
    url = RACE_CARD_URL.format(race_id=race_id)
    return client.get(url, encoding="utf-8")


def fetch_race_card(client: NetkeibaClient, race_id: str) -> RaceCard:
    html = fetch_race_card_html(client, race_id)
    return parse_race_card(race_id, html)


def fetch_odds_api_debug(client: NetkeibaClient, race_id: str) -> str:
    """調査用: オッズ非同期取得APIの生レスポンスを返す。"""
    url = ODDS_API_URL.format(race_id=race_id)
    return client.get(url, encoding="utf-8")


def parse_odds_response(json_text: str) -> dict[int, dict]:
    """オッズAPI(api_get_jra_odds.html)のレスポンスをパースする。

    馬券発売前で"status"が"result"/"yoso"以外(例: "middle")の場合はデータが
    無いので空dictを返す(エラーではなく正常系として扱う)。
    戻り値: {馬番: {"win_odds": float, "popularity": int,
                   "place_odds_min": float, "place_odds_max": float}}
    """
    try:
        obj = json.loads(json_text)
    except (json.JSONDecodeError, TypeError):
        return {}
    if obj.get("status") not in ("result", "yoso"):
        return {}

    odds_by_type = obj.get("data", {}).get("odds", {})
    win = odds_by_type.get("1", {})
    place = odds_by_type.get("2", {})

    result: dict[int, dict] = {}
    for horse_number_str, values in win.items():
        try:
            horse_number = int(horse_number_str)
            result[horse_number] = {"win_odds": float(values[0]), "popularity": int(values[2])}
        except (ValueError, IndexError, TypeError):
            continue
    for horse_number_str, values in place.items():
        try:
            horse_number = int(horse_number_str)
        except ValueError:
            continue
        entry = result.setdefault(horse_number, {})
        try:
            entry["place_odds_min"] = float(values[0])
            entry["place_odds_max"] = float(values[1])
        except (IndexError, ValueError, TypeError):
            continue
    return result


def fetch_odds(client: NetkeibaClient, race_id: str) -> dict[int, dict]:
    """レースの単勝/複勝オッズを非同期APIから取得する。未発表の場合は空dict。"""
    response = client.get(ODDS_API_URL.format(race_id=race_id), encoding="utf-8")
    return parse_odds_response(response)
