# PAXG Spot pullback ve ortalamaya dönüş deneyi

**Aşama 1 sonucu.** Dört varyant da en az 50 ileri test işlemi üretti. Hepsi net zarar etti, Profit Factor 1,30'un altında kaldı ve Sharpe negatifti. Online aşaması için seçilen strateji yok.

| Varyant | OOS işlem | Net USDT getirisi | Profit Factor | Sharpe | Azami düşüş |
|---|---:|---:|---:|---:|---:|
| A · 4H trend, 1H EMA geri çekilmesi | 62 | −%4,74 | 0,356 | −2,80 | %4,77 |
| A · Kapanış bar aralığının üst dörtte birinde | 63 | −%3,73 | 0,445 | −2,27 | %3,73 |
| B · Düşük ADX, Bollinger/dip geri kazanımı | 52 | −%4,12 | 0,423 | −2,25 | %4,71 |
| B · Kapanış bar aralığının üst dörtte birinde | 50 | −%5,98 | 0,147 | −3,84 | %6,20 |

## Kurallar ve gerçekleşme varsayımları

A, kapanmış 4H bloklarında fiyatın 20 bar ortalaması ve 20 blok önceki kapanışın üzerinde olmasını ister. Saatlik mum EMA20 bölgesine iner ve üzerinde yükselişle kapanır. B, ADX(14) ≤ 25 iken önceki 20 kapanıştan hesaplanan alt Bollinger bandını veya önceki 20 mumun dibini süpürüp tekrar üzerinde kapanır. İki seviyeden biri geçerliyse yalnızca geri kazanılan seviyeler hesaba katılır. Üst dörtte bir şartı her iki aileye ikinci deney olarak eklendi. Bu ikinci tur aynı arşivi tekrar kullandığı için keşif amaçlıdır.

Sinyal kapandıktan sonra emir en erken sonraki bar açılışında sanal deftere girer ve bir ya da üç bar geçerlidir. Yeni emir açılışta alış limitine ulaşılmışsa iptal edilir. Normal dolumda fiyat limitin 2 baz puan ötesine geçmelidir. Önceden bekleyen limitin altında açılırsa limit fiyatından dolum varsayılır ve stop altındaki boşluk açılıştan kapatılır. Sadece dokunma dolum sayılmaz. Giriş barında kâr hedefi sayılmaz, stop geçerlidir. Sonraki barlarda iki seviyeye birden erişilirse stopa öncelik verilir. Kâr hedefi maker, stop ve süre sonu taker kabul edilir. Sınırda açık pozisyon kapatılır.

Baz senaryo maker/taker için ayrı ayrı 10 baz puan, taker çıkışında 6 baz puan ek kayma kullanır. Stres senaryosunda bunlar 12/12/12 ve fiyat penetrasyonu 5 baz puandır. OHLCV emir kuyruğu, spread veya kısmi dolum göstermez. Alış ücreti alınan varlıktan düşülür. Pozisyon başlangıçta sermayenin %25'iyle ve stopta planlanan %0,5 riskle sınırlandırılır. Açılış boşluğu bu riski aşabilir. [Binance Spot ücret tablosu](https://www.binance.com/en/fee/trading)

## Walk-forward ve kayıp teşhisi

25 Kasım 2024–24 Kasım 2026 UTC boyunca 17.520 saat ve ayrıca 200 ısınma saati kullanıldı. On ileri test dilimi 24 Mayıs 2025–24 Kasım 2026 UTC arasındaki 13.200 saati kapsıyor. Her dilim için 179 günlük eğitim, bir günlük boşluk ve en fazla 60 günlük test vardır. Dört varyantın her biri için 36 ayar denendi. Seçimde yalnız eğitim sonuçları ve tek parametrede farklı olan komşuların ortalaması kullanıldı. Eğitimde 15 işlem üreten aday bulunmadığında fallback seçim raporda işaretlenir. Bu seçim araştırma karşılaştırması üretir, dağıtım izni vermez.

A ve B'nin baz sonuçları aynı dolum fiyatlarını koruyup doğrudan ücret ve kayma etkisini geri ekleyince bile sırasıyla −102,50 ve −94,06 USDT. Güçlü kapanışlı A aynı hesapta +10,67 USDT brüt verdi, ancak 383,92 USDT ücret ve kayma etkisiyle −373,25 USDT nete indi. Bu ayrıştırma aynı dolumları ve pozisyon büyüklüklerini sabit tutan bir teşhistir. Ücretsiz yeni bir replay sonucu değildir. Stres senaryosunda dört varyant da negatif kaldı.

## Online aşamasına geçiş koşulu

Geçiş için OOS işlem sayısı en az 50, Profit Factor > 1,30, net sonuç ve Sharpe pozitif olmalıdır. Çıktıda `online_eligible_family` boş kaldı. Bu nedenle ikinci aşama başlamadı. Başarılı bir aday oluştuğunda sonraki doğrulama, Binance'in herkese açık Spot WebSocket akışı ve REST ile boşluk tamamlama üzerinden gerçek zamanlı sanal dolumları ölçer. Saatlik mum varsayımlarını gerçek emir kuyruğu davranışıyla karşılaştırmak için bu adım gerekir. [Binance Spot piyasa verisi belgeleri](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md)

[Dönem bazında emir sonuçları, ayarlar ve tüm risk metrikleri](paper_runs/paxg-edge.json)
