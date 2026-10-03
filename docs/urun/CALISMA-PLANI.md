# Rasathane ürün geliştirmesi

Sahip: **Av. Mehmet Arın Gülüm**. Başlangıç: 3 Ekim 2026.
Kaynak kökü: `C:\Users\aring\Desktop\Rasathane`; dal: `codex/rasathane-urun`.

## Hedef ve kabul

Rasathane Radar'ın takip, kaynak, bülten ve araştırma özellikleri ile Gözlemevi'nin ayrıntılı analiz motoru tek **Rasathane** ürününde birleşir. Yerel çekirdek AGPL-3.0-or-later; marka, Muhakeme hesabı, yönetilen servisler ve ticari servis uygulaması ayrı kalır. Açık çekirdeğin ticari kullanımı serbesttir; marka lisansı verilmez. Yönetilen üyelik aylık KDV dahil toplam 49 TL'dir. Ücretli servislerin 14 günlük denemesi yalnız kullanıcının açık talebiyle `POST /api/lisans/v2/deneme` üzerinden başlar. Yerel çekirdek ücretsizdir ve üyelik olmadan çalışır.

| Aşama | Yapılacak iş | Kabul kanıtı | Durum |
| --- | --- | --- | --- |
| Envanter | GitHub ve yerel kaynaklar, mimari, lisans ve standartlar | Kaynak yolları, Git revision ve korunmuş geçmiş | Tamamlandı |
| Ortak çekirdek | SQLite/FTS, kalıcı işler, Gözlemevi engine adapter, Radar veri import'u | 96 kaynak / 16.834 kayıt kayıpsız import; integrity_check OK; doğrulanan uzak CI'da Windows 765, Linux 764 test geçti | Kaynak ve migration tamamlandı |
| Araştırma | Web search, sürümlü kaynaklar, çalışma alanı, notlar, konu takipleri | Türkçe not → yerel arama → kaynaklı sonuç → restart/readback geçti; public RG/Yargıtay gerçek veri | Uygulandı ve doğrulandı |
| Tasarım | Bağımsız logo, birleşik arayüz, tek ürün sitesi | Logo/ikonlar üretildi; gerçek browser akışları, web build ve Vercel preview kontrolü geçti; hukuki metinler korundu | Uygulandı ve preview doğrulandı |
| Üyelik | Muhakeme PKCE client, açık deneme başlangıcı, 49 TL toplam fiyat, indirme | 1318 Muhakeme test, dört mevcut skip; son yerel GUI kontrolünde 31 Electron ve 10 UI test; private PR #59 | Kaynak hazır; production kabulü bekliyor |
| Paket | Bağımsız worker, kurulum sihirbazı, RAM bütçesi | İmzalı NSIS normal kurulum; TEMP cwd ve geliştirme araçları olmadan gerçek analiz/PDF/harita, 5.713 dosyanın tam size/SHA incelemesi ve doğal kapanış geçti | Windows kurulum kabulü tamamlandı; fiziksel 8 GB testi ayrı |
| Geliştirme standardı | Frozen lock, CI, secret scan, bağımsız review, SBOM/hash/readback | Windows 765 / Linux 764 kaynak testi; 31 Electron + 10 UI, 202 PDF hash, 196 SBOM bileşeni / 303 lisans referansı; kurulu artifact ve kaynak incelemesi | Uygulandı; son source export/CI makbuzları ayrı saklanır |
| Yayın | AGPL kaynak, site, üyelik, indirme | Native karşılık kaynakları yayımlandı; son installer R2 tam readback'i geçti; kaynak/site/üyelik PR'ları review akışındadır | Installer deposu hazır; production ve canlı kullanıcı kabulü bekliyor |
| Emeklilik ve duyuru | Tek kurulum/kök ve tamamlanma sonrası duyuru | Eski kurulum ve dört staging klasörü, dört kısayol kaldırıldı; yalnız dört owned servis ve iki Rasathane container durduruldu; veri/model/volume korundu | Yerel emeklilik tamamlandı; duyurular son yayın kabulünden sonra |

## Koruma ve sınırlar

- Muhakeme İçtihat'ın güncel çekirdeği tescillidir. Kod kopyalanmaz; bağımsız uygulama veya versiyonlu servis adapter'ı kullanılır.
- Mevcut Radar PostgreSQL verisi ve analiz çıktıları silinmez. Import salt okunur kaynaktan, transaction ve migration ledger ile yapılır.
- Hermes kurulumuna yazılmaz. Gerçek `.env`, model ağırlıkları, kullanıcı DB'leri ve özel dosyalar Git'e alınmaz.
- Üyelik ve yerel veri işleme ayrıdır. Yerel çekirdek açılışta kullanıcı içeriğini dışarı göndermez.
- 8 GB minimum hedefi yalnız profil adına dayanarak doğrulanmış sayılmaz. Spawn öncesi boş RAM denetlenir; gerçek 8 GB kabulü ayrı kaydedilir.
- Açık kaynak yayınına özel eski Git geçmişi denetimsiz taşınmaz. Kaynak kökeni ve eski private tarih korunur.
- Paketlenmiş ürün doğrulanmadan eski Gözlemevi kurulumu emekliye ayrılmaz; tamamlanmadan sonuç duyurusu yapılmaz.
- `main`/`master` üzerine doğrudan commit/merge yapılmaz; değişiklikler PR ve bağımsız review üzerinden ilerler.

## Referanslar

Orçun Ağca'nın yaşayan standardı: IoT Inn `docs/CLOSED-LOOP-ARCHITECTURE.md`; repo korumaları `docs/REPOSITORY-GUARDRAILS.md`. Bağımsız review, güncel artifact hash'i, gerçek yürütme makbuzu ve uzak readback ayrı tutulur. Tarihsel zorunlu insan onay akışı uygulanmış gibi gösterilmez; GitHub PR korumaları ayrı değerlendirilir.

Mevcut kaynaklar: `apps/desktop` birleşik Rasathane 0.5.0 (Gözlemevi 0.4.1 kökeni), `apps/radar` korunmuş Radar kaynağı, `apps/web` Next.js sitesi. İnceleme sırasında Radar FastAPI/SQLAlchemy/Pydantic sürümleri günceldir; teknik borç esas olarak runtime, monolit ve paketleme sınırındadır.

## Son kalite düzeltmeleri

Resmî Gazete'nin Windows-1254 kaynağı strict charset kontrolüyle açılır; Türkçe mevzuat gereksiz yeniden çeviriye girmez. Modelin destek puanı bağımsız doğruluk onayı olarak sunulmaz. Her ürün analizinin job kimliğine bağlı ayrı çıktı klasörü vardır; yeniden analiz önceki dosya ve hash'leri değiştirmez. Bu davranışların regresyonları geçti. Son frozen paket üzerinde gerçek analiz ve PDF/DOCX/map kabulü ayrıca yürütülmektedir.

Yerel model envanteri ve üretim örnekleri salt okunur referans alındı. 128 GB çalışma bilgisayarındaki büyük modeller, 8 GB ürün profilinin dağıtım gereksinimi olarak alınmadı; veri ve model depoları korunur.

İlk gerçek paketli model analizinin PDF/harita yolu geçti; içerik incelemesi hatalı mevzuat numaralandırması ve web doğrulaması yakaladı. Bunun üzerine resmî normatif metinlerde doğrudan kaynak alıntısı modu eklendi. Bağımsız review alıntı içindeki MADDE ve cümle içi fıkra atıfları için ek regresyonlar istedi; bu vakalar da düzeltildi. Son imzalı adayda resmî kaynak yolu doğrulandı; genel model yolu ve yeni bağımsız kurulum ayrı kabul edilir. Üyelik repo'sunda kabul gate'i, 64 MiB multipart, koşullu nesne oluşturma ve tam R2 readback yordamı dokuz testle geçti; installer R2'ye yüklendi ve tam byte/SHA readback'i geçti; üyeye açık production indirme henüz açılmadı.

## 3 Ekim 2026 doğrulama durumu

Doğrulanan private `e00a970` ve public `ccbded4` snapshot'larında her iki snapshot'ın CI kontrolleri başarılıdır: Windows **765 passed / 6 skipped / 16 deselected**, Linux **764 passed / 7 skipped / 16 deselected**; strict mypy 94 kaynak, GUI 27 Electron + 10 UI test ve 202 PDF vendor hash'i temizdir. Son `6732bf4` smoke düzeltmesi **31 Electron + 10 UI / 202 PDF** kontrolünü geçti. Private `6732bf4` uzak CI kontrolleri başarılıdır; public başarılı snapshot hâlâ `ccbded4` olup yeni smoke fix'in public CI kabulü henüz yoktur. Kaynak test sayıları ve skip/exclusion kapsamı değişmedi. Temiz kaynakla imzalı installer üretildi; resmî kaynak native ve bağımsız içerik incelemesi geçti. Genel native analiz, bağımsız kaynak incelemesi ve gerçek kurulu ürün kabulü geçti; genel model doğruluğu ayrıca onaylanmış sayılmaz. Python kaynağındaki 342 dosya son installer/smoke değişikliklerinden etkilenmedi.

İlk bağımsız kurulum, Electron 43.7.7'nin sandbox erişim kontrolünde `0x80000003` ile başarısız oldu; imzalı installer üretimi bu başlangıç hatasını örtmez. 3 Ekim tarihli `e00a970` düzeltmesi yalnız uygulamanın kurulum klasörüne gereken inherited read/execute iznini verir; sandbox korunur. Genel analiz işi tamamlanan sonraki adayda boş arama sonucunun `kanit_turu=yok`, **BELİRSİZ / güven 0** kaydı smoke kontrolünde yanlış başarısız sayıldı. `6732bf4` bu kabul koşulunu dört regresyonla düzeltti ve temiz kaynakla signed build tamamlandı; genel native analiz ve gerçek kurulu ürün kabulü geçti; eski başarısız makbuzlar korundu. Eski başarısız kanıtlar korunur.

Yerel kurulum kabulü, eski kurulumların emekliliği ve installer/R2 readback'i tamamlandı. Canlı üyelik/ödeme, lisanslı gündem producer host'u ve düzenli yenileme işletimi açık kabul adımlarıdır. Fiziksel 8 GB cihaz testi yapılmadı. PR korumalarının gerektirdiği bağımsız insan/CODEOWNERS onayı tamamlanmadan merge/production ve tamamlanma duyurusu yapılmış sayılmaz.

## Son yerel ve dağıtım kabulü

Son imzalı Windows kurulumunun bağımsız analizi, içerik/byte incelemesi ve R2 tam readback'i geçti. Eski kurulumlar emekli edildi. Canlı üyelik/ödeme, yönetilen gündem producer işletimi, bağımsız insan review'u ve production yayını açık adımlardır; tamamlanma duyuruları bunların ardından yapılır. Fiziksel 8 GB cihaz testi yapılmadı.

Installer 0.5.0: **1.332.628.288 byte**, SHA256 `8b353e1b2c61f1fd5f8d49aae249050bb506ca9db0446550a54705c3d9ef4bde`. Normal Windows kurulumundan gerçek UI → IPC → frozen analiz → kalıcı çıktı yolu geçti. Aynı dosya R2'den tamamen okunarak SHA ve boyut doğrulandı; üyelik/release flag açılmadı. Eski Gözlemevi/Radar bağımsız başlatıcıları yeni Rasathane'ye yönlenir; kaynak geçmişleri korunur.
