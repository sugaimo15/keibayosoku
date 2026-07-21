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
    # race.netkeiba.com速報ページ(race_result_live.py)はdb版と列見出しの
    # 表記が一部異なる。
    "単勝オッズ": "win_odds",
    "後3F": "last_3f",
    "コーナー通過順": "passing_order",
    "厩舎": "trainer",
    "馬体重(増減)": "horse_weight",
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
    # 単勝/複勝/枠連/馬連/ワイド/馬単/三連複/三連単の払戻。
    payouts: list[dict] = field(default_factory=list)


# db.netkeiba.com側の払戻テーブル(class="pay_table_01")で使われる表記。
# race.netkeiba.com速報ページ(race_result_live.py)は半角数字で"3連複"/"3連単"だが、
# db.netkeiba.com側は漢数字の"三連複"/"三連単"。保存済みデータとの表記統一のため、
# こちらの漢数字表記をそのまま採用する。
PAYOUT_BET_TYPE_LABELS = ["単勝", "複勝", "枠連", "馬連", "ワイド", "馬単", "三連複", "三連単"]
_COMBO_SEPARATOR_RE = re.compile(r"\s*(?:-|→)\s*")


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

    # 通常レース: "芝右1800m" / "ダ右外1600m" のように向き・内外の文字が距離の
    # 直前に挟まる。障害レースは "障芝3380m" のように挟まらない。
    surface_m = re.search(r"(芝|ダ)([右左内外]{0,2})(\d{3,4})m", detail_text)
    if surface_m:
        info["surface"] = "芝" if surface_m.group(1) == "芝" else "ダート"
        info["distance_m"] = int(surface_m.group(3))
        dir_char = next((c for c in surface_m.group(2) if c in "右左"), None)
        if dir_char:
            info["direction"] = dir_char

    if "direction" not in info:
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


def _split_multi(text: str) -> list[str]:
    """複勝/ワイドのように1つのセルに複数の値が改行区切りで入る場合を分割する。"""
    return [p.strip() for p in re.split(r"[\n]+", text) if p.strip()]


def parse_payouts(soup: BeautifulSoup) -> list[dict]:
    """払戻テーブル(class="pay_table_01")をパースする。

    db.netkeiba.com側は組番が既に1セル内に "3 - 6" / "6 → 3" のように結合されて
    入っているため、race_result_live.py側のような複数行からのグループ化は不要。
    馬単・三連単の"→"区切りも含めて"-"区切りに統一し、保存済みデータと表記を揃える。
    """
    payouts: list[dict] = []
    for table in soup.find_all("table", class_="pay_table_01"):
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) < 3:
                continue
            label = cells[0].get_text(strip=True)
            if label not in PAYOUT_BET_TYPE_LABELS:
                continue

            combo_texts = _split_multi(cells[1].get_text("\n", strip=True))
            amount_texts = _split_multi(cells[2].get_text("\n", strip=True))
            popularity_texts = _split_multi(cells[3].get_text("\n", strip=True)) if len(cells) > 3 else []

            n = max(len(combo_texts), len(amount_texts), 1)
            for i in range(n):
                combo_text = combo_texts[i] if i < len(combo_texts) else None
                combo = _COMBO_SEPARATOR_RE.sub("-", combo_text) if combo_text else None
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
                    {"bet_type": label, "combination": combo, "amount": amount, "popularity": popularity}
                )
    return payouts


def parse_race_result(race_id: str, html: str) -> RaceResult:
    soup = BeautifulSoup(html, "lxml")
    info = parse_race_info(soup)
    entries = parse_entries(soup)
    payouts = parse_payouts(soup)
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


def fetch_race_result_html(client: NetkeibaClient, race_id: str) -> str:
    """デバッグ用: レース結果ページの生HTMLを返す。"""
    url = RACE_RESULT_URL.format(race_id=race_id)
    return client.get(url, encoding="EUC-JP")


def fetch_race_result(client: NetkeibaClient, race_id: str) -> RaceResult:
    html = fetch_race_result_html(client, race_id)
    return parse_race_result(race_id, html)
