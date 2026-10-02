from __future__ import annotations

import glob
import tempfile
from pathlib import Path
from typing import Any

from ytcore.config import get_config
from ytcore.transcript.altyazi import altyazi_sec
from ytcore.transcript.fetcher import AltyaziSonuc, FetchMeta


def _ydl_opts(cfg: Any, ek: dict[str, Any]) -> dict[str, Any]:
    """Ortak yt-dlp opsiyonları: cookie + POT (opsiyonel env-hook) + rate-limit."""
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "sleep_interval_requests": 1,  # A01: HTTP 429 altyazı rate-limit azaltma
    }
    if cfg.cookies_browser:
        opts["cookiesfrombrowser"] = (cfg.cookies_browser,)
    if cfg.pot_base_url:
        # bgutil-ytdlp-pot-provider HTTP modu (Docker/Node) — opsiyonel.
        opts["extractor_args"] = {"youtubepot-bgutilhttp": {"base_url": [cfg.pot_base_url]}}
    opts.update(ek)
    return opts


def _extract(ydl: Any, url: str) -> dict[str, Any]:
    """extract_info çağır; yt-dlp bazı edge'lerde RAISE ETMEDEN None döner ('extractor
    returned nothing') → bunu net RuntimeError'a çevir ki graph graceful 'hata' yakalasın
    (re-review: ham dict(None) TypeError'ı re-raise listesine kaçıp pipeline'ı çökertiyordu)."""
    info = ydl.extract_info(url, download=False)
    if not info:
        raise RuntimeError("video bilgisi alınamadı (extractor boş döndü)")
    return dict(info)


class YtDlpFetcher:
    """Gerçek yt-dlp sarmalayıcı: metadata + altyazı-önce + ses indir."""

    def metadata(self, url: str) -> FetchMeta:
        import yt_dlp  # lazy: ağır import

        with yt_dlp.YoutubeDL(_ydl_opts(get_config(), {"skip_download": True})) as ydl:
            info = _extract(ydl, url)
        return FetchMeta(info=info)

    def altyazi(self, url: str) -> AltyaziSonuc | None:
        """Manuel altyazı (tr>tr-orig>en) → yoksa/VTT-yoksa otomatik altyazı; yoksa None.

        Manuel ÖNCE denenir (A01 #9371) ama manuel seçilen dilde VTT format YOKSA
        otomatik altyazıya düşülür (manuel-XOR-oto değil; M4). Altyazı 'var' demek
        için VTT içeriğinin gerçekten indirilebilmesi gerekir.

        İndirme yt-dlp'nin KENDİ alt-yazı indiricisiyle yapılır (manuel urllib.urlopen
        DEĞİL): yt-dlp proper client/header + retry/sleep ile timedtext rate-limit'ini
        (HTTP 429 — A01) yönetir; çıplak urllib güvenilmez biçimde 429 yiyordu (canlı kanıt).
        """
        import yt_dlp

        cfg = get_config()
        # Faz 6 (#1): videonun ORİJİNAL dilini (info["language"]) sapta → oto-çevrilmiş track
        # yerine ORİJİNALİ tercih et (en doğru kaynak; sonra TR'ye çevrilir). Saptanamazsa
        # default tr/en önceliği (graceful). extract_info sayfa-API'si 429-güvenli (429 yalnız
        # timedtext-CDN'deydi, o da yt-dlp indiricisinde yönetiliyor).
        orig: str | None = None
        try:
            with yt_dlp.YoutubeDL(_ydl_opts(cfg, {"skip_download": True})) as ydl:
                orig = (_extract(ydl, url).get("language") or "").strip() or None
        except Exception:  # noqa: BLE001 — dil saptanamadı → default öncelik
            orig = None
        diller: list[str] = []
        for d2 in ([orig] if orig else []) + ["tr", "tr-orig", "en", "en-US", "en-orig"]:
            if d2 and d2 not in diller:
                diller.append(d2)
        # TEK GEÇİŞ indirme (8c): yt-dlp'nin kendi indiricisi (header/retry/sleep → 429 dayanıklı;
        # ignoreerrors: bir dil 429 yese öbürü yazılır, kısmi başarı okunur).
        with tempfile.TemporaryDirectory() as d:
            ek: dict[str, Any] = {
                "skip_download": True,
                "writesubtitles": True,  # manuel altyazı (A01 #9371 — uploader orijinal-dil)
                "writeautomaticsub": True,  # yoksa otomatik altyazı
                "subtitleslangs": diller,  # orijinal dil BAŞTA
                "subtitlesformat": "vtt",
                "outtmpl": {"default": str(Path(d) / "%(id)s.%(ext)s")},
                "ignoreerrors": True,
                "retries": 5,
                "extractor_retries": 3,
            }
            try:
                with yt_dlp.YoutubeDL(_ydl_opts(cfg, ek)) as ydl:
                    ydl.download([url])
            except Exception:  # noqa: BLE001 — kısmi başarı kullan (yazılan VTT'ler okunur)
                pass
            # Yazılan VTT'leri dil → yol topla (<id>.<dil>.vtt).
            dosyalar: dict[str, str] = {}
            for p in glob.glob(str(Path(d) / "*.vtt")):
                parcalar = Path(p).name.rsplit(".", 2)  # [id, dil, "vtt"]
                if len(parcalar) == 3:
                    dosyalar.setdefault(parcalar[1], p)
            if not dosyalar:
                return None
            # Orijinal dil indiyse ONU seç (#1); yoksa tr>tr-orig>en; o da yoksa eldeki ilk.
            dil = (
                (orig if orig in dosyalar else None)
                or altyazi_sec(dosyalar.keys())
                or next(iter(dosyalar))
            )
            vtt = Path(dosyalar[dil]).read_text(encoding="utf-8", errors="replace")
            return AltyaziSonuc(vtt=vtt, dil=dil) if vtt.strip() else None

    def ses_indir(self, url: str, hedef_dir: Path) -> Path:
        """En iyi ses dosyasını indir; frozen ASR PyAV ile doğrudan çözer.

        Harici ffmpeg executable gerektiren postprocessor kullanılmaz. Mevcut
        developer ASR adapter'ı da dosya yolunu kabul eder.
        """
        import yt_dlp

        hedef = hedef_dir / "ses.%(ext)s"
        opts = _ydl_opts(
            get_config(),
            {
                "format": "bestaudio/best",
                "outtmpl": str(hedef),
            },
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        # PyAV desteklenen webm/m4a/mp4 dosyasını doğrudan okur; WAV zorunlu değil.
        wavs = list(hedef_dir.glob("ses.wav")) or list(hedef_dir.glob("ses.*"))
        if not wavs:
            raise RuntimeError("ses indirilemedi")
        return wavs[0]
