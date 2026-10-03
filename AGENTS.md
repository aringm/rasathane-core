# Rasathane — birleşik çalışma kökü

Sahip: **Av. Mehmet Arın Gülüm**. Kullanıcıya yönelik içerikler modern, sade Türkçedir.

## Kaynaklar ve kapsam

- `apps/desktop`: birleşik Rasathane 0.5.4; Electron 43, Python/FastMCP, SQLite/FTS, bağımsız frozen worker ve yerel analiz.
- `apps/radar`: eski hukuk + AI radarı; kaynak `rasathane/main`. İzleme, bülten, Stüdyo, derin GitHub/arXiv edinimi korunacak özelliklerdir.
- `apps/web`: Next.js pazarlama sitesi; kaynak `rasathane-web/redesign`. Altındaki AGENTS.md ayrıca geçerlidir.
- `docs/urun`: ürün planı, mimari, doğrulama ve yayın kayıtları. Yerel/özel envanter açık export'a alınmaz.

Yeni özellikler `core/rasathane/product` altında bağımsız uygulanır; `ytcore` analiz sözleşmesi korunur. Muhakeme İçtihat'ın tescilli kaynak kodu ve prompt'ları public AGPL çekirdeğe kopyalanmaz. Ücretli servisler açık protokolle entegre edilir.

## Git

- Ana remote `aringm/rasathane-core`; default branch `main`.
- Çalışma dalı `codex/rasathane-urun`. `main`/`master` üzerine doğrudan commit veya merge yapma.
- Özgün kaynak geçmişleri private çalışma deposunda subtree, `sources/*` ve `source-*` ref'leriyle korunur. Bu açık repo yalnız denetlenmiş source export'u içerir; özel geçmişi taşımaz.
- `git add -A`, `git add .`, `git add --all` yasaktır. Önce status incele, sonra dosyaları açıkça stage et.
- `.env`, runtime verileri, modeller, kurulum paketleri ve `.git/recovery` altındaki yerel kurtarma kayıtları commit edilmez.
- Kaynak kökeni SOURCE-MANIFEST.json ile izlenir. Özel kaynak ref'leri bu açık depoda bulunmaz. Değişiklikler feature branch ve PR üzerinden yapılır.
- Commit mesajları Türkçe, conventional prefix ile yazılır.

## Doğrulama

- Desktop: `apps/desktop` içinde `uv sync --frozen --group content --group intel`, `uv run --frozen --group content --group intel pytest -q`, Ruff ve strict mypy; GUI'de `pnpm check`. Gerçek ağ/GPU/cloud testleri kendi marker'larıyla ayrıca çalıştırılır. UI → IPC → frozen sidecar → kalıcı sonuç yolu paket üzerinde doğrulanır.
- Web: `apps/web` içinde `pnpm lint`, `pnpm build`. Hukuki metinler korunur. Tasarım değişiklikleri mevcut web PR'ı/preview akışıyla doğrulanır.
- Radar: kendi uv workspace ve PostgreSQL/Redis ihtiyacı vardır. Masaüstü runtime'ıyla karıştırma; yalnız inventory/test amacıyla servis başlatma.
- Kullanıcı akışı görülmeden uygulamanın bütünü için “çalışıyor” denmez.
- Hermes yollarına hiçbir yazma işlemi yapılmaz.
- Worker ve paket staging kaynak checkout içinde kalır. Kullanıcı DB'leri, kişisel çıktılar ve model depoları cleanup'a dahil edilmez. Yeni ürün kabul edilmeden eski kurulumlar kaldırılmaz.
- Root CI Windows/Linux, frozen lock, pinned action SHA, secret scan kullanır. Yayında bağımsız review, güncel artifact hash'i, test makbuzu ve uzak readback gerekir.
