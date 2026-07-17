"""race.netkeiba.com の出馬表(当日/レース前)ページをパースする。

対象URL: https://race.netkeiba.com/race/shutuba.html?race_id={race_id}
出走前のため着順・タイム等は存在せず、枠番・馬番・馬名・斤量・騎手・厩舎・馬体重(前走比)・オッズ/人気(発表されていれば)を取得する。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from .http import NetkeibaClient

RACE_CARD_URL = "https://race.netkeiba.com/race/shutuba.html?race_id={race_id}"
ID_RE = re.compile(r"/(horse|jockey|trainer)/(\w+)/?")


@dataclass
class RaceCard:
    race_id: str
    race_name: str | None = None
    distance_m: int | None = None
    surface: str | None = None
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


def parse_race_card(race_id: str, html: str) -> RaceCard:
    soup = BeautifulSoup(html, "lxml")

    race_name = None
    name_tag = soup.find(class_="RaceName")
    if name_tag:
        race_name = name_tag.get_text(strip=True)

    distance_m = None
    surface = None
    data_tag = soup.find(class_=lambda c: c and "RaceData01" in c)
    if data_tag:
        detail_text = data_tag.get_text(" ", strip=True)
        surface_m = re.search(r"(芝|ダ)(\d{3,4})m", detail_text)
        if surface_m:
            surface = "芝" if surface_m.group(1) == "芝" else "ダート"
            distance_m = int(surface_m.group(2))

    table = soup.find(class_=lambda c: c and "Shutuba_Table" in c)
    entries: list[dict] = []
    if table is not None:
        rows = table.find_all("tr", class_=lambda c: c and "HorseList" in c)
        for row in rows:
            def cell(cls):
                return row.find(class_=cls)

            entry = {
                "waku": _text(cell("Waku")),
                "horse_number": _text(cell("Umaban")),
                "horse_name": _text(cell("HorseInfo") or cell("Horse_Name")),
                "sex_age": _text(cell("Barei")),
                "weight_carried": _text(cell("Jyuryo")),
                "jockey": _text(cell("Jockey")),
                "trainer": _text(cell("Trainer")),
                "horse_weight": _text(cell("Weight")),
                "win_odds": _text(cell("Odds") or cell("Popular")),
            }
            horse_id = _extract_id(cell("HorseInfo") or cell("Horse_Name"))
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
        entries=entries,
    )


def fetch_race_card_html(client: NetkeibaClient, race_id: str) -> str:
    """デバッグ用: 出馬表ページの生HTMLを返す。"""
    url = RACE_CARD_URL.format(race_id=race_id)
    return client.get(url, encoding="utf-8")


def fetch_race_card(client: NetkeibaClient, race_id: str) -> RaceCard:
    html = fetch_race_card_html(client, race_id)
    return parse_race_card(race_id, html)
