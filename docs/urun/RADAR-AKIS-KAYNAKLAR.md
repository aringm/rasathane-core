# Rasathane — Akış, bülten ve kaynak yönetimi

**Hedef sürüm:** 0.6.0 · **Sahip:** Av. Mehmet Arın Gülüm

Bu not, özgün Radar düzenine yaklaşan masaüstü revizyonunu açıklar. Kaynak kodu
doğrulamaları tamamlanmıştır; imzalı paket, kurulum ve kullanıcı akışı kabulü
ayrı release kayıtlarında tutulur.

## Akış ve günlük bülten

Akışın üstünde günlük bülten, altında kategori ve kaynak filtreleriyle haber
listesi bulunur. Özgün Radar'ın bülteni görünür tutan düzeni ve ayrı kaynak
yönetimi ekranı bu yapıya taşınmıştır. **Kayıtları yenile** yerel kayıtları yeniden
okur; **Akışı yenile** etkin kaynakların kontrolünü başlatır.

Kategori, kaynak, arama metni ve tarih filtreleri SQLite arşivinin tamamına
uygulanır. Sonuçlar daha sonra sayfalanır; eski bir kaynağın haberleri son 100
haber dışında kaldığı için kaybolmaz. `GET /api/rasathane/articles` yanıtı
`items`, `total`, `limit`, `offset` alanlarını içerir. Türkçe aramada büyük/küçük
harf ve karakter farkları normalize edilir. Karar tarihi, yayım tarihi olarak
yeniden etiketlenmeden mevcut sıralama mantığında kullanılır.

**Bülten oluştur** ile başlık, tarih aralığı ve en fazla 5, 10 veya 20 haber
seçilir. Bültenin kapsamı akışta yüklenmiş, mevcut filtrelerden geçen haberlerdir;
arşivin tamamından kendiliğinden seçim yapmaz. Kapsam ve aday başlıklar bülten
seçeneklerinde gösterilir.

Oluşturulan bülten kalıcı bir anlık görüntüdür. **Bülteni oku** metni açar;
önceki bültenler tarih sırasıyla yeniden açılabilir. Her haberin kaynağı ve
bağlantısı korunur. **Dinle**, ekranda açılan kayıtlı bülteni Türkçe Windows TTS
ile okur. Oynatma hızı 1×–2× arasında seçilebilir; WAV dosyası **Sesi indir** ile
alınır. Hız seçimi oynatıcıya aittir, indirilen WAV dosyasını yeniden üretmez.
Türkçe Windows sesi yoksa açıklayıcı hata gösterilir.

Özetleme **extractive** çalışır: kayıtlı kaynak açıklamalarından cümle seçer.
Haberlerin tam metni bu işlemde edinilmez; başlık dışında metin bulunmayan
kayıtlar da açıkça belirtilir. Özgün Stüdyo, çok konuşmacılı podcast veya LLM
editör sistemi bu revizyonda taşınmış değildir.

## Kaynakları yönetme

Sol menüdeki **Kaynaklar** ekranı ad/adres araması, takipte/duraklatılmış/hatalı
filtreleri ve kaynak tablosunu sunar. Kaynağın adresi, kategorisi, türü, kayıtlı
haber sayısı ve son kontrol durumu birlikte görülebilir.

- **Kaynak ekle** yeni abonelik oluşturur. **Düzenle** ad, adres, tür, kategori
  ve takip durumunu değiştirir.
- **Duraklatıldı** durumuna almak yeni edinimi durdurur; kayıtlı haberleri ve
  bültenleri silmez. **Kontrol et** tek kaynağı, **Tümünü kontrol et** etkin
  kaynakları yeniler.
- RSS/Atom, arXiv, Reddit, YouTube kanalları ve mevcut resmî kaynak bağlayıcıları
  desteklenir. Bilinmeyen eski kaynak türleri desteklenmiyor olarak gösterilir.

Özgün Radar geçişinde eksik kalmış kategoriler, başlangıçta kaynak URL'sini
eski katalogla eşleştirerek tamamlanır. Mevcut kullanıcı kategorisi ve diğer
metadata korunur; bilinmeyen adres için kategori tahmin edilmez. Yeni geçişler
kaynak kategorisini doğrudan taşır.

## Yenileme ve veri tutarlılığı

Otomatik kaynak kontrolü uygulama açıkken ve hesap oturumu geçerliyken çalışır.
Kaynağın etkinliği, kendi yenileme aralığı ve hata sonrası bekleme süresi esas
alınır. Araştırmadaki **web araması** ve **konu takibi sıklığı** bu aboneliklerden
bağımsızdır; konu takibini kapatmak haber kaynaklarını durdurmaz.

Otomatik kaynak işleri, araştırma/analiz ve manuel işlemlerden sonra sıraya
alınır. Başlamış tek edinim tamamlanabilir; sonraki iş seçiminde kullanıcı
işlemi önceliklidir. Bekleyen kaynak işi, iş geçmişinin görünür bölümünden çıksa
da ikinci kez kuyruğa alınmaz.

Edinim öncesinde kaynak tekrar okunur. Sonuç yayımlanırken adres, tür, etkinlik
ve yapılandırma revision değeri transaction içinde kontrol edilir. Edinim
sırasında düzenlenen veya duraklatılan kaynağın eski yanıtı haber, başarı tarihi
ya da hata durumuna yazılmaz.

## Profil ve ayarlar

Sol alttaki profil kartından **Ayarlar** açılır. Görünüm, web ve konu takibi,
yerel modeller ve dosyalar kendi bölümlerinde gösterilir. Alan değişiklikleri
taslak olarak tutulur; arka plandaki durum yenilemesi bunları ezmez. **Kaydet**
kalıcı ayarları günceller ve sonucu gösterir. Kayıt sürerken yapılan yeni bir
değişiklik kaydedilmiş sayılmaz. Bağlantı ve yerel servis durumu ayarlar içinden
yeniden kontrol edilebilir.

## Doğrulama kapsamı

API, store, scheduler ve kaynak adapter regression grubunda 65 test geçti.
Son kuyruk düzeltmesinden sonra adapter/scheduler dosyasındaki 24 test yeniden
geçti; product modüllerinin strict mypy ve Ruff kontrolleri temizdir. Salt okunur
gerçek ağ kontrolünde arXiv, Reddit ve YouTube kanalından içerik alındı; bu
kontrol kullanıcı veri tabanına kayıt yazmadı. Bu sonuçlar tek başına paket
kurulumu veya tüm yayıncıların sürekli erişilebilir olduğu anlamına gelmez.
