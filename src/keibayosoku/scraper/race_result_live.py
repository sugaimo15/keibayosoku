"""race.netkeiba.com の速報結果ページをパースする。

対象URL: https://race.netkeiba.com/race/result.html?race_id={race_id}
db.netkeiba.com側のデータベース版結果ページ(race_result.py)はレース終了後
しばらく経ってから反映されるため、レース当日はこちらの速報ページの方が
先に確定結果を確認できる。出馬表(race_card.py)と同じ race.netkeiba.com
サイトなので、RaceData01のような当日ページ特有のマークアップを流用しつつ、
結果テーブルはヘッダーのテキストで列を突き合わせる(db版と同じ方針)。
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .http import NetkeibaClient
from .race_result import COLUMN_ALIASES, ID_RE, RaceResult

RACE_RESULT_LIVE_URL = "https://race.netkeiba.com/race/result.html?race_id={race_id}"

BET_TYPE_LABELS = ["単勝", "複勝", "枠連", "馬連", "ワイド", "馬単", "三連複", "三連単"]


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


def _find_result_table(soup: BeautifulSoup):
    """クラス名の変更に強くするため、ヘッダーに"着順"を含むtableを探す。"""
    for table in soup.find_all("table"):
        header_row = table.find("tr")
        if header_row is None:
            continue
        header_text = header_row.get_text()
        if "着順" in header_text:
            return table
    return None


def parse_race_info_live(soup: BeautifulSoup) -> dict:
    info: dict = {}
    name_tag = soup.find(class_="RaceName")
    if name_tag:
        info["race_name"] = name_tag.get_text(strip=True)

    data_tag = soup.find(class_=lambda c: c and "RaceData01" in c)
    if data_tag:
        detail_text = data_tag.get_text(" ", strip=True)

        surface_m = re.search(r"(芝|ダ)([右左内外]{0,2})(\d{3,4})m", detail_text)
        if surface_m:
            info["surface"] = "芝" if surface_m.group(1) == "芝" else "ダート"
            info["distance_m"] = int(surface_m.group(3))
            dir_char = next((c for c in surface_m.group(2) if c in "右左"), None)
            if dir_char:
                info["direction"] = dir_char

        weather_m = re.search(r"天候\s*[::]\s*(\S+?)(\s|/|$)", detail_text)
        if weather_m:
            info["weather"] = weather_m.group(1)

        track_m = re.search(r"(?:馬場|芝|ダート)\s*[::]\s*(\S+?)(\s|/|$)", detail_text)
        if track_m:
            info["track_condition"] = track_m.group(1)

    # RaceData02等の開催情報欄に日付が無い場合もあるため、ページ全体からも探す。
    date_m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", soup.get_text(" ", strip=True))
    if date_m:
        y, mo, d = date_m.groups()
        info["date"] = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"

    return info


def parse_entries_live(soup: BeautifulSoup) -> list[dict]:
    table = _find_result_table(soup)
    if table is None:
        return []

    header_cells = table.find("tr").find_all(["th", "td"])
    headers = [_normalize_header(c.get_text(strip=True)) for c in header_cells]

    entries = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all(["td"])
        if not cells:
            continue
        entry: dict = {}
        for header, cell in zip(headers, cells):
            entry[header] = cell.get_text(strip=True)
            if header == "horse_name":
                horse_id = _extract_id(cell)
                if horse_id:
                    entry["horse_id"] = horse_id
            elif header == "jockey":
                jockey_id = _extract_id(cell)
                if jockey_id:
                    entry["jockey_id"] = jockey_id
            elif header == "trainer":
                trainer_id = _extract_id(cell)
                if trainer_id:
                    entry["trainer_id"] = trainer_id
        entries.append(entry)
    return entries


def _split_multi(text: str) -> list[str]:
    """複勝/ワイドのように1つのセルに複数の値が改行区切りで入る場合を分割する。"""
    return [p.strip() for p in re.split(r"[\n]+", text) if p.strip()]


def parse_payouts_live(soup: BeautifulSoup) -> list[dict]:
    """払戻テーブルをパースする。行の先頭セルが単勝/複勝/...のいずれかに完全一致するものを
    払戻行とみなし(クラス名の変更に強くするため)、組番・払戻金額・人気を抜き出す。
    複勝/ワイドのように1レースで複数組を払い戻す場合は、組ごとに1レコードにして返す。
    """
    payouts: list[dict] = []
    seen_rows: set[int] = set()

    for label in BET_TYPE_LABELS:
        for cell in soup.find_all(["th", "td"]):
            if cell.get_text(strip=True) != label:
                continue
            row = cell.find_parent("tr")
            if row is None or id(row) in seen_rows:
                continue
            seen_rows.add(id(row))

            other_cells = [c for c in row.find_all(["th", "td"]) if c is not cell]
            if not other_cells:
                continue
            combo_texts = _split_multi(other_cells[0].get_text("\n", strip=True))
            amount_texts = (
                _split_multi(other_cells[1].get_text("\n", strip=True)) if len(other_cells) > 1 else []
            )
            popularity_texts = (
                _split_multi(other_cells[2].get_text("\n", strip=True)) if len(other_cells) > 2 else []
            )

            n = max(len(combo_texts), len(amount_texts)) or 1
            for i in range(n):
                combo = combo_texts[i] if i < len(combo_texts) else None
                amount_text = amount_texts[i] if i < len(amount_texts) else None
                amount = None
                if amount_text:
                    m = re.search(r"[\d,]+", amount_text)
                    if m:
                        amount = int(m.group(0).replace(",", ""))
                popularity_text = popularity_texts[i] if i < len(popularity_texts) else None
                popularity = None
                if popularity_text:
                    m = re.search(r"\d+", popularity_text)
                    if m:
                        popularity = int(m.group(0))
                payouts.append(
                    {
                        "bet_type": label,
                        "combination": combo,
                        "amount": amount,
                        "popularity": popularity,
                    }
                )
    return payouts


def parse_race_result_live(race_id: str, html: str) -> RaceResult:
    soup = BeautifulSoup(html, "lxml")
    info = parse_race_info_live(soup)
    entries = parse_entries_live(soup)
    payouts = parse_payouts_live(soup)
    return RaceResult(
        race_id=race_id,
        race_name=info.get("race_name"),
        date=info.get("date"),
        distance_m=info.get("distance_m"),
        surface=info.get("surface"),
        direction=info.get("direction"),
        weather=info.get("weather"),
        track_condition=info.get("track_condition"),
        entries=entries,
        payouts=payouts,
    )


def fetch_race_result_live_html(client: NetkeibaClient, race_id: str) -> str:
    """デバッグ用: 速報結果ページの生HTMLを返す。"""
    url = RACE_RESULT_LIVE_URL.format(race_id=race_id)
    return client.get(url, encoding="utf-8")


def fetch_race_result_live(client: NetkeibaClient, race_id: str) -> RaceResult:
    html = fetch_race_result_live_html(client, race_id)
    return parse_race_result_live(race_id, html)
