"""Download public PAXGUSDT Spot hourly candles for the reproducible case study."""
import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from paxg_research import END, HOUR, START


def download(output: Path) -> None:
    start = START - 120 * HOUR
    cursor = int(start.timestamp() * 1000)
    end = int(END.timestamp() * 1000)
    records = []
    while cursor < end:
        query = urlencode(dict(symbol="PAXGUSDT", interval="1h", limit=1000,
                               startTime=cursor, endTime=end-1))
        with urlopen("https://data-api.binance.vision/api/v3/klines?" + query, timeout=20) as response:
            rows = json.load(response)
        if not rows:
            raise ValueError(f"Missing Binance candle at {cursor}")
        for row in rows:
            if row[0] != cursor or row[0] >= end or row[6] != cursor + 3_599_999:
                raise ValueError(f"Unexpected Binance candle at {cursor}")
            stamp = datetime.fromtimestamp(row[0]/1000, timezone.utc).isoformat()
            records.append((stamp, *row[1:5], row[7]))
            cursor += int(timedelta(hours=1).total_seconds() * 1000)
    with output.open("x", newline="", encoding="utf-8") as stream:
        out = csv.writer(stream)
        out.writerow(("timestamp", "open", "high", "low", "close", "quote_volume"))
        out.writerows(records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    download(parser.parse_args().output)
