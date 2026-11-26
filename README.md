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

`live/stream.py` Binance Spot kline ve bookTicker dinler. REST'ten ilk 250 kapalı mumu alır ve bağlantı yenilendiğinde eksik mumları tamamlar. `--public-stream` Binance'in yalnız piyasa verisi sunan alternatif alan adını seçer. `live/strategy.py` yeni stratejilerin kapalı mum ve güncel emir defteri üzerinden sanal emir önerisi üretmesini sağlar. Varsayılan paper stratejisi EMA 1D. Yalnızca fiyat izlemek için `--strategy observe` seçilebilir.

`live/executor.py`, yeni kotasyonda fiyat limitin ötesine geçtiğinde ve görünen miktar yeterliyse sanal dolum yazar. Limit, stop ve hedef ilişkisi ile miktar adımı denetlenir. Kotasyonlar arasındaki emir kuyruğu bilinmez. Kesinti sırasında varsayımsal gerçekleşme üretilmez, stop ve hedef ilk yeni kotasyonda tekrar değerlendirilir. Eski mumlardan yeni giriş başlatılmaz.

`live/state.py` SQLite içinde sanal nakit, açık pozisyon, bekleyen emir, kapanış başına tek emir kimliği ve gerçekleşen PnL saklar. `live/risk.py` UTC günündeki %1 özsermaye kaybında yeni girişleri kilitler ve bekleyen giriş emrini iptal eder. Açık pozisyon kendi stop veya hedefiyle yönetilir. Fiyat boşluğu veya yetersiz miktar yüzünden kayıp eşiği aşılabilir. Her sanal defter için tek süreç kullan. Aynı dosyayla tekrar başlatınca önceki bakiye kullanılır.

İsteğe bağlı ayarlar `.env.example` dosyasındadır. `PAPER_WEBHOOK_URL` bir HTTPS alıcısına sanal dolum, çıkış, bağlantı hatası ve günlük durum bildirimi gönderir. 7/24 çalışması için komutun açık bir makinede sürmesi gerekir.

`--mode live` gerçek Binance hesabına bağlanan bir mod değildir ve açıklayıcı bir hata ile kapanır. Desteklenen mod `paper`dır ve halka açık veri için Binance anahtarı gerekmez.

## V3 günlük trend ve Docker

```sh
python3 archive_data.py PAXGUSDT --end 2026-11-26
python3 paxg_edge_v3.py data/training/PAXGUSDT_1h.csv > paper_runs/paxg-edge-v3.json
python3 -m unittest -v
python3 -m live --mode paper --strategy donchian-1d --db donchian.sqlite3
python3 -m live --mode paper --strategy keltner-1d --db keltner.sqlite3
```

Günlük stratejiler açılışta 1.344 kapanmış saatlik mumla 4H ve 1D geçmişi oluşturur. 250 saat yalnızca yaklaşık 10 gün sağlar ve günlük SMA50 için yetmez. Başlangıçta günlük sinyal hesaplanır ve loglanır. Yeni paper emirleri güncel bir günlük kapanıştan sonra değerlendirilir. Aktif stop ve hesap durumu SQLite'ta kalır.

```sh
docker build -t analyist-bot .
docker volume create paxg-paper
docker run -d --name paxg-paper --restart unless-stopped \
  -v paxg-paper:/state analyist-bot --mode paper --strategy donchian-1d
docker logs -f paxg-paper
```

Docker ve yeniden başlatma kuralı açık makinede paper sürecini çalıştırır. `--mode testnet` ve `--mode live` hesap bağlantısı açmadan hata verir. Bu dağıtım halka açık Binance Spot verisini okur ve yerel paper emirleri simüle eder. [V3 araştırma raporu](PAXG_EDGE_V3.md)


### Paper paritesi ve Compose

```sh
python3 paxg_edge_v3.py data/training/PAXGUSDT_1h.csv --paper-parity > paper_runs/paxg-paper-parity.json
python3 -m live --mode paper --strategy ema-1d --db ema.sqlite3
```

Günlük kayıp kilidi bekleyen girişleri iptal eder. Açık pozisyonun ATR stopu veya kâr hedefi işlemeye devam eder. UTC gün değişiminde önceki son özsermaye yeni günün referansıdır. Parite denemesi online paper kodunu sentetik kotasyonla çalıştırır ve iki farklı mum içi fiyat sırasını raporlar. [Sonuçlar](PAXG_EDGE_V3.md#online-paper-paritesi)

```sh
cp .env.example .env  # yalnızca ilk kurulumda
docker compose up -d --build
docker compose logs -f paper
```

Compose 2.24+ gerekir. `PAPER_STRATEGY` varsayılanı `ema-1d`; `keltner-1d`, `donchian-1d` ve `observe` seçenekleri de var. `/state` adlandırılmış volume'da kalıcıdır. Strateji değiştirirken eski pozisyonları karıştırmamak için ayrı bir Compose proje adı kullan. Örneğin `docker compose -p paxg-ema up -d --build`. Günlük durum, 00:05 UTC veya sonrasındaki ilk geçerli kotasyonda SQLite'a ve loga bir kez yazılır. Webhook yapılandırılmışsa gönderim kuyruğuna da eklenir. Webhook teslimi bağlantıya bağlıdır.

Herkese açık piyasa verisiyle çalışan desteklenen seçenek `--mode paper`. `--mode testnet` ve `--mode live` (onay bayrağı dahil) hesap bağlantısı açmadan hata verir.


Varsayılan EMA 1D paper ayarı dört saat emir ömrü ve %25 pozisyon tavanıdır. EMA 1D için bir ve dört saatlik emir ömrü ile %25 ve %50 pozisyon tavanını karşılaştıran [duyarlılık deneyi](PAXG_EDGE_V3.md#ema-1d-emir-ömrü-ve-pozisyon-tavanı) şu komutla üretilebilir:

```sh
python3 paxg_edge_v3.py data/training/PAXGUSDT_1h.csv --ema-sensitivity > paper_runs/paxg-ema-sensitivity.json
```

### Canlı paper raporu ve bildirimler

```sh
python -m live --report --db paper.sqlite3
python -m live --report --db paper.sqlite3 --export-csv paper-events.csv
docker compose exec paper python -m live --report
docker compose exec paper python -m live --report --export-csv /state/paper-events.csv
```

Rapor SQLite'ı salt okunur açar ve ağ bağlantısı gerektirmez. Emir sayıları, dolum oranı, kapanan işlemler, Profit Factor, gerçekleşen PnL, toplam özsermaye değişimi, izlenen azami düşüş ve açık pozisyon JSON olarak yazılır. CSV olay defterini yeni bir dosyaya aktarır. Var olan dosyaların üzerine yazılmaz.

`mean_paper_entry_slippage_bps` sanal dolum fiyatını sinyalde görülen bid ile karşılaştırır. `mean_trigger_ask_vs_signal_bid_bps` dolumu tetikleyen kotasyonu ayrı gösterir. Limit girişinin sanal dolumu limit fiyatından kaydedilir. Eski kayıtlarda kotasyon alanları eksik olabilir. Bu kayıtlar kayma hesabına katılmaz. Yeterli örnek olmadığında ilgili metrik `null` görünür. Önceden oluşturulmuş defterlerde azami düşüş takibi bu sürüme geçişten sonra başlar.

`ExecutionAdapter` motorun yerel yürütme sınırıdır. Ana döngü bu arayüze sinyal ve kotasyon verir. Dahili `PaperExecutionAdapter` emir oluşturma, iptal, durum sorgulama ve bakiye okumayı yürütür. Motor yalnızca sanal defter adaptörünü çalıştırır.

JSON webhook için `PAPER_WEBHOOK_URL`, Türkçe Telegram mesajları için `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` ayarlanabilir. Telegram iki değer de doluyken etkinleşir. İşlem sinyali, sanal dolum, çıkış, günlük giriş kilidi ve günlük durum özeti gönderim kuyruğuna alınır. Ağ hatası motoru bekletmez. Kuyruk dolduğunda veya gönderim başarısız olduğunda mesaj düşebilir. [Telegram Bot API](https://core.telegram.org/bots/api#sendmessage)

Compose, her biri en fazla 10 MB olan üç log dosyası tutar. Sağlık kontrolü SQLite'ın okunabildiğini ve son 180 saniyede kotasyon işlendiğini denetler. `unhealthy` durumu izleme içindir; Compose'un yeniden başlatma politikası süreç çıkışına uygulanır. WebSocket yaklaşık 23 saat 55 dakikada yenilenir. Bağlantı kurulduğunda eksik mumlar tamamlanır ve geçmiş kapanışlardan yeni emir açılmaz. [Binance Spot WebSocket belgeleri](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams)

### EMA 1D paper risk kapısı

EMA paper sinyalleri %0,5 planlı risk, %25 pozisyon tavanı, %1 günlük giriş kilidi ve yedi kontrolle değerlendirilir. Açılışta Monte Carlo için 4.321 kapanmış saatlik mum istenir. `--mc-seed` varsayılanı 42. 180 günlük geçmiş kesintiliyse fiş Monte Carlo eksikliğini raporlar. Fişler ve dolumlar SQLite olay defterine yazılır ve yapılandırılmış bildirimlere gider. EMA kâr referansı bir satış emri oluşturmaz. [Yöntem ve parite](PAXG_EDGE_V3.md#ema-1d-risk-kapısı-ve-timemachine)
