# Rasathane — bağımsız inceleme ve kabul kaydı

Sahip: **Av. Mehmet Arın Gülüm**. İnceleme tarihi: **3 Ekim 2026**.

Bu kayıt kaynak kodu incelemesini, bellek içinde çalıştırılan doğrulamaları ve dar kapsamlı canlı kaynak ölçümlerini ayırır. Bir production yayını, canlı ödeme veya 8 GB fiziksel cihaz kabulü gerçekleştiği anlamına gelmez. Gerçek token, kullanıcı oturumu, provider credential veya private Muhakeme implementation'ı bu belgeye alınmamıştır.

## Hesap, PKCE ve ücretli hizmet sınırı

İncelenen public istemci: `apps/desktop/gui/electron/account.cjs`, `account-flow.test.cjs`, `account-concurrency.test.cjs`, `main.cjs`, `preload.cjs` ve `ui/src/product.js`. Private Muhakeme sunucusunun gerçek authorize doğrulayıcısı, PKCE doğrulayıcısı, session kayıt üreticisi ve exchange/refresh/session/revoke route'ları salt okunur karşılaştırıldı. Private kod public depoya kopyalanmadı.

| Kontrol | Kanıt ve sonuç |
| --- | --- |
| Authorize | Sabit `https://www.muhakeme.ai/hesap/cihaz-yetkilendir`; `response_type=code`, `client_id=rasathane-desktop`, `scope=desktop`, PKCE `S256` ve rastgele state. İstemcinin ürettiği gerçek query private sunucu doğrulayıcısına verildi; kabul edildi. |
| Callback | Dinleyici yalnız `127.0.0.1` ve rastgele portta; yol `/cihaz/geri-donus`. Yanlış state kod değişimine ulaşmaz. Doğru state ile `error=access_denied` bağlantıyı kapatır, beklemeyi sonlandırır. |
| Exchange | Gövde `client_id,code,code_verifier,device_id,redirect_uri`. Gerçek client/code/device/redirect ve PKCE doğrulayıcıları bu alanları kabul etti. Sunucunun oluşturduğu `schema_version=1.1` kaydı istemci tarafından kabul edildi. |
| Ürün kapsamı | İstemci yalnız `desktop` ister; sunucu doğrulanmış Rasathane client kimliğinden `desktop urun:rasathane` scope'unu üretir. İstemci başka ürün scope'unu veya ek scope'u kabul etmez. |
| Refresh | Gövde `refresh_token,device_id`. Aynı anda iki hak sorgusu, bellek içi transport ölçümünde yalnız **bir** refresh yaptı. Exchange ile aynı kayıt şeması döner. |
| Revoke | `POST /api/auth/device/revoke`, access bearer ve `{}` gövdesi sunucunun ilk kimlik yoluyla uyumludur; `session_id` bu yolda zorunlu değildir. Başarılı boş `204` yanıtı JSON olarak parse edilmez. |
| Yerel kayıt | `safeStorage` yoksa token düz metin saklanmaz. Token renderer'a açılmaz; main process içinde kalır. `401` sonrası encrypted kayıt silinir. Çıkışla yarışan callback/refresh eski oturumu yeniden açamaz. |
| UI | Hizmetin etkin olduğu yalnız başarılı `/api/lisans/v2/durum` yanıtından sonra gösterilir. Kalan süre sunucu zamanı ile hesaplanır. Deneme uygunluğu yalnız `deneme_baslatilabilir === true` iken düğmeyi açar. |

Bağımsız doğrulama fiziksel dosya ve socket kullanmadan, gerçek `account.cjs` kodunun bellek içi filesystem/HTTP transport ile çalıştırılmasıyla yapıldı. Gerçek sunucu saf fonksiyonları kullanıldı. Authorize, exchange/refresh, tek refresh, revoke/204, iptal callback'i ve terminal `401` temizliği geçti. Bu ölçüm production DB transaction'ını, gerçek OTP gönderimini veya canlı kullanıcının tarayıcı onayını çalıştırmadı.

Ücretli hizmet aylık **KDV dahil toplam 49 TL**; ödeme dönemliktir, otomatik kart tahsilatı uygulanmaz. **14 günlük deneme** yalnız explicit `POST /api/lisans/v2/deneme` ile başlar. Hesap sayfası veya hak durumu GET'i deneme açmaz. Rasathane diğer Muhakeme ürünlerini kapsamaz; onların kapsam zinciri Rasathane'yi kapsamaz. Açık yerel çekirdek hesabı veya ücretli hakkı bulunmadan kullanılabilir.

### Hesap kabulünde kalanlar

- Canlı OTP → tarayıcı onayı → loopback → exchange → hak sorgusu yolu private üyelik değişiklikleri production'a deploy edildikten sonra doğrulanmalı.
- `TOKEN_SURESI_DOLDU` yanıtında koduna göre bir refresh/retry yerine tüm `401` yanıtları yerel çıkışa dönüşür. Proactive 30 saniye yenileme normal akışı karşılar; büyük saat farkında yeniden giriş gerekebilir.
- Çevrimdışı çıkışta yerel kayıt silinir ve `remoteRevoked:false` açıkça bildirilir; sunucuya tekrar ulaşıldığında iptal gönderen kalıcı kuyruk bulunmaz.
- Native `401` temizliği sonrası UI catch bloğunun `accountStatus()` durumunu yeniden okuduğu son kaynakta doğrulandı. Eski isteğin geç `401` yanıtı için epoch kontrolü access token beklemesinden önce alınır; yeni girişin kaydı korunur. Gerçek tarayıcı/production kabulü yine ayrı adımdır.
- Mevcut auth scope alanı TEXT olduğundan Rasathane için yeni migration gerekmez. Var olan device/trial/license/download tabloları ve `trial_user_product_uq` tekilliğinin hedef ortamda mevcut olması gerekir.

## Canlı resmî kaynak ölçümü

3 Ekim 2026 tarihinde yalnız **bir** public Bedesten arama POST'u gönderildi. Auth veya API key kullanılmadı. Endpoint: `https://bedesten.adalet.gov.tr/emsal-karar/searchDocuments`. `Content-Type` ve `Accept` JSON; gövde `data` ve `applicationName=UyapMevzuat` envelope'udur. Sorgu `pageSize=2`, `pageNumber=1`, `itemTypeList=[YARGITAYKARARI]`, `phrase=karar`, `sortFields=[KARAR_TARIHI]`, `sortDirection=DESC`; tarih aralığı 4 Ağustos–3 Ekim 2026'dır.

Yanıt HTTP **200**; root alanları `data,metadata`, veri alanları `emsalKararList,total,start`; toplam **556** sonuçtur. İlk iki kayıt:

| documentId | Daire | Esas | Karar | Karar tarihi |
| --- | --- | --- | --- | --- |
| 1228680200 | 10. Ceza Dairesi | 2026/8295 | 2026/12094 | 2026-09-23T00:00:00+03:00 |
| 1228676300 | 10. Ceza Dairesi | 2026/9303 | 2026/12096 | 2026-09-23T00:00:00+03:00 |

Bu tarihler **karar tarihidir**; kaynağın yüklenme/yayım zamanı olarak sunulamaz. Görüntülenebilir resmî portal adresi `https://mevzuat.adalet.gov.tr/ictihat/{documentId}` biçimindedir. İlk kaydın GET'i HTTP 200 SPA sayfası döndürdü; bu ölçüm browser'da karar içeriğinin render edildiğini kanıtlamaz. Bedesten HTTP 200 altında `metadata.FMTY=ERROR` hata envelope'u verebildiğinden bu durum boş ve başarılı feed'e çevrilmemelidir. `429/Retry-After` ve kaynak kesintisi açıkça ele alınmalıdır.

Resmî Gazete'nin [3 Ekim 2026 fihristi](https://www.resmigazete.gov.tr/eskiler/2026/10/20261003.htm) HTTP **200** döndürdü ve **33389** sayısını içerdi. Güncel mevzuat gündemi günlük fihrist ve mükerrerlerinden beslenir; bu veri tüm mevzuatın konsolide yürürlük metninin tarandığı anlamına gelmez. Konsolide mevzuat araması ayrı Bedesten mevzuat endpoint'idir.

Public Bedesten/Resmî Gazete adapter'ı ile ücretli Muhakeme managed feed ayrı sınırlar olarak tutulur. Managed feed için geçerli session, Rasathane scope'u ve lisans/deneme gerekir. Worker kaynağı yapılandırılmadığında managed feed'in `503` vermesi, public resmî kaynakların hazır olmadığı anlamına gelmez.

## Paketleme ve CI bağımsız incelemesi

İncelenen kaynaklar: `.github/workflows/verify.yml`, `apps/desktop/infra/build-electron.ps1`, `prepare-runtime.py`, `build-worker.ps1`, `build-sidecar.ps1`, `build-notices.py`, `gui/package.json`, `electron/model-setup.cjs`, `model-catalog.json`, `scripts/export-source.py`, `NOTICE.md` ve `THIRD-PARTY.md`.

| Kontrol | Kanıt ve sonuç |
| --- | --- |
| Sabit native runtime | llama.cpp `b10599` CPU ZIP'i sabit URL/SHA-256 ile indirilir. GitHub release API'nin **18.061.865 byte** asset digest'i kodda sabit SHA ile eşleşti. |
| ZIP traversal | Gerçek `prepare-runtime.py` AST'sindeki hedef resolve/`relative_to` koruması yazma yapmadan çalıştırıldı. `../`, Windows `..\\`, drive absolute, slash absolute ve UNC girdileri reddedildi; güvenli alt yol kabul edildi. |
| Model indirme | Model URL'si commit revision'a bağlıdır; byte boyutu ve SHA-256 sabittir. HTTPS provider allowlist'i her redirect'te yeniden uygulanır. `.partial` dosyası yalnız tam boyut ve hash doğrulamasından sonra hedefe taşınır. |
| Installer model sınırı | Electron resource filter yalnız native `bin`, NER, ASR ve manifest'i alır; GGUF veya Piper dfki sesi almaz. `0.5.0-review/win-unpacked/resources` staging ağacındaki **5085** dosyada GGUF ve dfki ses dosyası bulunmadı. Bu staging ölçümü final signed installer kabulü değildir. |
| Kullanıcı verisini koruma | Kullanıcı DB/model/legacy kurulum veya Hermes ağacını silen operasyon yoktur. Worker yalnız exact resolved `infra/dist/worker` staging'ini, hedef reparse point değilken yeniler. Export dolu hedefi reddeder. NSIS `deleteAppDataOnUninstall=false`. Build çıktıları kaynak checkout içinde kalır. |
| CI | Windows/Linux engine testleri, Ruff/strict mypy, dar IPC/PKCE/model testleri, web lint/type/build ve secret scan bulunur. Actions SHA'larının gerçek upstream commit'leri olduğu doğrulandı. Gitleaks 8.30.1 asset digest'i sabit checksum ile eşleşti. Uzak CI run sonucu bu incelemede gözlenmedi. |

### Paketleme bulgularının son durumu

1. **Gemma kaydı düzeltildi.** Seçilen `unsloth/gemma-4-E2B-it-qat-GGUF` revision `66a399f68ddd113b06dff02fca9523e55465d11d` README'si HTTP 200 ile `license: apache-2.0` doğrulandı. [Google Gemma 4 lisansı Apache 2.0](https://ai.google.dev/gemma/apache_2). Model kataloğu, NOTICE/UI metinleri ve yeniden üretilmiş SBOM Apache-2.0 gösterir.
2. **Lisans dosyası çakışması düzeltildi.** İlk 306 referansta 57 hash uyuşmazlığı bulunmuştu. Dosya adı artık içerik SHA-256'sıdır ve özgün yol metadata'da korunur. Son envanter **194 component / 303 lisans referansı**; **303/303 hash eşleşti**, Piper component yoktur.
3. **Native source sunumu hazırlandı ve ayrı public kaynak yayını doğrulandı.** Gerçek `av.ffmpeg_version_info` **8.1.2**; `av._core.library_meta` libavcodec **62.28.102**, libavutil **60.26.102** ve LGPL-3.0-or-later metadata'sı verir. Vendor patch'i GPL x264/x265'i version3 listesine taşır; iki GPL codec DLL'i gerçek wheel'de bulunur. Tüm payload LGPL veya PyAV BSD olarak etiketlenmez. Tam kaynak ve build/patch/configure haritası [SOURCE-OFFER.md](../../apps/desktop/infra/SOURCE-OFFER.md) ve pinned manifest'tedir.
4. **Staging atlama/merge düzeltildi.** `prepare-runtime.py` mevcut exe olsa da sabit upstream arşiv SHA'sını yeniden doğrular. Worker hedefi yalnız sınırı doğrulanmış staging'de yenilenir. Son `infra/dist/worker` ölçümünde **4331 dosya / 759.904.270 byte**; Piper, dfki ve GGUF yoktur. `-ReuseCompiled` açık kullanılırsa fresh build atlanır ve release manifest `compiled_reused=true` kaydeder; final artefakt kabulü ayrıca gerekir.
5. **Temiz clone orkestrasyonu düzeltildi.** Default `build-electron.ps1` artık `fetch-motor.ps1`, worker ve sidecar build'lerini çağırır; hazırlık betiği pinned runtime/model staging'i sağlar. Bu inceleme temiz clone'da bütün installer build'i gerçekleştirmedi.
6. **Kısmi disk yazması düzeltildi ve bağımsız yeniden ölçüldü.** Gerçek `model-setup.cjs` `writeFile()` kullanır ve `.partial` dosyasının disk boyutu/hash'ini rename öncesi kontrol eder. Bellek içi fixture'da normal 3 byte indirme `completed/ready:true`; 1 byte disk yazması, yanlış hash, fazla boyut ve izinsiz redirect `failed`, rename **0** oldu. Gerçek model indirilmedi ve fiziksel model dosyası yazılmadı.

### Native kaynak sunumu ölçümü

`source-offer.py prepare` **32/32** pinned source girdisini gerçek indirmede SHA-256 ile doğruladı. **237** tam lisans/copyright referansı üretildi; ayrı readback'te **237/237 hash eşleşti**. Tam llama.cpp MIT metni **1078 byte**, SHA-256 `94f29bbed6a22c35b992c5c6ebf0e7c92f13b836b90f36f461c9cf2f0f1d010d`; upstream GPL/LGPL/COPYING.RUNTIME metinleri de staging'de korunur. Kaynak arşivleri checkout içindeki `infra/vendor/source-offer`, lisanslar `infra/vendor/licenses/upstream` altındadır; Git'e source tarball/model/binary eklenmez.

Araç hash veya indirme hatasında bundle üretmez; 32 kaynağın tamamı hazır olduğunda `corresponding_sources_prepared=true` kaydeder. Sidecar/worker frozen PYZ içeriği ve SBOM birlikte kontrol edildi; FFmpeg/x264/x265, libiconv/GCC runtime, docxtpl, yake, certifi, orjson, tqdm ve PyInstaller kaynak kapsamı manifest'in dokuz reciprocal satırına bağlandı. winpthreads MIT/BSD ve zlib permissive eşleme iyileştirmesi yayın engeli değildir; GCC Runtime Exception bağımsız ürünün tüm kaynağını GPL'ye açmayı gerektirmez. Somut kaynaklar, tam lisanslar ve recipe/patch'ler bundle'dadır.

Sekiz offline doğrulama grubu safe provider, traversal, staging, manifest pinleri, symlink license sınırı ve publication URL/hash/boyut/stale-receipt vakalarını geçti; Ruff ve diff whitespace kontrolü geçti. Kaynak bundle iki üretimde aynı hash verdi. Yayın sırasında yapılan yeniden üretim kontrolü nedeniyle yalnız hazırlama helper'ı farklı bir yerel bundle oluştu; public arşiv sabit tutuldu ve local staging yayınlanan arşiv/manifest'e göre hizalanmalıdır. Public GitHub API, [native-sources-0.5.0](https://github.com/aringm/rasathane-core/releases/tag/native-sources-0.5.0) kaynak artefaktının **244.061.209 byte** / SHA-256 `6f2d08d6634d43879a7d98e6af40cf4c126c5f9d6f8f908ce882f5d6aa272dbf` olduğunu doğruladı. Bu metadata ölçümü full byte readback değildir. `record-publication --url` remote arşivin tamamını diske yazmadan hash'ler; local/public SHA veya readback sırasında local makbuz değişirse yayın makbuzu üretmez. Ayrı `PUBLICATION-RECEIPT.json` doğrulaması `verify --release` içinde kalan `published_source_access` gate'ini kapatır. Kaynak artefaktı/manifest yeniden üretilmez; hazırlık makbuzundaki `source_offer_complete=false` staging kaydı korunur.

Piper kütüphanesi ile ses ağırlığının lisansı ayrı tutulur. [dfki medium model kartı](https://huggingface.co/rhasspy/piper-voices/blob/main/tr/tr_TR/dfki/medium/MODEL_CARD) eğitim veri seti için CC BY-NC-SA 4.0 bildirir. Bu ses yeni ticari dağıtıma alınmamıştır; eski kişisel dosyalar silinmez. Windows Türkçe sesleri işletim sisteminden kullanılır ve installer tarafından yeniden dağıtılmaz.

### Public kaynak readback ve Typst/PDF font eki

Son bağımsız yerel kontrolünde native `source-offer.py verify --release`: **32 kaynak / 237 lisans referansı, failures=[], release_blockers=[], publication_verified=true, source_offer_complete=true**. Public artefakt `6f2d...` ile sabit kaldı; root'un full-stream readback makbuzu local bundle/source/manifest hash'lerine bağlandı. Public metadata ile full-stream makbuzu aynı kanıt olarak sunulmaz.

Typst 0.15.1 Windows x64 CPU ZIP'i primary release digest'i `19ce3551153c2fe7ee9fa2f95208310c8f4d3209fedb699e0333faf8913f6736` ile pinlidir. Exact release commit `9dfd3a08500b7896045f907433cf7b4b02434fad`; LICENSE/NOTICE ve Rust 1.95.0 release recipe kaynak ekinde korunur. Executable içinde typst-assets 0.15.1'in **31 fontunun tam değişmemiş byte dizisi** bulundu. Gömülü yedi NewCM fontu exact upstream 8.1.1 dağıtımıyla byte-byte aynı. NewCM10-Regular GPL3 + FE/DE; diğer NewCM GUST/LPPL; Libertinus OFL; DejaVu Bitstream/Arev; Foxit PDFium BSD lisanslıdır.

Cargo.lock'taki **403 registry entry** license/checksum metadata'sı primary crates.io ile doğrulandı. Tek reciprocal Rust entry option-ext 0.2.0 MPL2.0; actual Windows kodda fonksiyon kaldığı varsayılmadı, exact küçük source crate ve full MPL metni yine sunuldu. resvg/usvg 0.47.0 Apache-2.0 OR MIT lisanslıdır. Envanter dev/build/diğer platform bağımlılıklarını da kapsar; exact Windows binary SBOM'u değildir.

PDF.js 6.3.289'un dört LiberationSans TTF name tablosu **1.07.4** gösterir; local byte'lar primary PDF.js commit `1c8020a7d4e43668ac287a3ecf9a8dbea17e4c56` ile aynı, primary README değişmemiş upstream release olduğunu kaydeder. Liberation 2.x OFL bu fontlara uygulanmaz. Preferred SFD source, Makefile `VER=1.07.4`, FontForge export script, AUTHORS/COPYING ve full font exception metni exact `dbeb786b4ede1eaec2ec5cb8d3b75d21641e2a35` kaynağından sunuldu. NewCM'nin preferred SFD source ve upstream FontForge build açıklaması exact `29149c0a75b5386c7e8ccc818a1ea6d2ca1e0128` commit'inden alındı. FontForge yeniden build veya byte-identical yeniden font üretimi denenmiş olarak ileri sürülmez.

Ayrı [Typst/PDF-font kaynak eki](https://github.com/aringm/rasathane-core/releases/download/native-sources-0.5.0/Rasathane-Typst-source-supplement-0.15.1.tar.gz) **25.302.608 byte / SHA-256 `2274abfae7787fcbda874d6f5214fb8dc493ecb2551e047885ca3b09e6900273`**. 790 source/notice dosyası hash doğrulamasını geçti; frozen build idempotence aynı SHA'yı korudu. Root full-stream readback makbuzu ayrı tutuldu; canonical `verify-source-supplement.py --release` bağımsız ölçümünde **publication_verified=true, source_offer_complete=true, failures=[]**, exit0. Eski 32 kaynaklık public artefakt/manifest değiştirilmedi; supplement manifest'leri ayrı adla yayımlandı.

Clean checkout kabulü için `restore-published-sources.py` exact public artefakt/manifest hash'lerini doğrular, tracked helper/dokümanları değiştirmeden staging'i geri kurar. Traversal, absolute/drive/backslash yolu, symlink/junction, duplicate ve mevcut farklı dosya guard'ları offline geçti. Gerçek local public artefaktlarda native **187** normal member, supplement **791** normal member restore validation ve idempotent restore geçti. Supplement 791'in biri kendi SOURCE-MANIFEST'idir; kaynak payload sayısı 790'dır. Mevcut dosyaların üzerine yazılmadı. İlk clean checkout'ta full uzaktan restore/build yapılmış olarak ileri sürülmez; source32 ve supplement public readback ile mevcut staging doğrulaması ayrı kanıttır.

## Production kabulünde açık adımlar

Private üyelik deploy'u, doğrulanmış installer/R2 nesnesi, actual artifact hash'i, gerçek signed download ve ödeme callback'i; managed feed worker URL/key; uygun ürün/veri işleme metinleri ve fiziksel 8 GB kullanıcı yolu ayrı kabul adımlarıdır. `RASATHANE_RELEASE_AT` bu adımlar tamamlanınca etkinleştirilmeli ve environment değişikliğinden sonra deployment yeniden üretilmelidir. Hazır olmayan macOS platformu unavailable kalır. Bu kayıttaki açık bulgular kapatılmadan genel ürün veya dağıtım için eksiksiz kabul verilmez.
