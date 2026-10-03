# Rasathane

**Av. Mehmet Arın Gülüm** tarafından geliştirilen yerel kaynak takip, içerik analizi ve araştırma uygulaması. Radar'ın kaynak geçmişi ile Gözlemevi'nin analiz motoru tek masaüstü arayüzünde birleşir.

| Bölüm | İşlev |
| --- | --- |
| Akış | RSS/Atom ve resmî kaynak takibi; tek haber özeti, kalıcı toplu bülten ve Türkçe seslendirme |
| Analiz | Video, web, GitHub, arXiv ve sosyal kaynak analizi; özet, çeviri, değerlendirme ve üretim araçları |
| Araştır | Tek chat görünümü; header'da konuşma geçmişi, web ve yerel kaynaklarla devam soruları |
| Kaynaklar | Kategorili kaynak yönetimi; URL ekleme, kaynak sohbeti, düzenleme ve duraklatma |
| Profil ve ayarlar | Header’ın sağındaki profil kartından hesap, sekmeli ayarlar, kurulum ve çıkış |

Yerel çekirdek **AGPL-3.0-or-later** lisansıyla ücretsizdir; ticari kullanım dahil AGPL hakları geçerlidir. Masaüstü uygulamasında Muhakeme hesabıyla giriş zorunludur; yerel özellikler ücretli abonelik gerektirmez. Yönetilen servisler için aylık toplam **49 TL** ve **14 günlük** deneme sözleşmesi ayrı yürütülür. Marka ve üçüncü taraf model lisansları: [NOTICE](NOTICE.md).

Giriş, uygulama içinde e-posta ve altı haneli doğrulama koduyla yapılır. Muhakeme'deki mevcut kullanıcı yeniden kullanılır; yeni kullanıcı doğrulama sonrasında aynı hesap sisteminde oluşturulur. Kod ve cihaz doğrulama bilgileri bellekte, oturum token'ları yalnız Electron main sürecinde Windows güvenli deposunda tutulur. Yeni giriş akışının kullanılabilmesi için Muhakeme sunucusunda karşılık gelen endpoint'lerin yayımlanması gerekir.

## Kaynak ve geliştirme

Tek kaynak kökü bu depodur. `apps/desktop` yeni ürünün runtime'ıdır; `apps/web` Türkçe ürün sitesidir. `apps/radar` eski PostgreSQL servislerinin migration ve kaynak referansını korur; yeni masaüstü kurulumu Docker, PostgreSQL, Python veya uv gerektirmez.

```powershell
cd apps/desktop
uv sync --frozen --group content --group intel
uv run --frozen --group content --group intel pytest -q
uv run --frozen --group content --group intel mypy core mcp eval

cd gui
pnpm install --frozen-lockfile
pnpm check
```

Site için `apps/web` içinde `pnpm lint` ve `pnpm build` kullanılır. Windows paketi `apps/desktop/infra/build-electron.ps1` ile üretilir. Release build geçerli certificate store/Windows SDK imzası ve zaman damgası ister; kendi geliştirici paketi için açıkça `-Unsigned` kullanılır. İmza hesabının kimlik bilgileri kaynak veya `.env` dosyalarına yazılmaz. Model ağırlıkları ve uygulama verileri Git'e girmez.

## Çalışma sınırları

Akıştaki **Bülten seçenekleri**, mevcut filtrelerdeki en fazla 20 haberden kaynak alıntılarına dayalı bir derleme oluşturur. Metin ve kaynaklar yerel snapshot olarak saklanır; yeniden açıldığında değişmez. Türkçe ses Windows konuşma motoruyla üretilir. Tam karar metni bulunmayan künyelerden karar özeti üretilmez. LLM veya model indirmesi gerektirmez.

Kişisel gündem, Akış’taki **İlgi alanlarım ve proje bağlamım** açıklamalarını kullanır. Etkin kaynaklar kendi kontrol aralıklarıyla yenilenir; gündem kaynak işlerinin tamamlanmasını bekler. Yerel model haberin önemini, proje etkisini ve sonraki adımı kaynak alıntısıyla değerlendirir; model kullanılamazsa konu eşleşmesi açıkça etiketlenir. Otomatik takip uygulama ve hesap oturumu açıkken çalışır. Kullanım adımları: [bülten ve araştırma](docs/urun/BULTEN-ARASTIRMA.md).

Header’ın ortasında dört ana sekme bulunur: Akış, Analiz, Araştır ve Kaynaklar. Analiz çıktıları **Analiz arşivi** içinde açılır. Çalışma alanı ve konu takibi özellikleri kaldırılmıştır; eski kayıtlar veri kaybı olmadan arşivde ve tam export’ta korunur. Önceki araştırma konuşmaları sürdürülebilir. Yeni gündem bağlamı kişisel ilgi alanı ve proje açıklamalarından oluşur.

8 GB profilinde 4096 context, CPU inference ve tek ağır iş kullanılır. LLM/embedding birlikte yüklenmez; worker spawn öncesinde anlık boş RAM denetlenir. Bu profil gerçek bir 8 GB makinenin kabul testini ikame etmez.

Web aramasını açmak arama terimini seçilen sağlayıcıya gönderir. Kaynak takibi ve içerik edinimi ilgili kamu sitelerine bağlanır. Yerel arşiv, SQLite, hash'ler ve analiz çıktıları kullanıcı cihazında kalır. Cloud analiz varsayılan olarak kapalıdır. Renderer token, shell veya dosya sistemine doğrudan erişmez.

Resmî karar metadata'sı kapsamlı karar metni değildir. Kaynakta yayımlanma tarihi bulunmadığında karar tarihi bu adla gösterilir. Servis yapılandırılmamışsa veya yanıt alınamıyorsa arayüz bunu açıkça belirtir.

Türkçe Resmî Gazete normatif metinlerinde özet ve harita doğrudan kaynak alıntılarından hazırlanır; madde/fıkra yapısı ve kaynak hash'i korunur. Alıntı sınırları belirsizse ana metin tam tutulur. Bu görünüm hukuki yorum, konsolide mevzuat veya bağımsız doğruluk puanı üretmez. Diğer içerikler yerel model analizinden geçer.

Doğrulanmış Windows release yerelde mevcutsa `scripts/windows/Kur-Rasathane.ps1` paketin boyutunu, SHA-256 değerini ve kabul kaydını kontrol ederek kurulumu yapar. Sonraki açılışlar `scripts/windows/Baslat-Rasathane.ps1` veya Rasathane kısayoluyla yapılır. Eski Radar/Gözlemevi başlatıcıları aynı birleşik kuruluma yönlenir.

Geliştirme ve yayın durumu: [çalışma planı](docs/urun/CALISMA-PLANI.md). Mimari ve veri sınırları: [mimari](docs/urun/MIMARI.md). Dağıtım bileşenleri: [üçüncü taraf bildirimleri](apps/desktop/infra/THIRD-PARTY.md).

Özgün Radar/Gözlemevi/web Git geçmişleri private çalışma deposunda `sources/*` ve `source-*` ref'leriyle korunur. Açık çekirdek yayını, özel geçmişi ve yerel secrets'ı taşımayan hash manifest'li source export üzerinden hazırlanır.
