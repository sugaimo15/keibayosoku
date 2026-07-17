"""指定日に開催されるレースのrace_id一覧を取得する。

race_list.html はレース一覧をJavaScript(jQuery UI tabs)で非同期に描画するため、
プレーンなHTML取得では中身が空になる。実際の取得には2段階のAjax呼び出しが必要:

  1. race_list_get_date_list.html?kaisai_date=... が、その週の開催日タブ一覧
     (各 <li date="YYYYMMDD"> に race_list_sub.html への実リンクを持つ) を返す。
     指定日に対応する <li> が無ければその日は開催が無い。
  2. 1で見つけた <li> のリンク先 (race_list_sub.html?kaisai_date=...&current_group=...)
     が、実際のレース一覧(race_id付きリンクを含む)を返す。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup

from .http import NetkeibaClient

RACE_TOP_BASE_URL = "https://race.netkeiba.com/top/"
DATE_LIST_URL = "https://race.netkeiba.com/top/race_list_get_date_list.html?kaisai_date={date}&encoding=UTF-8"
RACE_ID_RE = re.compile(r"race_id=(\d{12})")


@dataclass
class RaceListItem:
    race_id: str
    race_name: str | None
    url: str


def fetch_race_list_html(client: NetkeibaClient, date: str) -> str:
    """デバッグ用: kaisai_dateの開催日タブAjaxフラグメントの生HTMLを返す。"""
    url = DATE_LIST_URL.format(date=date)
    return client.get(url, encoding="UTF-8")


def find_sub_url_for_date(date_list_html: str, date: str) -> str | None:
    """開催日タブフラグメントから、指定日に対応するrace_list_sub.htmlへのURLを探す。

    対応する<li>が無ければその日は開催が無いのでNoneを返す。
    """
    soup = BeautifulSoup(date_list_html, "lxml")
    li = soup.find("li", attrs={"date": date})
    if li is None:
        return None
    a = li.find("a", href=True)
    if a is None:
        return None
    url, _fragment = urldefrag(urljoin(RACE_TOP_BASE_URL, a["href"]))
    return url


def parse_race_list(html: str) -> list[RaceListItem]:
    soup = BeautifulSoup(html, "lxml")

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


def fetch_race_ids(client: NetkeibaClient, date: str) -> list[RaceListItem]:
    """kaisai_date (YYYYMMDD) に開催されるレースのrace_id一覧を返す。

    開催がない日は空リストを返す。
    """
    date_list_html = fetch_race_list_html(client, date)
    sub_url = find_sub_url_for_date(date_list_html, date)
    if sub_url is None:
        return []

    sub_html = client.get(sub_url, encoding="UTF-8")
    return parse_race_list(sub_html)
