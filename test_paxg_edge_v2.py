import unittest
from datetime import datetime, timezone

from paxg_edge_v2 import Bar, HOUR, Plan, replay, resample


class SwingTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026,1,1,tzinfo=timezone.utc)
        self.bars = [Bar(self.start+i*HOUR,100+i,101+i,99+i,100+i,10) for i in range(8)]

    def test_resample_rejects_partial_or_gapped_bars(self):
        a, b = resample(self.bars,4)
        self.assertEqual((a.open,a.high,a.low,a.close,a.volume),(100,104,99,103,40))
        self.assertEqual(resample(self.bars[1:],4),[b])
        self.assertEqual(resample(self.bars[:6],4),[a])

    def test_costs_reduce_fixed_benchmark_and_net_expectancy(self):
        args = self.bars, {}
        a = replay(*args,"buy_hold",12,self.start,self.start+8*HOUR)
        b = replay(*args,"buy_hold",36,self.start,self.start+8*HOUR)
        self.assertEqual(a["trades"],1)
        self.assertGreater(a["gross_expectancy_usdt"],a["expectancy_usdt"])
        self.assertGreater(a["net_return_pct"],b["net_return_pct"])
