"""指定日に開催されるレースのrace_id一覧を取得する。"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .http import NetkeibaClient

RACE_LIST_URL = "https://race.netkeiba.com/top/race_list.html?kaisai_date={date}"
RACE_ID_RE = re.compile(r"race_id=(\d{12})")


@dataclass
class RaceListItem:
    race_id: str
    race_name: str | None
    url: str


def fetch_race_ids(client: NetkeibaClient, date: str) -> list[RaceListItem]:
    """kaisai_date (YYYYMMDD) に開催されるレースのrace_id一覧を返す。

    開催がない日は空リストを返す。
    """
    url = RACE_LIST_URL.format(date=date)
    soup = client.get_soup(url, encoding="EUC-JP")

    seen: dict[str, RaceListItem] = {}
    for a in soup.find_all("a", href=True):
        m = RACE_ID_RE.search(a["href"])
        if not m:
            continue
        race_id = m.group(1)
        if race_id in seen:
            continue
        name_tag = a.find(class_="RaceName") or a.find(class_="ItemTitle")
        race_name = name_tag.get_text(strip=True) if name_tag else a.get_text(strip=True) or None
        seen[race_id] = RaceListItem(race_id=race_id, race_name=race_name, url=a["href"])

    return list(seen.values())
