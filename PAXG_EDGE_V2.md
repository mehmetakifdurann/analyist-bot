# PAXG Spot strateji araştırması, ikinci tur

Karşılaştırma 10.000 USDT başlangıç sermayesiyle yapıldı. Aşağıdaki eşikler önceden sabit araştırma kurallarıdır. Sonuçlar aynı geçmiş veri üzerinde karşılaştırmalı keşif niteliğindedir. Paylaşılan arşivin dışındaki yeni veride bağımsız performans ölçülmedi.

## Veri ve yürütme

- PAXG, XAUT ve BTC saatlik Binance Spot mumları archive_data.py arşivinden okunur. PAXG mumları UTC 4H ve 1D olarak toplanır. Eksik veya henüz bitmemiş gruplar göstergeye girmez. Karar, tamamlanmış mumdan sonra ilk saatlik açılışta uygulanır. [Binance Spot veri arşivi](https://github.com/binance/binance-public-data)
- Donchian, önceki 20 mumun tepesinin üzerinde kapanışla alır. Keltner, EMA20 + 1,5 ATR kırılımını kullanır. EMA kuralı yükselen EMA20, SMA50 üzerinde trend ve EMA üzerinde kapanış arar. Üçü de 3 ATR takip eden stop kullanır. Stop bir sonraki saatten itibaren güncellenir. Sabit hedef veya tutma süresi yoktur. Swing ve makas işlemleri en fazla %70 sermaye ile açılır.
- Makas, PAXG/XAUT log fiyat oranının önceki 120 saate göre Z skorudur. −2 altında PAXG uzun pozisyonu açılır, −0,25 üzerine dönüldüğünde çıkılır. XAUT kısa satılmaz. BTC filtresi, son kapanmış 24 saatte BTC mutlak getirisi %6 veya üzerindeyse PAXG girişini durdurup varsa pozisyonu kapatır.
- Grid, yalnızca 4H yükseliş filtresinde EMA etrafında üç alış kademesi kurar. Kademe mesafesi en az bir ATR veya fiyatın %0,4'üdür. Kademe başına %20 özsermaye kullanılır. Dönüş hedefi bir üst kademe, rejim çıkışı bir sonraki açılıştır. Limit geçişinde 2 bp fiyat penetrasyonu aranır ve dolum saatinde kâr hedefi sayılmaz. Önceden bekleyen limitin altında açılışta limit fiyatından dolum varsayılır. Aynı bar içindeki belirsiz satış gelirleri yeni alımı finanse etmez. Stop, hedefe göre önceliklidir.
- Modelde baz maliyet **her yön için 10 bp ücret + 2 bp fiyat sürtünmesi**. Stresler yine her yön için **26 ve 36 bp**. Grid limitleri pasif, trend ve makas açılışları ile stoplar taker olarak yorumlanır. Binance normal kullanıcı tablosunda iki ücret de %0,10 olduğundan modelde ikisine de aynı ücret uygulanır. 2 bp varsayımı tarihsel alış/satış farkı veya gerçekleşme ölçümü değildir. Kuyruk ve kısmi dolum verisi bulunmaz. Al ve tut kıyasına aynı maliyetler uygulanır. [Binance Spot ücret tablosu](https://www.binance.com/en/fee/trading)

## Ortak dönem · 1 Mayıs–24 Kasım 2026 UTC

Maliyet sütunları tek yönlüdür. Brüt/net beklenti, kapanan işlem veya grid kademesi başına USDT olarak verilir. İşlem sayısı baz senaryoya aittir.

| Kural | İşlem | 12 bp net getiri | 26 bp net getiri | 36 bp net getiri | 12 bp brüt/net beklenti | 26 bp brüt/net beklenti | 36 bp brüt/net beklenti | Baz azami düşüş |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| PAXG al ve tut | 1 | %-23.37 | %-23.59 | %-23.74 | -2315.88 / -2337.09 | -2312.65 / -2358.51 | -2310.34 / -2373.78 | %26.62 |
| DONCHIAN 4H | 22 | %-5.62 | %-9.59 | %-12.33 | -8.87 / -25.53 | -8.30 / -43.61 | -7.91 / -56.04 | %8.35 |
| KELTNER 4H | 26 | %-4.57 | %-9.31 | %-12.54 | -0.86 / -17.59 | -0.47 / -35.80 | -0.22 / -48.25 | %7.71 |
| EMA 4H | 45 | %-16.28 | %-23.34 | %-28.00 | -20.83 / -36.19 | -19.99 / -51.86 | -19.42 / -62.23 | %17.04 |
| DONCHIAN 1D | 1 | %+2.98 | %+2.77 | %+2.63 | +315.07 / +297.90 | +314.63 / +277.50 | +314.32 / +262.96 | %3.28 |
| KELTNER 1D | 1 | %+2.98 | %+2.77 | %+2.63 | +315.07 / +297.90 | +314.63 / +277.50 | +314.32 / +262.96 | %3.28 |
| EMA 1D | 3 | %-2.59 | %-3.16 | %-3.56 | -69.67 / -86.28 | -69.37 / -105.23 | -69.15 / -118.69 | %6.71 |
| PAXG/XAUT makası | 44 | %-7.14 | %-14.81 | %-19.89 | +0.15 / -16.24 | +0.35 / -33.65 | +0.47 / -45.20 | %9.17 |
| PAXG/XAUT + BTC şok filtresi | 48 | %-8.14 | %-16.38 | %-21.81 | -0.68 / -16.97 | -0.45 / -34.13 | -0.31 / -45.43 | %10.15 |
| Dinamik 4H grid | 13 | %-0.81 | %-1.53 | %-2.04 | -1.46 / -6.24 | -1.46 / -11.75 | -1.46 / -15.66 | %0.92 |

## Uzun dönem · 25 Kasım 2024–24 Kasım 2026 UTC

Maliyet sütunları tek yönlüdür. Brüt/net beklenti, kapanan işlem veya grid kademesi başına USDT olarak verilir. İşlem sayısı baz senaryoya aittir.

| Kural | İşlem | 12 bp net getiri | 26 bp net getiri | 36 bp net getiri | 12 bp brüt/net beklenti | 26 bp brüt/net beklenti | 36 bp brüt/net beklenti | Baz azami düşüş |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| PAXG al ve tut | 1 | %+29.62 | %+29.26 | %+29.00 | +2989.96 / +2962.39 | +2985.78 / +2926.15 | +2982.80 / +2900.32 | %37.67 |
| DONCHIAN 4H | 85 | %+1.63 | %-13.96 | %-23.60 | +19.90 / +1.92 | +19.40 / -16.43 | +19.02 / -27.77 | %17.88 |
| KELTNER 4H | 93 | %+16.13 | %-3.22 | %-15.03 | +36.28 / +17.35 | +33.85 / -3.47 | +32.22 / -16.16 | %12.28 |
| EMA 4H | 144 | %+3.68 | %-21.81 | %-36.07 | +21.25 / +2.55 | +20.00 / -15.15 | +19.10 / -25.05 | %21.87 |
| DONCHIAN 1D | 16 | %+28.63 | %+24.64 | %+21.86 | +197.35 / +178.96 | +193.16 / +154.00 | +190.24 / +136.65 | %8.94 |
| KELTNER 1D | 20 | %+17.27 | %+12.75 | %+9.63 | +104.55 / +86.35 | +102.38 / +63.75 | +100.86 / +48.16 | %13.68 |
| EMA 1D | 24 | %+27.68 | %+21.80 | %+17.76 | +135.66 / +115.35 | +133.72 / +90.82 | +132.35 / +74.01 | %15.45 |
| Dinamik 4H grid | 53 | %-2.67 | %-5.51 | %-7.48 | -0.31 / -5.03 | -0.31 / -10.39 | -0.31 / -14.11 | %2.83 |

## Değerlendirme

İki yılda günlük Donchian, baz senaryoda al ve tut getirisine yaklaşırken düşüşü kayda değer ölçüde azalttı. Üç maliyette de pozitif kaldı. Ancak örneklem 16 kapanan işlem ve tüm dönem aynı araştırma arşivinden. Ortak dönemde günlük Donchian ve Keltner sonuçları birer işleme dayanıyor. Bunlar tekrar test edilmeye değer adaylar, doğrulanmış işlem stratejisi statüsü almadılar.

Kısa ortak dönemde BTC şok filtresi, bu makas kuralını iyileştirmedi. Makas stratejisinin brüt başabaşa yakın sonucu, model maliyetleri sonrası negatife döndü. Grid al ve tuta göre düşüşü sınırladı, ancak her maliyet senaryosunda net zarar etti. Tüm metrikler [JSON çıktısında](paper_runs/paxg-edge-v2.json).
