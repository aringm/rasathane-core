from __future__ import annotations

import ipaddress
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# Masaüstü gözlem kökünün adı iki kez değişti. Yeni ad ilk sırada; kalanlar eskiden yeniye
# doğru legacy zinciri. "Rasathane  Gözlemevi" içindeki ÇİFT boşluk kasıtlıdır (Explorer'da
# okunaklı iki-satır etiket; muhakeme ailesi konvansiyonu — bkz. muhakeme-ictihat
# packaging/installer.iss DesktopName "Muhakeme   İçtihat").
GOZLEM_KOKU_ADI = "Rasathane  Gözlemevi"
GOZLEM_KOKU_LEGACY_ADLARI = ("Rasathane Gözlemleri", "Youtube Analizleri")


def _dolu_dizin_mi(p: Path) -> bool:
    """Var olan ve en az bir öğe içeren dizin mi? (yok/dosya/erişilemez → False)"""
    try:
        return p.is_dir() and any(p.iterdir())
    except OSError:
        return False


def _default_output_base() -> Path:
    """Yeni kurulum `Rasathane  Gözlemevi` ile başlar; mevcut kurulum kendi klasöründe kalır.

    Mevcut kullanıcı verisini görünmez biçimde iki köke bölme (#regresyon): karar VARLIĞA değil
    DOLULUĞA bakar. Yeni kök boşken (ör. elle açılmış) dolu bir legacy varsa, o legacy veri
    görünmez kalmasın diye legacy kök seçilir. Yeni kök doluysa legacy yok sayılır (göç bitti).
    Hiçbiri dolu değilse temiz kurulum → yeni ad. Tek köke sadeleştirme: `infra/gozlem-koku-goc.py`.
    """
    masaustu = Path.home() / "Desktop"
    yeni = masaustu / GOZLEM_KOKU_ADI
    if _dolu_dizin_mi(yeni):
        return yeni
    for eski in GOZLEM_KOKU_LEGACY_ADLARI:
        aday = masaustu / eski
        if _dolu_dizin_mi(aday):
            return aday
    return yeni


def ayarlar_yolu(output_base: Path) -> Path:
    """GUI Ayarlar sayfasının kalıcı ayar dosyası (output_base/_ayarlar.json)."""
    return output_base / "_ayarlar.json"


def _ayarlar_oku(output_base: Path) -> dict[str, object]:
    """Kalıcı GUI ayarlarını oku (best-effort: yok/bozuksa {}). Env değişkenleri HER ZAMAN
    öncelikli — dosya yalnız ilgili env yokken devreye girer (KVKK guard'ları korunur)."""
    try:
        p = ayarlar_yolu(output_base)
        if p.is_file():
            d = json.loads(p.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        pass
    return {}


def _normalize_host(host: str) -> str:
    """Ollama'nın şemasız env konvansiyonu (127.0.0.1:11434) httpx için http:// ister."""
    host = host.strip()
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    return host.rstrip("/")


def _loopback_host_mi(host: str) -> bool:
    """Host loopback (127.x/localhost/::1) mi? KVKK fail-closed (#1) — PII içerik yalnız
    yerel Ollama'ya gidebilir; uzak host = veri-çıkış riski."""
    try:
        hn = (urlparse(host).hostname or "").strip("[]").lower()
    except ValueError:
        return False
    if hn == "localhost":
        return True
    try:
        return ipaddress.ip_address(hn).is_loopback
    except ValueError:
        return False


def _venv_python_ara() -> str | None:
    """sys.executable konumundan ve cwd'den YUKARI yürüyerek bir `.venv` python'u bul.

    Frozen exe'de NER worker'ı koşacak ayrı env'i (transformers'lı) bulmak için (ASR/Piper
    emsali: ağır-runtime exe-DIŞI). YALNIZ VARLIK kontrolü (ucuz — get_config sık çağrılır);
    gerçek transformers probe'u kurulum_kontrol'de (ayrı, yavaş). Bulamazsa None.
    """
    rel = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    # GÜVENLİK (review HIGH path-traversal): YALNIZ sys.executable (güvenilen exe konumu) yukarı-
    # yürümesi. cwd KÖK DEĞİL — güvenilmez cwd'ye (ör. Downloads) konmuş sahte .venv keyfi-python
    # spawn'ı (KVKK fail-OPEN) açardı. Repo-dışı kurulumda YT_NER_PYTHON açık override şart.
    try:
        kok = Path(sys.executable).resolve().parent
    except OSError:
        return None
    for ata in (kok, *kok.parents):
        aday = ata / ".venv" / rel
        try:
            if aday.is_file():
                return str(aday.resolve())  # symlink dereference (review MED)
        except OSError:
            continue
    return None


def _venv_rel() -> Path:
    return Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")


def motor_kok_bul() -> Path | None:
    """NER/TTS worker'larının yaşadığı 'motor kökü' (repo: `.venv` + `core/ytcore` içerir).

    Kurulu (frozen) app AppData'dan motoru bulamaz → açık konumdan çöz; bulununca kurulu app de
    TAM ÖZELLİK olur (NER + sesli özet). Öncelik: env YT_MOTOR_KOK > _ayarlar.json 'motor_kok' >
    standart konum (~/Desktop/youtube-analiz-sistemi). Geçerli = `.venv/python` + `core/ytcore` var.
    """

    def _gecerli(p: Path) -> bool:
        try:
            return (p / ".venv" / _venv_rel()).is_file() and (p / "core" / "ytcore").is_dir()
        except OSError:
            return False

    env = os.environ.get("YT_MOTOR_KOK", "").strip()
    if env and _gecerli(Path(env)):
        return Path(env).resolve()
    try:
        base = os.environ.get("YT_OUTPUT_BASE", "").strip()
        ob = Path(base) if base else _default_output_base()
        ayar = _ayarlar_oku(ob).get("motor_kok")
        if isinstance(ayar, str) and ayar.strip() and _gecerli(Path(ayar)):
            return Path(ayar).resolve()
    except OSError:
        pass
    varsayilan = Path.home() / "Desktop" / "youtube-analiz-sistemi"
    if _gecerli(varsayilan):
        return varsayilan.resolve()
    return None


def motor_core_root() -> Path | None:
    """Worker PYTHONPATH'i için motor kökündeki `core/` (kurulu app'te exe-dışı gerçek repo)."""
    mk = motor_kok_bul()
    return mk / "core" if mk else None


def _ner_python_bul() -> str:
    """NER worker python'u: env YT_NER_PYTHON > motor_kok/.venv > frozen .venv oto-tespiti >
    sys.executable. motor_kok kurulu app'in repo motorunu bulmasını sağlar (tam özellik)."""
    acik = os.environ.get("YT_NER_PYTHON", "").strip()
    if acik:
        return acik
    mk = motor_kok_bul()
    if mk:
        return str((mk / ".venv" / _venv_rel()).resolve())
    if getattr(sys, "frozen", False):
        bulunan = _venv_python_ara()
        if bulunan:
            return bulunan
    return sys.executable


def _tts_python_bul() -> str:
    """Piper TTS worker python'u: env YT_TTS_PYTHON > motor_kok/.venv > frozen .venv oto-tespiti >
    sys.executable (NER ile aynı motor; tek `.venv` torch/transformers/piper taşır)."""
    acik = os.environ.get("YT_TTS_PYTHON", "").strip()
    if acik:
        return acik
    mk = motor_kok_bul()
    if mk:
        return str((mk / ".venv" / _venv_rel()).resolve())
    if getattr(sys, "frozen", False):
        bulunan = _venv_python_ara()
        if bulunan:
            return bulunan
    return sys.executable


def fiziksel_ram_gb() -> float:
    """Fiziksel RAM (GB) — model profili seçimi için. Windows: GlobalMemoryStatusEx;
    POSIX: sysconf. Okunamazsa muhafazakâr 8.0 döner (küçük profil seçilir)."""
    if sys.platform == "win32":
        try:
            import ctypes

            class _MEMSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            durum = _MEMSTATUSEX()
            durum.dwLength = ctypes.sizeof(_MEMSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(durum)):
                return float(durum.ullTotalPhys) / (1024**3)
        except (OSError, AttributeError, ValueError):
            pass
        return 8.0
    if sys.platform != "win32":
        try:
            sayfa_bayti = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            return float(sayfa_bayti) / (1024**3)
        except (OSError, ValueError, AttributeError):
            pass
    return 8.0


def llamacpp_motor_kok() -> Path | None:
    """Gömülü llama.cpp motor kökü (`llama-server.exe` + `modeller/` içerir).

    Öncelik: env RASATHANE_MOTOR_DIR (Electron paketli kurulumda resources/motor'u
    işaretler) > geliştirme reposu `infra/vendor/motor`. Yoksa None (Ollama fallback).
    """
    env = os.environ.get("RASATHANE_MOTOR_DIR", "").strip()
    adaylar: list[Path] = []
    if env:
        adaylar.append(Path(env))
    try:
        kok = Path(__file__).resolve().parents[2]  # repo kökü (core/ytcore/ → kök)
        adaylar.append(kok / "infra" / "vendor" / "motor")
    except (OSError, IndexError):
        pass
    for aday in adaylar:
        try:
            if aday.is_dir() and (aday / "modeller").is_dir():
                return aday
        except OSError:
            continue
    return None


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str | None
    ollama_host: str
    ollama_ping_model: str
    # Kuruluma gömülü llama.cpp backend'i. motor_backend: "auto" (gömülü motor varsa
    # llamacpp, yoksa ollama) | "llamacpp" | "ollama" (env YT_MOTOR_BACKEND).
    motor_backend: str
    llamacpp_host: str
    llamacpp_embed_host: str
    llamacpp_profil: str
    output_base: Path
    pot_base_url: str | None
    cookies_browser: str | None
    asr_python: str
    # Faz 2 içerik hattı modelleri (Ollama-HTTP, torch-free). bge-m3 (MIT) embedding;
    # qwen2.5:14b araştırma-doğrulanmış TR özet (TurkBench SM %75). map küçültülebilir.
    ollama_embedding_model: str
    ollama_ceviri_model: str
    ollama_map_model: str
    ollama_reduce_model: str
    ollama_judge_model: str
    # ≤16GB değişmezi (#2): num_ctx KV cache'i sınırlar. qwen2.5:14b@32K=17GB (tek 16GB
    # GPU'ya SIĞMAZ); @8K ~10-11GB sığar. Özet chunk'ları ~1-2K token → 8192 yeterli.
    ollama_num_ctx: int
    # Faz 3 zeka katmanı. Web search anahtarları env'den (hardcode YASAK); yoksa fact-check
    # web-sorgu inert (anahtarsız stub). Verdict/claim/bellek yeni model YOK (qwen2.5:14b
    # reuse — ≤16GB). eval-embedding = qwen3-emb (yalnız RETRIEVAL_RECALL A/B; bge-m3 primary).
    serper_api_key: str | None
    tavily_api_key: str | None
    # Faz 7: SearXNG self-hosted yerel web arama (anahtarsız; YT_SEARXNG_URL ile opt-in,
    # örn. http://127.0.0.1:8888). Set ise fact-check Serper yerine yerel SearXNG kullanır.
    searxng_url: str | None
    # Faz 7b: self-hosted Firecrawl yerel web arama (anahtarsız; VARSAYILAN 127.0.0.1:3002 —
    # kuruluysa otomatik kullanılır). YT_FIRECRAWL_URL ile override; YT_FIRECRAWL_URL="" ile kapat.
    firecrawl_url: str | None
    ollama_claim_model: str
    ollama_verdict_model: str
    ollama_memory_model: str
    ollama_eval_embedding_model: str
    index_base: Path
    kullanici_base: Path
    degerleme_agirliklari: dict[str, float]
    # Faz 4 üretim & sunum. cloud TTS anahtarı env'den (hardcode YASAK); yoksa inert. cloud
    # default KAPALI (PII-temiz için bile bilinçli YT_TTS_CLOUD=1 — KVKK). Piper voice
    # output_base altında (Piper = onnxruntime/CPU, exe-dışı). harita LLM = qwen2.5:14b reuse.
    openai_api_key: str | None
    tts_cloud_model: str
    tts_cloud_acik: bool
    piper_voice_dir: Path
    # Piper TTS AYRI PROSES (ASR/NER deseni — piper/onnxruntime exe-DIŞI; frozen GUI'de de
    # sentez çalışsın). YT_TTS_PYTHON ile ayrı env; frozen'da repo .venv oto-tespiti.
    tts_python: str
    harita_model: str
    # Faz 5 hibrit servis. NER ayrı-proses (ASR deseni — torch exe-DIŞI; YT_NER_PYTHON ile
    # ayrı env). anthropic_model: COMPLEX cloud verdict modeli (proje-planı A11: Sonnet 4.x).
    # cloud_verdict_acik: bilinçli opt-in (YT_CLOUD_VERDICT=1; TTS YT_TTS_CLOUD emsali — KVKK).
    ner_python: str
    anthropic_model: str
    cloud_verdict_acik: bool


def _motor_backend_sec(ayarlar: dict[str, object]) -> str:
    """LLM/embedding backend'i: "auto" (gömülü llama.cpp motoru varsa llamacpp, yoksa
    ollama) | "llamacpp" | "ollama". env YT_MOTOR_BACKEND > _ayarlar.json > auto."""
    _dosya = ayarlar.get("motor_backend")
    ham = (
        (
            os.environ.get("YT_MOTOR_BACKEND")
            or (str(_dosya) if isinstance(_dosya, str) and _dosya.strip() else "")
            or "auto"
        )
        .strip()
        .lower()
    )
    if ham not in ("auto", "ollama", "llamacpp"):
        return "auto"
    if ham == "auto":
        return "llamacpp" if llamacpp_motor_kok() is not None else "ollama"
    return ham


def _llamacpp_profil_sec(ayarlar: dict[str, object]) -> str:
    """RAM profili seçimi: env YT_LLAMACPP_PROFIL > _ayarlar.json > "auto".

    "auto"deki RAM+eşik ve dosya-varlığı çözümü ytcore.local.llamacpp.aktif_profil'de
    yapılır (paketli kurulumda yalnız ram8 seti gömülüdür — NSIS ~4GB sınırı; büyük-RAM
    makinede bile gömülü olmayan profile düşmemek için dosya varlığı şart).
    """
    _dosya = ayarlar.get("llamacpp_profil")
    ham = (
        (
            os.environ.get("YT_LLAMACPP_PROFIL")
            or (str(_dosya) if isinstance(_dosya, str) and _dosya.strip() else "")
        )
        .strip()
        .lower()
    )
    if ham in ("ram8", "ram16"):
        return ham
    return "auto"


def _loopback_zorla(host: str, degisken: str) -> str:
    """KVKK fail-closed (#1) — normalize + loopback guard (Ollama ile aynı kontrat)."""
    host = _normalize_host(host)
    if not _loopback_host_mi(host) and os.environ.get("YT_ALLOW_REMOTE_OLLAMA") != "1":
        raise ValueError(
            f"KVKK fail-closed: {degisken} loopback değil ({host}). PII içerik uzak "
            "host'a gidebilir. Yerel sunucu kullanın ya da bilinçli olarak "
            "YT_ALLOW_REMOTE_OLLAMA=1 ayarlayın (PII'nin uzak servise gitmesini kabul ederek)."
        )
    return host


def get_config() -> Config:
    base = os.environ.get("YT_OUTPUT_BASE", "").strip()
    output_base = Path(base) if base else _default_output_base()
    # GUI Ayarlar sayfası kalıcı ayarları (env her zaman önceliklidir).
    _ayarlar = _ayarlar_oku(output_base)
    # KVKK fail-closed (#1): tüm Faz 2 içerik (çeviri/özet/faithfulness/embedding) bu host'a
    # POST edilir. Loopback değilse PII uzak host'a sızar → bilinçli opt-in YOKsa REDDET
    # (deny-by-default; varsayılan değerle ima etmek yetmez — kod düzeyinde zorla).
    # host çözümü: env OLLAMA_HOST > _ayarlar.json > varsayılan (KVKK guard her durumda çalışır).
    _dosya_host = _ayarlar.get("ollama_host")
    _ham_host = (
        os.environ.get("OLLAMA_HOST")
        or (str(_dosya_host) if isinstance(_dosya_host, str) and _dosya_host.strip() else "")
        or "http://127.0.0.1:11434"
    )
    ollama_host = _normalize_host(_ham_host)
    if not _loopback_host_mi(ollama_host) and os.environ.get("YT_ALLOW_REMOTE_OLLAMA") != "1":
        raise ValueError(
            f"KVKK fail-closed: OLLAMA_HOST loopback değil ({ollama_host}). PII içerik uzak "
            "host'a gidebilir. Yerel Ollama kullanın ya da bilinçli olarak "
            "YT_ALLOW_REMOTE_OLLAMA=1 ayarlayın (PII'nin uzak servise gitmesini kabul ederek)."
        )
    # Gömülü llama.cpp backend'i — Ollama ile AYNI KVKK fail-closed kontratı (#1).
    llamacpp_host = _loopback_zorla(
        os.environ.get("YT_LLAMACPP_HOST") or "http://127.0.0.1:8077", "YT_LLAMACPP_HOST"
    )
    llamacpp_embed_host = _loopback_zorla(
        os.environ.get("YT_LLAMACPP_EMBED_HOST") or "http://127.0.0.1:8091",
        "YT_LLAMACPP_EMBED_HOST",
    )
    return Config(
        anthropic_api_key=(os.environ.get("ANTHROPIC_API_KEY") or None),
        ollama_host=ollama_host,
        # Faz 2: ping default kurulu modele çekildi (qwen3:8b makinede YOK; ping yine de
        # ping_modeli_sec ile mevcut modele düşer ama default doğru olmalı — faz2 promtu).
        ollama_ping_model=os.environ.get("OLLAMA_PING_MODEL", "qwen2.5:14b"),
        motor_backend=_motor_backend_sec(_ayarlar),
        llamacpp_host=llamacpp_host,
        llamacpp_embed_host=llamacpp_embed_host,
        llamacpp_profil=_llamacpp_profil_sec(_ayarlar),
        output_base=output_base,
        # Faz 1: POT opsiyonel env-hook (Docker yok kararı); cookie fallback; ASR ayrı proses.
        pot_base_url=(os.environ.get("YT_POT_BASE_URL") or None),
        cookies_browser=(os.environ.get("YT_COOKIES_BROWSER") or None),
        asr_python=(os.environ.get("YT_ASR_PYTHON") or sys.executable),
        ollama_embedding_model=os.environ.get("YT_EMBED_MODEL", "bge-m3"),
        ollama_ceviri_model=os.environ.get("YT_CEVIRI_MODEL", "qwen2.5:14b"),
        ollama_map_model=os.environ.get("YT_MAP_MODEL", "qwen2.5:14b"),
        ollama_reduce_model=os.environ.get("YT_REDUCE_MODEL", "qwen2.5:14b"),
        ollama_judge_model=os.environ.get("YT_JUDGE_MODEL", "qwen2.5:14b"),
        ollama_num_ctx=int(os.environ.get("YT_OLLAMA_NUM_CTX", "8192")),
        serper_api_key=(os.environ.get("SERPER_API_KEY") or None),
        tavily_api_key=(os.environ.get("TAVILY_API_KEY") or None),
        searxng_url=(os.environ.get("YT_SEARXNG_URL") or None),
        # Kuruluysa otomatik (default 127.0.0.1:3002); YT_FIRECRAWL_URL="" ile kapatılır.
        firecrawl_url=(os.environ.get("YT_FIRECRAWL_URL", "http://127.0.0.1:3002") or None),
        ollama_claim_model=os.environ.get("YT_CLAIM_MODEL", "qwen2.5:14b"),
        ollama_verdict_model=os.environ.get("YT_VERDICT_MODEL", "qwen2.5:14b"),
        ollama_memory_model=os.environ.get("YT_MEMORY_MODEL", "qwen2.5:14b"),
        ollama_eval_embedding_model=os.environ.get("YT_EVAL_EMBED_MODEL", "qwen3-embedding:8b"),
        index_base=output_base / "_index",
        kullanici_base=output_base / "_kullanici",
        degerleme_agirliklari={
            "novelty": 0.35,
            "rarity": 0.25,
            "nis": 0.20,
            "recency": 0.15,
            "length": 0.05,
        },
        openai_api_key=(os.environ.get("OPENAI_API_KEY") or None),
        tts_cloud_model=os.environ.get("YT_TTS_CLOUD_MODEL", "gpt-4o-mini-tts"),
        tts_cloud_acik=(os.environ.get("YT_TTS_CLOUD") == "1"),
        piper_voice_dir=(
            Path(p)
            if (p := os.environ.get("YT_PIPER_VOICE_DIR", "").strip())
            else output_base / "_models" / "piper"
        ),
        tts_python=_tts_python_bul(),
        harita_model=os.environ.get("YT_HARITA_MODEL", "qwen2.5:14b"),
        ner_python=_ner_python_bul(),
        anthropic_model=os.environ.get("YT_ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        cloud_verdict_acik=(os.environ.get("YT_CLOUD_VERDICT") == "1"),
    )
