import unittest
from dataclasses import replace
from datetime import datetime, timezone

from paxg_edge import Bar, Costs, HOUR, Order, passes, passive_fill, replay


class PassiveReplayTests(unittest.TestCase):
    def setUp(self):
        self.t = datetime(2025, 1, 1, tzinfo=timezone.utc)
        self.bars = [Bar(self.t + i*HOUR, 100, 101, 99, 100, 1) for i in range(5)]

    def test_limit_touch_is_not_a_fill(self):
        order = Order(99, 95, 108, 3)
        self.assertFalse(passive_fill(self.bars[2], order, Costs()))
        self.assertTrue(passive_fill(replace(self.bars[2], low=98), order, Costs()))

    def test_expiry_excludes_first_bar_after_deadline(self):
        self.bars[3] = replace(self.bars[3], low=98)
        result = replay(self.bars, [None, Order(99, 95, 108, 3), None, None, None],
                        1, 5, Costs())
        self.assertEqual(result["orders"]["expired"], 1)
        self.assertEqual(result["pnls"], [])

    def test_stop_precedes_target_in_fill_bar_and_charges_costs(self):
        self.bars[2] = replace(self.bars[2], high=120, low=94)
        result = replay(self.bars, [None, Order(99, 95, 108, 3), None, None, None],
                        1, 5, Costs())
        self.assertEqual(result["orders"]["stop"], 1)
        self.assertEqual(result["orders"]["target"], 0)
        self.assertAlmostEqual(result["pnls"][0], -50)
        self.assertGreater(result["friction_usdt"], 0)

    def test_maker_rejection_and_resting_gap_are_distinct(self):
        order = Order(99, 95, 108, 5)
        gap = dict(open=93, low=91, close=94)
        self.bars[3] = replace(self.bars[3], **gap)
        result = replay(self.bars, [None, order, None, None, None], 1, 5, Costs())
        self.assertEqual(result["orders"]["entry_gap_stop"], 1)
        self.assertLess(result["pnls"][0], -50)
        self.bars[2] = replace(self.bars[2], **gap)
        result = replay(self.bars, [None, order, None, None, None], 1, 5, Costs())
        self.assertEqual(result["orders"]["marketable_cancel"], 1)
        self.assertEqual(result["pnls"], [])

    def test_gate_requires_all_thresholds(self):
        result = dict(trades=50, profit_factor=1.31, net_return_pct=1., sharpe=.5)
        self.assertTrue(passes(result))
        for changes in (dict(trades=49), dict(profit_factor=1.30),
                        dict(net_return_pct=0.), dict(sharpe=0.)):
            self.assertFalse(passes(result | changes))
