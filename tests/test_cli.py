import argparse

import pytest

from keibayosoku.cli import cmd_backfill_results


def test_backfill_results_rejects_start_after_end():
    args = argparse.Namespace(start="20260720", end="20260710", interval=2.0)
    with pytest.raises(SystemExit):
        cmd_backfill_results(args)
