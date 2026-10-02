# Rasathane tasarım planı

Sahip: **Av. Mehmet Arın Gülüm**. Tarih: 3 Ekim 2026.

## Ürün

Tek Rasathane: kaynak takibi, ayrıntılı analiz, kaynaklı araştırma ve yerel çalışma alanı. Gözlemevi'nin analiz çıktısı aynı ürünün Analiz görünümüdür. Radar/Gözlemevi ayrı ürün adı veya ayrı indirme olarak sunulmaz.

## Kimlik

Muhakeme'nin faithful HQ logo style guide'ı görsel olarak incelendi. Aile ilişkisi terazi kopyasıyla değil, bakır yüzey, krem çizgi ve geometrik biçimle kurulur. Rasathane'nin bağımsız işareti faceted kare içindeki lens ve yörüngedir: farklı kaynaklar tek inceleme odağında buluşur.

| Token      | Değer     | Rol                  |
| ---------- | --------- | -------------------- |
| Mürekkep   | `#0b1712` | Derin zemin          |
| Yeşil      | `#153d34` | Ürün yüzeyi          |
| Bakır      | `#c86e42` | İşaret ve dolu eylem |
| Altın      | `#d5ae78` | Odak çizgisi         |
| Krem       | `#f7f0df` | Metin ve açık alan   |
| Açık yeşil | `#a9bfb3` | İkincil metin        |

Masaüstü: yerel Space Grotesk başlık, IBM Plex Sans metin, yalnız teknik değerlerde IBM Plex Mono. Web: mevcut Inter metin ailesi; logo ve büyük başlık aynı sans dili kullanır. Harici çalışma zamanı font çağrısı eklenmez.

## Yerleşim

Webde ana imza kaynakların yörünge/lens diyagramıdır. Sol hizalı ürün vaadi ve sağda inceleme odağı, ardından gerçek sıralı kullanım akışı; eşit kartlardan oluşan bir SaaS katalog düzeni yoktur. Site yalnız Rasathane'yi anlatır.

```text
Rasathane     Ürün · Veri ve kaynak · Fiyat       Hesap · İndirme
Kaynakları izle.              kaynak yörüngeleri
Bağlantıyı çözümle.           tek inceleme odağı
Araştırmanı biriktir.         yerel çalışma alanı
                 takip → analiz → araştır → çalışma alanı
Yerel çekirdek / yönetilen hizmet                  49 TL / ay
```

Masaüstünde altı ana sekme: Akış, Analiz, Araştır, Çalışma alanı, Konu takibi, Ayarlar. Analiz künyesi, kısa/ayrıntılı özet, kişisel analiz, kaynak sinyalleri, doğrulama, zihin haritası, bilgi değeri, aşamalar, artifact'lar ve teknik provenance korunur. Kütüphane Çalışma alanı içinde yer alır.

## Gözden geçirme

İlk fikirde yalnız büyük bir marka işareti vardı; bu, ürünün takip/inceleme/toplama işini açıklamıyordu. İmza bu yüzden kaynak yörüngelerine ve tek odak noktasına dönüştürüldü. Bakır renk aile gereğidir; dekoratif gradient wash ve sürekli animasyon eklenmez. Sekmeler, gerçek veri listeleri ve editörler kullanıcının işini öne çıkarır.

## Davranış ve doğrulama

- Production UI mock içerik göstermez. Gerçek boş, loading, hata ve son başarılı ölçüm durumları ayrı sunulur.
- Kaynak metni yalnız textContent güvenli DOM helper'larıyla yazılır. Dış URL yalnız http/https kabul eder.
- Production renderer API çağrıları dar preload üzerinden geçer. Loopback browser preview ayrı test seam'idir.
- Analiz ve araştırma job'ları gerçek stage/status/result ile gösterilir; iptal backend makbuzu gelmeden tamamlanmış sayılmaz.
- Artifact HTML'si çalıştırılmaz. Harita yalnız sınırlandırılmış JSON ağacından güvenli SVG/metin görünümüne dönüştürülür; PDF paketlenen PDF.js worker ve canvas ile açılır. iframe veya uzaktan renderer kullanılmaz.
- Minimum 8 GB RAM profili açıkça seçilir; kurulum donanım performansı garantisi olarak anlatılmaz.
- Yerel açık çekirdek ücretsizdir. Yönetilen hizmet aylık toplam 49 TL; 14 günlük deneme hizmete aittir. Üyelik/indirme gerçek endpoint'lere gider; doğrulanmamış installer mevcut diye sunulmaz.
- Klavye tab gezinmesi, görünür focus, mobile taşma, metin kontrastı ve reduced motion kontrol edilir. Web lint/build ve gerçek kullanıcı yolu ayrıca doğrulanır.

Lisans kapsamı ve ücretli hizmet koşullarının kaynağı ürünün lisans/üyelik belgeleridir; arayüz yeni bir hukuki lisans uydurmaz. Mevcut KVKK/gizlilik metinleri bu çalışma kapsamında değiştirilmez.

## Uygulanan ürün davranışı

Akış gerçek kaynak listesini, son kontrol zamanı ve hatalarını gösterir. Resmî Gazete günlük indeks adaptörü ile kamuya açık Yargıtay karar künyeleri ayrı kaynak türleridir. Karar künyesinde karar tarihi ve tam metin bulunmadığı açıklanır; bu kayıtlar tam karar analizi başlatmaz. Başlık/açıklama araması, kaynak filtresi ve 25 kayıtlık kademeli görünüm düşük RAM profilinde gereksiz DOM büyümesini sınırlar.

İşlem listesi kısa kayıtları okur; ayrıntılı sonuç yalnız açıldığında veya etkin job izlenirken tek-job endpoint'inden edinilir. Ayarlardaki gerçek `analysis_profile`, analiz girdisinin profil etiketiyle aynıdır. Yerel kitaplıktaki kısaltılmış metin önizleme olarak işaretlenir; tam kayıt veritabanı ve dışa aktarma dosyasında korunur.

Hesap paneli native Muhakeme PKCE bağlantısını kullanır. Cihazdaki oturum kaydı hizmetin etkin olduğuna kanıt sayılmaz; plan, sunucu zamanı ve deneme uygunluğu entitlement yanıtıyla doğrulanır. 14 günlük deneme ayrı kullanıcı düğmesiyle başlatılır; yalnız `deneme_baslatilabilir === true` olduğunda kullanılabilir. Oturum geçersizleştiğinde giriş düğmesi yeniden görünür. Yerel çıkış sunucuya erişilemediğinde de tamamlanabilir ve bu durum kullanıcıya söylenir.

İlk kurulum yerel profil ve web tercihini kaydeder; model indirmesini kendiliğinden başlatmaz. Paketlenen Gemma 4 sürümü Apache 2.0, BGE MIT lisanslıdır. Checkbox lisans bildirimlerinin okunması ve yaklaşık 3,1 GB indirme isteğidir; ek bir Gemma kullanım koşulu kabulü oluşturmaz. Kurulum durumu native indirme makbuzu ve checksum sonucundan okunur. Windows Türkçe ses kurulumu açıkça anlatılır; bulunmayan ses motoru hazır gösterilmez.

Bu paket temel 8 GB profilini içerir. 16 GB profili, native model metadata'sında gelişmiş model kurulumu ve checksum sonucu doğrulanmadan seçilemez; ayrı geliştirici kurulumu backend'de korunur. Büyük arşivlerde Akış'ın yalnız son kayıtları yüklediği belirtilir; tüm yerel arşivde arama Araştır görünümündedir.

Analiz ekranındaki bulut sayacı yalnız kaydedilen bulut LLM çağrılarını anlatır. Sıfır değer kaynak edinimi, web doğrulaması ve ses motorunun bütün internet trafiği için kanıt sayılmaz. Bu aşamalar ayrı gösterilir.

Lazy job geçişinden sonra gerçek araştırma akışı tekrar doğrulandı: yeni araştırma POST 202 → tek-job GET 200 → bir Türkçe yerel not, sıfır web sonucu. Geçmiş araştırma kısa job listesindeki düğmeden tek-job GET ile yeniden açıldı; sorgu ve çalışma alanı da geri yüklendi.

Native dışa aktarma, dosya seçme dialog'u ve main process'teki stream/atomic yazma işlemini kullanır. Arayüz yalnız `saved/path/bytes/sha256` makbuzu geldiğinde kaydedildi der; iptal ayrı durumdur. Browser preview JSON/Blob indirmesini tarayıcıya iletir.

## Doğrulama kaydı · 3 Ekim 2026

| Kontrol                                   | Sonuç                                                                                                                                                                            |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Web lint ve production build              | Başarılı. Landing ve marka bileşenleri Server Component; ek client bundle veya çalışma zamanı font çağrısı yok.                                                                  |
| React kalite incelemesi                   | Statik bileşen sınırları, listelerde kararlı key, semantik link/button, metadata ve erişilebilir SVG label kontrol edildi. MUI, CSS-in-JS, gereksiz hook/state/effect eklenmedi. |
| Masaüstü JS syntax                        | `main.js` ve `product.js` başarılı.                                                                                                                                              |
| Marka, artifact/IPC ve sidecar sözleşmesi | Yetkili üç test dosyası: 17 test başarılı. Production ağ sınırı main process'teki renderer network deny ile doğrulanır.                                                          |
| İzole gerçek kullanıcı yolu               | İlk profil ayarı → çalışma alanı → Türkçe not → yerel araştırma → job tamamlanması → kaydı yeniden açma ve reload sonrası kalıcılık doğrulandı.                                  |
| Kaynak akışı                              | 71 gerçek kayıt; 25→50 kademeli görünüm, Yargıtay filtresi 20/20, E. 2026/10380 araması 1/1. Karar künyesinde Analize al düğmesi yok.                                            |
| Klavye                                    | Akış sekmesinde ArrowDown ile Analiz'e geçiş ve `aria-selected` doğrulandı.                                                                                                      |
| Responsive yerleşim                       | Web ve masaüstü 390 px ve normal desktop viewport'ta yatay body taşması yok; masaüstü footer taşması giderildi.                                                                  |
| Hesap/indirme web yolu                    | `/hesap` fiyat/denemeyi doğru açıklar; `/indir` doğrulanmış yayımlanmış paket olmadığında indirme bağlantısı sunmaz.                                                             |
| Browser dışa aktarma                      | 1.408 bayt JSON; ürün/schema, bir çalışma alanı ve Türkçe not readback ile doğrulandı. SHA256: `BE27F698FEA3C32D2AEDB9AF85B06C0E68B788A2E85544BE9F6961129D6CB478`.               |

Browser doğrulaması uygulama verisinden ayrı geçici veritabanı ve loopback servisle yapıldı. Native model indirmesi, gerçek inference ve native export/account bridge doğrulaması paket testinin parçasıdır; browser sonucu bu adımların geçtiği anlamına gelmez. Canlı Muhakeme hizmeti ve yayımlanmış indirme makbuzu henüz erişilebilir değilse arayüz bu sınırı açıkça korur. Deneme, ödeme veya gerçek üyelik otomatik başlatılmadı.

## Artifact önizleme doğrulaması

Gerçek native Resmî Gazete analizinin sonucu ve 13 artifact'ı hash kontrolüyle geçici çalışma alanına kopyalandı; test için üretim veritabanına kayıt yazılmadı ve yeni inference başlatılmadı. Analiz ekranında kaynak künyesi, kısa/ayrıntılı özet, kişisel analiz, 14 iddia, işlem aşamaları ve gerçek model kökeni açıldı. Döküm uzantıları yalnız dönen artifact listesine göre gösterilir.

Harita HTML'sinde yalnız `const veri` JSON ağacı kabul edilir. Script, HTML etiketi ve dış bağlantı çalıştırılmaz; düğüm, metin, derinlik ve 8 MB boyut sınırları uygulanır. Gerçek harita 38 düğüm ve 37 SVG bağlantısıyla açıldı. 390 px görünümünde okunabilir metin ağacı varsayılandır; kök dalı kapatılıp yeniden açıldığında görünür düğüm sayısı 38 → 1 → 38 oldu.

PDF.js `6.3.289` ve seçilen 201 upstream dosya resmî npm tarball'ının SHA512/SHA256 makbuzundan doğrulanır; paketleme öncesi `pnpm check:pdf` değişmiş veya eksik asset'ı reddeder. Apache 2.0 yanında CMap, Liberation font, Foxit, codec ve ICC lisans metinleri korunur. QuickJS script engine pakete alınmaz. PDF script'leri, annotation eylemleri, eval, Wasm ve sistem font kullanımı kapalıdır. Worker doğrudan aynı kaynaklı asset'tan oluşturulur; parent CSP gevşetilmez. Tek sayfa canvas'ı ve sınırlı piksel alanı düşük RAM tüketimini destekler; görüntü kapatılınca worker ve kaynaklar bırakılır.

Gerçek 80.902 bayt PDF beş sayfa olarak açıldı; 1 → 2 sayfa geçişi, Türkçe metin ve 390 px görünüm doğrulandı. Bu görünümde body 375/375 px, modal 337/337 px ölçüldü; yatay taşma yoktu. İndirilen PDF'nin SHA256 değeri özgün dosyayla eşleşti: `08724fa30f3b764299928fb1a88afa6b314240f7df203342e4e2707693e781fc`. Beş artifact güvenlik testi, 18 Electron/IPC testi ve 17 ilgili Python testi geçti; son tarayıcı konsolunda error/warn bulunmadı. `rasathane://app` custom origin üzerindeki paket doğrulaması ayrıca native smoke kapsamındadır.

Model destek tahmini, ayrıntılı özet ile türetilmiş analiz metninin karşılaştırmasıdır; resmî kaynak doğruluğu onayı gibi gösterilmez. BilgiDeğeri araştırma önceliğini anlatır. İlk gerçek çıktıda bulunan karakter ve terim hataları core incelemesine iletildi; bu önizleme testi içeriğin hukuki doğruluğunu onaylamaz.
