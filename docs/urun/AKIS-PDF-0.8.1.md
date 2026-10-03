# Rasathane 0.8.1: okunabilir gündem ve PDF kaynakları

Sahip: **Av. Mehmet Arın Gülüm**.

Gündem, ilgi alanları ve projeler için seçilen haberlerdir. Bülten, haberlerden
oluşturulan kayıtlı derlemedir. Açılışta bir gündem haberi gösterilir;
**Tümünü oku** seçkiyi genişletir. Profil düzenlemesi, kaynak kontrol durumu,
model değerlendirmesi ve kaynak kapsamı kapalı ayrıntı bölümlerindedir.

Akış, Gündem ve Bülten haberlerinde **Kaynağı aç**, **Özetle**, **Seslendir** ve
**Derinlemesine analiz et** eylemleri doğrudan bulunur. Seslendir gerektiğinde
Türkçe özeti hazırlayıp yerel sesi oynatır. Özetle, haberin görünür metnini
günceller. Karar künyesi veya yönetilen özet tam kaynak analizi yerine geçmez;
desteklenmeyen eylem açıkça devre dışıdır. Kaynağı aç gerçek haber adresine gider.

HN RSS içindeki Article URL, Comments URL ve puan sayaçları haber metni sayılmaz.
Türkçe kaynak excerpt'i doğrudan cümle seçimiyle, yabancı kaynak ise yerel modelle
özetlenir. Kaynak alıntısı, kullanılan metin ve hash saklanır. Bu kontrol özetin
bağımsız içerik doğrulaması değildir. Abonelik, doğrulama ve çerez ekranları
haber diye özetlenmez. Hazır olmayan özetin yerine İngilizce veya teknik metin
gösterilmez; kullanıcı hazırlığı başlatabilir.

Otomatik özetleme son 72 saatin en yeni sekiz kaydıyla sınırlıdır. Aynı anda
en fazla iki iş bekler, saatte en fazla sekiz otomatik özet denenir. Kullanıcı
arşivdeki bir haberin özetini ayrıca başlatabilir. Cache içerik hash'iyle
ilişkilidir. Eski bültenlerin gösteriminde Türkçe özet kullanılabilir; özgün
snapshot, kişisel değerlendirme kanıtı ve özet kanıtı birbirinden ayrıdır.

Web adapter HTML yanında gerçek PDF byte imzasını tanır. PDF metin katmanı
yerel `pypdf[fonts]` ile okunur; sayfa sayıları, metin hash'i, kaynak byte hash'i,
OCR yapılmadığı ve kısmi okuma nedenleri UI ve dosyalarda bulunur. PDF indirmesi
20 MB, HTML 2 MB ile sınırlıdır. PDF sayfa, stream, işlem, metin ve süre
bütçeleri vardır. Taranmış, şifreli veya bozuk dosyalar açıklayıcı hata verir;
görsel ya da tablo düzeninin anlaşıldığı varsayılmaz. DNS/redirect koruması sürer.

Native File/Edit/View/Window menüsü kaldırılmıştır; uygulama kontrolleri header
ve profil içinde kalır. Yeni çıktı kökü **Belgeler/Rasathane** olur. Mevcut
kullanıcı seçimi ve legacy çıktılar açık migration'a kadar korunur.
**Masaüstü/Rasathane** kaynak repo olduğundan çıktı kökü olarak seçilmez.
Migration helper kaynak repo, dolu hedef ve symlink/junction üzerine taşımaz.

Doğrulama: kaynak regresyonları, bağımsız read-only review, izole native UI→IPC→
motor akışı, 1K/3K/4K ve zoom kontrolleri, imzalı frozen paket ve aynı Cambridge
PDF URL'siyle kurulu gerçek oturum testi. Son paket/kurulum makbuzları yerel
tarihli teslim kaydında tutulur; kaynak testi tek başına kurulum kabulü sayılmaz.
