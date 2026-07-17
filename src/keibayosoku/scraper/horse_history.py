"""db.netkeiba.com の馬個別ページから、その馬の過去出走成績を取得する。

対象URL: https://db.netkeiba.com/horse/{horse_id}/
出馬表に載っている馬のIDから、レース単位ではなく馬単位で過去成績を辿りたい場合に使う
(例: 明日出走する馬たちの過去レースをまとめて知りたい、など)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from .http import NetkeibaClient

HORSE_URL = "https://db.netkeiba.com/horse/{horse_id}/"

ID_RE = re.compile(r"/(jockey|trainer|race)/(?:result/recent/)?(\w+)/?(?:$|[?#])")

# ヘッダーテキスト -> 正規化した列名 (db_h_race_results テーブルの想定列)
COLUMN_ALIASES = {
    "日付": "date",
    "開催": "venue",
    "天気": "weather",
    "R": "race_number",
    "レース名": "race_name",
    "頭数": "field_size",
    "枠番": "waku",
    "馬番": "horse_number",
    "オッズ": "win_odds",
    "人気": "popularity",
    "着順": "finish_position",
    "騎手": "jockey",
    "斤量": "weight_carried",
    "距離": "distance",
    "馬場": "track_condition",
    "タイム": "time",
    "着差": "margin",
    "通過": "passing_order",
    "ペース": "pace",
    "上り": "last_3f",
    "馬体重": "horse_weight",
    "厩舎ｺﾒﾝﾄ": "trainer_comment",
    "備考": "remarks",
    "勝ち馬(2着馬)": "winner_or_second",
    "賞金": "prize_money",
}


@dataclass
class HorseHistory:
    horse_id: str
    horse_name: str | None = None
    races: list[dict] = field(default_factory=list)


def _normalize_header(text: str) -> str:
    text = text.strip()
    return COLUMN_ALIASES.get(text, text)


def _extract_id(cell) -> str | None:
    if cell is None:
        return None
    a = cell.find("a", href=True)
    if not a:
        return None
    m = ID_RE.search(a["href"])
    return m.group(2) if m else None


def _split_distance(distance_text: str) -> tuple[str | None, int | None]:
    m = re.search(r"(芝|ダ)(\d{3,4})", distance_text)
    if not m:
        return None, None
    surface = "芝" if m.group(1) == "芝" else "ダート"
    return surface, int(m.group(2))


def fetch_horse_history_html(client: NetkeibaClient, horse_id: str) -> str:
    """デバッグ用: 馬個別ページの生HTMLを返す。"""
    url = HORSE_URL.format(horse_id=horse_id)
    return client.get(url, encoding="EUC-JP")


def parse_horse_history(horse_id: str, html: str) -> HorseHistory:
    soup = BeautifulSoup(html, "lxml")

    horse_name = None
    name_tag = soup.find(class_="horse_title") or soup.find("h1")
    if name_tag:
        horse_name = name_tag.get_text(strip=True)

    table = soup.find(class_=lambda c: c and "db_h_race_results" in c) or soup.find(id="result_list")
    races: list[dict] = []
    if table is not None:
        header_row = table.find("tr")
        headers = [_normalize_header(c.get_text(strip=True)) for c in header_row.find_all(["th", "td"])]

        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if not cells:
                continue
            entry: dict = {}
            for header, cell in zip(headers, cells):
                entry[header] = cell.get_text(strip=True)
                if header == "race_name":
                    race_id = _extract_id(cell)
                    if race_id:
                        entry["race_id"] = race_id
                elif header == "jockey":
                    jockey_id = _extract_id(cell)
                    if jockey_id:
                        entry["jockey_id"] = jockey_id

            if "distance" in entry:
                surface, distance_m = _split_distance(entry["distance"])
                entry["surface"] = surface
                entry["distance_m"] = distance_m

            races.append(entry)

    return HorseHistory(horse_id=horse_id, horse_name=horse_name, races=races)


def fetch_horse_history(client: NetkeibaClient, horse_id: str) -> HorseHistory:
    html = fetch_horse_history_html(client, horse_id)
    return parse_horse_history(horse_id, html)
