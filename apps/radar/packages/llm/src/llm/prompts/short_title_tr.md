Aşağıdaki yabancı dildeki haber/makale başlığını **sade, modern Türkçeye** çevir.

Original (orijinal başlık):
```
{{title}}
```

Bağlam (kaynak ve kategori):
- Kaynak: {{source_name}}
- Kategori: {{category}}

KURALLAR:

1. **Sadece çeviri metnini döndür** — hiçbir başlık, açıklama, "Çeviri:", "Türkçe başlık:" gibi prefix kullanma.
2. **Maksimum 120 karakter** — orijinal uzunsa özetleyici çeviri yap, anlam korunsun.
3. **Modern Türkçe**: arkaik veya dini çağrışımlı kelime kullanma ("müşarünileyh", "işbu", "mahrem" gibi).
4. **Teknik terimler**: yerleşmiş Türkçe varsa onu kullan ("yapay zeka", "büyük dil modeli"); yoksa orijinali parantezsiz olduğu gibi tut ("Transformer", "MoE", "Outlines", "GitHub", "arXiv", "vLLM", "DeepSeek").
5. **Özel isim ve şirket adı çevrilmez**: Apple, OpenAI, Anthropic, Tencent Hunyuan, MiniMax, Sakana AI, ggml-org, Qwen, DeepSeek aynen kalır.
6. **Sayı/oran**: orijinal rakam ve birimi koru (ör. "%73", "$200M", "175B parametre").
7. **Çift dilli başlık** (zaten Türkçe içeriyor) ise → değişiklik yapma, orijinali döndür.
8. **Başlık zaten Türkçe** ise → orijinali aynen döndür (heuristik: TR-spesifik karakterler ı/ş/ğ/ç/ö var veya tamamı Türkçe sözcük).

ÇIKTI: **Tek satır, sadece çeviri metni.** Yorum yok, formatting yok.
