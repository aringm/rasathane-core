"""Gömülü llama.cpp backend'i — llama-server yaşam döngüsü + OpenAI-uyumlu istemci.

Kurulum (NSIS) `motor/` altında llama-server.exe + GGUF modelleri taşır; Ollama kurulumu
GEREKMEZ. İki ayrı sunucu prosesi koşar (llama-server proses başına tek model yükler):

- LLM sunucusu    : /v1/chat/completions (çeviri/özet/judge/verdict/harita)
- Embedding sunucusu: /v1/embeddings (bge-m3 GGUF — segmentasyon/keyword/indeks)

KVKK fail-closed (#1): host çözümü config'te loopback'e zorlanır; sunucu her durumda
yalnız 127.0.0.1'e bind edilir. torch/transformers IMPORT ETMEZ (#2 değişmez).

RAM profilleri (setup'a ram8 gömülür — NSIS ~4GB mmap sınırı; ram16 dev/manuel indirilir):

- ram8  ( <12 GB): Gemma 4 E2B-it QAT UD-Q4_K_XL (2.6GB) + bge-m3 Q4_K_M (0.44GB)
- ram16 (≥12 GB): Gemma 4 12B-it QAT UD-Q4_K_XL (6.7GB) + bge-m3 Q8_0 (0.63GB)

QAT (Quantization-Aware Training) sayesinde int4 GGUF, BF16'ya yakın kalite korur
(Unsloth/Google Gemma 4 QAT notları). Gemma chat şablonu system rolünü DESTEKLEMEZ —
istemci sistem prompt'unu ilk kullanıcı turuna katlar (template hatası önlenir).
"""

from __future__ import annotations

import atexit
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

import httpx

from ytcore.config import get_config, llamacpp_motor_kok

# Profil → model dosya adları. Dosya adları infra/fetch-motor.ps1 ile BİREBİR aynı olmalı.
# NOT (NSIS ~4GB mmap sınırı): installer'a yalnız ram8 seti gömülür (package.json
# extraResources filter). ram16 seti fetch-motor.ps1 -Profil ram16 ile dev/manuel kuruluma
# iner; uygulama-içi yükseltme indirmesi roadmap'tedir.
PROFILLER: dict[str, dict[str, str | int]] = {
    "ram8": {
        "llm_dosya": "gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf",
        "embed_dosya": "bge-m3-Q4_K_M.gguf",
        "num_ctx": 4096,
    },
    "ram16": {
        "llm_dosya": "gemma-4-12B-it-qat-UD-Q4_K_XL.gguf",
        "embed_dosya": "bge-m3-Q8_0.gguf",
        "num_ctx": 8192,
    },
}

_SAGLIK_ZAMAN_ASIMI_SN = 2.0
# CPU'da 4-7GB GGUF yükleme + ısınma; yavaş disk/makine payı bırakılır.
_ACILIS_ZAMAN_ASIMI_SN = 240.0
_ISTEK_ZAMAN_ASIMI_SN = 900.0  # CPU çıkarımı uzun sürebilir (12B özet/map-reduce)

_kilit = threading.Lock()
_cikarim_kilidi = threading.RLock()
_generation_profile: ContextVar[str | None] = ContextVar("generation_profile", default=None)
# tur ("llm"/"embed") → bu proseste başlatılan llama-server Popen'i
_prosesler: dict[str, subprocess.Popen[bytes]] = {}
_aktif_hostlar: dict[str, str] = {}
# Yalnız bu sürecin başlattığı modelin dosya/profil/context kimliği. Dosya değiştirilince
# yeni istek eski mmap'i yeniden kullanmaz; GGUF'nin tamamı her istekte hash'lenmez.
_model_fingerprints: dict[str, tuple[str, str, int, int, int]] = {}
_son_kullanilan_modeller: dict[str, dict[str, object]] = {}
# tur → açık log dosyası handle'ı (sunucu stdout+stderr buraya akar; _prosesleri_kapat kapatır)
_log_handlelari: dict[str, object] = {}


def _sunucu_log_yolu(tur: str) -> Path | None:
    """llama-server stdout/stderr logu — gözlebilirlik (2026-08-24 saha dersi: sunucu
    DEVNULL'a akıyordu, embed 500'ün kök nedeni görünemiyordu). Motor kökü/logs/ altına
    append-modda yazılır; motor kökü yoksa None (çağıran DEVNULL'a düşer — graceful)."""
    kok = llamacpp_motor_kok()
    if kok is None:
        return None
    try:
        log_dizin = Path(os.environ.get("RASATHANE_LOG_DIR", str(kok / "logs")))
        log_dizin.mkdir(parents=True, exist_ok=True)
        return log_dizin / f"llama-server-{tur}.log"
    except OSError:
        return None


def aktif_profil() -> str:
    """Çalıştırılacak profili çöz: açık seçim (env/ayar) > auto.

    auto: fiziksel RAM'in önerdiği en güçlü profil — AMA model dosyaları motor kökünde
    mevcutsa. Paketli kurulumda yalnız ram8 seti gömülüdür (NSIS sınırı); 16GB+ makinede
    bile ram16 dosyaları yoksa ram8'e düşer (paket içi tutarlılık garantisi).
    """
    secim = _generation_profile.get() or get_config().llamacpp_profil
    if secim in PROFILLER:
        return secim
    from ytcore.config import fiziksel_ram_gb  # monkeypatch dostu (test: ytcore.config)

    tercih = "ram16" if fiziksel_ram_gb() >= 12.0 else "ram8"
    kok = llamacpp_motor_kok()
    if kok is not None:
        sira = [tercih] + [p for p in PROFILLER if p != tercih]
        for aday in sira:
            if all(
                (kok / "modeller" / str(PROFILLER[aday][anahtar])).is_file()
                for anahtar in ("llm_dosya", "embed_dosya")
            ):
                return aday
    return tercih  # dosyalar hiç yoksa _model_yolu anlaşılır hata verir


def profil_bilgisi(profil: str | None = None) -> dict[str, str | int]:
    """Aktif (veya verilen) profilin model dosyaları ve ctx sınırı.

    profil=None ya da "auto" → aktif_profil() (RAM + dosya varlığı duyarlı).
    """
    ad = profil or "auto"
    if ad not in PROFILLER:
        if ad != "auto":
            raise ValueError(f"Bilinmeyen llama.cpp profili: {ad} (beklenen: {sorted(PROFILLER)})")
        ad = aktif_profil()
    return PROFILLER[ad]


def _host_coz(tur: str) -> str:
    if tur in _aktif_hostlar:
        return _aktif_hostlar[tur]
    cfg = get_config()
    return cfg.llamacpp_host if tur == "llm" else cfg.llamacpp_embed_host


def _model_yolu(tur: str) -> Path:
    kok = llamacpp_motor_kok()
    if kok is None:
        raise FileNotFoundError(
            "Gömülü llama.cpp motoru bulunamadı (RASATHANE_MOTOR_DIR veya "
            "infra/vendor/motor). Geliştirme için infra/fetch-motor.ps1 çalıştırın ya da "
            "YT_MOTOR_BACKEND=ollama ile Ollama'ya dönün."
        )
    dosya = str(profil_bilgisi()[f"{tur}_dosya"])
    yol = kok / "modeller" / dosya
    if not yol.is_file():
        raise FileNotFoundError(
            f"Model dosyası eksik: {yol} — infra/fetch-motor.ps1 -Profil "
            f"{get_config().llamacpp_profil} ile indirin."
        )
    return yol


def _sunucu_bin() -> Path:
    acik = os.environ.get("YT_LLAMACPP_BIN", "").strip()
    if acik:
        return Path(acik)
    kok = llamacpp_motor_kok()
    if kok is None:
        raise FileNotFoundError("Gömülü llama.cpp motoru bulunamadı — llama-server.exe çözülemedi.")
    exe = kok / "bin" / "llama-server.exe"
    if not exe.is_file():
        raise FileNotFoundError(
            f"llama-server.exe eksik: {exe} — infra/fetch-motor.ps1 çalıştırın."
        )
    return exe


def sunucu_saglikli_mi(host: str, timeout: float = _SAGLIK_ZAMAN_ASIMI_SN) -> bool:
    """llama-server /health 200 mü? (loopback; kısa zaman aşımı)

    motor_raporu gibi salt-gözlem çağrılar daha kısa timeout geçirir (beklemek değil,
    anlık durumu yansıtmak amaç — test/paketli ortamda kapalı port 2s bekletmez).
    """
    try:
        yanit = httpx.get(f"{host}/health", timeout=timeout, trust_env=False)
        return yanit.status_code == 200
    except httpx.HTTPError:
        return False


def sunucu_model_kimligi(host: str, timeout: float = _SAGLIK_ZAMAN_ASIMI_SN) -> str | None:
    """Sağlıklı port tek başına yeterli değil: OpenAI models endpoint'ini doğrula."""
    try:
        yanit = httpx.get(f"{host}/v1/models", timeout=timeout, trust_env=False)
        if yanit.status_code != 200 or len(yanit.content) > 64 * 1024:
            return None
        veri = yanit.json()
        modeller = veri.get("data") if isinstance(veri, dict) else None
        if not isinstance(modeller, list) or len(modeller) != 1:
            return None
        model = modeller[0]
        kimlik = model.get("id") if isinstance(model, dict) else None
        return kimlik if isinstance(kimlik, str) and 0 < len(kimlik) <= 2048 else None
    except (httpx.HTTPError, ValueError):
        return None


def _model_adi(kimlik: str) -> str:
    return kimlik.replace("\\", "/").rsplit("/", 1)[-1].casefold()


def _model_fingerprint(tur: str) -> tuple[str, str, int, int, int]:
    model = _model_yolu(tur).resolve()
    bilgi = model.stat()
    return (
        str(model),
        aktif_profil(),
        int(profil_bilgisi()["num_ctx"]),
        bilgi.st_size,
        bilgi.st_mtime_ns,
    )


def _koken_kaydet(tur: str, host: str, kimlik: str, owned: bool) -> None:
    fingerprint = _model_fingerprints.get(tur) if owned else None
    _son_kullanilan_modeller[tur] = {
        "host": host,
        "verified_model_id": kimlik,
        "ownership": "owned" if owned else "external",
        "requested_profile": aktif_profil(),
        "num_ctx_verified": fingerprint[2] if fingerprint else None,
        "model_path": fingerprint[0] if fingerprint else None,
        "model_size": fingerprint[3] if fingerprint else None,
        "model_mtime_ns": fingerprint[4] if fingerprint else None,
    }


def _bos_port_sec(taban: int) -> int:
    """Taban porttan başlayarak ilk boş loopback portunu bul (10 deneme)."""
    for ofset in range(10):
        port = taban + ofset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"llama-server için boş port bulunamadı (taban: {taban}).")


def _host_port_ayristir(host: str) -> tuple[str, int]:
    from urllib.parse import urlparse

    u = urlparse(host)
    return (u.hostname or "127.0.0.1", u.port or 8077)


def sunucu_baslat_gerekirse(
    tur: str,
    *,
    check: Callable[[], None] | None = None,
    startup_timeout: float | None = None,
) -> str:
    """İstenen türde (llm/embed) sağlıklı sunucu yoksa başlat; host URL'sini döndür.

    - Dış sunucu yalnız /v1/models beklenen model dosyasını doğrularsa kullanılır.
    - Port meşgul ama sağlıksızsa (başka uygulama) taban+ofset ile boş porta geçer.
    - Bu proseste başlatılan sunucular atexit ile kapatılır; Electron paketinde sidecar
      ağacı taskkill /T ile öldüğü için çocuklar da temizlenir (yetim kalmaz).
    """
    if tur not in {"llm", "embed"}:
        raise ValueError(f"Bilinmeyen model türü: {tur}")
    if check:
        check()
    with _kilit:
        profil = aktif_profil()
        beklenen = str(PROFILLER[profil][f"{tur}_dosya"])
        if profil == "ram8":
            # Model değişiminde yalnız bize ait karşı model unload edilir.
            # Bu kontrol hedef sunucu zaten sağlıklı olsa da uygulanır.
            _proses_kapat("embed" if tur == "llm" else "llm")
        host = _host_coz(tur)
        mevcut = _prosesler.get(tur)
        yeniden_baslat = False
        if mevcut is not None:
            try:
                ayni_dosya = _model_fingerprints.get(tur) == _model_fingerprint(tur)
            except FileNotFoundError:
                _proses_kapat(tur)
                raise
            if mevcut.poll() is not None or not ayni_dosya:
                _proses_kapat(tur)
                yeniden_baslat = True
                mevcut = None
        if not yeniden_baslat and sunucu_saglikli_mi(host):
            kimlik = sunucu_model_kimligi(host)
            if kimlik is not None and _model_adi(kimlik) == _model_adi(beklenen):
                _koken_kaydet(tur, host, kimlik, mevcut is not None)
                return host
            # Yalnız bize ait yanlış model kapatılır; yabancı port sahibine dokunulmaz.
            if mevcut is not None:
                _proses_kapat(tur)
                mevcut = None
        if mevcut is None:
            _, taban_port = _host_port_ayristir(host)
            port = _bos_port_sec(taban_port)
            host = f"http://127.0.0.1:{port}"
            fingerprint = _model_fingerprint(tur)
            model = Path(fingerprint[0])
            bin_yolu = _sunucu_bin()
            from ytcore.local.resources import require_memory

            require_memory(fingerprint[3] + (640 * 1024**2 if tur == "llm" else 256 * 1024**2))
            komut = [
                str(bin_yolu),
                "--model",
                str(model),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--ctx-size",
                str(fingerprint[2]),
                "--no-webui",
            ]
            if tur == "embed":
                komut.append("--embeddings")
            if profil == "ram8":
                komut += ["--parallel", "1", "--n-gpu-layers", "0"]
            olusturma_bayraklari = 0
            if sys.platform == "win32":
                olusturma_bayraklari = subprocess.CREATE_NO_WINDOW
            log_yolu = _sunucu_log_yolu(tur)
            log_handle = open(log_yolu, "ab") if log_yolu is not None else None  # noqa: SIM115
            try:
                _prosesler[tur] = subprocess.Popen(  # noqa: S603
                    komut,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle if log_handle is not None else subprocess.DEVNULL,
                    stderr=subprocess.STDOUT if log_handle is not None else subprocess.DEVNULL,
                    creationflags=olusturma_bayraklari,
                )
            except OSError:
                if log_handle is not None:
                    log_handle.close()
                raise
            if log_handle is not None:
                _log_handlelari[tur] = log_handle
            _aktif_hostlar[tur] = host
            _model_fingerprints[tur] = fingerprint
        # Kilit hazır olana dek tutulur: başka thread karşı modeli açıp ram8 sınırını
        # aşamaz ve yüklenmekte olan sunucuyu hazır sanıp kullanamaz.
        deadline_seconds = (
            startup_timeout if startup_timeout is not None else _ACILIS_ZAMAN_ASIMI_SN
        )
        son = time.monotonic() + deadline_seconds
        while time.monotonic() < son:
            if check:
                try:
                    check()
                except Exception:
                    _proses_kapat(tur)
                    raise
            if sunucu_saglikli_mi(host):
                kimlik = sunucu_model_kimligi(host)
                if kimlik is not None and _model_adi(kimlik) == _model_adi(beklenen):
                    _koken_kaydet(tur, host, kimlik, True)
                    return host
                _proses_kapat(tur)
                raise RuntimeError(f"llama-server ({tur}) yüklenen model kimliği doğrulanamadı.")
            proc = _prosesler.get(tur)
            if proc is not None and proc.poll() is not None:
                kod = proc.returncode
                _proses_kapat(tur)
                raise RuntimeError(f"llama-server ({tur}) çıkış kodu {kod} ile kapandı.")
            time.sleep(0.5)
        _proses_kapat(tur)
        raise TimeoutError(f"llama-server ({tur}) {deadline_seconds:.0f}s içinde hazır olmadı.")


@contextmanager
def generation_session(check: Callable[[], None], *, profile: str | None = None) -> Iterator[str]:
    """Gündem gibi stream istemcileri için iptal edilebilir, sınırlı çıkarım lease'i."""
    if profile not in {None, "auto", "ram8", "ram16"}:
        raise ValueError("Bilinmeyen yerel model profili.")
    deadline = time.monotonic() + 90
    while not _cikarim_kilidi.acquire(timeout=0.25):
        check()
        if time.monotonic() >= deadline:
            raise TimeoutError("Yerel model başka bir işlemde; gündem sonraki aralıkta denenecek.")
    token = _generation_profile.set(profile)
    try:
        check()
        yield sunucu_baslat_gerekirse("llm", check=check, startup_timeout=90)
    finally:
        _generation_profile.reset(token)
        _cikarim_kilidi.release()


def _proses_kapat(tur: str) -> None:
    proc = _prosesler.get(tur)
    if proc is not None:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                except OSError:
                    pass
        _prosesler.pop(tur, None)
        _aktif_hostlar.pop(tur, None)
        _model_fingerprints.pop(tur, None)
        handle = _log_handlelari.pop(tur, None)
        if handle is not None:
            try:
                handle.close()  # type: ignore[attr-defined]
            except OSError:
                pass


def _prosesleri_kapat() -> None:
    with _cikarim_kilidi, _kilit:
        for tur in list(_prosesler):
            _proses_kapat(tur)


atexit.register(_prosesleri_kapat)


def motor_raporu() -> dict[str, object]:
    """Analizde kullanılan motorun köken raporu — 00_index.json + GUI 'Teknik' bölümüne yazılır.

    Kullanıcı isteği (2026-08-24): hangi LLM/embedding modeli, hangi profil, hangi araç
    görünür olmalı. llamacpp'te değerler config + profil tablosundan (dosya-varlığı duyarlı)
    okunur; sunucuların o AN ayakta olup olmadığı '*_saglikli' bayraklarıyla yansıtılır
    (her biri ≤2s'lik loopback sağlık sorgusu — output node'da bir kez çağrılır).
    """
    cfg = get_config()
    if cfg.motor_backend != "llamacpp":
        return {
            "backend": "ollama",
            "ollama_host": cfg.ollama_host,
            "llm_model": cfg.ollama_reduce_model,
            "embedding_model": cfg.ollama_embedding_model,
            "num_ctx": cfg.ollama_num_ctx,
        }
    profil = aktif_profil()
    bilgi = PROFILLER[profil]
    kok = llamacpp_motor_kok()
    llm_kimligi = sunucu_model_kimligi(_host_coz("llm"), timeout=0.4)
    embed_kimligi = sunucu_model_kimligi(_host_coz("embed"), timeout=0.4)
    return {
        "backend": "llamacpp",
        "profil": profil,
        "llm_model": str(bilgi["llm_dosya"]),
        "embedding_model": str(bilgi["embed_dosya"]),
        "num_ctx": int(bilgi["num_ctx"]),
        "llm_host": _host_coz("llm"),
        "embed_host": _host_coz("embed"),
        "motor_kok": str(kok) if kok is not None else None,
        "llm_saglikli": sunucu_saglikli_mi(_host_coz("llm"), timeout=0.4),
        "embed_saglikli": sunucu_saglikli_mi(_host_coz("embed"), timeout=0.4),
        "llm_yuklu_model": llm_kimligi,
        "embed_yuklu_model": embed_kimligi,
        "llm_koken": dict(_son_kullanilan_modeller.get("llm", {})),
        "embed_koken": dict(_son_kullanilan_modeller.get("embed", {})),
    }


def _mesajlari_hazirla(sistem: str, kullanici: str, model: str) -> list[dict[str, str]]:
    """Gemma chat şablonu system rolünü desteklemez → sistem prompt'unu kullanıcı turuna
    katla (llama-server jinja template hatasını önler). Diğer modellerde roller korunur."""
    if "gemma" in model.lower():
        birlesik = f"{sistem.strip()}\n\n{kullanici.strip()}" if sistem.strip() else kullanici
        return [{"role": "user", "content": birlesik}]
    return [
        {"role": "system", "content": sistem},
        {"role": "user", "content": kullanici},
    ]


class LlamaCppLLM:
    """llama-server chat — OllamaLLM ile aynı `uret` kontratı (torch-free, #2 değişmez).

    Düşük sıcaklık (tutarlılık). Model adı sunucuya bilgi amaçlı gider (tek model yüklü);
    asıl seçim profil + sunucu başlatmada yapılır.
    """

    def __init__(
        self, model: str | None = None, host: str | None = None, num_ctx: int | None = None
    ) -> None:
        cfg = get_config()
        self.model = model or str(profil_bilgisi(cfg.llamacpp_profil)["llm_dosya"])
        self.host = host or cfg.llamacpp_host
        self.num_ctx = num_ctx or int(profil_bilgisi(cfg.llamacpp_profil)["num_ctx"])

    def uret(self, sistem: str, kullanici: str, *, model: str | None = None) -> str:
        # Karşı model ancak HTTP çıkarımı tamamlandıktan sonra unload edilebilir.
        with _cikarim_kilidi:
            return self._uret(sistem, kullanici, model=model)

    def _uret(self, sistem: str, kullanici: str, *, model: str | None = None) -> str:
        secilen = model or self.model
        cfg_host = get_config().llamacpp_host
        managed = self.host == cfg_host
        host = sunucu_baslat_gerekirse("llm") if managed else self.host
        # Katlama kararı İSTEKTEKİ model adına değil SUNUCUDA YÜKLÜ modele bakar: llamacpp
        # backend'inde node'lar Ollama model adı geçirebilir ("qwen2.5:14b" — config reuse);
        # sunucuda her zaman profilin Gemma'sı yüklüdür → system-rolü HER ZAMAN katlanır
        # (aksi: ad "gemma" içermeyince system rolü sızar, template-uyumsuzluğu riski).
        sunucu_modeli = str(profil_bilgisi(get_config().llamacpp_profil)["llm_dosya"])
        yanit = httpx.post(
            f"{host}/v1/chat/completions",
            json={
                "model": secilen,
                "messages": _mesajlari_hazirla(sistem, kullanici, sunucu_modeli),
                "temperature": 0.2,
                "max_tokens": min(self.num_ctx, int(profil_bilgisi()["num_ctx"]))
                if managed
                else self.num_ctx,
                # Gemma 4 reasoning modelidir: thinking açık kalırsa üretim reasoning_content'e
                # gider ve content BOŞ döner (b10599 ile doğrulandı). QAT chat şablonu
                # enable_thinking=False'u destekler → deterministik, token-tasarruflu yanıt.
                "chat_template_kwargs": {"enable_thinking": False},
            },
            timeout=_ISTEK_ZAMAN_ASIMI_SN,
        )
        yanit.raise_for_status()
        veri = yanit.json()
        return str(veri["choices"][0]["message"]["content"])


class LlamaCppEmbedding:
    """bge-m3 GGUF embedding — llama-server /v1/embeddings (ayrı proses, --embeddings).

    BgeM3Provider ile aynı batch'leme kontratı; CPU sunucuda muhafazakâr sabit batch=32.
    MIT lisans (ticari-net — Ollama provider ile aynı model ailesi).

    Uzunluk koruması (2026-08-24 paketli-saha hatası): tam-gövde embed'i (degerleme/index
    ~6K+ karakter) bge-m3 Q4 sunucusunda HTTP 500 üretiyordu → degerleme 'hata', index'e
    ekleme hiç koşmuyordu (puan=None şartı). Tek metin _CHUNK_KAR üstündeyse cümle/kelime
    sınırında parçalanır, parçalar ayrı gömülür ve ORTALAMASI döner (belge vektörü emsali —
    novelty/niş benzerlik hesabı için chunk-mean tam-gövdeden daha kararlı). Dış kontrat
    korunur: N metin → N vektör.
    """

    ad = "bge-m3"
    lisans = "MIT"
    _BATCH = 32
    # bge-m3 ctx 8192 ama paketli Q4 sunucuda ~2K karakter üstü tek-parça girdi 500
    # üretti (empirik). 1024 karakter ≈ 350-400 token — güvenli bölge, iyi sinyal.
    _CHUNK_KAR = 1024

    def __init__(self, model: str | None = None, host: str | None = None) -> None:
        cfg = get_config()
        self.model = model or str(profil_bilgisi(cfg.llamacpp_profil)["embed_dosya"])
        self.host = host or cfg.llamacpp_embed_host

    @classmethod
    def _parcala(cls, metin: str) -> list[str]:
        """Uzun metni _CHUNK_KAR sınırında parçala. Önce satır/boşluk sınırı ara (kelime
        ortası kesme yok); bulunamazsa sert kes. Kısa metin tek parça döner."""
        metin = metin.strip()
        if len(metin) <= cls._CHUNK_KAR:
            return [metin] if metin else []
        parcalar: list[str] = []
        kalan = metin
        while len(kalan) > cls._CHUNK_KAR:
            pencere = kalan[: cls._CHUNK_KAR]
            kes = max(pencere.rfind("\n"), pencere.rfind(". "), pencere.rfind(" "))
            if kes < cls._CHUNK_KAR // 2:  # makul sınır yoksa sert kes (orta-uzunluk)
                kes = cls._CHUNK_KAR
            parcalar.append(kalan[:kes].strip())
            kalan = kalan[kes:].strip()
        if kalan:
            parcalar.append(kalan)
        return [p for p in parcalar if p]

    @staticmethod
    def _ortalama(vektorler: list[list[float]]) -> list[float]:
        """Chunk vektörlerinin boyut-bazında ortalaması (saf Python — torch/numpy yok)."""
        n = len(vektorler)
        if n == 1:
            return vektorler[0]
        boyut = len(vektorler[0])
        return [sum(v[d] for v in vektorler) / n for d in range(boyut)]

    def _gonder(self, host: str, metinler: list[str]) -> list[list[float]]:
        """Düz metin listesini batch'leyerek göm (mevcut OpenAI kontratı; sıra 'index'le)."""
        cikti: list[list[float]] = []
        for i in range(0, len(metinler), self._BATCH):
            yanit = httpx.post(
                f"{host}/v1/embeddings",
                json={"model": self.model, "input": metinler[i : i + self._BATCH]},
                timeout=_ISTEK_ZAMAN_ASIMI_SN,
            )
            yanit.raise_for_status()
            veri = yanit.json()
            # OpenAI şeması: data[].embedding (sıra 'index' alanıyla korunur).
            sirali = sorted(veri["data"], key=lambda d: int(d.get("index", 0)))
            cikti.extend([list(v) for v in (d["embedding"] for d in sirali)])
        return cikti

    def embed(self, metinler: list[str]) -> list[list[float]]:
        with _cikarim_kilidi:
            return self._embed(metinler)

    def _embed(self, metinler: list[str]) -> list[list[float]]:
        if not metinler:
            return []
        host = (
            sunucu_baslat_gerekirse("embed")
            if self.host == get_config().llamacpp_embed_host
            else self.host
        )
        # Uzun metinleri parçalara aç; (metin_indexi, parca) düz listesi → tek turda göm →
        # metin bazında grupla ve ortala. Kısa metinler tek parça (davranış birebir korunur).
        duz: list[str] = []
        sahip: list[int] = []
        for mi, metin in enumerate(metinler):
            parcalar = self._parcala(metin)
            if not parcalar:  # tamamen boş metin — kontrat: yine de bir vektör borçluyuz
                parcalar = [" "]
            for p in parcalar:
                duz.append(p)
                sahip.append(mi)
        gomulmus = self._gonder(host, duz)
        gruplar: dict[int, list[list[float]]] = {}
        for mi, v in zip(sahip, gomulmus, strict=True):
            gruplar.setdefault(mi, []).append(v)
        return [self._ortalama(gruplar[i]) for i in range(len(metinler))]
