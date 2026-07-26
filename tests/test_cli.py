import argparse

import pytest

from keibayosoku import cli
from keibayosoku.cli import cmd_backfill_results, cmd_daily


def test_backfill_results_rejects_start_after_end():
    args = argparse.Namespace(start="20260720", end="20260710", interval=2.0)
    with pytest.raises(SystemExit):
        cmd_backfill_results(args)


def test_daily_builds_scrape_card_namespace_with_all_required_attrs(monkeypatch):
    """cmd_dailyがcmd_scrape_card用に組み立てるNamespaceには、cmd_scrape_cardが
    参照する全属性(--dump-html追加時に見落とされていたdump_html含む)が必要。
    実際にdaily.ymlの定時実行がAttributeError: 'Namespace' object has no
    attribute 'dump_html'で失敗した回帰に対するテスト。
    """
    captured = {}

    def fake_scrape_results(args):
        pass

    def fake_scrape_card(args):
        captured["card_ns"] = args

    def fake_predict(args):
        pass

    monkeypatch.setattr(cli, "cmd_scrape_results", fake_scrape_results)
    monkeypatch.setattr(cli, "cmd_scrape_card", fake_scrape_card)
    monkeypatch.setattr(cli, "cmd_predict", fake_predict)

    args = argparse.Namespace(date="20260101", results_date="20251231", interval=2.0)
    cmd_daily(args)

    assert hasattr(captured["card_ns"], "dump_html")
    assert captured["card_ns"].dump_html is False
