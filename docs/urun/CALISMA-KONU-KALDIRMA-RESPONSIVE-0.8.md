# Rasathane 0.8: sade gezinme ve responsive arayüz

Sahip: **Av. Mehmet Arın Gülüm**. Tarih: 3 Ekim 2026.

## Kapsam

Çalışma alanı ve konu takibi özellikleri ana gezinmeden, formlardan, ayarlardan,
aktif API sözleşmesinden ve Electron IPC allowlist’inden kaldırılır. Konu
scheduler’ı ve yeni konu refresh işleri çalışmaz. Kullanıcı ilgi alanları ve
proje açıklaması kişisel gündemin bağlamı olmaya devam eder. Haber kaynakları,
kategori yönetimi, kaynak sohbeti, web araması, araştırma konuşmaları, analiz,
bülten ve seslendirme korunur. Analiz dosyalarının fiziksel çıktı klasörü ayarı
bu kaldırmanın kapsamına girmez.

Header’ın orta ekseninde dört ana sekme bulunur: **Akış**, **Analiz**,
**Araştır**, **Kaynaklar**. Profil ve Ayarlar erişimi sağda kalır. Küçük etkin
viewport’ta kontroller yeniden yerleşir; geniş ekranda içerik yüzeyi ve metin
boyutları ekran genişliğine uyarlanır. Okuma satırlarının uzunluğu sınırlandırılır;
sohbet ve bülten metinleri kontrolsüz biçimde tüm ekran genişliğine yayılmaz.

## Eski kayıtların korunması

Önceki çalışma alanları, notlar, konu kayıtları, tamamlanmış işler ve konuşma
geçmişleri silinmez. Tam veri export’u arşivi içerir. Eski çalışma alanına bağlı
konuşmalar okunabilir ve sürdürülebilir; yeni araştırma işleri çalışma alanı
scope’u almaz. Yerel arşiv belgeleri genel araştırmada kaynak olarak bulunabilir.

Eski gündem profilindeki `workspace_ids` ve `include_topics` alanları okurken
yok sayılır. Yeni girdiler bu alanları ve `topic_refresh_minutes` ayarını kabul
etmez. Eski bekleyen konu işleri özellik kaldırıldığı için iptal edilir;
tamamlanmış işlerin sonuçları değişmez. Aktif iş listesi emekli konu işlerini
göstermez. Veri schema’sını yıkıcı bir migration ile değiştirmek gerekmez.

## Doğrulama matrisi

Kaynak arayüzünde aşağıdaki yedi pencere/zoom senaryosu açık ve koyu tema ile
çalıştırıldı. Her senaryoda dört ekranın görünür olduğu, header ve içerik orta
ekseni, yatay taşma, araştırma composer’ı ve Ayarlar dialog sınırları ölçüldü.
Zoom testinde etkin CSS viewport’a göre responsive kurallar devreye girer;
fiziksel ekran DPI testi bu çalışmanın kapsamı değildir.

| Pencere | Zoom | Kaynak kabulü |
| --- | --- | --- |
| 1024 × 768 | %100 | Geçti |
| 1920 × 1080 | %100 | Geçti |
| 2880 × 1800 | %100 | Geçti |
| 3072 × 1728 | %100 | Geçti |
| 3840 × 2160 | %100 | Geçti |
| 2880 × 1800 | %150 | Geçti |
| 3840 × 2160 | %200 | Geçti |

Toplam **56 ekran yerleşimi ve 14 Ayarlar dialog senaryosu** doğrulandı.
3K/4K’de geniş içerik yüzeyi ve font ölçeği ayrıca kontrol edildi. Kaynak
kabulündeki **154 kontrol**; giriş kilidi, sesli bülten, kaynak yönetimi,
sohbet geçmişi, ayar kaydı ve kaldırılmış özelliklerin yokluğunu da kapsıyor.
Kaynak makbuzu: `.local/urun/ui-integration-1791058484135/receipt.json`.
Paketlenmiş sürümde aynı kabul henüz beklemededir.

## Backend ve uyumluluk doğrulaması

- 112 hedef Python testi geçti; kaldırılmış endpointler, eski profil uyumu,
  araştırma, kaynak yenileme ve bülten davranışları kapsandı.
- Son üç arşiv/uyumluluk testi değişiklikten sonra yeniden geçti.
- Yedi IPC testi geçti; kaldırılmış yollar ve alanlar engelleniyor.
- Ruff check/format ve strict mypy temiz.
- İzole paket fixture’ında 55 eski araştırma dönüşü, eski konuşma ilişkisi
  korunarak yeni iş sözleşmesiyle seed edildi. Gerçek kullanıcı DB’si kullanılmadı.

Paket, kurulum ve responsive kabul sonuçları bu belgedeki kapsamdan bağımsız
makbuzlarla doğrulanmalıdır; backend testlerinin geçmesi arayüz kabulü sayılmaz.
