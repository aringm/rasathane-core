# Rasathane web font bildirimleri

Bu dizin web dağıtımının `public/font-licenses` alanıdır. Mevcut `next/font/google` kurulumu Inter, Cormorant Garamond ve IBM Plex Mono fontlarını build sırasında edinir ve kendi site dosyaları içinden sunar. Font yapılandırması veya CSS bu lisans çalışmasında değiştirilmedi.

3 Ekim 2026 production build'inin `.next/static/media/*.woff2` dosyalarının OpenType `name` tablosu okunmuştur. Build çıktısına özgü dosya adları, SHA256, boyut, sürüm ve copyright alanları `FONT-METADATA.json` içindedir; sonraki build'de asset adları değişebilir.

| Font                   | Gömülü sürüm         | Gömülü copyright bildirimi                                                         | Lisans                       |
| ---------------------- | -------------------- | ---------------------------------------------------------------------------------- | ---------------------------- |
| Inter                  | 4.001; git-66647c0bb | Copyright 2016 The Inter Project Authors (https://github.com/rsms/inter)           | `Inter-OFL.txt`              |
| Cormorant Garamond     | 4.001                | Copyright 2015 The Cormorant Project Authors (github.com/CatharsisFonts/Cormorant) | `Cormorant-Garamond-OFL.txt` |
| IBM Plex Mono / Medium | 2.3                  | Copyright 2017 IBM Corp. All rights reserved.                                      | `IBM-Plex-OFL.txt`           |

Her font SIL Open Font License 1.1 lisansıyla dağıtılır. Gömülü copyright satırları yukarıda korunmuştur. Google Fonts Inter lisans dosyasındaki 2020 copyright satırı ayrıca değişmeden korunur; bu, kullanılan subset'in gömülü 2016 kaydını kaldırmaz.

Birincil kaynaklar:

- [Inter · Google Fonts OFL](https://github.com/google/fonts/blob/main/ofl/inter/OFL.txt), [Inter upstream](https://github.com/rsms/inter).
- [Cormorant Garamond · Google Fonts OFL](https://github.com/google/fonts/blob/main/ofl/cormorantgaramond/OFL.txt), [Cormorant upstream](https://github.com/CatharsisFonts/Cormorant).
- [IBM Plex · IBM resmi OFL](https://github.com/IBM/plex/blob/master/LICENSE.txt).
- [Next.js · font optimizasyonu](https://nextjs.org/docs/app/getting-started/fonts).

Tam lisans metinleri 3 Ekim 2026'da birincil kaynaklardan değişmeden alınmıştır. Lisans dosyalarının SHA256 ve kaynak adresleri `LICENSE-SHA256.json` içindedir. Fontun orijinal CDN indirme adresi build metadata'sında bulunmadığında tahminle yazılmaz.
