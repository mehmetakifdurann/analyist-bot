# analyist-bot

Offline Python research for hourly PAXG/USDT Spot candles. The repository contains a paper simulator, a historical comparison, a public market-data downloader and regression tests. It has no account or order API integration.

Use Python 3.10 or later in a system with the IANA timezone database.

```sh
python3 fetch_paxg_archive.py paxg.csv
python3 paxg_research.py paxg.csv > result.json
python3 -m unittest -v
```

The bundled report evaluates execution assumptions, trend and session filters, exits, risk controls and walk-forward validation. The active configurations did not establish a profitable edge. See the [research report](PAXG_RESEARCH.md) and [derived metrics](paper_runs/paxg-research.json). Raw Binance data is downloaded separately.

## Two-year pullback and mean-reversion study

```sh
python3 archive_data.py PAXGUSDT --end 2026-11-25
python3 paxg_edge.py data/training/PAXGUSDT_1h.csv > result.json
```

The [study report](PAXG_EDGE.md) and [walk-forward metrics](paper_runs/paxg-edge.json) cover passive entry simulation, order expiry, and cost stress. All configurations failed the online eligibility criteria.
