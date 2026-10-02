# Yerel model profilleri ve üretim referansı

Sahip: **Av. Mehmet Arın Gülüm**. Referans tarihi: 3 Ekim 2026.

Rasathane'nin temel paketi, geliştirme bilgisayarının kapasitesine bağımlı değildir. Yerel laboratuvar envanteri ve üretim rehberindeki model/runtime ayrımı, pinned model sürümü, hash doğrulaması ve aşamalar arasında bellek bırakma ilkeleri uygulandı.

| Alan | Rasathane temel profili | Geliştirme bilgisayarı referansı |
| --- | --- | --- |
| Donanım | Minimum hedef 8 GB RAM; gerçek donanım kabulü ayrıca gerekir | Xeon, 128 GB RAM, iki RTX 3090 |
| LLM | Gemma 4 E2B Q4; llama.cpp CPU, 4096 context, parallel=1 | Qwen 27B GGUF, büyük RAM offload modelleri; ürün paketine dahil edilmez |
| Embedding | BGE-M3 Q4, LLM ile aynı anda yüklenmez | Qwen embedding 0.6B/8B ve BGE-M3 envanteri |
| NER/ASR | Ayrı CPU worker; spawn öncesi anlık boş RAM denetimi | GPU laboratuvar runtime'larından bağımsız frozen ortam |
| Türkçe ses | Windows OneCore/SAPI; işletim sistemindeki ses | Chatterbox V3 MIT ve diğer üretim ses ortamları referans olarak incelendi |
| Kaynak izleme | Açık uygulamada, kayıtlı aralık ve Retry-After/backoff | Sürekli sistem servisleri kullanıcının makinesine gizlice eklenmez |

Model indirme kurulumu engine binary, NER/ASR ve büyük GGUF ağırlıkları için ayrı yürütülür. GGUF katalog revision/hash'leri sabittir; runtime modeli global laboratuvar klasörüne yazmaz. Önceden mevcut ve hash'i eşleşen GGUF yeniden indirilmeksizin kullanılabilir.

Kullanıcı notları ve analiz içeriği yerel saklanır. Web araması açık seçimle arama terimini sağlar; NER kişi tespitinde sağlayıcı sorgusu bloklanır. Cloud analiz, ücretli hesap ve kamu kaynağı edinimi ayrı sınırlar olarak belgelenir.

Varsayılan analiz klasörü uygulamanın `userData/workspace` alanıdır; Windows Belgeler klasörünün OneDrive yönlendirmesi otomatik seçilmez. Ayarlardan kullanıcı tarafından seçilen başka bir klasör korunur. Seçilen klasör bir senkronizasyon servisi kapsamındaysa dosyaları o servis eşitleyebilir. Önceden üretilmiş çıktılar taşınmaz veya silinmez.

Referanslar read-only incelendi: `D:/models/yerel-model-envanteri.json`, yerel üretim kullanım rehberi ve Yerel-Model-Laboratuvari/AGENTS.md. Laboratuvar baseline'ı, model cache'i, ComfyUI veya Hermes değiştirilmedi. İndirilmiş model, ölçülmüş kalite sonucu veya Rasathane'de doğrulanmış model seçeneği gibi gösterilmez.
