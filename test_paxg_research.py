import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from paxg_research import Bar, Config, Signal, indicators, levels_hit, simulate

NOW = datetime(2026, 8, 3, 12, tzinfo=timezone.utc)


class ResearchTests(unittest.TestCase):
    def test_gap_and_intrabar_order(self):
        bar = Bar(NOW, 100, 110, 90, 105, 1000)
        self.assertEqual(levels_hit(bar, 95, 108), ("stop", 95))
        self.assertEqual(levels_hit(replace(bar, open=91), 95, 108), ("stop_gap", 91))
        self.assertEqual(levels_hit(replace(bar, open=109), 95, 108), ("target", 108))

    def test_indicator_warmup_and_causality(self):
        bars = [Bar(NOW + i*timedelta(hours=1), 100+i, 102+i, 99+i, 101+i, 1000)
                for i in range(100)]
        with self.assertRaises(ValueError):
            indicators(bars[:50], Config())
        original = indicators(bars, Config())
        self.assertIsNone(original[49])
        self.assertEqual(original[50].resistance, 151)
        bars[90] = replace(bars[90], close=bars[90].close+1)
        self.assertEqual(original[:90], indicators(bars, Config())[:90])

    def test_paid_price_and_stop_use_same_execution_costs_as_sizing(self):
        bars = [Bar(NOW+i*timedelta(hours=1), 100, 110, 90, 105, 1000) for i in range(3)]
        sig = Signal(104, 101, 97, True, 90, 100, 5, 2, 35, True)
        cfg = Config(target_atr=3)
        out = simulate(bars, [sig]*3, cfg, 1, 3)
        paid = 100 * (1+.0016) * (1+.001)
        proceeds = 95 * (1-.0016) * (1-.001)
        qty = min(2500/paid, 50/(paid-proceeds))
        self.assertAlmostEqual(out["pnls"][0], qty*(proceeds-paid))
        self.assertEqual(out["decisions"]["stop"], 1)

    def test_partial_target_and_fees(self):
        bars = [Bar(NOW+i*timedelta(hours=1), 100, 116, 99, 115, 1000) for i in range(3)]
        sig = Signal(104, 101, 97, True, 90, 100, 5, 2, 35, True)
        cfg = Config(target_atr=3, partial=True, maker_fee_bps=0, taker_fee_bps=0, slippage_bps=0)
        out = simulate(bars, [sig]*3, cfg, 1, 3)
        self.assertEqual(out["decisions"]["partial"], 1)
        self.assertEqual(out["decisions"]["target"], 1)
        self.assertEqual(out["pnls"], [100.])


if __name__ == "__main__":
    unittest.main()
