# Bülten, araştırma ve çalışma alanları

Sahip: **Av. Mehmet Arın Gülüm**. Rasathane 0.5.4.

## Akıştan bülten

1. Akışta kaynak veya metin filtresi seçin.
2. **Bülten hazırla / aç** ile başlık, tarih aralığı ve 5/10/20 haber sınırını belirleyin. Alınacak başlıklar önizlemede listelenir; yalnız yüklenmiş haberler değerlendirilir.
3. **Bülten oluştur** metni, kaynak bağlantılarını ve kapsam açıklamalarını yerel veritabanına kaydeder. Metin kayıtlı haberlerden cümle seçilerek derlenir; yeni iddialar üretilmez.
4. **Bülteni seslendir** Türkçe WAV hazırlar. Windows Türkçe konuşma sesi gerekir. Ses yoksa metin kaybolmaz ve hata görünür. Oynatıcıyla duraklatıp devam edebilirsiniz.
5. Kayıtlı bültenler listesinden önceki bir bülteni açın. Kaynak daha sonra değişse de kayıtlı bülten aynı kalır. Tam veri dışa aktarımı bülten snapshot'larını da içerir.

Tarih filtresi varsa yayın tarihi, bulunmuyorsa edinim/kayıt tarihi kullanılır. Tarihsiz kayıtlar yalnız tüm tarihler seçiminde yer alır. Metadata künyeleri ve yönetilen özetler tam metin gibi sunulmaz. Ses, kaynak adreslerini harf harf okumaz; madde başlıklarını, özeti ve gerekli kapsam açıklamasını okur.

## Araştır

Mesajlar tek bir konuşma alanında, yazma kutusu altta gösterilir. **Geçmiş** header'da açılır ve konuşma başlığıyla aranır. Enter gönderir, Shift+Enter satır ekler. İlk sorudan önce çalışma alanını seçin; açık konuşmanın alanı sabittir. Başka alan için **Yeni konuşma** kullanın.

Yanıtlar mevcut kaynak alıntılarına dayanır. Kaynak bölümü metni ve bağlantıyı gösterir. Bir çalışma alanı seçildiğinde o alanın not/kaynakları ve genel haberler aranır. Ortak kitaplıktaki bağımsız konu kaynaklarını da aramak için **Tüm yerel kayıtlar** seçilir. Bu ayrım kitaplık görünümünde de açıklanır.

## Örnek çalışma alanları

**Çalışma alanı → Örnek çalışma alanlarını kur** iki alan, iki plan notu ve iki takip sorgusu ekler:

| Çalışma alanı | Plan | Bağımsız konu sorgusu |
|---|---|---|
| Örnek · İş hukuku araştırması | İşçilik alacakları için kaynakları toplama ve not alma | Yargıtay işçilik alacakları kıdem tazminatı |
| Örnek · Yapay zekâ ve veri koruma | Resmî kaynakları inceleme ve açık soruları kaydetme | site:kvkk.gov.tr yapay zekâ |

Planlar örnek metinlerdir; gerçek dosya, karar veya hukuki görüş değildir. Mevcut kayıtlar değiştirilmez; kurulum tekrarında eşleşen kayıtlar korunur. İlk denemede Araştır'da ilgili alanı seçip web'i kapatarak “İşçilik alacakları araştırma planı” sorusuyla notun bulunmasını kontrol edebilirsiniz.

## Konu takibi

Takip adı ve web sorgusu kaydedilir. **Şimdi kontrol et** ilk aramayı başlatır; sonuçlarda ilk kez görülen URL sayılır. **Sonuçları aç** son başarılı aramanın kaynaklarını gösterir; daha sonraki bir hata bu sonucu silmez. Henüz kontrol yoksa boş durum açıkça gösterilir.

Takip RSS haber akışıyla aynı veri kümesi değildir. Arama başına en fazla beş web sonucu alınır. İlk kontrolden sonra uygulama açık ve kullanıcı giriş yapmışken, ayarlardaki süreyle tekrar çalışır. Uygulama kapalıyken arama yapan bağımsız bir servis yoktur. Örnek kurulum otomatik internet araması başlatmaz; ilk kontrol kullanıcı tarafından yapılır.

## Profil ve ayarlar

Sol alttaki profil kartı hesap/plan, ayarlar ve çıkış menüsünü açar. Ayarlar mevcut sayfanın üzerinde modal olarak açılır: Görünüm, Web ve konu takibi, Yerel modeller, Dosyalar ve veri, Hesap ve plan. Değişiklikler **Ayarları kaydet** ile kalıcı olur. Escape pencereyi kapatır; oturum token'ları renderer'a verilmez.
