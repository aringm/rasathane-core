# Rasathane ürün geliştirmesi

Sahip: **Av. Mehmet Arın Gülüm**. Başlangıç: 3 Ekim 2026.
Kaynak kökü: `C:\Users\aring\Desktop\Rasathane`; dal: `codex/rasathane-urun`.

## Hedef ve kabul

Rasathane Radar'ın takip, kaynak, bülten ve araştırma özellikleri ile Gözlemevi'nin ayrıntılı analiz motoru tek **Rasathane** ürününde birleşir. Yerel çekirdek AGPL-3.0-or-later; marka, Muhakeme hesabı, yönetilen servisler ve ticari servis uygulaması ayrı kalır. Açık çekirdeğin ticari kullanımı serbesttir; marka lisansı verilmez. Yönetilen üyelik aylık toplam 49 TL, ücretli servis denemesi 14 gündür. Yerel çekirdek üyelik olmadan çalışır.

| Aşama | Yapılacak iş | Kabul kanıtı | Durum |
| --- | --- | --- | --- |
| Envanter | GitHub ve yerel kaynaklar, mimari, lisans ve standartlar | Kaynak yolları, Git revision ve korunmuş geçmiş | Tamamlandı |
| Ortak çekirdek | SQLite/FTS, kalıcı işler, Gözlemevi engine adapter, Radar veri import'u | 96 kaynak / 16.834 kayıt kayıpsız import; integrity_check OK; 718 kaynak testi geçti, bir platform testi atlandı | Kaynak ve migration tamamlandı |
| Araştırma | Web search, sürümlü kaynaklar, çalışma alanı, notlar, konu takipleri | Türkçe not → yerel arama → kaynaklı sonuç → restart/readback geçti; public RG/Yargıtay gerçek veri | Uygulandı ve doğrulandı |
| Tasarım | Bağımsız logo, birleşik arayüz, tek ürün sitesi | Logo/ikonlar üretildi; gerçek browser akışları, web build ve Vercel preview kontrolü geçti; hukuki metinler korundu | Uygulandı ve preview doğrulandı |
| Üyelik | Muhakeme PKCE client, açık deneme başlangıcı, 49 TL toplam fiyat, indirme | 1274 Muhakeme test; istemcide 18 Electron test; private PR #59 | Kaynak hazır; production kabulü bekliyor |
| Paket | Bağımsız worker runtime, kurulum sihirbazı, RAM bütçesi, veri konumu | Repo/Python/uv/Docker gerektirmeyen paket; gerçek inference ve kapanış | Uygulanıyor |
| Geliştirme standardı | Root CI, frozen lock, secret scan, SBOM/lisans, release hash | Windows/Linux CI kaynağı; 196 SBOM bileşeni, 303 lisans referansı; strict mypy 93 dosya; 67 runtime hash'i | Uygulandı; uzak çekirdek CI/paket kabulü sürüyor |
| Yayın | Açık çekirdeğin temiz kaynak yayını, site preview ve installer | Public kaynak tekliflerinin tam uzak readback'i geçti; site PR #2 ve private üyelik PR #59 preview/CI hazır; temiz çekirdek export'u denetleniyor | Sürüyor |
| Emeklilik ve duyuru | Eski kurulumların temizliği; Discord/Atölye/Drive/OpenClaw güncellemesi | Yeni ürün kabulünden sonra tek kurulum; hedef başına makbuz/readback | Bekliyor |

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

Mevcut kaynaklar: `apps/desktop` Gözlemevi 0.4.1, `apps/radar` Radar, `apps/web` Next.js sitesi. İnceleme sırasında Radar FastAPI/SQLAlchemy/Pydantic sürümleri günceldir; teknik borç esas olarak runtime, monolit ve paketleme sınırındadır.

## Son kalite düzeltmeleri

Resmî Gazete'nin Windows-1254 kaynağı strict charset kontrolüyle açılır; Türkçe mevzuat gereksiz yeniden çeviriye girmez. Modelin destek puanı bağımsız doğruluk onayı olarak sunulmaz. Her ürün analizinin job kimliğine bağlı ayrı çıktı klasörü vardır; yeniden analiz önceki dosya ve hash'leri değiştirmez. Bu davranışların regresyonları geçti. Son frozen paket üzerinde gerçek analiz ve PDF/DOCX/map kabulü ayrıca yürütülmektedir.

Yerel model envanteri ve üretim örnekleri salt okunur referans alındı. 128 GB çalışma bilgisayarındaki büyük modeller, 8 GB ürün profilinin dağıtım gereksinimi olarak alınmadı; veri ve model depoları korunur.
