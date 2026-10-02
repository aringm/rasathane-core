# Katkı

Sahip: **Av. Mehmet Arın Gülüm**.

Node 24 ve pnpm 11.23.0; Python 3.12 ve uv kullanılır. Manifest ile lockfile birlikte güncellenir. `codex/` dalından PR açılır; ana dala doğrudan commit yapılmaz. Stage edilecek dosyalar açıkça yazılır; `git add .`, `git add -A`, `git add --all` kullanılmaz.

Kaynak, kişisel veri ve runtime birbirinden ayrılır. `.env`, tokens, model ağırlıkları, DB, özel belgeler ve `.local` Git'e alınmaz. `.env.example` yalnız boş veya sentetik değerler içerir. Secret scan başarısızlığı genel allowlist ile susturulmaz.

Yeni özellik için anlamlı test ve gerçek kullanıcı akışı kanıtı gerekir. Kontrol dış servis/GPU/8 GB gerçek cihaz gerektiriyorsa çalıştırılmayan kapsam belirtilir. Başarılı build, ürün kabulü veya canlı yayın sayılmaz. Mimari değişiklik `docs/urun/MIMARI.md` ile birlikte güncellenir.

PR bağımsız review, güncel artifact SHA256 ve çalıştırma makbuzunu içerir. Duyuru/yayın için hedefte readback gerekir. Yalnız stdout veya hazırlanmış duyuru teslim kanıtı değildir.

Katkı, katkı sahibinin dağıtma hakkına sahip olduğu kodu kapsamalıdır. Muhakeme İçtihat'ın tescilli implementation'ı veya üçüncü taraf özel kodu bu depoya kopyalanmaz. Katkılar AGPL-3.0-or-later altında sunulur; ayrı lisans veya marka hakkı otomatik verilmez.
