# Yerel model profilleri ve üretim referansı

Sahip: **Av. Mehmet Arın Gülüm**. Referans tarihi: 3 Ekim 2026.

Rasathane'nin temel paketi, geliştirme bilgisayarının kapasitesine bağımlı değildir. Yerel laboratuvar envanteri ve üretim rehberindeki model/runtime ayrımı, pinned model sürümü, hash doğrulaması ve aşamalar arasında bellek bırakma ilkeleri uygulandı.

| Alan | Rasathane temel profili | Geliştirme bilgisayarı referansı |
| --- | --- | --- |
| Donanım | Minimum hedef 8 GB RAM; gerçek donanım kabulü ayrıca gerekir | Xeon, 128 GB RAM, iki RTX 3090 |
| LLM | Gemma 4 E2B Q4 GGUF ilk kurulum sihirbazında indirilir; llama.cpp CPU, 4096 context, parallel=1 | Qwen 27B GGUF, büyük RAM offload modelleri; ürün paketine dahil edilmez |
| Embedding | BGE-M3 Q4 GGUF ilk kurulum sihirbazında indirilir; LLM ile aynı anda yüklenmez | Qwen embedding 0.6B/8B ve BGE-M3 envanteri |
| NER/ASR | Modelleri ve frozen CPU worker installer içindedir; spawn öncesi anlık boş RAM denetimi | GPU laboratuvar runtime'larından bağımsız frozen ortam |
| Türkçe ses | Windows OneCore/SAPI; işletim sistemindeki ses | Chatterbox V3 MIT ve diğer üretim ses ortamları referans olarak incelendi |
| Kaynak izleme | Açık uygulamada, kayıtlı aralık ve Retry-After/backoff | Sürekli sistem servisleri kullanıcının makinesine gizlice eklenmez |

Native CPU motor binary'leri (`motor/bin`), NER/ASR modelleri, frozen worker ve sidecar installer içinde gelir. Kullanıcıdan ayrıca Python, uv veya Docker kurulumu istenmez. Büyük LLM ve embedding **GGUF ağırlıkları installer'a dahil değildir**; ilk kurulum sihirbazı yalnız pinned Gemma 4 E2B ve BGE-M3 dosyalarını kullanıcının onayıyla indirir. Yaklaşık 3,1 GB indirme ve en az 3,5 GB boş disk gereksinimi sihirbazda açıklanır. GGUF katalog revision, boyut ve SHA-256 değerleri sabittir; tam doğrulama bitmeden model hazır sayılmaz. Runtime global laboratuvar model klasörüne yazmaz; önceden mevcut ve hash'i eşleşen GGUF yeniden indirilmeksizin kullanılabilir. Bu makinedeki setup kontrolünde önceden mevcut iki GGUF'un hash'i doğrulandı ve yeniden indirme yapılmadan ready durumu okundu. Taze, tam 3,1 GB ağ indirmesi kabul testi yapılmış sayılmaz.

Kullanıcı notları ve analiz içeriği yerel saklanır. Web araması açık seçimle arama terimini sağlar; NER kişi tespitinde sağlayıcı sorgusu bloklanır. Cloud analiz, ücretli hesap ve kamu kaynağı edinimi ayrı sınırlar olarak belgelenir.

Varsayılan analiz klasörü uygulamanın `userData/workspace` alanıdır; Windows Belgeler klasörünün OneDrive yönlendirmesi otomatik seçilmez. Ayarlardan kullanıcı tarafından seçilen başka bir klasör korunur. Seçilen klasör bir senkronizasyon servisi kapsamındaysa dosyaları o servis eşitleyebilir. Önceden üretilmiş çıktılar taşınmaz veya silinmez.

Referanslar read-only incelendi: `D:/models/yerel-model-envanteri.json`, yerel üretim kullanım rehberi ve Yerel-Model-Laboratuvari/AGENTS.md. Laboratuvar baseline'ı, model cache'i, ComfyUI veya Hermes değiştirilmedi. İndirilmiş model, ölçülmüş kalite sonucu veya Rasathane'de doğrulanmış model seçeneği gibi gösterilmez.

## Paket ve donanım kabulünün kapsamı

0.5.0 dağıtımının doğrulanan temel seçeneği `ram8` CPU profilidir; ek GGUF modeli doğrulanmadan 16 GB profili kurulu/hazır gösterilmez. 128 GB geliştirme bilgisayarında gerçek paketli inference ve süreç ailesi bellek ölçümleri yapıldı; bunlar fiziksel **8 GB cihaz testi değildir**. Fiziksel 8 GB kabulü henüz yapılmadı.

Önceki private `e00a970` ve public `ccbded4` snapshot'larının uzak CI kontrolleri geçti. Son `6732bf4` smoke düzeltmesinde 31 Electron + 10 UI / 202 PDF kontrolü ve private uzak CI kontrolleri geçti; yeni public snapshot'ın kanıtı ayrı export ve uzak CI makbuzuyla tutulur. Python kaynağındaki 342 dosya değişmedi. İlk bağımsız kurulumun sandbox ACL hatası ve ardından eklenen installer izni ayrı kaydedilir. Son signed build, resmî ve genel kaynak native testleri, bağımsız kaynak/kapsam review'i, gerçek bağımsız kurulum ve eski kurulum emekliliği geçti. İki sabit GGUF modelinin mevcut dosyalarla kurulumu doğrulandı; sıfırdan tam model indirme yolu kabul edilmiş sayılmaz. R2 nesnesinin tamamı uzak boyut/SHA readback'iyle doğrulandı. Genel model doğruluğu, fiziksel 8 GB cihaz ve production üyelik/ödeme/indirme kabulü açık kalır.

Son ölçümler: resmî native akışta 1.656.680.448 byte, genel native akışta 3.606.454.272 byte, kurulu resmî akışta 1.673.105.408 byte süreç ailesi tepe working set. Her üç kapanışta owned süreç 0. Bu değerler 127,51 GiB RAM'li geliştirme bilgisayarındadır; fiziksel 8 GB kabulü false olarak kalır. Genel model kaynak dışı detay/kişisel yorum üretme sınırlılığıyla kullanılır; özgün kaynak ve model yorumu ayrıdır.
