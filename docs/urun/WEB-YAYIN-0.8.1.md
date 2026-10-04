# Ürün sitesinin kaynak ağacına aktarımı

Ürün sahibi: **Av. Mehmet Arın Gülüm**. Bu güncelleme yalnız web kaynakları ve
yayın/lisans açıklamalarını eşitler; yeni bir desktop sürümü oluşturmaz.

Website PR #2 normal merge ile `rasathane-web/main` dalına alınmıştır:

- İlk ürün yayını: `a38f97168f8ae452f923e7f771e668c3e4787f49`.
- Son marka alias yayın commit'i: `a6a79bd1a0dde9f72cb478938df1f70a6ba932ef`.
- İncelenen son feature commit'i: `7a8b061113019b88df5f223ec6ee9aa00c6b66c7`.
- Son iki ref'in web tree'si: `1d184c9ce8df07f1d2224214d571ca55fe70f286`.
- `apps/web` bu tree ile birebir eşittir. Özgün Git geçmişi squash yapılmadan
  subtree merge'in ikinci parent'ında korunur.

Web kontrolleri: lint, TypeScript, üç hesap/indirme sözleşme testi ve production
build geçti. Headless browser doğrulaması 375, 1024, 1920, 3072 ve 3840 px'te
taşma/başlık çakışması bulmadı; mobil menü, dört tabın klavye gezinmesi ve beş
public rota geçti. Hukuki sayfalar güncel website `main` metinlerini korur.
Computer Use kullanılmadı. Eski marka asset URL'i aktif yeşil r SVG'siyle byte
olarak eşitlendi; kullanılmayan turuncu component'ler kaldırıldı. Mevcut yedi
desktop marka sözleşme testi değişiklik yapılmadan geçti.

Deneme gerçek kullanıcı yoluyla açıklanır: Rasathane masaüstü uygulaması,
profil kartı, **Hesap ve plan → 14 günlük denemeyi başlat**. Muhakeme'nin genel
üye panelinde Rasathane ürün yönetimi varmış gibi bağlantı sunulmaz.

## Değişmeyen desktop yayını

- Sürüm: `0.8.1`, Windows x64.
- Kabul edilen kaynak: `43b038d95958de06bd0da7756bc16026668f57f1`.
- Installer: `Rasathane-Setup-0.8.1-x64.exe`, `1.335.922.184` byte.
- SHA-256: `b82939f60d4b6d8325a4b5bb213847b84f4b9b41f2c97bb7755864b9a7318373`.
- Kabul edilen desktop tree: `a16395bb426bbf53078198c201dd8e6725620cf2`.

Desktop kodu, installer, release manifest, `v0.8.1` tag'i ve yayımlanmış source
arşivi bu kaynak eşitlemesinde değiştirilmez. Yeni public source snapshot'ı
güncel web kodunu ayrıca taşır; 0.8.1 installer'ın build kaynağı olduğu iddia
edilmez. Mevcut export allowlist'i web kaynaklarını da kapsar; marka ve font
lisans sınırları `NOTICE.md` ve font bildirimlerinde korunur. Sunucu sırları,
özel servis implementation'ları ve runtime verileri export'a dahil edilmez.
