import json
import tempfile
import unittest
from contextlib import nullcontext
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import Mock, patch

from live.executor import Filters, PaperExecutor
from live.state import State
from live.strategy import Intent
from live.stream import Book, History, backfill, events, stamp
from spot_data import INTERVAL_MS as H


def rest_row(i):
    return [i*H,"100","101","99","100","10",(i+1)*H-1]


class FeedTests(unittest.TestCase):
    def test_rest_requests_only_missing_closed_bars(self):
        with patch("live.stream.get_json", side_effect=[{"serverTime": 5*H+42},[rest_row(3),rest_row(4)]]) as get:
            bars = backfill(2*H)
        self.assertEqual([stamp(b) for b in bars],[3*H,4*H])
        self.assertEqual(get.call_args.kwargs["endTime"],5*H-1)

    def test_rest_gap_fails(self):
        with patch("live.stream.get_json", side_effect=[{"serverTime":5*H},[rest_row(4)]]):
            with self.assertRaises(ValueError):
                backfill(2*H)

    def test_reconnect_recovers_candles_without_old_trade_signals(self):
        with patch("live.stream.get_json", side_effect=[
            {"serverTime":5*H}, [rest_row(3),rest_row(4)],
            {"serverTime":6*H}, [rest_row(5)],
        ]):
            warm = backfill(2*H)
            recovered = backfill(4*H)
        wire = json.dumps({"stream":"paxgusdt@bookTicker",
                          "data":dict(s="PAXGUSDT",u=42,b="100",a="101",B="100",A="100")})
        a, b = Mock(), Mock()
        a.recv.side_effect = TimeoutError()
        b.recv.return_value = wire
        with patch("live.stream.connect",side_effect=[nullcontext(a),nullcontext(b)]), \
             patch("live.stream.backfill",side_effect=[warm,recovered]) as fill, \
             patch("live.stream.time.sleep"):
            gen = events()
            self.assertTrue(next(gen).warmup)
            second = next(gen)
            self.assertIsInstance(second, History)
            self.assertTrue(second.warmup)
            self.assertEqual(stamp(second.candles[-1]),5*H)
            self.assertEqual(next(gen).update,42)
            self.assertEqual(fill.call_args.args,(4*H,))
            gen.close()


class ExecutorTests(unittest.TestCase):
    def test_duplicate_submission_and_recovery_of_position_and_pnl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"test.sqlite3"
            state = State(path,"10000")
            f = Filters(D(".001"),D(".001"),D("5"),D(".01"))
            ex = PaperExecutor(state,f)
            now = 1_800_000_000
            book = Book(1,D("100"),D("101"),D("1000"),D("1000"))
            intent = Intent(D("99"),D("95"),D("105"))
            ex.on_book(book,now)
            ex.on_close(123,intent,book,now)
            ex.on_close(123,intent,book,now)
            with state.transaction() as w:
                self.assertIsNotNone(w["pending"])
            # A quote exactly on the limit is insufficient.
            ex.on_book(Book(2,D("98"),D("99"),D("1000"),D("1000")),now+1)
            with state.transaction() as w:
                self.assertIsNone(w["position"])
            ex.on_book(Book(3,D("98"),D("98.5"),D("1000"),D("1000")),now+2)
            state.db.close()
            state = State(path,"1")
            ex = PaperExecutor(state,f)
            equity, pnl, changes = ex.on_book(Book(4,D("106"),D("107"),D("1000"),D("1000")),now+3)
            self.assertEqual(changes[0]["kind"],"target")
            self.assertGreater(pnl,0)
            self.assertEqual(equity,D(10000)+pnl)
            self.assertEqual(state.db.execute("SELECT COUNT(*) FROM events").fetchone()[0],3)
            state.db.close()

    def test_circuit_cancels_entries_after_gapped_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp)/"test.sqlite3","10000")
            ex = PaperExecutor(state,Filters(D(".001"),D(".001"),D("5"),D(".01")))
            now = 1_800_000_000
            book = Book(1,D("100"),D("101"),D("1000"),D("1000"))
            intent = Intent(D("99"),D("95"),D("105"))
            ex.on_book(book,now)
            ex.on_close(123,intent,book,now)
            ex.on_book(Book(2,D("98"),D("98.5"),D("1000"),D("1000")),now+1)
            ex.on_book(Book(3,D("93"),D("94"),D("1000"),D("1000")),now+2)
            ex.on_close(124,intent,book,now+3)
            with state.transaction() as w:
                self.assertTrue(w["locked"])
                self.assertIsNone(w["pending"])
            state.db.close()


class DailySwingTests(unittest.TestCase):
    def test_shared_daily_signal_uses_only_closed_utc_days(self):
        from datetime import datetime, timedelta, timezone
        from spot_data import Candle
        from paxg_edge_v2 import resample, swing_view
        from paxg_research import Bar
        from live.strategy import DailySwing

        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        hours = [Candle(start+timedelta(hours=i),D(100+i//24),D(101+i//24),
                        D(99+i//24),D(100+i//24),D(1)) for i in range(52*24)]
        last = hours[-1]
        hours[-1] = Candle(last.time,last.open,D(155),last.low,D(155),D(1))
        strategy = DailySwing("donchian-1d")
        raw = [Bar(c.time,*(float(x) for x in (c.open,c.high,c.low,c.close,c.volume))) for c in hours]
        self.assertEqual(strategy.view(hours),swing_view(resample(raw,24)))
        self.assertIsNone(strategy.view(hours[-250:]))
        book = Book(1,D(154),D(155),D(20),D(20))
        self.assertIsNone(strategy.on_close(hours[:-1],book))
        self.assertIsNotNone(strategy.on_close(hours,book))

    def test_trailing_stop_is_persistent_and_never_moves_down(self):
        from datetime import datetime, timedelta, timezone
        from spot_data import Candle

        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"trail.sqlite3"
            state = State(path,"10000")
            f = Filters(D(".001"),D(".001"),D("5"),D(".01"))
            engine = PaperExecutor(state,f)
            now = 1_800_000_000
            book = Book(1,D(100),D(101),D(100),D(100))
            engine.on_book(book,now)
            engine.on_close(123,Intent(D(99),D(95),None),book,now)
            engine.on_book(Book(2,D(98),D("98.5"),D(100),D(100)),now+1)
            after = datetime.fromtimestamp(now, timezone.utc)+timedelta(hours=1)
            fresh = Candle(after,D(100),D(108),D(100),D(106),D(1))
            stale = Candle(after-timedelta(hours=2),D(100),D(200),D(100),D(106),D(1))
            engine.trail((stale,fresh),D(2))
            state.db.close()
            state = State(path,"1")
            engine = PaperExecutor(state,f)
            engine.trail((fresh,),D(3))
            with state.transaction() as w:
                self.assertEqual(D(w["position"]["stop"]),D(102))
            state.db.close()
