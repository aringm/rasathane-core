# Rasathane masaüstü font bildirimleri

Bu dizin `gui/ui/**/*` dağıtım kapsamındadır. Font dosyaları değiştirilmedi; ayrı bir font ürünü olarak satılmaz. Uygulamanın kaynak lisansı, fontların SIL Open Font License 1.1 lisansının yerine geçmez.

3 Ekim 2026'da sekiz WOFF2 dosyasının OpenType `name` tablosu fontTools ile okundu. Dosya boyutu, SHA256 ve kimlik kayıtları `FONT-METADATA.json` içinde korunur. WOFF2 subset dosyalarında lisans metni name ID 13'te bulunmuyor; name ID 14, OFL lisans adresini taşıyor. Aşağıdaki ayrı lisans dosyaları bu nedenle pakete eklenmiştir.

| Kullanılan font        | Dosyalar                             | Gömülü sürüm | Gömülü copyright bildirimi                                                                         | Dağıtılan lisans        |
| ---------------------- | ------------------------------------ | ------------ | -------------------------------------------------------------------------------------------------- | ----------------------- |
| Space Grotesk          | `space-grotesk-latin*.woff2`         | 2.000        | Copyright 2020 The Space Grotesk Project Authors (https://github.com/floriankarsten/space-grotesk) | `Space-Grotesk-OFL.txt` |
| IBM Plex Sans          | `ibm-plex-sans-latin*.woff2`         | 3.201        | Copyright 2019 IBM Corp. All rights reserved.                                                      | `IBM-Plex-OFL.txt`      |
| IBM Plex Mono / Medium | `ibm-plex-mono-400/500-latin*.woff2` | 2.3          | Copyright 2017 IBM Corp. All rights reserved.                                                      | `IBM-Plex-OFL.txt`      |

Birincil lisans kaynakları:

- [Space Grotesk · Google Fonts OFL](https://github.com/google/fonts/blob/main/ofl/spacegrotesk/OFL.txt), [fontun upstream projesi](https://github.com/floriankarsten/space-grotesk).
- [IBM Plex · IBM resmi lisansı](https://github.com/IBM/plex/blob/master/LICENSE.txt). Lisans ilk satırı `Copyright © 2017 IBM Corp. with Reserved Font Name "Plex"` bildirimini korur; yerel Sans dosyasındaki ek 2019 bildirimi yukarıda ve metadata'da korunmuştur.

Bu dosyaların ilk indirme URL'leri eski projede kaydedilmemiştir. Dosya adından exact Google Fonts CDN URL'i veya font commit'i tahmin edilmez; family, sürüm, copyright ve OFL adresi gerçek font metadata'sıyla doğrulanmıştır. Tam lisans metinleri 3 Ekim 2026'da yukarıdaki birincil kaynaklardan değişmeden alınmıştır. SHA256 lisans makbuzları `LICENSE-SHA256.json` içindedir.
