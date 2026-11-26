# PAXG Spot V3 · günlük swing ve 1D/4H hibrit

Arşiv, 28 Ağustos 2020 12:00 UTC–26 Kasım 2026 04:00 UTC arasında 54.712 kapanmış PAXG/USDT saatlik mum içeriyor. Mevcut Binance arşivindeki ilk kayıt kullanıldı. Arşivde 11 boşluk var, 6 geçersiz satır elendi. Resample, yalnızca eksiksiz UTC 4H ve 1D blokları kabul eder. Kesintisiz 51 blok yoksa yeni gösterge üretilmez. Açık pozisyonlar boşluktan sonraki ilk gözlenen açılışta stop koşuluyla değerlendirilir. Eksik saat için fiyat üretilmez. [Binance Spot arşivi](https://github.com/binance/binance-public-data)

## Walk-forward sonuçları

11 dilimde 365 gün eğitim, 1 gün boşluk ve 182 güne kadar ileri test kullanıldı. İleri test 30 Ağustos 2021–26 Kasım 2026 UTC aralığındadır. Her eğitimde seçim 26 bp tek yönlü maliyetle getiriden azami düşüş çıkarılarak yapılır. En az üç eğitim işlemi yoksa sabit baz kullanılır. Aday kanal uzunluğu 15/20/25, Keltner çarpanı 1/1,5/2, takip mesafesi 2,5/3/3,5 ATR. EMA giriş parametresi sabittir. Bakiye dilimler arasında taşınır. Pozisyonlar dilim sonunda kapanır, al ve tut tüm test süresince tek pozisyondur. Sonuçlar USDT. Maliyetler tek yönlüdür.

| Walk-forward | İşlem | Net 12 bp | Net 26 bp | Net 36 bp | PF 36 bp | Azami düşüş 36 bp | Sharpe 36 bp | 26 bp pozitif dönem |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Donchian 1D | 39 | +%17,93 | +%9,24 | +%3,44 | 1,07 | %17,42 | 0,12 | 6/11 |
| Keltner 1D | 34 | +%32,88 | +%24,29 | +%18,50 | 1,45 | %11,90 | 0,47 | 6/11 |
| EMA 1D | 50 | +%60,55 | +%45,52 | +%35,66 | 1,39 | %19,07 | 0,54 | 5/11 |
| Donchian 1D rejimi + Keltner 4H | 83 | −%3,78 | −%18,22 | −%27,18 | 0,34 | %29,41 | −1,36 | 1/11 |
| PAXG al ve tut | 1 | +%96,07 | +%95,52 | +%95,13 | — | %38,84 | 0,68 | — |

Sabit paper ayarlarına karşılık gelen sinyal parametreleri de aynı ileri test dilimlerinde ayrıca test edildi. **Donchian 20 / takip 3 ATR**, 38 işlem ve 36 bp'de +%11,77 getiri üretti. **Keltner 1,5 / takip 3 ATR**, 43 işlem ve +%15,49 üretti. Dolayısıyla ayarlanmış Donchian ve Keltner için 40 işlem hedefi karşılanmadı. Sabit Keltner ve iki EMA koşusu bu sayıyı aştı. EMA en yüksek net getirili aktif adayken al ve tut, toplam net getiride bütün varyantları geçti.

## V2 ile aynı iki yıllık pencere

| Sabit ayar | İşlem | Net 12 bp | Net 26 bp | Net 36 bp | Azami düşüş 12 bp |
|---|---:|---:|---:|---:|---:|
| Keltner 4H, V2 | 93 | +%16,13 | −%3,22 | −%15,03 | %12,28 |
| Donchian rejimli Keltner 4H, V3 | 52 | +%3,34 | −%6,67 | −%13,22 | %5,99 |
| PAXG al ve tut | 1 | +%29,62 | +%29,26 | +%29,00 | %37,67 |

Hibrit rejim, kapanmış günlük Donchian kırılımı ve yükselen günlük trendle başlar. Günlük trend bozulunca yeni 4H girişleri durur. Keltner 4H girişten sonra iki ATR'de yarıyı kapatır, kalan bölüm ATR stopla izlenir. Stop ve hedef aynı saatte görünürse stop önceliklidir. Kısmi çıkış ve son çıkış tek işlem sayılır.

Sonuçlar bağımsız yeni canlı gerçekleşme testi değildir. Paper ve V3 sabit stratejileri aynı kapanmış mum sinyali ile ATR fonksiyonunu kullanır. V3 girişleri sonraki mumun açılışından varsayarken paper bid tarafında pasif limit, %25 sanal büyüklük ve günlük devre kesici uygular. Paper pozisyonunun takip seviyesi saatlik kapanıştan sonra güncellenir. Bu farklardan ötürü V3 PnL’si paper motorunun beklenen PnL’si olarak kullanılmaz.

[Dönem bazında parametreler, maliyet stresi ve tüm metrikler](paper_runs/paxg-edge-v3.json)

## Online paper paritesi

30 Ağustos 2021–26 Kasım 2026 UTC aralığında iki sabit strateji, online motorun aynı strateji, yürütücü, SQLite ve günlük risk koduyla yeniden oynatıldı. Giriş, gün kapanışından sonraki ilk kotasyonun bid tarafında pasif limit olarak yazılır. Emir ömrü bir saat. Pozisyon nakdin %25'iyle sınırlıdır. Maker ücreti %0,10, stop çıkışı taker ücreti %0,10 ve ek %0,02 kayma kullanır. Günlük %1 kuralı yeni girişleri kilitler ve bekleyen girişi iptal eder. Açık pozisyon kendi stopuyla yönetilir.

| Strateji | Saat içi fiyat sırası | Emir | Dolan | Kapanan | Net USDT getirisi | Profit Factor | Azami düşüş |
|---|---|---:|---:|---:|---:|---:|---:|
| Keltner 1D | Önce dip | 48 | 40 | 40 | +%1,13 | 1,061 | %11,31 |
| Keltner 1D | Önce tepe | 48 | 40 | 40 | +%5,58 | 1,289 | %9,01 |
| EMA 1D | Önce dip | 61 | 50 | 50 | +%7,01 | 1,306 | %10,00 |
| EMA 1D | Önce tepe | 61 | 50 | 50 | +%11,79 | 1,500 | %9,01 |

Her saat, açılış, iki uç ve kapanıştan oluşan dört sentetik kotasyona dönüştürülür. İki senaryoda aynı iki baz puan toplam spread ve yeterli görünen miktar varsayılır. Gerçek saat içi sıra, emir defteri, kuyruk ve geçmiş filtre değişiklikleri bilinmiyor. İki sıra duyarlılık örneğidir ve mümkün olan tüm sonuçları sınırlamaz. Zorunlu dönem sonu satışı yoktur. Net sonuç son bid üzerinden özsermayeyi, PF kapanan işlemleri ölçer. Dört koşunun sonunda da pozisyon kapalıydı.

EMA'nın düşük senaryoda PF 1,30 sınırını az farkla geçmesi, gerçek kotasyon ve dolum koşullarında aynı sonucu kanıtlamaz. Keltner iki senaryoda da PF 1,30'un altında kaldı. [Parite veri çıktısı](paper_runs/paxg-paper-parity.json)

## EMA 1D emir ömrü ve pozisyon tavanı

Aynı tarih aralığı, sentetik kotasyonlar, fiyat sıraları ve %1 UTC giriş kilidiyle dört ayar tekrar oynatıldı. Dolum oranı, dolan emir sayısının verilen emir sayısına oranıdır. Net getiri son kotasyondaki özsermayeyi, Profit Factor kapanan işlemleri ölçer.

| Emir ömrü | Tavan | Mum içi sıra | Dolan / verilen | Dolum oranı | Net getiri | PF | Azami düşüş |
|---:|---:|---|---:|---:|---:|---:|---:|
| 1 saat | %25 | Dip önce | 50/61 | %81.97 | %+7.01 | 1.306 | %10.00 |
| 1 saat | %25 | Tepe önce | 50/61 | %81.97 | %+11.79 | 1.500 | %9.01 |
| 1 saat | %50 | Dip önce | 50/61 | %81.97 | %+13.58 | 1.280 | %18.36 |
| 1 saat | %50 | Tepe önce | 50/61 | %81.97 | %+23.62 | 1.458 | %16.54 |
| 4 saat | %25 | Dip önce | 50/52 | %96.15 | %+8.71 | 1.377 | %10.00 |
| 4 saat | %25 | Tepe önce | 50/52 | %96.15 | %+13.57 | 1.570 | %9.01 |
| 4 saat | %50 | Dip önce | 50/52 | %96.15 | %+17.18 | 1.348 | %18.36 |
| 4 saat | %50 | Tepe önce | 50/52 | %96.15 | %+27.54 | 1.524 | %16.54 |

Bir saat ve %25 referans ayarı önceki EMA paritesinin tüm metriklerini birebir üretti. Dört saat ve %25 iki fiyat sırasında da PF'yi iyileştirdi ve azami düşüşü değiştirmedi. Dolu emir sayısı 50 kaldı. Oranın yükselmesi, daha az emir verilmesinden kaynaklandı. %50 pozisyon tavanı iki fiyat sırasında da azami düşüşü artırdı. EMA 1D paper varsayılanı dört saat ve %25 olarak ayarlandı. Bu seçim aynı tarihsel arşivdeki duyarlılık deneyine dayanır.

[Sekiz koşunun ayrıntıları](paper_runs/paxg-ema-sensitivity.json)
