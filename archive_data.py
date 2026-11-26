"""Download verified Binance Vision Spot 1h archives for offline research."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from spot_data import BASE, INTERVAL_MS, get_json


VISION = "https://data.binance.vision/data/spot/monthly/klines"
STARTS = {"PAXGUSDT": date(2020, 8, 28), "XAUTUSDT": date(2026, 3, 26),
          "BTCUSDT": date(2020, 8, 28)}
FIELDS = ["timestamp", "open", "high", "low", "close", "base_volume", "quote_volume",
          "trade_count", "taker_buy_base", "taker_buy_quote", "source"]


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fetch_bytes(url: str) -> bytes:
    for attempt in range(3):
        try:
            with urlopen(url, timeout=30) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise ValueError(f"Arşiv HTTP {exc.code}: {url}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt == 2:
                raise ValueError(f"Arşiv erişim hatası: {url}: {exc}") from exc
        time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def month_starts(first: date, last: date):
    cursor = first.replace(day=1)
    while cursor <= last:
        yield cursor
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)


def archive_file(symbol: str, month: date, root: Path) -> tuple[Path, str]:
    name = f"{symbol}-1h-{month.year}-{month.month:02d}.zip"
    path = root / symbol / name
    checksum_path = path.with_suffix(".zip.CHECKSUM")
    if path.exists() and checksum_path.exists():
        expected = checksum_path.read_text(encoding="utf-8").split()[0]
        if sha256(path.read_bytes()) == expected:
            return path, expected
    url = f"{VISION}/{symbol}/1h/{name}"
    raw = fetch_bytes(url)
    checksum = fetch_bytes(url + ".CHECKSUM").decode("utf-8").strip().split()[0]
    if sha256(raw) != checksum:
        raise ValueError(f"Binance SHA-256 uyuşmazlığı: {name}")
    with zipfile.ZipFile(io.BytesIO(raw)) as zipped:
        if zipped.namelist() != [name.replace(".zip", ".csv")]:
            raise ValueError(f"Arşiv içeriği beklenenden farklı: {name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".tmp").write_bytes(raw)
    path.with_suffix(".tmp").replace(path)
    checksum_path.write_text(f"{checksum}  {name}\n", encoding="utf-8")
    return path, checksum


def millis(value: str | int) -> int:
    number = int(value)
    return number // 1000 if number >= 10**15 else number


def normalized_row(raw: list[str], source: str) -> list[str]:
    if len(raw) < 11:
        raise ValueError(f"Spot mum satırı eksik: {source}")
    stamp = datetime.fromtimestamp(millis(raw[0]) / 1000, timezone.utc)
    prices = [D(raw[i]) for i in (1, 2, 3, 4)]
    volumes = [D(raw[i]) for i in (5, 7, 9, 10)]
    trades = int(raw[8])
    if any(not x.is_finite() or x <= 0 for x in prices):
        raise ValueError(f"Geçersiz Spot fiyatı: {source}")
    if prices[1] < max(prices[0], prices[3]) or prices[2] > min(prices[0], prices[3]):
        raise ValueError(f"Geçersiz Spot OHLC: {source}")
    if any(not x.is_finite() or x < 0 for x in volumes) or trades < 0:
        raise ValueError(f"Geçersiz Spot hacim: {source}")
    if millis(raw[6]) < millis(raw[0]) + INTERVAL_MS - 1:
        raise ValueError(f"Kapanış zamanı geçersiz: {source}")
    return [stamp.isoformat(), *[str(x) for x in prices], str(volumes[0]), str(volumes[1]),
            str(trades), str(volumes[2]), str(volumes[3]), source]


def api_tail(symbol: str, start: date, end: date, root: Path) -> tuple[list[list[str]], dict]:
    first_ms = int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc).timestamp() * 1000)
    server_ms = int(get_json("time")["serverTime"])
    end_ms = min(end_ms, server_ms)
    rows: list[list[str]] = []
    cursor = first_ms
    while cursor < end_ms:
        batch = get_json("klines", symbol=symbol, interval="1h", startTime=cursor,
                         endTime=end_ms - 1, limit=1000)
        if not batch:
            break
        for row in batch:
            if row[6] < server_ms and row[0] < end_ms:
                rows.append(normalized_row([str(x) for x in row], "spot_api"))
        next_cursor = int(batch[-1][0]) + INTERVAL_MS
        if next_cursor <= cursor:
            raise ValueError("Spot API sayfalama ilerlemiyor")
        cursor = next_cursor
    raw_path = root / symbol / f"{start.year}-{start.month:02d}_spot_api.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_bytes = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    raw_path.write_bytes(raw_bytes)
    return rows, {"file": str(raw_path), "sha256": sha256(raw_bytes), "rows": len(rows)}


def collect(symbol: str, end: date, root: Path) -> dict:
    if symbol not in STARTS:
        raise ValueError("Yalnızca onaylı Spot araştırma sembolleri kullanılabilir")
    first = STARTS[symbol]
    if end < first:
        raise ValueError("Bitiş tarihi listeleme tarihinden önce")
    info = get_json("exchangeInfo", symbol=symbol)["symbols"][0]
    if info["symbol"] != symbol or info["status"] != "TRADING" or not info["isSpotTradingAllowed"]:
        raise ValueError(f"Aktif Spot sembolü değil: {symbol}")

    this_month = end.replace(day=1)
    archived_months = [m for m in month_starts(first, end) if m < this_month]
    archives: list[tuple[Path, str]] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(archive_file, symbol, month, root): month for month in archived_months}
        for future in as_completed(futures):
            archives.append(future.result())
    archives.sort()
    rows: list[list[str]] = []
    sources: list[dict] = []
    anomalies: list[dict] = []
    for path, digest in archives:
        with zipfile.ZipFile(path) as zipped:
            with zipped.open(zipped.namelist()[0]) as stream:
                reader = csv.reader(io.TextIOWrapper(stream, encoding="utf-8"))
                for line, raw in enumerate(reader, 1):
                    try:
                        row = normalized_row(raw, path.name)
                    except (ValueError, IndexError) as exc:
                        anomalies.append({"source": path.name, "line": line, "reason": str(exc)})
                        continue
                    if first <= date.fromisoformat(row[0][:10]) <= end:
                        rows.append(row)
        sources.append({"file": str(path), "sha256": digest})
    tail, tail_source = api_tail(symbol, this_month, end, root)
    rows.extend(tail)
    sources.append(tail_source)
    rows.sort(key=lambda row: row[0])
    if len(rows) < 200:
        raise ValueError("Eğitim için yeterli kapanmış Spot mumu yok")
    gaps = []
    for previous, current in zip(rows, rows[1:]):
        delta = datetime.fromisoformat(current[0]) - datetime.fromisoformat(previous[0])
        if delta <= timedelta(0):
            raise ValueError("Tekrarlanan veya ters Spot saati")
        if delta != timedelta(hours=1):
            gaps.append({"after": previous[0], "before": current[0], "missing_hours": int(delta.total_seconds() / 3600) - 1})
    out = root.parent / "training" / f"{symbol}_1h.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.with_suffix(".tmp")
    with temp.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(FIELDS)
        writer.writerows(rows)
    temp.replace(out)
    manifest = {"venue": "Binance Spot", "symbol": symbol, "interval": "1h",
                "first": rows[0][0], "last": rows[-1][0], "count": len(rows),
                "gaps": gaps, "anomalies": anomalies, "sources": sources,
                "csv_sha256": sha256(out.read_bytes()),
                "license": "Binance Vision dataset terms: CC BY-NC-SA 4.0, personal non-production research"}
    out.with_suffix(".json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"path": str(out), "count": len(rows), "gaps": len(gaps),
            "anomalies": len(anomalies), "first": rows[0][0], "last": rows[-1][0]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Doğrulanmış Binance Vision Spot 1h araştırma verisi")
    parser.add_argument("symbols", nargs="+", choices=sorted(STARTS))
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--root", type=Path, default=Path("data/vision"))
    args = parser.parse_args()
    try:
        for symbol in args.symbols:
            result = collect(symbol, args.end, args.root)
            print(f"{symbol}: {result['count']} saat, {result['gaps']} boşluk, "
                  f"{result['anomalies']} hatalı satır dışlandı, "
                  f"{result['first']} → {result['last']} → {result['path']}", flush=True)
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
