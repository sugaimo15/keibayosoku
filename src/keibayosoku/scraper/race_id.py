"""netkeibaのrace_id (12桁) の分解ユーティリティ。

race_id 形式: YYYY CC KK DD RR
  YYYY: 開催年
  CC  : 競馬場コード
  KK  : 開催回(第何回)
  DD  : 開催日目
  RR  : レース番号
"""
from __future__ import annotations

from dataclasses import dataclass

COURSE_NAMES = {
    "01": "札幌",
    "02": "函館",
    "03": "福島",
    "04": "新潟",
    "05": "東京",
    "06": "中山",
    "07": "中京",
    "08": "京都",
    "09": "阪神",
    "10": "小倉",
}


@dataclass(frozen=True)
class RaceId:
    year: int
    course_code: str
    kai: int
    day: int
    race_number: int
    raw: str

    @property
    def course_name(self) -> str:
        return COURSE_NAMES.get(self.course_code, f"不明({self.course_code})")


def parse_race_id(race_id: str) -> RaceId:
    if len(race_id) != 12 or not race_id.isdigit():
        raise ValueError(f"race_idは12桁の数字である必要があります: {race_id!r}")
    return RaceId(
        year=int(race_id[0:4]),
        course_code=race_id[4:6],
        kai=int(race_id[6:8]),
        day=int(race_id[8:10]),
        race_number=int(race_id[10:12]),
        raw=race_id,
    )
