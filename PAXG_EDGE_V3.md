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
