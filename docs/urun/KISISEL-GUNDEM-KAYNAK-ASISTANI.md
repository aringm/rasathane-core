# Rasathane 0.8: kişisel gündem ve kaynak yönetimi

Sahip: **Av. Mehmet Arın Gülüm**.

Akış ekranında **İlgi alanlarım ve proje bağlamım** bölümünü açın. İlgi ve
projelerinizi yazın. Haberler bu iki açıklamaya göre değerlendirilir. Profili kaydedin;
**Kaynakları yenile ve gündem hazırla** ile ilk gündemi oluşturun.

Otomatik güncelleme uygulama açıkken ve oturum geçerliyken çalışır. Her kaynak
kendi kontrol aralığıyla yenilenir; gündem kaynak işlerinin sonuçlanmasını
bekler. Erişilemeyen kaynaklar ve son başarılı kontrol ekranda görünür.
Değişmeyen içerik için yeni bülten oluşturulmaz. Uygulama kapalıyken arka planda
bir servis çalışmaz; yeniden açıldığında vadesi gelen kaynaklar kontrol edilir.

Kurulu yerel model haberi önem, ilginizle bağlantı, proje etkisi ve sonraki adım
açısından değerlendirir. **Değerlendirmenin dayandığı kaynak metni** bölümünde
alıntı, **Haberi aç** bağlantısında yayın bulunur. Yorum, yayıncının doğrulanmış
sonucu olarak sunulmaz. Model kurulmamışsa veya tamamlayamazsa sözcük eşleşmesi
açıkça etiketlenir; model indirme kurulum sihirbazındaki açık kullanıcı eylemidir.

8 GB RAM profilinde bülten en çok 8 haber içerir. Daha yüksek RAM profilleri
20 habere kadar derleme oluşturabilir; ilk 8 haber yerel modelle değerlendirilir,
diğerleri konu eşleşmesi olarak etiketlenir.

**Dinle** Türkçe bülten sesini hazırlar. Oynatıcıdan hız değiştirilebilir veya
WAV indirilebilir. Önceki bültenler saklanır. **Yeni bülten oluştur**, akışta
seçtiğiniz kategori/kaynak/tarih filtrelerinden ayrıca bir derleme oluşturur.

Kaynaklar ana menüde kategori başlıklarıyla gruplanır. Kategori düğmeleri,
arama ve takip durumu birlikte filtrelenebilir. **Düzenle** ad, adres, tür ve
kategoriyi değiştirir; yeni kategori de yazılabilir. Takibi duraklatmak arşivi
silmez. **Haberlerini gör** kaynak arşivini açar.

Kaynak asistanına örneğin şunları yazın:

- `https://example.org/feed adresini Hukuk kategorisine ekle`
- `Lexpera Blog kaynağını "İş hukuku" kategorisine taşı`
- `Lexpera Blog kaynağını duraklat`
- `AI kaynakları öner`

Yalnız web adresi de gönderilebilir; RSS/Atom bağlantısı keşfedilir. Desteklenen
YouTube, arXiv ve Reddit adresleri uygun kaynak türüne dönüştürülür. Asistan
uyguladığı işlemin adını, kategorisini ve bağlantısını sohbet içinde gösterir.
Belirsiz veya birbiriyle çelişen komutta işlem yapmaz, açıklama ister. Öneri
düğmesine basmak seçilen kaynağı ekler. Sohbet geçmişi bu bilgisayarda tutulur.

Header'daki **Ayarlar** veya profil menüsündeki **Ayarlar** aynı pencereyi açar.
Görünüm, web araması, yerel modeller, dosyalar ve hesap ayrı bölümlerdedir.
Arka plan yenilemesi kaydedilmemiş değişikliklerinizi ezmez. **Ayarları kaydet**
sonucu yerel kayıtla doğrulanır; **Değişiklikleri geri al** son kaydı yükler.


Ana gezinme header’ın ortasında **Akış**, **Analiz**, **Araştır** ve **Kaynaklar**
sekmelerinden oluşur. Çalışma alanı ve konu takibi özellikleri kaldırılmıştır;
bu özelliklerden kalan kayıtlar arşivde veri kaybı olmadan saklanır ve tam
veri export’una dahil edilir. Önceki araştırma konuşmaları okunabilir ve
sürdürülebilir. Kişisel gündem ilgi alanı ve proje açıklamalarınıza göre çalışır.
