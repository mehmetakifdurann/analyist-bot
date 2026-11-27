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

    def test_missing_hour_cannot_relabel_previous_day_as_current(self):
        from live.strategy import DailySwing
        from live.stream import candle_at

        hours = [candle_at(i*H, [100+i//24,101+i//24,99+i//24,100+i//24,1])
                 for i in range(52*24)]
        strategy = DailySwing("ema-1d")
        book = Book(1,D(151),D(152),D(20),D(20))
        self.assertTrue(strategy.view(hours[:-24]).flags[2])
        missing_last_day_hour = hours[:-12]+hours[-11:]
        self.assertIsNone(strategy.on_close(missing_last_day_hour,book))
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


class PaperParityRegressionTests(unittest.TestCase):
    def test_daily_entry_lock_preserves_open_swing_until_its_stop(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"test.sqlite3"
            state = State(path,"10000")
            engine = PaperExecutor(state,Filters(D(".001"),D(".001"),D("5"),D(".01")))
            now = 1_800_000_000
            engine.on_book(Book(1,D(100),D(101),D(100),D(100)),now)
            engine.on_close(123,Intent(D(99),D(90),None),
                            Book(1,D(100),D(101),D(100),D(100)),now)
            engine.on_book(Book(2,D(98),D("98.5"),D(100),D(100)),now+1)
            _, _, events = engine.on_book(Book(3,D(94),D(95),D(100),D(100)),now+2)
            self.assertEqual([e["kind"] for e in events], ["daily_limit"])
            with state.transaction() as wallet:
                self.assertTrue(wallet["locked"])
                self.assertIsNotNone(wallet["position"])
            _, _, events = engine.on_book(Book(4,D(89),D(90),D(100),D(100)),now+3)
            self.assertEqual(events[0]["kind"], "stop")
            state.db.close()

    def test_heartbeat_after_0005_once_across_restart(self):
        from datetime import datetime, timezone
        from live.notify import heartbeat
        t = int(datetime(2026,11,26,tzinfo=timezone.utc).timestamp())
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"beat.sqlite3"
            state = State(path,"10000")
            engine = PaperExecutor(state,Filters(D(".001"),D(".001"),D("5"),D(".01")))
            book = Book(1,D(100),D(101),D(100),D(100))
            engine.on_book(book,t)
            notifier = Mock()
            heartbeat(state,notifier,t+299,None)
            notifier.publish.assert_not_called()
            heartbeat(state,notifier,t+300,{"entry":True})
            state.db.close()
            state = State(path,"1")
            heartbeat(state,notifier,t+370,None)
            notifier.publish.assert_called_once()
            payload = notifier.publish.call_args.args[0]
            self.assertEqual(payload["equity_usdt"],"10000")
            self.assertEqual(payload["last_closed_signal"],{"entry":True})
            self.assertEqual(state.db.execute("SELECT COUNT(*) FROM events").fetchone()[0],1)
            state.db.close()


class PaperSettingsTests(unittest.TestCase):
    def test_size_caps_and_ttl_expiry_at_boundary(self):
        now = 1_800_000_000
        f = Filters(D(".001"), D(".001"), D("5"), D(".01"))
        book = Book(1,D(100),D(101),D(1000),D(1000))
        fill_quote = Book(2,D(98),D("98.5"),D(1000),D(1000))
        for hours in (1,4):
            for cap in (D(".25"),D(".50")):
                with self.subTest(hours=hours,cap=cap):
                    state = State(Path(":memory:"),"10000")
                    self.addCleanup(state.db.close)
                    engine = PaperExecutor(state,f,position_cap=cap)
                    engine.on_book(book,now)
                    engine.on_close(123,Intent(D("99.019"),D(90),None,hours*3600),book,now)
                    with state.transaction() as wallet:
                        order = wallet["pending"]
                        self.assertEqual(D(order["limit"]),D("99.01"))
                        self.assertEqual(order["expires"],now+hours*3600)
                        reserved = D(order["units"])*D(order["limit"])*D("1.001")
                        self.assertLessEqual(reserved,10000*cap)
                        self.assertGreater(reserved,10000*cap-1)
                    _, _, events = engine.on_book(fill_quote,now+hours*3600)
                    self.assertEqual(events[0]["kind"],"canceled")

    def test_authenticated_modes_exit_before_market_or_account_access(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from live.__main__ import main

        for mode in ("testnet","live"):
            with self.subTest(mode=mode), patch("sys.argv",["live","--mode",mode]), \
                 patch("live.__main__.filters") as filters, redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as err:
                    main()
                self.assertEqual(err.exception.code,2)
                filters.assert_not_called()

    def test_ema_default_ttl_keeps_historical_override_available(self):
        from live.strategy import DailySwing
        self.assertEqual(DailySwing("ema-1d").ttl_seconds,14400)
        self.assertEqual(DailySwing("ema-1d",ttl_seconds=3600).ttl_seconds,3600)
        self.assertEqual(DailySwing("keltner-1d").ttl_seconds,3600)


class ObservabilityTests(unittest.TestCase):
    def test_report_slippage_expiry_and_drawdown_survive_reopen(self):
        from live.report import export_csv, healthy, performance, read

        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/"paper.sqlite3"
            state = State(path,"10000")
            engine = PaperExecutor(state,Filters(D(".001"),D(".001"),D("5"),D(".01")))
            t = 1_800_000_000
            book = Book(1,D(100),D(101),D(100),D(100))
            engine.on_book(book,t)
            order = engine.submit(123,Intent(D(99),D(90),D(105)),book,t)
            self.assertEqual(engine.order_status(order["id"]),"submitted")
            engine.on_book(Book(2,D(98),D("98.5"),D(100),D(100)),t+1)
            self.assertEqual(engine.order_status(order["id"]),"filled")
            engine.on_book(Book(3,D(89),D(90),D(100),D(100)),t+2)
            engine.on_book(book,t+86400)
            pending = engine.submit(124,Intent(D(99),D(90),None),book,t+86400)
            engine.on_book(book,t+90000)
            self.assertEqual(engine.order_status(pending["id"]),"canceled")
            self.assertEqual(engine.balance()["pending"],None)
            state.db.close()
            wallet, events_ = read(path)
            result = performance(wallet,events_)
            self.assertEqual((result["submitted"],result["filled"],result["expired"]),(2,1,1))
            self.assertEqual(result["mean_paper_entry_slippage_bps"],-100)
            self.assertEqual(result["mean_trigger_ask_vs_signal_bid_bps"],-150)
            self.assertEqual(result["closed_trades"],1)
            self.assertGreater(result["max_drawdown_pct"],0)
            self.assertTrue(healthy(path, t+90001))
            self.assertFalse(healthy(path, t+90200))
            csv_path = Path(root)/"events.csv"
            export_csv(csv_path,events_)
            self.assertIn("trigger_ask",csv_path.read_text())
            with self.assertRaises(FileExistsError):
                export_csv(csv_path,events_)

    def test_telegram_message_is_queued_and_blank_settings_are_disabled(self):
        from live.notify import Notifier, message
        event = {"kind":"filled","units":"0.3","fill_price":"3500"}
        self.assertIn("Sanal dolum",message(event))
        self.assertIsNone(Notifier(None,"123:example","").queue)
        with patch("live.notify.Thread") as worker:
            notifier = Notifier(None,"123:example","100")
            notifier.publish(event)
            self.assertEqual(notifier.queue.get_nowait(),event)
            worker.return_value.start.assert_called_once()

    def test_24_hour_disconnect_resyncs_book_and_closed_candle_without_replay(self):
        from websockets.exceptions import ConnectionClosedError
        from websockets.frames import Close

        def quote(i):
            return json.dumps({"stream":"paxgusdt@bookTicker",
                               "data":dict(s="PAXGUSDT",u=i,b="100",a="101",B="100",A="100")})

        def candle(i):
            return json.dumps({"stream":"paxgusdt@kline_1h","data":{"s":"PAXGUSDT","k":{
                "t":i*H,"T":(i+1)*H-1,"i":"1h","x":True,"o":"100","h":"101",
                "l":"99","c":"100","v":"10"}}})

        a,b = Mock(), Mock()
        close = Close(1008,"24 hour connection lifetime")
        a.recv.side_effect = [quote(8),ConnectionClosedError(close,None)]
        b.recv.side_effect = [candle(4),quote(9),candle(5),quote(10)]
        with patch("live.stream.connect",side_effect=[nullcontext(a),nullcontext(b)]), \
             patch("live.stream.get_json",side_effect=[{"serverTime":4*H},[rest_row(3)],
                                                        {"serverTime":5*H},[rest_row(4)]]), \
             patch("live.stream.time.sleep"):
            gen = events(warmup_hours=1)
            self.assertTrue(next(gen).warmup)
            self.assertEqual(next(gen).update,8)
            recovered = next(gen)
            self.assertTrue(recovered.warmup)
            self.assertEqual(stamp(recovered.candles[-1]),4*H)
            self.assertEqual(next(gen).update,9)
            realtime = next(gen)
            self.assertFalse(realtime.warmup)
            self.assertEqual(stamp(realtime.candles[-1]),5*H)
            self.assertEqual(next(gen).update,10)
            gen.close()


class SoakTests(unittest.TestCase):
    def test_timed_command_closes_stream_and_database_and_exports(self):
        import io
        import sqlite3
        from contextlib import redirect_stdout
        from live.__main__ import main

        now = 1_800_000_000
        monotonic = [10.]
        closed = []
        f = Filters(D(".001"), D(".001"), D(5), D(".01"))

        def feed(*args, deadline, stats):
            self.assertEqual(deadline, 13.6)
            stats["websocket_connections"] = 1
            try:
                yield Book(1,D(100),D(101),D(100),D(100))
                monotonic[0] = deadline
                yield Book(2,D(100),D(101),D(100),D(100))
            finally:
                closed.append("stream")

        with tempfile.TemporaryDirectory() as folder:
            db, csv = (Path(folder)/name for name in ("soak.sqlite3","soak.csv"))
            state = State(db,"10000")
            out = io.StringIO()
            with patch("sys.argv",["live","--duration-hours",".001","--strategy","observe",
                                  "--db",str(db),"--export-csv",str(csv)]), \
                 patch("live.__main__.filters",return_value=f), \
                 patch("live.__main__.State",return_value=state), \
                 patch("live.__main__.events",side_effect=feed), \
                 patch("live.__main__.time.monotonic",side_effect=lambda:monotonic[0]), \
                 patch("live.__main__.healthy",return_value=True), redirect_stdout(out):
                main()
            report = json.loads(out.getvalue())
            self.assertTrue(report["soak"]["completed"])
            self.assertEqual(report["soak"]["book_tickers"],1)
            self.assertEqual(report["soak"]["websocket_reconnections"],0)
            self.assertEqual(report["soak"]["healthcheck"],"healthy")
            self.assertEqual(closed,["stream"])
            self.assertTrue(csv.is_file())
            self.assertEqual(json.loads(csv.with_suffix(".json").read_text()),report)
            with self.assertRaises(sqlite3.ProgrammingError):
                state.db.execute("SELECT 1")

    def test_deadline_bounds_idle_receive_without_counting_disconnect(self):
        from live.stream import candle_at

        now = [10.]
        ws = Mock()

        def idle(*, timeout):
            self.assertAlmostEqual(timeout,2)
            now[0] = 12.
            raise TimeoutError()

        ws.recv.side_effect = idle
        stats = {}
        with patch("live.stream.connect",return_value=nullcontext(ws)), \
             patch("live.stream.backfill",return_value=[candle_at(0, rest_row(0)[1:6])]), \
             patch("live.stream.time.monotonic",side_effect=lambda:now[0]):
            self.assertEqual(len(list(events(deadline=12,stats=stats))),1)
        self.assertEqual(stats,{"websocket_connections":1})


class RiskTicketTests(unittest.TestCase):
    def test_bootstrap_deterministic_and_exhaustive(self):
        from live.timemachine import simulate
        args = ([-.02, .03, 0.],100.,95.,110.)
        first = simulate(*args,seed=81,paths=250,hours=12)
        self.assertEqual(first,simulate(*args,seed=81,paths=250,hours=12))
        self.assertAlmostEqual(sum(first[k] for k in ("p_target_pct","p_stop_pct","p_open_pct")),100)
        self.assertEqual(simulate([0],100,95,110,paths=2)["p_open_pct"],100)

    def test_risk_ticket_size_and_quote_guards(self):
        from live.notify import message
        state = State(Path(":memory:"),"10000")
        self.addCleanup(state.db.close)
        executor = PaperExecutor(state,Filters(D(".001"),D(".001"),D(5),D(".01")))
        book = Book(1,D(100),D("100.01"),D(1000),D(1000))
        wide = Book(2,D(100),D(101),D(1000),D(1000))
        now = 1_800_000_000
        executor.on_book(book,now)
        intent = Intent(D(100),D(90),None,14400)
        mc = dict(p_target_pct=25,expected_r=.1)
        for candle,b,shock,expected in ((1,wide,D(1),"BLOCK: spread"),
                                        (2,book,D(4),"BLOCK: volatility"),
                                        (3,book,D(1),"PASS")):
            ticket = executor.submit(candle,intent,b,now,context=dict(shock=shock,timemachine=mc))
            self.assertEqual(ticket["risk_check"],expected)
            self.assertIn(expected,message(ticket))
        self.assertLess(D(ticket["units"]),D(5))
        self.assertLessEqual(D(ticket["risk_usdt"]),D(50))
        self.assertTrue(ticket["target_is_diagnostic"])
        self.assertIsNone(executor.balance()["pending"]["target"])
        changes = executor.on_book(Book(3,D(99),D("99.01"),D(1000),D(1000)),now+1)[2]
        self.assertEqual(changes[0]["ticket"],ticket)
        self.assertIn("dolum",message(changes[0]))


class TenHourSoakTests(unittest.TestCase):
    def test_existing_position_block_is_not_queued(self):
        from live.notify import Notifier

        url = "https://example.invalid/webhook"
        with patch("live.notify.Thread"):
            notifier = Notifier(url, "123:mock-token", "456")
            routine = {"kind":"trade_ticket","risk_check":"BLOCK: existing_order_or_position"}
            notifier.publish(routine)
            self.assertTrue(notifier.queue.empty())
            allowed = [
                {"kind":"trade_ticket","risk_check":"PASS"},
                {"kind":"trade_ticket","risk_check":"BLOCK: spread"},
                {"kind":"trade_ticket","risk_check":"BLOCK: volatility"},
                {"kind":"filled"},
                {"kind":"stop"},
                {"kind":"paper_heartbeat"},
            ]
            for event in allowed:
                notifier.publish(event)
                self.assertEqual(notifier.queue.get_nowait(),event)

    def test_ten_hour_default_paths_and_duration(self):
        import io
        from contextlib import redirect_stdout
        from live.__main__ import main

        f = Filters(D(".001"),D(".001"),D(5),D(".01"))
        clock = [10.]

        def feed(*args, deadline, stats):
            self.assertEqual(deadline,36010)
            stats["websocket_connections"] = 1
            yield Book(1,D(100),D(101),D(100),D(100))
            clock[0] = deadline

        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            db = folder/"paper.sqlite3"
            with patch("sys.argv",["live","--duration-hours","10","--db",str(db)]), \
                 patch("live.__main__.Path",side_effect=lambda p:folder/p), \
                 patch("live.__main__.time.monotonic",side_effect=lambda:clock[0]), \
                 patch("live.__main__.filters",return_value=f), \
                 patch("live.__main__.events",side_effect=feed), redirect_stdout(io.StringIO()):
                main()
            csv = folder/"paper_runs/soak-10h.csv"
            self.assertTrue(csv.is_file())
            report = json.loads(csv.with_suffix(".json").read_text())
            self.assertTrue(report["soak"]["completed"])
            self.assertEqual(report["soak"]["elapsed_seconds"],36000)
            self.assertEqual(report["soak"]["book_tickers"],1)

    def test_daily_close_includes_ticket_and_diagnostics_in_soak_report(self):
        from live.__main__ import run
        from live.strategy import DailySwing
        from live.stream import candle_at
        from paxg_edge_v2 import View

        stamp_ms = 23*H
        c = candle_at(stamp_ms,rest_row(23)[1:6])
        book = Book(1,D(100),D("100.01"),D(100),D(100))
        strategy = DailySwing("ema-1d")
        engine = Mock()
        ticket = {"kind":"trade_ticket","risk_check":"PASS","timemachine":{"p_target_pct":50}}
        engine.submit.return_value = ticket
        engine.on_book.return_value = D(10000),D(0),[]
        engine.daily_heartbeat.return_value = None
        stats = dict(warmup_candles=0,closed_1h_candles=0,backfilled_candles=0,utc_daily_closes=0,
                     entry_signals=0,daily_decisions=[])
        view = View(3, 98, True, (False, False, True), 100, 96, 97)
        with patch.object(strategy,"view",return_value=view), \
             patch("live.__main__.diagnose",return_value=ticket["timemachine"]):
            run([History((c,),False),book],engine,strategy,Mock(),clock=lambda:86400,
                stats=stats,risk_overlay=True)
        decision, = stats["daily_decisions"]
        self.assertEqual(decision["closed_at_utc"],"1970-01-02T00:00:00+00:00")
        self.assertTrue(decision["fresh_quote"])
        self.assertTrue(decision["signal"]["entry"])
        self.assertEqual(decision["signal"]["closed_at_utc"], decision["closed_at_utc"])
        self.assertEqual(decision["signal"]["indicators"]["ema20"], 98)
        self.assertTrue(all(decision["signal"]["checks"].values()))
        self.assertEqual(decision["trade_ticket"],ticket)
