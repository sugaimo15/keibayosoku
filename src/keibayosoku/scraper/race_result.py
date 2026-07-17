"""db.netkeiba.com のレース結果ページをパースする。

対象URL: https://db.netkeiba.com/race/{race_id}/
netkeibaのHTML構造は将来変更される可能性があるため、
・列はヘッダーのテキストで突き合わせる(列順に依存しない)
・想定した要素が見つからない場合はNone/空のまま処理を続行する
という方針で書いている。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from .http import NetkeibaClient

RACE_RESULT_URL = "https://db.netkeiba.com/race/{race_id}/"

# horse: /horse/{id}/  だが jockey/trainer は /jockey/result/recent/{id}/ という
# 形式で "result/recent/" を挟むため、素朴な "次のパス要素" 抽出だと "result" という
# 固定文字列を誤って拾ってしまう。race_card.pyで見つかったのと同じ問題。
ID_RE = re.compile(r"/(horse|jockey|trainer|owner)/(?:result/recent/)?(\w+)/?(?:$|[?#])")

# ヘッダーテキスト -> 正規化した列名
# タイム指数系の列はUIの切替ボタンのラベルまで巻き込んでテキストが連結されるため
# (例: "ﾀｲﾑ指数タイム指数(通常)タイム指数マスター")、実際に観測された文字列を
# そのままキーにして分かりやすい名前に寄せている。値自体は会員限定機能のため
# 現状は "**" (非公開) が入る。
COLUMN_ALIASES = {
    "着順": "finish_position",
    "枠": "waku",
    "枠番": "waku",
    "馬番": "horse_number",
    "馬名": "horse_name",
    "性齢": "sex_age",
    "斤量": "weight_carried",
    "騎手": "jockey",
    "タイム": "time",
    "着差": "margin",
    "ﾀｲﾑ指数タイム指数(通常)タイム指数マスター": "time_index",
    "ﾀｲﾑ指数Mタイム指数(通常)タイム指数マスター": "time_index_master",
    "ｽﾀｰﾄ指数": "start_index",
    "追走指数": "pace_index",
    "上がり指数": "last_3f_index",
    "通過": "passing_order",
    "上り": "last_3f",
    "単勝": "win_odds",
    "人気": "popularity",
    "馬体重": "horse_weight",
    "調教ﾀｲﾑ": "training_time",
    "厩舎ｺﾒﾝﾄ": "trainer_comment",
    "備考": "remarks",
    "調教師": "trainer",
    "馬主": "owner",
    "賞金": "prize_money",
    "賞金(万円)": "prize_money",
}


@dataclass
class RaceResult:
    race_id: str
    race_name: str | None = None
    date: str | None = None
    course_name: str | None = None
    distance_m: int | None = None
    surface: str | None = None
    direction: str | None = None
    weather: str | None = None
    track_condition: str | None = None
    entries: list[dict] = field(default_factory=list)


def _normalize_header(text: str) -> str:
    text = text.strip()
    return COLUMN_ALIASES.get(text, text)


def _extract_id(cell) -> str | None:
    a = cell.find("a", href=True)
    if not a:
        return None
    m = ID_RE.search(a["href"])
    return m.group(2) if m else None


def parse_race_info(soup: BeautifulSoup) -> dict:
    info: dict = {}
    intro = soup.find(class_="data_intro")
    if intro is None:
        return info

    h1 = intro.find("h1")
    if h1:
        info["race_name"] = h1.get_text(strip=True)

    smalltxt = intro.find(class_="smalltxt")
    if smalltxt:
        text = smalltxt.get_text(" ", strip=True)
        date_m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
        if date_m:
            y, mo, d = date_m.groups()
            info["date"] = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"

    detail = intro.find("span") or intro.find("p", class_=lambda c: c != "smalltxt" if c else True)
    detail_text = ""
    for span in intro.find_all("span"):
        detail_text += span.get_text(" ", strip=True) + " "
    if not detail_text:
        detail_text = intro.get_text(" ", strip=True)

    surface_m = re.search(r"(芝|ダ)(\d{3,4})m", detail_text)
    if surface_m:
        info["surface"] = "芝" if surface_m.group(1) == "芝" else "ダート"
        info["distance_m"] = int(surface_m.group(2))

    dir_m = re.search(r"[(（]([右左])", detail_text)
    if dir_m:
        info["direction"] = dir_m.group(1)

    weather_m = re.search(r"天候\s*[::]\s*(\S+?)(\s|/|$)", detail_text)
    if weather_m:
        info["weather"] = weather_m.group(1)

    # 通常のレースは "馬場 : 良" だが、障害レースは "芝 : 良" / "ダート : 良" と
    # 馬場種別そのものがラベルになる。
    track_m = re.search(r"(?:馬場|芝|ダート)\s*[::]\s*(\S+?)(\s|/|$)", detail_text)
    if track_m:
        info["track_condition"] = track_m.group(1)

    return info


def parse_entries(soup: BeautifulSoup) -> list[dict]:
    table = soup.find("table", class_=lambda c: c and "race_table" in c)
    if table is None:
        return []

    header_cells = table.find("tr").find_all(["th", "td"])
    headers = [_normalize_header(c.get_text(strip=True)) for c in header_cells]

    entries = []
    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
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


def parse_race_result(race_id: str, html: str) -> RaceResult:
    soup = BeautifulSoup(html, "lxml")
    info = parse_race_info(soup)
    entries = parse_entries(soup)
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
    )


def fetch_race_result_html(client: NetkeibaClient, race_id: str) -> str:
    """デバッグ用: レース結果ページの生HTMLを返す。"""
    url = RACE_RESULT_URL.format(race_id=race_id)
    return client.get(url, encoding="EUC-JP")


def fetch_race_result(client: NetkeibaClient, race_id: str) -> RaceResult:
    html = fetch_race_result_html(client, race_id)
    return parse_race_result(race_id, html)
