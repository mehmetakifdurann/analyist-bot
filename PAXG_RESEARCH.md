# PAXG/USDT saatlik Spot araştırması

Çevrimdışı, uzun yönlü sanal işlem. Sermaye 10.000 USDT. Önce özgün kural ve düzeltilmiş baz karşılaştırıldı, ardından değişiklikler aynı altı ileri test bölümünde ölçüldü. Test aralığı 24 Haziran–24 Kasım 2026 UTC, toplam 3.696 saat.

## Önce baz karşılaştırması

| Varyant | İşlem | Net getiri | Profit Factor | Azami düşüş | Sharpe |
|---|---:|---:|---:|---:|---:|
| Eski, 2 ATR hedef ve toplam 52 bp | 0 | %0,000 | — | %0,000 | — |
| Düzeltilmiş, 2 ATR hedef ve karşılaştırılabilir maliyet senaryosu | 0 | %0,000 | — | %0,000 | — |

Her iki kural da nakitte kaldı. Baz testte fiyat simülasyonu düzeldi ancak bir işlem gözlenmediği için performans farkı ölçülemedi. Tüm 2 ATR aşamalarında sonuç aynıydı.

## A/B karşılaştırması

Aşağıdaki **6 ATR senaryosu**, işlem sayısını artırarak çıkış kurallarının davranışını görmek için kullanılan ayrı duyarlılık deneyidir. 6 ATR ayarı dağıtım için seçilmedi. Seans ve 4H dalları ADX satırıyla kıyaslanır. Daha sonraki çıkış deneyleri 4H dalından ilerler. Tire, ilgili metriğin tanımsız olduğunu gösterir.

| Varyant | İşlem | Net getiri | Profit Factor | Azami düşüş | Sharpe |
|---|---:|---:|---:|---:|---:|
| Düzeltilmiş, sabit maliyet | 18 | −%2,345 | 0,238 | %2,570 | −3,66 |
| Dinamik kayma | 11 | −%1,785 | 0,177 | %2,352 | −3,50 |
| + ADX(14) | 11 | −%1,785 | 0,177 | %2,352 | −3,50 |
| + Londra–New York örtüşmesi | 1 | −%0,422 | 0,000 | %0,422 | −2,58 |
| + 4H trend onayı | 10 | −%1,520 | 0,201 | %2,088 | −3,10 |
| + Örtüşme ve 4H birlikte | 1 | −%0,422 | 0,000 | %0,422 | −2,58 |
| 4H + başa baş, 1R veya 1,5R | 10 | −%1,520 | 0,201 | %2,088 | −3,10 |
| + 1R’de kısmi çıkış | 10 | −%1,480 | 0,222 | %1,985 | −3,06 |
| + ATR takibi ve dinamik süre | 10 | −%1,289 | 0,370 | %1,581 | −2,73 |
| + Devre kesici ve risk ölçekleme | 10 | −%1,169 | 0,393 | %1,574 | −2,53 |
| Yüksek maliyet stresi | 0 | %0,000 | — | %0,000 | — |
| Eğitim platolarıyla walk-forward seçim | 0 | %0,000 | — | %0,000 | — |

Tek işlemli seans sonucu kıyas için zayıftır. ADX ve başa baş bu örnekte sonucu değiştirmedi. Kısmi çıkış ve takip eden stop düşüşü azalttı, fakat sınanan hiçbir aktif varyant pozitif net getiri sağlamadı.

## Simülasyon ve doğrulama

- Giriş, stop ve hedef için aynı fiyat ve maliyet modeli kullanılır. Giriş maliyeti ile net stop arasındaki fark risk, net hedef ile giriş maliyeti arasındaki fark ödüldür. Önceki formülün yaklaşık maliyetleri ile gerçekleşme modeli arasındaki fark böylece giderildi. Maker ve taker ücretleri ayrı ayarlanır. Varsayılan her ikisi için 10 bp, hedef pasif limit dolumu varsayar. Kuyruk ve kısmi gerçekleşme bilgisi OHLCV’de yoktur. Sabit bazda taker kayması bacak başına 16 bp. Dinamik senaryoda 4 bp taban ve önceki mum ATR’sine bağlı, 35 bp ile sınırlanan ek terim kullanılır. [Binance Spot ücret tablosu](https://www.binance.com/en/fee/trading)
- Stop seviyesinin altında açılışta açılış fiyatı ve kayma uygulanır. Bar içinde stop ve hedefe beraber dokunulursa stop önce gelir. Açılışın hedefte veya üstünde olması, zaten açık pozisyon için öncelikli olaydır. Takip eden stop ve başa baş güncellemesi bir sonraki barda yürürlüğe girer. Başa baş, aktivasyon anındaki maliyeti kullanır. Fiyat boşluğu ve kayma sonradan değişebilir.
- EMA ilk N kapanışın SMA'sıyla başlatılır. İlk 50 bar sonunda bir önceki SMA ile karşılaştırma mümkün olduğunda sinyal oluşur. Destek ve direnç, sinyal barını dışarıda bırakır. Üst zaman dilimi filtreleri yalnızca kapanmış UTC 4H bloklarını kullanır. Saat filtresi, Londra ve New York yerel saatlerine göre idealize edilen hafta içi örtüşmedir. Tatil takvimi veya likidite garantisi içermez. ADX trendin gücünü, EMA ve 4H onayı yönünü değerlendirir. [ADX yöntem açıklaması](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/dmi)
- Pozisyon boyutu özsermaye ile hesaplanır ve nakit ile sınırlandırılır. Devre kesici UTC günlük %1 ve haftalık %2,5 eşiğini açılış ve kapanış özsermayesinde denetler. Üç ardışık zarar sonrasında 24 saat yeni pozisyon açılmaz. ATR arttıkça risk bütçesi küçülür. Bar içi boşluklar, limitin üzerinde gerçekleşen kayıp doğurabilir.
- Walk-forward için önceki 83 gün eğitim, ardından bir gün boşluk ve en çok 28 gün ileri test kullanılır. Her eğitim penceresinde EMA, kanal uzunluğu, hacim oranı ve stop/hedef ATR çarpanları yerel bir komşulukta taranır. Merkez ve komşular için en az beş işlem, pozitif sonuç ve komşuların çoğunda pozitiflik aranır. Hiçbir pencerede bu koşullar sağlanmadı. Bu arşiv önceki incelemelerde de kullanıldığı için sonuçlar yeni, bağımsız bir canlı doğrulama sayılmaz. [Zaman sıralı test](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)
- Sharpe ve Sortino, nakit saatlerini de içeren saatlik özsermaye getirilerinden 8.760 saat ile yıllıklaştırılır. Calmar yıllık bileşik getiri ve düşüş oranıdır. Yeni simülasyon düşüşü bar içi muhafazakâr işaretlerle ölçer. Eski düşüş ölçümü saatliktir. Kısmi çıkışlar tek pozisyon sonucu olarak toplanır. Seçim, her test bölümü ve toplam için tüm metrikler [JSON çıktısında](paper_runs/paxg-research.json).

Tüm sonuçlar USDT cinsinden. Tarihsel emir sırası, kuyruk, gerçek bid/ask, miktar adımları ve hesap özelindeki ücretler mevcut simülasyonda modellenmiyor.
