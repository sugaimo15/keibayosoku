"""1レース分の出馬表と蓄積済みの過去レース結果から予測を行うオーケストレーション。"""
from __future__ import annotations

import pandas as pd

from .. import storage
from ..scraper.race_card import RaceCard
from .scoring import score_race_card


def predict(card: RaceCard, history: pd.DataFrame | None = None) -> pd.DataFrame:
    if history is None:
        history = storage.load_all_race_results()
    card_df = pd.DataFrame(card.entries)
    if card_df.empty:
        return card_df
    return score_race_card(card_df, history, distance_m=card.distance_m, surface=card.surface)
