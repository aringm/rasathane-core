# Native kaynak sunumu ve yayın kabulü

Sahip: **Av. Mehmet Arın Gülüm**. Kapsam: Rasathane 0.5.0 Windows x64 paketindeki PyAV/FFmpeg, llama.cpp CPU motoru ve final SBOM/frozen arşivinde saptanan reciprocal Python bileşenleri.

`source-offer-manifest.json` 32 sabit kaynak girdisini URL ve SHA-256 ile bağlar. `source-offer.py` yalnız bu kaynakları indirir; binary, GGUF veya ses modeli indirmez. Arşivler `infra/vendor/source-offer/0.5.0/archives`, tam lisans metinleri `infra/vendor/licenses/upstream` altında kalır. Lisans metinleri byte olarak korunur; içerik hash'i dosya adıdır. Her kaydın upstream arşiv yolu, boyutu ve hash'i `LICENSE-MANIFEST.json` içinde bulunur. Symlink/hardlink extract edilmez; `extractall()` kullanılmaz. Kullanıcı verileri, eski kurulumlar ve model depoları silinmez.

Henüz yayınlanmamış yeni bir kaynak sürümünü hazırlamak için `apps/desktop` içinde çalıştırın. Aşağıdaki `prepare/build` akışı, mevcut immutable 0.5.0 public byte'larını geri yükleme yöntemi değildir:

```powershell
uv run --no-sync python -B infra/source-offer.py self-test
uv run --no-sync python -B infra/source-offer.py prepare
uv run --no-sync python -B infra/source-offer.py build
uv run --no-sync python -B infra/source-offer.py verify --release
```

Native kaynak paketi [native-sources-0.5.0 release'inde](https://github.com/aringm/rasathane-core/releases/tag/native-sources-0.5.0) ayrı sunulur; bu release installer içermez. Yayınlanan kaynak artefaktı **244.061.209 byte**, SHA-256 **`6f2d08d6634d43879a7d98e6af40cf4c126c5f9d6f8f908ce882f5d6aa272dbf`**. Yayın sonrasında arşiv, source manifest ve bundle manifest yeniden üretilmez.

## Yeni checkout'ta yayınlanmış kaynakları geri yükleme

Public 0.5.0 paketi yayımlandıktan sonra canonical helper ve bu doküman geliştirildi. Güncel `prepare/build`, aynı 32 upstream kaynakla bile yeni helper/doküman byte'larını pakete ekler; yayınlanmış `6f2d...` SHA'sını yeniden üretmesi beklenmez. Yayınlanmış dosyanın resmi kimliği exact public artefakttır. Güncel araçlarla yeniden hazırlanan farklı byte'lar eski release'in üzerine yazılmaz.

Temiz checkout'ta, desktop kökünden:

```powershell
uv run --no-sync python -B infra/restore-published-sources.py --self-test
uv run --no-sync python -B infra/restore-published-sources.py native
uv run --no-sync python -B infra/restore-published-sources.py typst
```

`restore-published-sources.py` yalnız sabit GitHub release HTTPS adreslerini indirir; redirect'ler GitHub release/objects host allowlist'iyle sınırlıdır. Tam stream boyutu ve pinned SHA doğrulanana kadar `.local/public-source-downloads` altındaki benzersiz `.partial` dosya staging'e alınmaz. Mevcut download veya staging dosyası farklıysa araç durur, üzerine yazmaz. Arşivler `extractall()` ile açılmaz; yalnız makbuzdaki normal dosyalar izinli checkout dizinlerine tek tek kopyalanır. Traversal, absolute/drive yolu, symlink, junction, duplicate member ve mevcut farklı dosya kabul edilmez. Restore kullanıcı verisi veya model cache'ine dokunmaz.

Native restore, exact public bundle/manifest'i `vendor/source-offer/0.5.0` altına; 32 arşivi `archives` altına; full lisansları ve lisans inventory'sini `vendor/licenses/upstream` altına koyar. Canonical `source-offer.py`, bu belge ve kaynak manifest'i public arşivdeki eski sürümle değiştirilmez. Canonical source manifest'in LF byte politikası korunmalıdır; makbuzdaki SHA `1c5ea3b9ba3b1446f7a48375cda5e3bce97674b10d7db1dc2f83605772acf495` ile eşleşir.

Typst restore, ayrı **25.302.608 byte**, SHA **`2274abfae7787fcbda874d6f5214fb8dc493ecb2551e047885ca3b09e6900273`** kaynak ekini `vendor/source-supplement/typst-0.15.1` altında ve kitin 790 kaynak/bildirim dosyasını `vendor/tooling/typst-licenses` altında kurar. Git'e alınmayan `build-supplement.py` böylece clean checkout'ta doğrulanmış public kit içinden geri gelir. Büyük font SFD kaynakları ve upstream source arşivleri bu kaynak kitinde kalır; installer lisans kopyasına eklenmez. Kit kendi yeniden üretim ve font build açıklamasını `SOURCE-SUPPLEMENT.md` içinde taşır.

| Public asset | Boyut / SHA-256 |
| --- | --- |
| `BUNDLE-MANIFEST.json` (native) | 707 byte / `e08c5126954c8e9192a4023e21cb82f36bb885bc59ec9abd8dc8b4727c2c333b` |
| `RASATHANE-TYPST-BUNDLE-MANIFEST.json` | 184504 byte / `f7cd11e72ade5bcc15b1a63b0c8d6a76442b9e0e3069c89d8a2ce60be974a430` |
| `RASATHANE-TYPST-SOURCE-MANIFEST.json` | 184902 byte / `a7115565e2784ee6249e3d4144b30f52d8e1d010462dfda457e5049c9b106b31` |

İki makbuz release'de ayrı adla sunulur; native manifest'in üzerine yazılmaz. Typst source manifest'i hash doğrulanmış kit içinden okunur. Remote readback makbuzları yeni checkout'ta yeniden oluşturulur:

```powershell
uv run --no-sync python -B infra/source-offer.py record-publication --url 'https://github.com/aringm/rasathane-core/releases/download/native-sources-0.5.0/Rasathane-native-corresponding-source-0.5.0.tar.gz'
uv run --no-sync python -B infra/vendor/tooling/typst-licenses/build-supplement.py record-publication --url 'https://github.com/aringm/rasathane-core/releases/download/native-sources-0.5.0/Rasathane-Typst-source-supplement-0.15.1.tar.gz'
uv run --no-sync python -B infra/source-offer.py verify --release
uv run --no-sync python -B infra/verify-source-supplement.py --release
```

Supplement release verifier source bundle, iki manifest, staging'deki 790 dosya ve exact public URL/full-stream SHA/boyut makbuzunu birlikte doğrular. Public erişim makbuzu yoksa `--release` exit 2 verir. Frozen kit içindeki eski `build-supplement.py verify`, sadece yerel kaynak kontrolüdür; public release gate'i için canonical `verify-source-supplement.py --release` kullanılır. Bu iki source gate geçtikten sonra `build-notices.py` ve Electron paketleme çalıştırılır. Public preparation manifest'lerindeki `false` alanları değiştirilmez; güncel yayın kanıtı ayrı `PUBLICATION-RECEIPT.json` dosyalarıdır.

Yerel staging yayınlanan artefakt/manifest ile eşleştiğinde public byte doğrulaması ayrı makbuz oluşturur:

```powershell
uv run --no-sync python -B infra/source-offer.py record-publication --url 'https://github.com/aringm/rasathane-core/releases/download/native-sources-0.5.0/Rasathane-native-corresponding-source-0.5.0.tar.gz'
uv run --no-sync python -B infra/source-offer.py verify --release
```

`record-publication` yalnız bu exact HTTPS adresini kabul eder; redirect host'ları GitHub release host'larıyla sınırlıdır. Arşivin tüm remote byte'ları 1 MB buffer ile hash'lenir ve diske yazılmaz. SHA/boyut veya readback sırasında local bundle/manifest değişirse makbuz üretilmez. `PUBLICATION-RECEIPT.json` doğrulanmış URL, remote SHA/boyut ve local source/bundle makbuz hash'lerini bağlar. `verify --release` bu makbuz ile gerçek local artefakt eşleştiğinde `published_source_access` gate'ini kapatır. Bundle'daki `source_offer_complete=false` hazırlık kaydı değiştirilmez; yayın kanıtı ayrı makbuzdadır. Publication makbuzu bulunan staging'de `prepare/build` çalıştırılmaz; yeni içerik yeni release kapsamına alınır.

`prepare` tüm arşivleri doğrular ve lisans metinlerini üretir. `build` doğrulanmış kaynakları, tam lisansları, manifest'i, makbuzu ve bu yeniden üretim talimatlarını tek deterministik `.tar.gz` artefaktında toplar. Önceden indirilen arşivlerin SHA-256 değerleri tekrar kontrol edilir. Ağ veya hash hatası varsa bundle üretilmez. Kaynaklar hazırsa `corresponding_sources_prepared=true` olur. Binary'nin alıcılarına kaynak erişimi henüz sağlanmamışsa `build` ve `verify --release` **exit 2** verir ve `source_offer_complete=false` kalır. Lisans şartı olan kaynak erişimi ile ek provenance iyileştirmeleri ayrı alanlardır.

Final 0.5.0 installer'dan önce yukarıdaki immutable public restore/readback akışı tamamlanır; ardından `build-notices.py` ve Electron paketleme yapılır. Yeni kaynak sürümü hazırlanırken `prepare` ayrıca uygulanır. `resources/licenses/upstream` tam upstream metinlerini taşır. Kaynak artefaktı installer ile birlikte verilebilir veya indirme yanında açık kaynak erişim yolu sağlanabilir. Kaynak başka sunucudaysa binary'nin yanındaki talimatlar bunu açıkça belirtmelidir. Public kaynak sunumu/readback'i gerçekleşmeden `published_source_access` engeli kapatılmaz. Yerel ürün sahibinin kendi cihazında denemesi üçüncü kişiye binary dağıtımı olarak sunulmaz.

## Doğrulanmış eşleme

| Binary / kaynak | Kesin referans |
| --- | --- |
| PyAV | 18.0.0; `av-18.0.0-cp311-abi3-win_amd64.whl`, SHA-256 `aaf4d354d2beaa6651e4f92e54409a578bde64f79c0beef9a30b388d06f7c629`; source sdist manifest'te sabittir. PyAV git commit `54a4395bb4cdd9cdd53ff6216c50b69f6475c13d`. |
| PyAV vendor build | `pyav-ffmpeg` tag `8.1.2-1`, commit `a71bf9279f7a4659154b68ba6783e89be460bcd5`; tüm build script'leri, workflow ve `patches/` arşivde korunur. |
| FFmpeg | Gerçek `av.ffmpeg_version_info=8.1.2`; tag `n8.1.2`, commit `38b88335f99e76ed89ff3c93f877fdefce736c13`; `avcodec 62.28.102`, `avutil 60.26.102`. Tam configure satırı manifest'tedir. |
| x264 | Commit `b35605ace3ddf7c1a5d67a2eb553f034aef41d55`; `COPYING` ve `x264.h`, GPL-2.0-or-later. Kaynak arşivinin SHA-256 değeri canlı indirme ile doğrulandı. |
| x265 | 4.2; `x265Version.txt` revision `e444744`; `COPYING`, `source/x265.h` ve dynamicHDR10 lisansı GPL-2.0-or-later, json11 metni MIT. Kaynak arşivinin SHA-256 değeri canlı indirme ile doğrulandı. Tam revision yerine kaynak tarball SHA'sı kesin kimliktir. |
| llama.cpp | `b10599`, tam source commit `4a08fa29705b8177e332b134306566c2c4b95902`; CPU binary archive SHA-256 `d95eff420538b372273c5ee82258e238cc955ee3b5135443503d1fa4a38d8308`. Kaynak `LICENSE` tam MIT metni ve copyright bildirimi lisans staging'ine alınır. |

[PyAV build ayarı](https://github.com/PyAV-Org/PyAV/blob/54a4395bb4cdd9cdd53ff6216c50b69f6475c13d/scripts/ffmpeg-latest.json) exact vendor `8.1.2-1` arşivini seçer. Vendor `pkg.py` kaynak URL/hash'leri build girdilerini belirler; `README.rst` içindeki x264 revision'ı eski olduğundan esas alınmaz. Vendor source arşivinde bağımsız bir LICENSE dosyası bulunmamıştır; build script'leri AGPL olarak yeniden etiketlenmez.

FFmpeg DLL metadata'sı `LGPL version 3 or later` bildirir, fakat [vendor patch'i](https://github.com/PyAV-Org/pyav-ffmpeg/blob/a71bf9279f7a4659154b68ba6783e89be460bcd5/patches/ffmpeg.patch) x264/x265'i GPL listesinden version3 listesine taşır. DLL'ler bu GPL codec'lerini gerçekten içerir. Dolayısıyla kaynak ve lisans sunumu **GPL codec kapsamını da** korur; tüm native payload LGPL veya PyAV BSD olarak tanımlanmaz. [FFmpeg'in resmî lisans açıklaması](https://ffmpeg.org/legal.html) exact binary'ye karşılık gelen kaynakları, değişiklikleri ve build ayarlarını birlikte sunmayı açıklar.

## Somut reciprocal bileşenler ve karşılanan kaynak kapsamı

Final SBOM metadata'sı yalnız ortamda kurulu paketleri gösterdiğinden gerçek frozen `PYZ` içeriği de salt okunur kontrol edildi. Aşağıdakiler sidecar/worker'da gerçekten bulundu:

| Bileşen | Kaynak sunumu yükümlülüğü / karşılık |
| --- | --- |
| FFmpeg + x264/x265 | GPL/LGPL corresponding source; exact kaynak, vendor build script/patch ve configure satırı birlikte sunulur. |
| libiconv 1.19 | LGPL-2.1-or-later §§4/6; exact 1.19 kaynak, matching MSYS recipe ve patch'ler bundle'dadır. |
| GCC 16.1.0 runtime | GPL3 + Runtime Library Exception 3.1. `COPYING.RUNTIME` §1 uygun compiler süreciyle oluşan independent module birleşimine farklı lisans koşulları sağlar; bütün Rasathane veya private hizmet kaynaklarını açmayı gerektirmez. Runtime kaynak/recipe/patch metinleri ayrıca korunur. |
| docxtpl 0.20.2 | LGPL-2.1-only; exact library sdist, LGPL metni ve public Rasathane build/rebuild girdileri sunulur. |
| yake 0.7.3 | LGPLv3; exact library sdist ve değiştirerek yeniden paketleme girdileri sunulur. |
| certifi 2026.5.20 / 2026.7.22 | MPL-2.0; sidecar/worker covered kaynak dosyaları ve sertifika verisi exact sdist'lerde korunur. |
| orjson 3.11.9 | MPL-2.0 AND (Apache-2.0 OR MIT); sidecar native extension'ın covered kaynak dosyaları, tam MPL/Apache/MIT metinleri sdist'te bulunur. |
| tqdm 4.68.1 / 4.70.1 | MPL-2.0 AND MIT; iki runtime sürümünün exact kaynak ve copyright metinleri sunulur. |
| PyInstaller 6.20.0 | Bootloader exception üretilen uygulamanın kendi kaynak/lisansını GPL'ye bağlamaz. Sidecar PYZ'da PyInstaller modülleri de bulunduğu için exact project sdist ve COPYING ayrıca korunur. |

[MPL-2.0 §3.2(a)](https://www.mozilla.org/en-US/MPL/2.0/) covered dosyaların kaynağını alıcıya erişilebilir tutmayı ve erişim yolunu bildirmeyi gerektirir; ayrı ürün dosyalarını MPL altında yayınlama yükümlülüğü doğurmaz. [PyInstaller'ın resmî exception açıklaması](https://pyinstaller.org/en/stable/license.html) üretilen executable için uygulamanın kendi lisansının korunmasını açıklar. LGPL library'lerin değiştirilmesi ve yeniden build edilmesi kısıtlanmaz; açık Rasathane build script'leri ile source sdist'leri bu yolu sağlar. Bu tablonun her satırı manifest'in `reciprocal_inventory` alanında sabit source kimliklerine bağlıdır.

## MSYS2 runtime kanıtı ve provenance notları

Vendor Windows build script'i compiler `bin` ağacından `libgcc_s_seh-1`, `libstdc++-6`, `libiconv-2`, `libwinpthread-1`, `zlib1` DLL'lerini kopyalar. Workflow MSYS2 paket sürümlerini pinlemez. Yerel wheel'de GCC 16.1.0 Rev5, libiconv 1.19 ve ilgili compiler string'leri okundu; gerçek DLL SHA'ları manifest'tedir.

29 Haziran 2026 tarihli upstream build'e göre GCC 16.1.0-5, libiconv 1.19-1, zlib 1.3.2-2 ve winpthreads `14.0.0.r147.g31bd54ab7-1` recipe/source girdileri hazırlığa alınmıştır. Bunlar build tarihine ve embedded string'lere dayalı eşlemedir. Özellikle winpthreads ve zlib için exact package/binary karşılaştırması tamamlanmamıştır. [Upstream Windows job](https://github.com/PyAV-Org/pyav-ffmpeg/actions/runs/28393781929/job/84127236786) log endpoint'i inceleme tarihinde HTTP 410 verdi; kaybolmuş logdan kesin eşleme çıkarılmadı.

`msys2-build-recipes` arşivi tüm ilgili PKGBUILD/patch'leri korur. GCC'nin ayrı upstream SEH patch'i de kendi hash'iyle manifest'tedir. GCC runtime için `COPYING3`, `COPYING.LIB`, `COPYING.RUNTIME`; libiconv için `COPYING`, `COPYING.LIB`, `libcharset/COPYING.LIB`; winpthreads için kendi `COPYING` metni korunur. Libiconv DLL'in 1.19 sürümü doğrudan okundu; bu exact upstream source ve build dönemindeki matching recipe/patch'ler sunulur, çelişen kaynak sürümü veya yerel değişiklik saptanmadı.

winpthreads MIT/BSD ve zlib Zlib lisanslıdır; bunlarda exact binary/source eşlemesi tek başına corresponding source yükümlülüğü değildir. Bu eşleme eksikliği release blocker olmaktan çıkarılmış ve provenance notuna alınmıştır. GCC Runtime Exception source sınırı ayrı kapsam satırında açıklanır; GCC runtime kaynakları zaten sunumdadır. Package-byte eşlemesi ve bağımsız yeniden build gelecekte provenance'ı güçlendirir; yeni build yapılırsa native hash/kaynak makbuzu birlikte güncellenir.

Final envanterde saptanan reciprocal bileşenlerin exact kaynakları bu sunuma alınmıştır. Belirsiz “bütün bileşenleri ayrıca incele” release gate'i bulunmaz. Yeni sürümde SBOM, frozen module listesi ve bu dokuz satırlık kapsam birlikte güncellenir. Kalan somut release adımı kaynak artefaktını binary alıcılarına erişilebilir hale getirmek ve indirme/erişim talimatını doğrulamaktır.
