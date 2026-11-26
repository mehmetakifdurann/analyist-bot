"""Read-only Binance Spot market data. This module has no authenticated endpoints."""

from __future__ import annotations

import csv
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen


BASE = "https://data-api.binance.vision/api/v3"
ALLOWED_SYMBOLS = {"PAXGUSDT", "XAUTUSDT"}
INTERVAL_MS = 3_600_000  # 1h only, so validation and indicators use one clock.


@dataclass(frozen=True)
class Candle:
    time: datetime
    open: D
    high: D
    low: D
    close: D
    volume: D


def get_json(endpoint: str, **params):
    url = f"{BASE}/{endpoint}?{urlencode(params)}"
    for attempt in range(3):
        try:
            with urlopen(url, timeout=15) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise ValueError(f"Binance Spot API HTTP {exc.code}: {endpoint}") from exc
            time.sleep(min(int(exc.headers.get("Retry-After", "1")), 10))
        except (URLError, TimeoutError) as exc:
            if attempt == 2:
                raise ValueError(f"Binance Spot API erişilemedi: {exc}") from exc
            time.sleep(1 + attempt)


def spot_rules(symbol: str) -> dict:
    if symbol not in ALLOWED_SYMBOLS:
        raise ValueError(f"Desteklenen Spot pariteler: {', '.join(sorted(ALLOWED_SYMBOLS))}")
    items = get_json("exchangeInfo", symbol=symbol)["symbols"]
    if len(items) != 1:
        raise ValueError(f"Spot parite bulunamadı: {symbol}")
    item = items[0]
    if (item["symbol"] != symbol or item["status"] != "TRADING"
            or not item["isSpotTradingAllowed"] or item["quoteAsset"] != "USDT"
            or item["baseAsset"] != symbol[:-4]):
        raise ValueError(f"Aktif Spot parite değil: {symbol}")
    filters = {entry["filterType"]: entry for entry in item["filters"]}
    lot = filters["LOT_SIZE"]
    notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL")
    if not notional:
        raise ValueError("Spot minimum işlem değeri kuralı bulunamadı")
    return {"symbol": symbol, "base_asset": item["baseAsset"], "quote_asset": item["quoteAsset"],
            "step_size": lot["stepSize"], "min_qty": lot["minQty"],
            "min_notional": notional["minNotional"]}


def current_book(symbol: str) -> dict:
    spot_rules(symbol)
    item = get_json("ticker/bookTicker", symbol=symbol)
    bid, ask = D(item["bidPrice"]), D(item["askPrice"])
    bid_qty, ask_qty = D(item["bidQty"]), D(item["askQty"])
    if item["symbol"] != symbol or not (bid.is_finite() and ask.is_finite() and 0 < bid <= ask):
        raise ValueError("Spot alış/satış kotasyonu geçersiz")
    if any(not q.is_finite() or q < 0 for q in (bid_qty, ask_qty)):
        raise ValueError("Spot defter miktarı geçersiz")
    return {"symbol": symbol, "bid": bid, "ask": ask, "bid_qty": bid_qty, "ask_qty": ask_qty,
            "spread_bps": D("10000") * (ask - bid) / ((ask + bid) / 2),
            "observed_at_utc": datetime.now(timezone.utc).isoformat()}


def download_hourly(symbol: str, start: date, end: date) -> tuple[list[Candle], dict]:
    rules = spot_rules(symbol)
    if start > end:
        raise ValueError("Başlangıç tarihi bitişten sonra olamaz")
    first_ms = int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc).timestamp() * 1000)
    server_ms = int(get_json("time")["serverTime"])
    end_ms = min(end_ms, server_ms)
    if first_ms >= end_ms:
        raise ValueError("İstenen tarihlerde kapanmış mum yok")
    cursor = first_ms
    candles: list[Candle] = []
    while cursor < end_ms:
        rows = get_json("klines", symbol=symbol, interval="1h", startTime=cursor,
                        endTime=end_ms - 1, limit=1000)
        if not rows:
            break
        for row in rows:
            if row[6] >= server_ms or row[0] >= end_ms:
                continue  # Never use an unfinished candle.
            stamp = datetime.fromtimestamp(row[0] / 1000, timezone.utc)
            candle = Candle(stamp, D(row[1]), D(row[2]), D(row[3]), D(row[4]), D(row[5]))
            validate_candle(candle)
            if candles and stamp <= candles[-1].time:
                raise ValueError("Binance Spot verisinde tekrarlanan veya ters zaman var")
            candles.append(candle)
        next_cursor = int(rows[-1][0]) + INTERVAL_MS
        if next_cursor <= cursor:
            raise ValueError("Binance Spot sayfalama ilerlemiyor")
        cursor = next_cursor
    if len(candles) < 120:
        raise ValueError("İstenen aralıkta en az 120 kapanmış saatlik mum bulunmalı")
    validate_contiguity(candles)
    return candles, rules


def validate_candle(candle: Candle) -> None:
    prices = (candle.open, candle.high, candle.low, candle.close)
    if any(not p.is_finite() or p <= 0 for p in prices):
        raise ValueError("Mum fiyatı pozitif ve sonlu olmalı")
    if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close):
        raise ValueError("Mum OHLC değerleri tutarsız")
    if not candle.volume.is_finite() or candle.volume < 0:
        raise ValueError("Mum hacmi geçersiz")


def validate_contiguity(candles: list[Candle]) -> None:
    for previous, current in zip(candles, candles[1:]):
        if (current.time - previous.time).total_seconds() != 3600:
            raise ValueError(f"Saatlik veri boşluğu: {previous.time.isoformat()} → {current.time.isoformat()}")


def save_dataset(path: Path, candles: list[Candle], rules: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for c in candles:
            writer.writerow([c.time.isoformat(), c.open, c.high, c.low, c.close, c.volume])
    temporary.replace(path)
    metadata = {"venue": "Binance Spot", "source": BASE, "interval": "1h",
                "downloaded_at": datetime.now(timezone.utc).isoformat(), "rules": rules,
                "first": candles[0].time.isoformat(), "last": candles[-1].time.isoformat(),
                "count": len(candles), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    meta_path = path.with_suffix(".json")
    meta_temp = meta_path.with_suffix(".tmp")
    meta_temp.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    meta_temp.replace(meta_path)


def load_dataset(path: Path) -> tuple[list[Candle], dict]:
    metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    if metadata.get("venue") != "Binance Spot" or metadata.get("interval") != "1h":
        raise ValueError("Yalnızca Binance Spot 1h veri seti kabul edilir")
    if hashlib.sha256(path.read_bytes()).hexdigest() != metadata.get("sha256"):
        raise ValueError("Spot CSV dosyası meta veriyle uyuşmuyor (SHA-256)")
    rules = metadata["rules"]
    if rules["symbol"] not in ALLOWED_SYMBOLS:
        raise ValueError("Desteklenmeyen Spot parite")
    candles: list[Candle] = []
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != ["timestamp", "open", "high", "low", "close", "volume"]:
            raise ValueError("Spot CSV başlıkları geçersiz")
        for row in reader:
            stamp = datetime.fromisoformat(row["timestamp"])
            if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
                raise ValueError("Binance Spot veri saatleri UTC olmalı")
            candle = Candle(stamp, *(D(row[key]) for key in ("open", "high", "low", "close", "volume")))
            validate_candle(candle)
            candles.append(candle)
    if len(candles) != metadata["count"] or len(candles) < 120:
        raise ValueError("Spot veri sayısı beklenenle uyuşmuyor")
    validate_contiguity(candles)
    if candles[0].time.isoformat() != metadata["first"] or candles[-1].time.isoformat() != metadata["last"]:
        raise ValueError("Spot veri sınırları meta veriyle uyuşmuyor")
    return candles, rules
