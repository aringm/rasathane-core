# Rasathane dağıtım bileşenleri

Rasathane kaynak çekirdeği AGPL-3.0-or-later lisanslıdır. Bağımlılıkların ve model ağırlıklarının lisansları bağımsızdır; AGPL model dosyalarına yeniden lisans vermez.

| Bileşen | Sürüm / kaynak | Lisans / dağıtım |
| --- | --- | --- |
| Electron | 43.7.7 | MIT; Chromium bildirimleri paket içinde |
| llama.cpp CPU | b10599, commit 4a08fa29705b8177e332b134306566c2c4b95902 | MIT tam metin ve upstream copyright `licenses/upstream` altında; LLVM OpenMP bildirimi bin içinde |
| Typst Windows x64 CPU | 0.15.1, commit 9dfd3a08500b7896045f907433cf7b4b02434fad | Apache-2.0; exact LICENSE/NOTICE, Cargo bildirimleri ve gömülü font metinleri `vendor/tooling/typst-licenses` altında; ayrı kaynak eki aşağıda açıklanır |
| PDF.js / LiberationSans | pdfjs-dist 6.3.289; dört LiberationSans TTF 1.07.4 | PDF.js Apache-2.0; fontlar GPLv2 + Liberation font exception. OFL olarak yeniden etiketlenmez; exact preferred SFD kaynakları aynı ayrı source supplement'te sunulur |
| Türkçe NER | akdeniz27/bert-base-turkish-cased-ner, 99995f7d2be4b3a28c74f0d36ee97f8c04ee0571 | MIT |
| ASR | Systran/faster-whisper-small, 536b0662742c02347bc0e980a01041f333bce120 | MIT |
| Yerel LLM | unsloth/gemma-4-E2B-it-qat-GGUF, model-catalog.json revision | Apache-2.0 (Gemma 4); ilk kurulumda indirilir |
| Embedding | gpustack/bge-m3-GGUF, model-catalog.json revision | MIT; ilk kurulumda indirilir |
| PyTorch CPU | 2.8.0+cpu | BSD-3-Clause ve dağıtım bildirimleri |
| Transformers | 4.57.6 | Apache-2.0 |
| faster-whisper / CTranslate2 | worker uv.lock | MIT |
| PyAV | 18.0.0, commit 54a4395bb4cdd9cdd53ff6216c50b69f6475c13d | BSD-3-Clause wrapper; native bağımlılıklar ayrı lisanslıdır |
| FFmpeg / PyAV vendor | 8.1.2 / 8.1.2-1; manifest'te exact source/hash/configure | LGPL-3.0-or-later metadata; dahil x264/x265 GPL-2.0-or-later kapsamı ayrıca korunur |
| x264 / x265 | b35605ace3ddf7c1a5d67a2eb553f034aef41d55 / 4.2 | GPL-2.0-or-later; kaynak, copyright ve tam COPYING metinleri |
| MSYS2 runtime | GCC 16.1.0; libiconv 1.19; diğer recipe'ler source manifest'te | GCC runtime exception, LGPL, MIT/BSD ve Zlib metinleri; permissive DLL eşleme farkı provenance notudur |
| docxtpl / yake | 0.20.2 / 0.7.3 | LGPL-2.1-only / LGPLv3; exact source sdist'leri sunulur |
| certifi / orjson / tqdm | Sidecar ve worker SBOM sürümleri | MPL-2.0 kapsamındaki kaynaklar; orjson Apache/MIT ve tqdm MIT bildirimleri korunur |
| PyInstaller | 6.20.0 | GPLv2-or-later + bootloader exception; sidecar'a alınmış modüller için exact source sunulur |
| Windows Türkçe ses | İşletim sistemindeki OneCore/SAPI | Microsoft bileşeni; paket içinde yeniden dağıtılmaz |

`build-notices.py` sync edilmiş sidecar ve worker ortamından sürüm envanterini ve mevcut lisans metinlerini üretir. Paket bu bildirimleri `resources/licenses` altında taşır. Bu envanter kaynak provenance ve lisans incelemesini kolaylaştırır; otomatik bir hukuki uyumluluk kararı değildir.

`source-offer.py prepare/build` pinned native kaynaklarını ve tam upstream lisans metinlerini getirir; `source-offer-manifest.json` URL, SHA-256, revision ve bilinen provenance sınırlarını taşır. Yeniden üretim ve yayın kabulü [SOURCE-OFFER.md](SOURCE-OFFER.md) içindedir. Açık engeller varsa yerel kaynak artefaktı public binary yayınının tamamlandığını göstermez; `verify --release` başarısız olur. PyAV BSD ve FFmpeg metadata'sı GPL codec'lerini yeniden lisanslamaz.

Typst 0.15.1 için ayrı kaynak eki `vendor/source-supplement/typst-0.15.1` altında hazırlanır; yayınlanmış 32 kaynaklık native artefakt değiştirilmez. Ek; exact Typst ve typst-assets kaynaklarını, MPL-2.0 lisanslı option-ext 0.2.0 crate'ini ve gömülü yedi NewComputerModern 8.1.1 fontunun tercih edilen düzenleme biçimi olan SFD kaynaklarını içerir. Windows binary'de font byte'larının upstream ile aynı olduğu doğrulanmıştır. resvg/usvg 0.47.0 Apache-2.0 veya MIT lisanslıdır. option-ext, dirs-sys'in unconditional bağımlılığıdır; fonksiyon kullanımının Unix'e koşullu olması nedeniyle Windows executable'ına etkin kod olarak kaldığı ileri sürülmez. Küçük exact kaynak ve MPL metni yine sunulur.

Gömülü fontların lisansı Typst Apache lisansından ayrıdır: Libertinus OFL-1.1; DejaVu Bitstream/Arev; Foxit PDFium BSD; NewCM10-Regular GPL-3.0-or-later + Font Exception + Distribution Exception; diğer gömülü NewCM fontları GUST/LPPL-1.3c-or-later. Font Exception, değişmemiş fontun PDF'ye gömülmesinin belgenin lisansını değiştirmediğini belirtir. Distribution Exception, değişmemiş fontun GPL3-compatible programda dağıtılması koşuluyla programı font nedeniyle GPL yapmaz; fontun kaynak ve bildirim koşullarını kaldırmaz. Font source ve tam exception metinleri ek kaynak paketinde korunur. Upstream Typst LICENSE/NOTICE tek başına tüm gömülü fontların tam lisans metinlerini içermez; `typst-assets` NOTICE ve ayrı LPPL metni de installer'ın lisans dizinine alınır. Kaynak ekinin public URL/hash readback'i tamamlanmadan Typst içeren public binary yayını tamamlandı olarak kabul edilmez.

Cargo bildirim envanteri exact lock'taki 403 registry entry'sini kapsar; dev, build ve diğer platform bağımlılıklarını da içerdiğinden Windows binary'nin exact SBOM'u olarak sunulmaz. Tam lisans metinleri ve özgün copyright kaynakları hash'leriyle saklanır; sadece SPDX adlarından üretilmiş genel bildirim değildir.

PDF.js ile dağıtılan dört LiberationSans TTF'nin `name` tablosu 1.07.4 sürümünü belirtir; byte'ları pinned PDF.js primary commit'iyle aynı, upstream README bunları değişmemiş 1.07.4 release olarak tanımlar. Kaynak eki `liberationfonts/liberation-1.7-fonts` commit `dbeb786b4ede1eaec2ec5cb8d3b75d21641e2a35` kaynaklarını, FontForge export script'lerini ve Makefile'ını içerir. `LICENSE_LIBERATION`, GPLv2 ve tam exception metinleriyle korunur. Belgeye font gömme exception'ı fontun kendi kaynak sunma koşulunu kaldırmaz. Liberation 2.x OFL lisansı bu eski dört dosyaya uygulanmaz.

Gemma 4 lisansı: https://ai.google.dev/gemma/apache_2. Exact model revision'ın upstream kartı Apache-2.0 belirtir. Model kaynakları: https://huggingface.co/unsloth/gemma-4-E2B-it-qat-GGUF ve https://huggingface.co/gpustack/bge-m3-GGUF.

Önceki kurulumdaki `tr_TR-dfki-medium` ses ağırlığı ticari olmayan lisans nedeniyle yeni installer'a alınmaz. Kullanıcının eski kişisel dosyaları silinmez.

Piper Python/runtime bağımlılığı yeni CPU worker'dan kaldırılmıştır; Türkçe TTS Windows'ta kurulu OneCore/SAPI sesini kullanır. Eski Piper ve kişisel ses dosyaları bu değişiklikle silinmez.

Sahip: **Av. Mehmet Arın Gülüm**.
