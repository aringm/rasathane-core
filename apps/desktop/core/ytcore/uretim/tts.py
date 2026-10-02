from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from ytcore.errors import KOD_HATALARI as _KOD_HATALARI

_VOICE_AD = "tr_TR-dfki-medium"

# Piper TTS worker AYRI PROSES (ASR/NER deseni — piper/onnxruntime exe-DIŞI). Worker'ı koşan
# harici python'a GERÇEK repo core/'unu PYTHONPATH vermek için bu dosyaya göre kök. (frozen
# exe'de modül-göreli kök _MEIPASS olur → _gercek_core_root sys.executable'dan yürüyüp bulur.)
_CORE_ROOT = Path(__file__).resolve().parents[2]
_WORKER_REL = Path("ytcore") / "uretim" / "tts_worker.py"


def _is_file_guvenli(p: Path) -> bool:
    """is_file() POSIX'te EACCES/ELOOP'ta OSError atabilir → yut (ner.py emsali)."""
    try:
        return p.is_file()
    except OSError:
        return False


def _ayni_yol(a: str, b: str) -> bool:
    """İki yol AYNI dosyayı mı gösteriyor (NORMALİZE)? String eşitlik frozen-self guard'ı
    atlatabilirdi (ner.py emsali)."""
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return a == b


def _gercek_core_root() -> Path:
    """tts_worker.py'yi içeren GERÇEK repo core/ dizinini bul (harici python PYTHONPATH).

    Dev'de modül-göreli core (doğru). Frozen exe'de _CORE_ROOT=_MEIPASS ama tts_worker
    --exclude-module → sys.executable'dan YUKARI yürüyüp gerçek repo core'unu bul (ner.py emsali;
    YALNIZ sys.executable yürümesi — güvenilmez cwd'ye sahte worker konması engellenir)."""
    # Kurulu app: motor kökü (config; YT_MOTOR_KOK/_ayarlar.json/standart konum) — AppData'dan
    # bulunamayan gerçek repo core'unu açık konumdan çöz (tam özellik).
    from ytcore.config import motor_core_root

    mk = motor_core_root()
    if mk and _is_file_guvenli(mk / _WORKER_REL):
        return mk
    if not getattr(sys, "frozen", False) and _is_file_guvenli(_CORE_ROOT / _WORKER_REL):
        return _CORE_ROOT
    try:
        kok = Path(sys.executable).resolve().parent
    except OSError:
        return _CORE_ROOT
    isaret = Path("core") / _WORKER_REL
    for ata in (kok, *kok.parents):
        if _is_file_guvenli(ata / isaret):
            return (ata / "core").resolve()
    return _CORE_ROOT


def piper_hazir_mi(voice_dir: Path) -> bool:
    """Piper TR voice GERÇEKTEN hazır mı: .onnx VE .onnx.json İKİSİ birden (PiperTTS ikisini
    de ister — tts.py 'seslendir' kontrolüyle TEK doğruluk kaynağı). Yarım indirme (.onnx var,
    .onnx.json yok) 'hazır' raporlanmasın (denetim MED — kurulum_kontrol bunu çağırır)."""
    return (voice_dir / f"{_VOICE_AD}.onnx").exists() and (
        voice_dir / f"{_VOICE_AD}.onnx.json"
    ).exists()


def _ses_dosyasi_gecerli(yol: Path, min_bayt: int = 44) -> bool:
    """Yazılan ses dosyası GERÇEKTEN oluştu + boş-değil mi (boş≠başarı). Sentez sessizce
    0-frame/eksik dosya üretebilir → 'uretildi' demeden önce doğrula. 44 = min WAV header."""
    try:
        return yol.exists() and yol.stat().st_size >= min_bayt
    except OSError:
        return False


@dataclass
class SesSonuc:
    durum: str  # uretildi | ses_modeli_yok | piper_kurulu_degil | anahtar_yok | icerik_yok | hata
    kaynak: str | None = None  # "piper" | "cloud" | "fake"
    sure_sn: float | None = None


@runtime_checkable
class TTSProvider(Protocol):
    def seslendir(self, metin: str, hedef_yol: Path) -> SesSonuc: ...


def seslendirme_karari(*, pii_var: bool, cloud_acik: bool, anahtar_var: bool) -> tuple[str, str]:
    """KVKK fail-closed TTS sağlayıcı kararı. PII → yalnız yerel Piper (cloud REDDEDİLİR).
    Cloud yalnız: PII-temiz VE bilinçli opt-in VE anahtar var. Şüphede yerel (değişmez #1)."""
    if pii_var:
        return "piper", "pii (KVKK fail-closed → yerel)"
    if not cloud_acik:
        return "piper", "cloud opt-in yok (YT_TTS_CLOUD)"
    if not anahtar_var:
        return "piper", "cloud anahtarı yok (inert)"
    return "cloud", "PII-temiz + cloud opt-in + anahtar"


def tts_pii_var_mi(metin: str) -> bool:
    """TTS KVKK gate'i — TEK enforcement yardımcısı (review tur-1: kopya gate'ler sapar).

    pattern-PII + (cloud-egress gerçekten mümkünse) ad-soyad NER (Faz 5 bloker: çıplak ad
    pattern-gate'i atlatır). NER yalnız opt-in+anahtar varken çağrılır — Piper-only
    kurulumda subprocess maliyeti yok. Pipeline node'u ve MCP tool'u AYNI kararı kullanır.
    """
    from ytcore.config import get_config
    from ytcore.router.pii_gate import pii_iceriyor_mu

    cfg = get_config()
    pii = pii_iceriyor_mu(metin).var
    if not pii and cfg.tts_cloud_acik and cfg.openai_api_key:
        from ytcore.router.ner import ner_al

        pii = ner_al().kisi_var_mi([metin])[0]
    return pii


class FakeTTS:
    """Hermetik TTS (ağsız/Piper'siz/onnx'siz). Geçerli minimal WAV yazar (boş≠başarı)."""

    def seslendir(self, metin: str, hedef_yol: Path) -> SesSonuc:
        if not metin.strip():
            return SesSonuc("icerik_yok", "fake")
        hedef_yol.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(hedef_yol), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(b"\x00\x00" * 2205)  # 0.1s sessizlik = gerçek geçerli WAV
        return SesSonuc("uretildi", "fake", sure_sn=0.1)


class PiperTTS:
    """Piper-dfki yerel TTS (onnxruntime, torch-free, CPU, KVKK-garantili). WAV üretir.

    Voice modeli yoksa → 'ses_modeli_yok' (sessiz başarı YOK; piper_voice_indir() ile çek).
    piper importu/sentezi DAR sınırda guard'lı (Windows wheel/phonemize ham hatası çökertmez).
    """

    def __init__(self, voice_dir: Path | None = None) -> None:
        from ytcore.config import get_config

        self._dir = voice_dir or get_config().piper_voice_dir
        self._onnx = self._dir / f"{_VOICE_AD}.onnx"
        self._json = self._dir / f"{_VOICE_AD}.onnx.json"

    def seslendir(self, metin: str, hedef_yol: Path) -> SesSonuc:
        if not metin.strip():
            return SesSonuc("icerik_yok", "piper")
        if not (self._onnx.exists() and self._json.exists()):
            return SesSonuc("ses_modeli_yok", "piper")  # sessiz başarı YOK; dürüst durum
        hedef_yol.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Import AYRI guard'da (review tur-1 HIGH): frozen exe'de piper bundle'da YOK
            # (exe-dışı, ASR deseni); voice indirilmişse ImportError = KOD_HATALARI sayılıp
            # analizi ÇÖKERTMEMELİ — ortam-eksikliği ≠ kod-bug, dürüst durumla dön.
            from piper import PiperVoice  # lazy (torch-free; exe-dışı; espeak-ng-data bundle'lı)
        except ImportError:
            return SesSonuc("piper_kurulu_degil", "piper")
        try:
            voice = PiperVoice.load(str(self._onnx), str(self._json))
            with wave.open(str(hedef_yol), "wb") as w:
                voice.synthesize_wav(metin, w)  # piper 1.x API (wav_file 2. arg)
        except _KOD_HATALARI:
            raise  # kod bug görünür çök (sessiz 'hata' maskelemesi YOK — Faz 1/2/3 dersi)
        except Exception:  # noqa: BLE001 — piper/onnx/phonemize ham hata sınırda graceful
            return SesSonuc("hata", "piper")
        if not _ses_dosyasi_gecerli(hedef_yol):
            return SesSonuc("hata", "piper")  # boş≠başarı: 0-frame/eksik WAV "uretildi" sayılmaz
        return SesSonuc("uretildi", "piper")


class SubprocessPiperTTS:
    """Piper sentezini AYRI PROSESTE koşar (ASR/NER deseni: piper/onnxruntime ana engine'e ve
    exe'ye GİRMEZ — <200MB, değişmez #2). Engine yalnız worker'ı sürer + durum/dosya doğrular;
    piper IMPORT ETMEZ. Sentez mantığı in-process PiperTTS'ten (worker üzerinden) yeniden
    kullanılır (tek doğruluk kaynağı). KVKK: yalnız YEREL sentez (egress yok); PII egress
    kararı seslendirme_node'da ZATEN verildi. Frozen GUI'de de sesli özet çalışsın diye."""

    def __init__(
        self, python: str | None = None, voice_dir: Path | None = None, timeout_sn: float = 180.0
    ) -> None:
        from ytcore.config import get_config

        cfg = get_config()
        self.python = python if python is not None else cfg.tts_python
        self._dir = voice_dir or cfg.piper_voice_dir
        self._onnx = self._dir / f"{_VOICE_AD}.onnx"
        self._json = self._dir / f"{_VOICE_AD}.onnx.json"
        self.timeout_sn = timeout_sn

    def seslendir(self, metin: str, hedef_yol: Path) -> SesSonuc:
        if not metin.strip():
            return SesSonuc("icerik_yok", "piper")
        # Model kontrolü SPAWN'DAN ÖNCE (boş≠başarı + gereksiz proses yok; KVKK testleri bu
        # erken-dönüşe güvenir): .onnx VE .onnx.json İKİSİ birden.
        if not (self._onnx.exists() and self._json.exists()):
            return SesSonuc("ses_modeli_yok", "piper")
        # Frozen self-spawn guard (ner.py:122 deseni): exe kendini worker spawn ederse stdio MCP
        # moduna düşer (blok + stdin çalma). Ayrı python yoksa piper desteklenmez → dürüst durum.
        if (
            getattr(sys, "frozen", False)
            and _ayni_yol(self.python, sys.executable)
            and not os.environ.get("RASATHANE_WORKER_EXE")
        ):
            return SesSonuc("piper_kurulu_degil", "piper")
        hedef_yol.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory() as d:
                girdi = Path(d) / "in.json"
                meta = Path(d) / "meta.json"
                girdi.write_text(
                    json.dumps({"metin": metin, "voice_dir": str(self._dir)}, ensure_ascii=False),
                    encoding="utf-8",
                )
                from ytcore.local.worker import worker_command

                cmd = worker_command(
                    "tts",
                    self.python,
                    [
                        "--in",
                        str(girdi),
                        "--out",
                        str(hedef_yol),
                        "--meta",
                        str(meta),
                    ],
                )
                env = dict(os.environ)
                # Worker sandbox (ner.py deseni): PYTHONPATH'e YALNIZ gerçek core; kirli parent
                # PYTHONPATH worker'a kötücül modül shadow-import etmesin. stdin=DEVNULL: child
                # parent'ın stdin'ini (stdio MCP pipe'ı) miras almasın.
                env["PYTHONPATH"] = str(_gercek_core_root())
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=self.timeout_sn,
                    stdin=subprocess.DEVNULL,
                )
                if meta.exists():
                    try:
                        durum = str(
                            json.loads(meta.read_text(encoding="utf-8")).get("durum", "hata")
                        )
                    except (json.JSONDecodeError, OSError):
                        durum = "hata"
                else:
                    # meta yok: worker modülü import/spawn edilemedi (ör. piper'sız/PYTHONPATH'siz
                    # env) → piper_kurulu_degil; başka çökme → hata.
                    durum = "piper_kurulu_degil" if proc.returncode != 0 else "hata"
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return SesSonuc("hata", "piper")
        if durum == "uretildi" and not _ses_dosyasi_gecerli(hedef_yol):
            return SesSonuc("hata", "piper")  # boş≠başarı
        return SesSonuc(durum, "piper")


class CloudTTS:
    """OpenAI gpt-4o-mini-tts REST (httpx). Anahtar YOKSA inert ('anahtar_yok' — SerperSearch
    deseni). KVKK: yalnız PII-temiz metin için (node gate'i sağlar). mp3 üretir."""

    def __init__(self, api_key: str | None = None) -> None:
        from ytcore.config import get_config

        cfg = get_config()
        self.api_key = api_key if api_key is not None else cfg.openai_api_key
        self.model = cfg.tts_cloud_model

    def seslendir(self, metin: str, hedef_yol: Path) -> SesSonuc:
        if not metin.strip():
            return SesSonuc("icerik_yok", "cloud")
        if not self.api_key:
            return SesSonuc("anahtar_yok", None)  # inert (SerperSearch deseni)
        hedef_yol.parent.mkdir(parents=True, exist_ok=True)
        import httpx

        try:
            r = httpx.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "input": metin,
                    "voice": "alloy",
                    "response_format": "mp3",
                },
                timeout=60.0,
            )
            r.raise_for_status()
            if not r.content:
                return SesSonuc("hata", "cloud")  # boş yanıt (200 ama gövde yok) ≠ başarı
            hedef_yol.write_bytes(r.content)
        except _KOD_HATALARI:
            raise  # kod bug görünür çök (sessiz 'hata' maskelemesi YOK)
        except Exception:  # noqa: BLE001 — ağ/HTTP ham hata sınırda graceful
            return SesSonuc("hata", "cloud")
        if not _ses_dosyasi_gecerli(hedef_yol, min_bayt=1):
            return SesSonuc("hata", "cloud")  # boş≠başarı
        return SesSonuc("uretildi", "cloud")


class WindowsTTS:
    """Windows'un kurulu Türkçe sesi; model indirme ve cloud çağrısı yapmaz."""

    def seslendir(self, metin: str, hedef_yol: Path) -> SesSonuc:
        if not metin.strip():
            return SesSonuc("icerik_yok", "windows")
        if os.name != "nt":
            return SesSonuc("ses_modeli_yok", "windows")
        script = Path(__file__).with_name("windows-tts.ps1")
        executable = (
            Path(os.environ.get("SystemRoot", "C:/Windows"))
            / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        hedef_yol.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory() as folder:
                source = Path(folder) / "speech.json"
                source.write_text(
                    json.dumps({"metin": metin}, ensure_ascii=False), encoding="utf-8"
                )
                proc = subprocess.run(
                    [
                        str(executable),
                        "-NoProfile",
                        "-NonInteractive",
                        "-File",
                        str(script),
                        "-InputPath",
                        str(source),
                        "-OutputPath",
                        str(hedef_yol),
                    ],
                    capture_output=True,
                    timeout=180,
                    stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if proc.returncode != 0:
                    return SesSonuc("ses_modeli_yok", "windows")
            return SesSonuc("uretildi" if _ses_dosyasi_gecerli(hedef_yol) else "hata", "windows")
        except (OSError, subprocess.TimeoutExpired):
            return SesSonuc("hata", "windows")


def tts_al(kaynak: str) -> TTSProvider:
    """YT_TTS_FIXTURE set ise FakeTTS (hermetik); 'cloud' → CloudTTS; aksi SubprocessPiperTTS
    (Piper AYRI PROSES — exe-dışı; frozen GUI'de de sentez çalışır)."""
    if os.environ.get("YT_TTS_FIXTURE", "").strip():
        return FakeTTS()
    if kaynak == "cloud":
        return CloudTTS()
    if os.environ.get("RASATHANE_NATIVE_TTS") == "1":
        return WindowsTTS()
    return SubprocessPiperTTS()


def piper_voice_indir(voice_dir: Path | None = None) -> Path:
    """dfki TR voice modelini HF'den indir (dev/ilk-kullanım; runtime'da otomatik DEĞİL —
    kullanıcı bilinçli çağırır). Döndürür: onnx yolu."""
    import httpx

    from ytcore.config import get_config

    d = voice_dir or get_config().piper_voice_dir
    d.mkdir(parents=True, exist_ok=True)
    taban = "https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium"
    for ek in (".onnx", ".onnx.json"):
        hedef = d / f"{_VOICE_AD}{ek}"
        if hedef.exists():
            continue
        r = httpx.get(f"{taban}/{_VOICE_AD}{ek}", follow_redirects=True, timeout=120.0)
        r.raise_for_status()
        hedef.write_bytes(r.content)
    return d / f"{_VOICE_AD}.onnx"
