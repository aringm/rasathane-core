# Rasathane

**Av. Mehmet Arın Gülüm** tarafından geliştirilen yerel kaynak takip, içerik analizi ve araştırma uygulaması. Radar'ın kaynak geçmişi ile Gözlemevi'nin analiz motoru tek masaüstü arayüzünde birleşir.

| Bölüm | İşlev |
| --- | --- |
| Akış | RSS/Atom, Resmî Gazete ve resmî karar metadata takibi; tarih, kaynak ve yenileme durumu |
| Analiz | Video, web, GitHub, arXiv ve sosyal kaynak analizi; özet, çeviri, değerlendirme ve üretim araçları |
| Araştır | Web ve yerel tam metin araması; kaynak sürümü, hash ve citation |
| Çalışma alanı | Kalıcı notlar, araştırma geçmişi ve kaynaklar |
| Konu takibi | Değişiklikleri kaydetme, yenileme aralığı ve hata/güncellik durumu |
| Ayarlar | Kurulum sihirbazı, model kontrolü, çalışma klasörü ve Muhakeme hesabı |

Yerel çekirdek **AGPL-3.0-or-later** lisansıyla ücretsizdir; ticari kullanım dahil AGPL hakları geçerlidir. Muhakeme hesabıyla sunulan yönetilen servisler için aylık toplam **49 TL** ve **14 günlük** deneme sözleşmesi ayrı yürütülür. Yerel özellikler üyelik olmadan çalışır. Marka ve üçüncü taraf model lisansları: [NOTICE](NOTICE.md).

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

8 GB profilinde 4096 context, CPU inference ve tek ağır iş kullanılır. LLM/embedding birlikte yüklenmez; worker spawn öncesinde anlık boş RAM denetlenir. Bu profil gerçek bir 8 GB makinenin kabul testini ikame etmez.

Web aramasını açmak arama terimini seçilen sağlayıcıya gönderir. Kaynak takibi ve içerik edinimi ilgili kamu sitelerine bağlanır. Notlar, SQLite, hash'ler ve analiz çıktıları kullanıcı cihazında kalır. Cloud analiz varsayılan olarak kapalıdır. Renderer token, shell veya dosya sistemine doğrudan erişmez.

Resmî karar metadata'sı kapsamlı karar metni değildir. Kaynakta yayımlanma tarihi bulunmadığında karar tarihi bu adla gösterilir. Servis yapılandırılmamışsa veya yanıt alınamıyorsa arayüz bunu açıkça belirtir.

Türkçe Resmî Gazete normatif metinlerinde özet ve harita doğrudan kaynak alıntılarından hazırlanır; madde/fıkra yapısı ve kaynak hash'i korunur. Alıntı sınırları belirsizse ana metin tam tutulur. Bu görünüm hukuki yorum, konsolide mevzuat veya bağımsız doğruluk puanı üretmez. Diğer içerikler yerel model analizinden geçer.

Doğrulanmış Windows release yerelde mevcutsa `scripts/windows/Kur-Rasathane.ps1` paketin boyutunu, SHA-256 değerini ve kabul kaydını kontrol ederek kurulumu yapar. Sonraki açılışlar `scripts/windows/Baslat-Rasathane.ps1` veya Rasathane kısayoluyla yapılır. Eski Radar/Gözlemevi başlatıcıları aynı birleşik kuruluma yönlenir.

Geliştirme ve yayın durumu: [çalışma planı](docs/urun/CALISMA-PLANI.md). Mimari ve veri sınırları: [mimari](docs/urun/MIMARI.md). Dağıtım bileşenleri: [üçüncü taraf bildirimleri](apps/desktop/infra/THIRD-PARTY.md).

Özgün Radar/Gözlemevi/web Git geçmişleri private çalışma deposunda `sources/*` ve `source-*` ref'leriyle korunur. Açık çekirdek yayını, özel geçmişi ve yerel secrets'ı taşımayan hash manifest'li source export üzerinden hazırlanır.
