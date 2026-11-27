# analyist-bot

Offline Python research for hourly PAXG/USDT Spot candles. The repository contains a paper simulator, a historical comparison, a public market-data downloader and regression tests. It uses public Binance Spot data for real-time paper execution and has no real-account integration.

Use Python 3.10 or later in a system with the IANA timezone database.

```sh
python3 fetch_paxg_archive.py paxg.csv
python3 paxg_research.py paxg.csv > result.json
```

The bundled report evaluates execution assumptions, trend and session filters, exits, risk controls and walk-forward validation. The active configurations did not establish a profitable edge. See the [research report](PAXG_RESEARCH.md) and [derived metrics](paper_runs/paxg-research.json). Raw Binance data is downloaded separately.

## Two-year pullback and mean-reversion study

```sh
python3 archive_data.py PAXGUSDT --end 2026-11-25
python3 paxg_edge.py data/training/PAXGUSDT_1h.csv > result.json
```

The [study report](PAXG_EDGE.md) and [walk-forward metrics](paper_runs/paxg-edge.json) cover passive entry simulation, order expiry, and cost stress. All configurations failed the online eligibility criteria.

## PAXG V2 research and real-time paper trading

```sh
python3 -m pip install -r requirements.txt
python3 archive_data.py PAXGUSDT XAUTUSDT BTCUSDT --end 2026-11-25
python3 paxg_edge_v2.py data/training > paper_runs/paxg-edge-v2.json
python3 -m unittest -v
```

The [4H and 1D research report](PAXG_EDGE_V2.md) covers spread trading, grid trading, cost stress, and the buy-and-hold benchmark.

```sh
# Run with no time limit.
python3 -m live --mode paper --db paper.sqlite3

# Exercise simulated orders with the sample strategy and a separate ledger.
python3 -m live --mode paper --strategy demo-pullback --db demo.sqlite3

# Check the live connection with three quotes.
python3 -m live --mode paper --max-books 3 --db smoke.sqlite3
```

`live/stream.py` listens to Binance Spot kline and bookTicker streams. It loads closed candles over REST and backfills gaps on reconnect. `--public-stream` selects Binance's alternate market-data-only host. Strategies in `live/strategy.py` build simulated order proposals from closed candles and current quotes. The default strategy is EMA 1D. Use `--strategy observe` for price monitoring.

`live/executor.py` records a simulated fill when a new quote moves beyond the limit and the displayed quantity is sufficient. It validates the relationship between the limit, stop, and target, as well as the quantity step. Order queue position between quotes is unknown. The first quote after a disconnect is used to evaluate stops and targets. Historical candles recovered on reconnect do not initiate new entries.

`live/state.py` stores simulated cash, the open position, pending orders, an idempotency key for each candle close, and realized PnL in SQLite. A 1% UTC-day equity loss blocks new entries and cancels pending entries. Open positions follow their own stop or target. Price gaps or insufficient liquidity can result in losses beyond the threshold. Run one process per ledger. Restarting with the same database resumes with the saved balance.

Optional settings are listed in `.env.example`. `PAPER_WEBHOOK_URL` sends simulated fills, exits, connection errors, and daily status updates to an HTTPS endpoint. Continuous operation requires a running host.

The supported mode is `paper`. Public data requires no Binance API key.

## V3 daily trend strategies and Docker

```sh
python3 archive_data.py PAXGUSDT --end 2026-11-26
python3 paxg_edge_v3.py data/training/PAXGUSDT_1h.csv > paper_runs/paxg-edge-v3.json
python3 -m unittest -v
python3 -m live --mode paper --strategy donchian-1d --db donchian.sqlite3
python3 -m live --mode paper --strategy keltner-1d --db keltner.sqlite3
```

Donchian 1D and Keltner 1D load 1,344 closed hourly candles to build the 4H and 1D history. EMA 1D loads 4,321 closed hourly candles to cover its Monte Carlo lookback. Strategies compute and log the latest daily signal at startup. New paper orders are evaluated after a fresh daily close. Active stops and wallet state persist in SQLite.

```sh
docker build -t analyist-bot .
docker volume create paxg-paper
docker run -d --name paxg-paper --restart unless-stopped \
  -v paxg-paper:/state analyist-bot --mode paper --strategy donchian-1d
docker logs -f paxg-paper
```

Docker keeps the paper process running on an active host under the configured restart policy. Both `--mode testnet` and `--mode live` exit before connecting to an account. This deployment reads public Binance Spot data and simulates orders locally. [V3 research report](PAXG_EDGE_V3.md)

### Paper execution parity and Compose

```sh
python3 paxg_edge_v3.py data/training/PAXGUSDT_1h.csv --paper-parity > paper_runs/paxg-paper-parity.json
python3 -m live --mode paper --strategy ema-1d --db ema.sqlite3
```

The daily loss lock cancels pending entries. Open positions continue to follow their ATR stop or profit target. At the UTC day rollover, the last recorded equity becomes the new day's reference. The parity test runs the online paper code with synthetic quotes and compares two intrabar price paths. [Parity results](PAXG_EDGE_V3.md#online-paper-paritesi)

```sh
cp .env.example .env  # First-time setup only.
docker compose up -d --build
docker compose logs -f paper
```

Compose 2.24 or later is required. `PAPER_STRATEGY` defaults to `ema-1d`. Options include `keltner-1d`, `donchian-1d`, and `observe`. The named volume persists `/state`. To use a separate ledger when changing strategies, use a different Compose project name, such as `docker compose -p paxg-ema up -d --build`. Once a day, the first valid quote at or after 00:05 UTC triggers a status entry in SQLite and the logs. A configured webhook also receives the update through its delivery queue.

The default EMA 1D paper settings are a four-hour order lifetime and a 25% position cap. The following command runs the [sensitivity study](PAXG_EDGE_V3.md#ema-1d-emir-ömrü-ve-pozisyon-tavanı), which compares one- and four-hour order lifetimes and 25% and 50% position caps.

```sh
python3 paxg_edge_v3.py data/training/PAXGUSDT_1h.csv --ema-sensitivity > paper_runs/paxg-ema-sensitivity.json
```

### Live paper reports and notifications

```sh
python -m live --report --db paper.sqlite3
python -m live --report --db paper.sqlite3 --export-csv paper-events.csv
docker compose exec paper python -m live --report
docker compose exec paper python -m live --report --export-csv /state/paper-events.csv
```

The report opens SQLite in read-only mode and works offline. JSON includes order counts, fill rate, closed trades, profit factor, realized PnL, equity change, tracked maximum drawdown, and the open position. CSV export writes the event ledger to a new file. Existing files are preserved.

`mean_paper_entry_slippage_bps` compares the simulated fill price with the bid observed when the signal was generated. `mean_trigger_ask_vs_signal_bid_bps` separately measures how far the triggering ask was from that bid. The simulator records limit entries at the limit price. Legacy records without quotes are excluded from slippage calculations. Metrics without sufficient samples appear as `null`. Older ledgers begin tracking maximum drawdown once they run on a version that supports it.

The engine passes signals and quotes to an `ExecutionAdapter`. The built-in `PaperExecutionAdapter` handles simulated order submission, cancellation, status checks, and balance reads.

Set `PAPER_WEBHOOK_URL` for JSON webhooks. Set both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to enable Turkish Telegram messages. Signals, simulated fills, exits, daily entry locks, and daily status updates go to a delivery queue. Network errors do not block the engine. A full queue or a delivery failure can drop a notification. [Telegram Bot API](https://core.telegram.org/bots/api#sendmessage)

Compose retains up to three log files of 10 MB each. The health check verifies SQLite access and checks that a quote was processed within the last 180 seconds. An `unhealthy` status is reported for monitoring. The restart policy applies when the process exits. The WebSocket connection rotates after about 23 hours and 55 minutes. Reconnects backfill missing candles, and historical closes do not create new orders. [Binance Spot WebSocket documentation](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams)

### EMA 1D paper risk checks

EMA paper entries are evaluated against seven checks, including a 0.5% planned risk per trade, a 25% position cap, and a 1% daily entry lock. Startup requests 4,321 closed hourly candles for Monte Carlo analysis. The default `--mc-seed` is 42. Gaps in the 180-day history are reported on the trade ticket. Tickets and fills are recorded in the SQLite event ledger and sent to configured notification channels. The EMA profit reference is used for analysis and does not create a sell order. [Method and parity results](PAXG_EDGE_V3.md#ema-1d-risk-kapısı-ve-timemachine)

### 10-hour live paper test

To observe the daily EMA decision, include the 00:00 UTC close in the test window. Run the following from the project directory with a separate SQLite ledger and unused output paths. The command converts a virtual TRY 10,000 budget at the public USDT/TRY ask, with a modeled conversion fee of 0.10%.

```sh
PAPER_CASH_USDT="$(python3 -c 'from decimal import Decimal as D; from spot_data import get_json; q=get_json("ticker/bookTicker", symbol="USDTTRY"); print(D("9990")/D(q["askPrice"]))')" &&
python3 -m live --mode paper --strategy ema-1d --duration-hours 10 \
  --cash "$PAPER_CASH_USDT" --db paper_runs/soak-10h-next.sqlite3 \
  --export-csv paper_runs/soak-10h-next.csv
```

Install local dependencies with `python3 -m pip install -r requirements.txt`. When the run ends, it prints the report and writes it to `paper_runs/soak-10h-next.json`. The event log is exported as `paper_runs/soak-10h-next.csv`. The JSON includes live quotes, closed candles, disconnects and reconnects, the health check, and daily decisions. TimeMachine and a trade ticket are produced only if a daily entry signal qualifies for order evaluation. The Docker command below runs the same timed test in a separate container.

```sh
mkdir -p paper_runs
docker compose build paper
docker compose run -d --no-deps --name paxg-soak-10h-next --user "$(id -u):$(id -g)" \
  -e PAPER_DB=/results/soak-10h-next.sqlite3 -v "$PWD/paper_runs:/results" paper \
  --mode paper --strategy ema-1d --duration-hours 10 \
  --cash "${PAPER_CASH_USDT:?set virtual starting USDT using the formula above}" \
  --export-csv /results/soak-10h-next.csv
docker logs -f paxg-soak-10h-next
```

`BLOCK: existing_order_or_position` tickets are recorded in SQLite and CSV only.

### Completed live paper tests

Both PAXG/USDT Spot tests started with a virtual budget of TRY 10,000. The USDT equivalent used the opening USDT/TRY ask and a modeled conversion fee of 0.10%. All orders were simulated.

| Duration | Live quotes | Closed hourly candles | Disconnects / reconnects | Orders / fills | Final health |
| --- | ---: | ---: | ---: | ---: | --- |
| 4 hours | 25,449 | 4 | 0 / 0 | 0 / 0 | `healthy` |
| 10 hours | 650,236 | 10 | 1 / 1 | 0 / 0 | `healthy` |

The 10-hour test ran from 01:18:56 to 11:18:59 Istanbul time on November 27, 2026. At the 03:00 Istanbul time daily close, `ema-1d` reported `entry=false`, so no TimeMachine result or trade ticket was generated. No missing candles were found after reconnecting. The virtual balance stayed at **197.66521567 USDT**, with **0 USDT** in realized PnL and **0%** maximum drawdown. With no trade samples, fill rate, entry slippage, and profit factor appear as `null` in JSON. The 10-hour CSV contains two status updates.

- 10-hour test. [JSON report](paper_runs/soak-10h.json) · [CSV event log](paper_runs/soak-10h.csv) · [Opening conversion record](paper_runs/soak-10h-funding.json)
- 4-hour test. [JSON report](paper_runs/soak-4h.json) · [CSV event log](paper_runs/soak-4h.csv) · [Opening conversion record](paper_runs/soak-4h-funding.json)

The `initial_usdt` field in `--report` identifies the starting balance for comparison with the funding record. The following command revalues the virtual balance at the current USDT/TRY bid. The reports do not include a historical closing exchange rate.

```sh
python -m live.try_report paper_runs/soak-10h-funding.json < paper_runs/soak-10h.json
```

### Why the EMA 1D strategy produced no entry signal

The engine aggregates closed hourly candles into UTC daily candles. An entry requires the daily close to be above the EMA20, the EMA20 to be above the SMA50, and the EMA20 to be at least as high as its previous value. `bookTicker` updates do not create daily signals.

The 10-hour test contained one daily close, at 00:00 UTC on November 27, 2026. The daily OHLC values aggregated from 1,224 hourly candles from Binance Spot REST matched Binance's 51 daily candles. The close was **3,561.46 USDT**, the EMA20 was **3,736.28 USDT** (down from **3,754.69 USDT**), and the SMA50 was **3,958.98 USDT**. All three entry conditions failed, so the engine never reached order or risk evaluation. [Binance Spot kline documentation](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market)

Current reports include the candle close time, each EMA condition, and the indicator values in `last_signal` and the daily decisions. If the expected final candle is incomplete, reports show `entry: null` and `reason: missing_complete_daily_history`. The indicator can be recalculated after the missing data is recovered. The historical test reports above reflect the version used in each run.
