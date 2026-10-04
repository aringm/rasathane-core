# rasathane-web

rasathane.ai pazarlama sitesi. Next.js 16 (App Router) + React 19 + Tailwind CSS v4, pnpm ile yönetilir.

## Komutlar

```bash
pnpm dev      # geliştirme sunucusu (http://localhost:3000)
pnpm build    # production build (deploy öncesi mutlaka çalıştır)
pnpm lint     # eslint
```

## Yapı

- `src/app/page.tsx` — ana landing sayfası (tasarımın merkezi)
- `src/app/landing.css` — landing'e özel stiller
- `src/app/gizlilik/`, `src/app/kvkk/`, `src/app/iletisim/` — hukuki ve iletişim sayfaları (`legal.css` paylaşır)
- `src/app/layout.tsx` — kök layout, meta etiketleri, fontlar
- `src/app/manifest.ts`, `robots.ts`, `sitemap.ts` — PWA/SEO meta dosyaları
- Hukuki ve hesap açıklama sayfaları statik prerender olur; ana sayfa ve `/indir` güncel release durumunu server'da okur. Site içeriği Türkçedir.

## Git ve deploy akışı

- `main` → production (Vercel, otomatik deploy). Doğrudan `main`'e commit atma.
- Yeni çalışma: `main`'den dal aç → commit'le → push'la → PR aç.
- Her PR, Vercel üzerinde otomatik preview URL'i alır; görsel kontrolü preview üzerinden yap.
- Deploy: `main`'e merge. Vercel projesi: `rasathane-web` (bağlantı `.vercel/` içinde, gitignore'lıdır).

## Kurallar

- `.env*` dosyalarını asla commit etme (gitignore'da).
- Mevcut hukuki sayfa metinlerini (KVKK, gizilik) tasarım değişikliğinde koru; içerikleri değiştirme.
- Commit mesajları Türkçe, conventional prefix ile (`feat:`, `fix:`, `chore:`, `style:`).
