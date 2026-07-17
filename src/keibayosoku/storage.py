"""スクレイピング/予測結果をリポジトリ配下のdata/にCSVとして保存・読込するモジュール。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .scraper.race_card import RaceCard
from .scraper.race_id import parse_race_id
from .scraper.race_result import RaceResult

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RACE_RESULTS_DIR = DATA_DIR / "race_results"
RACE_CARDS_DIR = DATA_DIR / "race_cards"
PREDICTIONS_DIR = DATA_DIR / "predictions"


def race_result_path(race_id: str, base_dir: Path = RACE_RESULTS_DIR) -> Path:
    year = parse_race_id(race_id).year
    return base_dir / str(year) / f"{race_id}.csv"


def save_race_result(result: RaceResult, base_dir: Path = RACE_RESULTS_DIR) -> Path:
    path = race_result_path(result.race_id, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(result.entries)
    df.insert(0, "race_id", result.race_id)
    df.insert(1, "race_name", result.race_name)
    df.insert(2, "date", result.date)
    df.insert(3, "surface", result.surface)
    df.insert(4, "distance_m", result.distance_m)
    df.insert(5, "direction", result.direction)
    df.insert(6, "weather", result.weather)
    df.insert(7, "track_condition", result.track_condition)

    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def load_all_race_results(base_dir: Path = RACE_RESULTS_DIR) -> pd.DataFrame:
    """過去に保存した全レース結果を1つのDataFrameにまとめて返す。データが無ければ空DataFrame。"""
    csv_files = sorted(base_dir.glob("*/*.csv"))
    if not csv_files:
        return pd.DataFrame()
    frames = [pd.read_csv(f) for f in csv_files]
    return pd.concat(frames, ignore_index=True)


def race_card_path(date: str, race_id: str, base_dir: Path = RACE_CARDS_DIR) -> Path:
    return base_dir / date / f"{race_id}.csv"


def save_race_card(card: RaceCard, date: str, base_dir: Path = RACE_CARDS_DIR) -> Path:
    path = race_card_path(date, card.race_id, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(card.entries)
    df.insert(0, "race_id", card.race_id)
    df.insert(1, "race_name", card.race_name)
    df.insert(2, "surface", card.surface)
    df.insert(3, "distance_m", card.distance_m)

    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def prediction_path(date: str, race_id: str, base_dir: Path = PREDICTIONS_DIR) -> Path:
    return base_dir / date / f"{race_id}.csv"


def save_predictions(df: pd.DataFrame, date: str, race_id: str, base_dir: Path = PREDICTIONS_DIR) -> Path:
    path = prediction_path(date, race_id, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path
