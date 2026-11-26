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

## PAXG V2 araştırması ve gerçek zamanlı paper

```sh
python3 -m pip install -r requirements.txt
python3 archive_data.py PAXGUSDT XAUTUSDT BTCUSDT --end 2026-11-25
python3 paxg_edge_v2.py data/training > paper_runs/paxg-edge-v2.json
python3 -m unittest -v
```

[4H ve 1D araştırma raporu](PAXG_EDGE_V2.md) makas, grid, maliyet stresi ve al ve tut karşılaştırmasını içerir.

```sh
# Süre sınırı olmadan açık piyasa verisini izle.
python3 -m live --mode paper --db paper.sqlite3

# Sanal emir üretimini örnek strateji ile dene. Ayrı bir sanal defter kullan.
python3 -m live --mode paper --strategy demo-pullback --db demo.sqlite3

# Canlı bağlantıda üç kotasyonla sınırlı kontrol.
python3 -m live --mode paper --max-books 3 --db smoke.sqlite3
```

`live/stream.py` Binance Spot kline ve bookTicker dinler. REST'ten ilk 250 kapalı mumu alır ve bağlantı yenilendiğinde eksik mumları tamamlar. `--public-stream` Binance'in yalnız piyasa verisi sunan alternatif alan adını seçer. `live/strategy.py` yeni stratejilerin kapalı mum ve güncel emir defteri üzerinden sanal emir önerisi üretmesini sağlar. Varsayılan gözlem modudur.

`live/executor.py`, yeni kotasyonda fiyat limitin ötesine geçtiğinde ve görünen miktar yeterliyse sanal dolum yazar. Limit, stop ve hedef ilişkisi ile miktar adımı denetlenir. Kotasyonlar arasındaki emir kuyruğu bilinmez. Kesinti sırasında varsayımsal gerçekleşme üretilmez, stop ve hedef ilk yeni kotasyonda tekrar değerlendirilir. Eski mumlardan yeni giriş başlatılmaz.

`live/state.py` SQLite içinde sanal nakit, açık pozisyon, bekleyen emir, kapanış başına tek emir kimliği ve gerçekleşen PnL saklar. `live/risk.py` UTC günündeki %1 özsermaye kaybında yeni girişleri durdurur ve yeterli görüntülenen miktar geldiğinde açık sanal pozisyonu kapatmaya çalışır. Fiyat boşluğu veya yetersiz miktar yüzünden kayıp eşiği aşılabilir. Her sanal defter için tek süreç kullan. Aynı dosyayla tekrar başlatınca önceki bakiye kullanılır.

İsteğe bağlı ayarlar `.env.example` dosyasındadır. `PAPER_WEBHOOK_URL` bir HTTPS alıcısına sanal dolum, çıkış, bağlantı hatası ve UTC gün özeti gönderir. 7/24 çalışması için komutun açık bir makinede sürmesi gerekir.

`--mode live` gerçek Binance hesabına bağlanan bir mod değildir ve açıklayıcı bir hata ile kapanır. Desteklenen mod `paper`dır ve halka açık veri için Binance anahtarı gerekmez.

## V3 günlük trend ve Docker

```sh
python3 archive_data.py PAXGUSDT --end 2026-11-26
python3 paxg_edge_v3.py data/training/PAXGUSDT_1h.csv > paper_runs/paxg-edge-v3.json
python3 -m unittest -v
python3 -m live --mode paper --strategy donchian-1d --db donchian.sqlite3
python3 -m live --mode paper --strategy keltner-1d --db keltner.sqlite3
```

Her iki günlük strateji açılışta 1.344 kapanmış saatlik mumla 4H ve 1D geçmişi oluşturur. 250 saat yalnızca yaklaşık 10 gün sağlar ve günlük SMA50 için yetmez. Başlangıçta günlük sinyal hesaplanır ve loglanır. Yeni paper emirleri güncel bir günlük kapanıştan sonra değerlendirilir. Aktif stop ve hesap durumu SQLite'ta kalır.

```sh
docker build -t analyist-bot .
docker volume create paxg-paper
docker run -d --name paxg-paper --restart unless-stopped \
  -v paxg-paper:/state analyist-bot --mode paper --strategy donchian-1d
docker logs -f paxg-paper
```

Docker ve yeniden başlatma kuralı açık makinede paper sürecini çalıştırır. `--mode testnet` ve `--mode live` hesap bağlantısı açmadan hata verir. Bu dağıtım halka açık Binance Spot verisini okur ve yerel paper emirleri simüle eder. [V3 araştırma raporu](PAXG_EDGE_V3.md)
