# Rasathane: kişisel gündem ve yönetilebilir ürün revizyonu

Sahip: **Av. Mehmet Arın Gülüm**. Başlangıç: 3 Ekim 2026.

## Kabul ölçütleri ve çalışma sırası

1. **Gerçek ayar arızası:** Profil menüsü → ayarlar → alan değişikliği → kaydet → yeniden aç yolunu Electron pointer girdisiyle izle. Başlangıç, olay/focus, form, IPC ve kalıcı kayıt sınırlarını ayır. Kullanıcının 3 Ekim talimatı gereği Computer Use kullanılmaz; gizli Electron kabul testleri ve kurulu uygulamanın açıkça seçilen smoke modu kullanılır. Sentetik DOM `.click()` kontrolünü pointer testinin yerine sayma.
2. **Kişisel gündem:** İlgi alanları, proje bağlamı, seçilen çalışma alanları ve konu takibini kalıcı bir profile bağla. Kaynak güncellemesi ardından yeni içeriği önem, ilgili olduğu proje, gerekçe, kaynak kanıtı ve önerilen aksiyonla değerlendir. Durum/son başarılı kontrol/sonraki kontrol/hata görünür olsun; değişmeyen içerik için mükerrer bülten üretme.
3. **Yeni gezinme:** Soldaki ana menüyü header'a taşı. Profil/ayarlar üst sağda, görünür Ayarlar erişimiyle yer alsın. Gündem, akış ve kaynak yönetiminde gerçek içerik ve iş durumları öncelikli olsun. Küçük ekranda menü yatay kayabilsin; içerik yatay taşmasın.
4. **Kaynak yönetimi ve asistan:** Kategoriye göre grupla/filtrele; kolay adres girişiyle RSS keşfet. Sohbete yazılan açık kaynak ekleme, kategori değiştirme ve duraklatma işlemlerini dar, doğrulanmış araçlarla uygula. Belirsiz komutta sohbet içinde açıklama iste; başarılı işlemin somut sonucunu göster. Tarihçe, tekrar güvenliği ve hata görünürlüğü sağla.
5. **Muhakeme görünürlüğü:** Ayrı agent Muhakeme.ai vitrini/üye panelindeki Rasathane tanıtım ve ürün kartlarını kaldırır. Ortak giriş altyapısı, mevcut kullanıcı verisi ve ödeme/cihaz geçmişi korunur. Değişiklik kendi repo'sunda kaydedilir ve yayın durumu açıkça belirtilir.
6. **Kabul ve teslim:** Kaynak, kategori, ayar ve otomatik gündem senaryoları; gerçek pointer/klavye etkileşimi; model yok/başarısız/yanıt kaynaksız; logout/iptal; uygulama yeniden açılışı; küçük ekran ve iki tema. Sonra bağımsız inceleme, imzalı paket, yedekli kurulum, gerçek kurulu kullanıcı akışı ve temiz repo/kayıtlar.

## Tasarım yönü

Mevcut r logosu ve koyu yeşil marka korunur: zemin #0b1712, yüzey #14251d,
ikincil yüzey #1a3026, metin #f7f0df, ikincil metin #bfcec0, vurgu #efb389.
Yerel IBM Plex Sans okunabilir gövde; Space Grotesk ana başlıklar için kullanılır.
Header solda marka, ortada gezinme, sağda durum ve profil; altta tek geniş çalışma
yüzeyi bulunur. Gündem ilk sırada kişiye ilişkin değerlendirmeyi, ardından kanıtlı
haberleri gösterir. Kontroller görev adıyla etiketlenir, gereksiz teknik ayrıntılar
diagnostics içinde tutulur.

## Durum

- Tamamlandı: yatay header, doğrudan Ayarlar, blur sırasında menü kaybının kaldırılması, kişisel gündem UI ve kaynak sohbeti/kategori yönetimi.
- Tamamlandı: kaynak batch → gündem bağımlılığı, eşzamanlı isteklerde tek batch, ilgiye göre pencere taraması ve kaynak çeşitliliği, değişmeyen içerik için cache, güncel bağlam kontrolü, yerel model cold start ve RAM kilidi.
- Tamamlandı: 60 kaynak UI kabul kontrolü, 125 hedef backend testi, bağımsız UI incelemesi, gerçek RAM8 model testi. Testler kişisel gündem okuma/Türkçe WAV, profil kaydı, kaynak sohbeti, pointer ayarlar, reload/logout ve küçük ekranı kapsar.
- Tamamlandı: ayrı agent ile Muhakeme vitrini/üye paneli düzeltmesi; PR68 birleşti. Canlı ana sayfa/fiyatlandırma/yönlendirme ve giriş guard'ları 9/9, üye paneli server component 7/7 geçti. Canlı oturumlu üye ekranı okunmadı.
- Tamamlandı: 883 engine testi (1 skip, 16 deselected), 42 UI controller ve 51 Electron kontrolü, Ruff/format ve strict mypy. Gerçek RAM8 sekiz haberli model testi 33,86 saniyede sekiz doğrulanmış alıntıyla tamamlandı.
- Paket ve kurulum kabulü ayrıca `releases/0.7.0/release-manifest.json`, `packaged-acceptance.json` ve yerel kurulum readback makbuzuyla kaydedilir. Kaynak testlerinin geçmesi tek başına kurulum kabulü değildir.
