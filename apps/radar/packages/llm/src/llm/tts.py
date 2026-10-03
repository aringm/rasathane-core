"""Phase 35-i: ElevenLabs-only TTS wrapper.

Phase tarihi (2026-05-20): Edge-TTS ve Coqui XTTS-v2 path'leri tamamen
silindi; sadece ElevenLabs (creator tier, TR-native voices) kalır. Voice
defaults ElevenLabs API hard default'una (0.5 / 0.75 / 0.0 + speaker boost)
çekildi; loudnorm Apple Podcasts standardına (I=-16, LRA=11) reset edildi.

Kullanım (tek-spiker — kütüphane audio özet):
    from llm.tts import synthesize_to_mp3
    await synthesize_to_mp3(text, output_path=Path("audio.mp3"))

Kullanım (çok-spiker podcast — brief / deep analyze):
    from llm.tts import synthesize_podcast, PODCAST_VOICES_ELEVENLABS_BRIEF
    await synthesize_podcast(
        dialog=[{"speaker": "Filiz", "text": "..."}, ...],
        output_path=Path("podcast.mp3"),
        voices=PODCAST_VOICES_ELEVENLABS_BRIEF,
    )
"""

from __future__ import annotations

import asyncio
import json as _json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

# Phase 32-iii / 32-v.1: TR konuşmada yanlış okunan EN terimlerin fonetik
# karşılıkları. Üç kategori:
#
# (1) **Kısa harf kısaltmalar** (AI, MoE, GPU) — multilingual TTS dil
#     tespitinde bağlam yetersiz, TR fonetikle ("a-i") okur.
# (2) **AI şirket/model isimleri** (Anthropic, DeepSeek, GPT, Claude) —
#     TR cümle içindeki tek-kelime EN özel ismi yanlış okunabilir
#     (özellikle ElevenLabs anglofon premade voice'larında).
# (3) **Tech araç/protokol** (GitHub, HuggingFace, vLLM, llama.cpp) —
#     marka + nokta + alt-kelime karışımları parser'ı şaşırtır.
#
# Sözlük case-insensitive eşleştirilir (regex IGNORECASE) — LLM çıktısı
# "DeepSeek" / "DEEPSEEK" / "deepseek" arasında değişebilir. Yine de
# dict'te uppercase canonical (kod okunabilirliği için).
#
# Kararlı işlem: dict order'a göre uzun terimler ÖNCE replace edilir
# (örn. "DeepMind" + "DeepSeek" varken kısa olanı önce yapma — sub-string
# çakışması nadir ama olabilir; word-boundary ``\b`` zaten korur).
#
# Eklemek istediğin terim için kural: kullanıcı brief dinlediğinde
# "şu kelime kötü çıktı" diyorsa ekle. Aşırı genişletme yapay konuşma yaratır.
_ACRONYM_PHONETICS: dict[str, str] = {
    # ── Kısa kısaltmalar (Phase 32-iii) ─────────────────────────────
    "AI": "ey-ay",
    "API": "ey-pi-ay",
    "ASR": "ey-es-ar",
    "CPU": "si-pi-yu",
    "GPU": "ci-pi-yu",
    "LLM": "el-el-em",
    "MCP": "em-si-pi",
    "MoE": "mov-ii",
    "RAG": "rag",
    "SDK": "es-di-key",
    "TTS": "ti-ti-es",
    "UI": "yu-ay",
    "URL": "yu-ar-el",
    # ── Phase 32-v.1: AI lab + şirket isimleri ──────────────────────
    "Anthropic": "entropik",
    "OpenAI": "open-eyay",
    "DeepSeek": "diip-siik",
    "DeepMind": "diip-maynd",
    "Qwen": "kuven",
    "Alibaba": "alibaba",  # TR yaygın, dokunma riski az
    "MiniMax": "minimaks",
    "Moonshot": "munşat",
    "Kimi": "kimi",
    "Hunyuan": "hunyuan",
    "Baichuan": "baykuvan",
    "EXAONE": "eksavan",
    "Sakana": "sakana",
    "Mistral": "mistral",
    "Meta": "meta",
    # ── AI model adları ─────────────────────────────────────────────
    "GPT": "ci-pi-ti",
    "ChatGPT": "çet-cipiti",
    "Claude": "kılod",
    "Gemini": "cemini",
    "Llama": "lama",
    "Mixtral": "mikstral",
    "Sonnet": "sonnet",  # Claude Sonnet
    "Opus": "opus",
    "Haiku": "hayku",
    # ── Tech araç + protokol ────────────────────────────────────────
    "GitHub": "githab",
    "GitLab": "gitlab",
    "HuggingFace": "haging-feys",
    "Hugging Face": "haging feys",
    "LangChain": "leng-çeyn",
    "LangGraph": "leng-graf",
    "LlamaIndex": "lama-indeks",
    "vLLM": "vi-el-el-em",
    "llama.cpp": "lama-si-pi-pi",
    "Triton": "triton",
    "SGLang": "es-ci-leng",
    "MLX": "em-el-eks",
    # ── Hukuk + AI regülasyon kısaltmaları ──────────────────────────
    "GDPR": "ci-di-pi-ar",
    "EU AI Act": "iyu ey-ay akt",
    "CCPA": "si-si-pi-ey",
    "NIST": "nist",
}


# EN brand/kısaltma fonetik fix `_ACRONYM_PHONETICS` korunur (multilingual
# TTS bile "AI" / "GPT" acronym'leri TR fonetikle okuyabilir).


# ── Phase 32-v.3: Agent Profilleri (Stüdyo) ──────────────────────────
#
# Kullanıcı geri bildirimi: "konuşmacıların uzmanlık alanları ve isimleri
# ile ses tonlarını ayrı ayrı seçebilelim". Mevcut sistemde speaker isim
# (Filiz/Mehmet/Burak) hard-coded; voice_id picker'dan değişebilir ama
# isim/rol prompt'a embed'li. Bu commit slot-tabanlı mapping ekler:
# kullanıcı agent_profiles.json'da her slot için (isim, rol, voice_id)
# 3'lüsü tanımlar. Voice mapping bunlardan oluşturulur.
#
# Bu commit prompt template'lerini değiştirmez (Filiz/Mehmet/Burak isimleri
# hâlâ prompt'ta). Sonraki phase'de prompt {{speaker_1_name}} placeholder'a
# çevrilebilir. Şu an UI editlenebilir göstergesi — backend voice_id mapping
# yapar, isim/rol metadata olarak korunur.


def _agent_profile_defaults() -> dict[str, Any]:
    """Phase 32-v.4: Merkezi agent havuzu + mode slot mapping.

    Schema::

        {
          "agents": {
            "<agent_id>": {"name": str, "voice_id": str},
            ...
          },
          "modes": {
            "brief":   [{"agent_id": str, "role": str}, ...],
            "youtube": [{"agent_id": str, "role": str}, ...]
          }
        }

    Kritik: agent_id ↔ voice_id bağı **tek**. Aynı agent birden çok mod'da
    yer alabilir; ses tutarlılığı garantili (Mehmet hangi modda olursa
    olsun aynı voice).

    Lazy compute (ELEVENLABS_TR_NATIVE_VOICES module load order bypass).
    """
    return {
        "agents": {
            "filiz": {
                "name": "Filiz",
                "voice_id": ELEVENLABS_TR_NATIVE_VOICES["İrem"],
            },
            "mehmet": {
                "name": "Mehmet",
                "voice_id": ELEVENLABS_TR_NATIVE_VOICES["Adam TR"],
            },
            "burak": {
                "name": "Burak",
                "voice_id": ELEVENLABS_TR_NATIVE_VOICES["Ozan"],
            },
            "esra": {
                "name": "Esra",
                "voice_id": ELEVENLABS_TR_NATIVE_VOICES["Elvan"],
            },
        },
        "modes": {
            "brief": [
                {"agent_id": "filiz", "role": "Spiker · moderatör"},
                {"agent_id": "mehmet", "role": "Hukuk uzmanı · Yargıtay/AYM/Danıştay yorumcu"},
                {"agent_id": "burak", "role": "Teknik analist · AI/model/infra"},
            ],
            "youtube": [
                {"agent_id": "filiz", "role": "Spiker · video tanıtımı"},
                {"agent_id": "burak", "role": "Konu uzmanı · içerik özünü açar"},
                {"agent_id": "esra", "role": "Eleştirmen · alternatif yorum/eksikler"},
            ],
        },
    }


# Backward-compat: API ve testler defaults erişimi için. Proxy lazy compute.
class _AgentProfileDefaultsProxy:
    """Default agent profile dict-like erişim (proxy → lazy fn)."""

    def __getitem__(self, key: str) -> Any:
        return _agent_profile_defaults().get(key)

    def get(self, key: str, default: Any = None) -> Any:
        result = _agent_profile_defaults().get(key)
        return result if result is not None else default

    def keys(self) -> Any:
        return _agent_profile_defaults().keys()

    def items(self) -> Any:
        return _agent_profile_defaults().items()


_AGENT_PROFILES_DEFAULTS = _AgentProfileDefaultsProxy()

AGENT_PROFILES_FILENAME = "agent_profiles.json"


def _agent_profiles_path() -> Path:
    """Agent profiles JSON path. ``RASATHANE_AGENT_PROFILES_PATH`` env override."""
    env_path = os.environ.get("RASATHANE_AGENT_PROFILES_PATH")
    if env_path:
        return Path(env_path)
    here = Path(__file__).resolve()
    return here.parents[4] / "data" / AGENT_PROFILES_FILENAME


def _migrate_legacy_agent_profiles(legacy: dict[str, Any]) -> dict[str, Any]:
    """Phase 32-v.4: Eski schema ({brief: [...], youtube: [...]}) → yeni schema.

    Eski: her mod ayrı agent listesi, isim ↔ ses bağı yok.
    Yeni: merkezi agents havuzu (isim ↔ ses tek), modes mapping.

    İsim çakışması varsa (Mehmet hem brief hem youtube'da farklı voice ile)
    BRIEF'in voice'unu tercih et (uyarı log).
    """
    if "agents" in legacy and "modes" in legacy:
        return legacy  # zaten yeni format
    agents: dict[str, dict[str, str]] = {}
    modes: dict[str, list[dict[str, str]]] = {"brief": [], "youtube": []}
    for mode_name in ("brief", "youtube"):
        for agent in legacy.get(mode_name, []):
            if not isinstance(agent, dict):
                continue
            name = (agent.get("name") or "").strip()
            voice_id = (agent.get("voice_id") or "").strip()
            role = (agent.get("role") or "").strip()
            if not name:
                continue
            agent_id = _slugify_agent_name(name)
            if agent_id in agents and agents[agent_id]["voice_id"] != voice_id:
                log.warning(
                    "tts.agent_migration.voice_conflict",
                    name=name,
                    agent_id=agent_id,
                    keeping=agents[agent_id]["voice_id"],
                    discarding=voice_id,
                )
            else:
                agents[agent_id] = {"name": name, "voice_id": voice_id}
            modes[mode_name].append({"agent_id": agent_id, "role": role})
    return {"agents": agents, "modes": modes}


def _slugify_agent_name(name: str) -> str:
    """'Mehmet' → 'mehmet'; 'Sezen Aksu' → 'sezen-aksu'; TR karakterler korunur."""
    import re

    s = name.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^\w\-çğıöşüâîû]", "", s, flags=re.IGNORECASE)
    return s or "agent"


def load_agent_profiles() -> dict[str, Any]:
    """Agent profiles JSON dosyasını oku.

    Eski format ({brief: [...], youtube: [...]}) otomatik yeni schema'ya migrate.
    Yoksa boş dict.

    Phase 35-xi: `utf-8-sig` codec — Windows PowerShell `Set-Content
    -Encoding utf8` BOM ekliyor (WinPS 5.1 default davranışı). BOM'lu
    dosya `utf-8` parse'ında JSONDecodeError verir, fonksiyon sessizce
    boş dict döner → endpoint default'a fallback eder → UI'da kullanıcı
    "eski sesler seçili" semptomu yaşar. `utf-8-sig` BOM varsa otomatik
    atlar; yoksa düz utf-8 olarak okur.
    """
    path = _agent_profiles_path()
    if not path.is_file():
        return {}
    try:
        data = _json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            log.warning("tts.agent_profiles.invalid_root", path=str(path))
            return {}
        # Schema migration (Phase 32-v.4: eski format → yeni merkezi havuz)
        if "agents" not in data or "modes" not in data:
            migrated = _migrate_legacy_agent_profiles(data)
            log.info("tts.agent_profiles.migrated_from_legacy")
            return migrated
        # Yeni schema validation
        agents = data.get("agents")
        modes = data.get("modes")
        if not isinstance(agents, dict) or not isinstance(modes, dict):
            log.warning("tts.agent_profiles.invalid_schema", path=str(path))
            return {}
        return data
    except (OSError, _json.JSONDecodeError) as e:
        log.warning("tts.agent_profiles.read_failed", path=str(path), err=str(e)[:200])
        return {}


def save_agent_profiles(data: dict[str, Any]) -> bool:
    """Agent profiles JSON'ı atomik yaz (yeni schema)."""
    path = _agent_profiles_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))
        return True
    except OSError as e:
        log.warning("tts.agent_profiles.write_failed", path=str(path), err=str(e)[:200])
        return False


def get_active_agent_profiles(mode: str) -> list[dict[str, Any]]:
    """Default + user override merge → ``mode`` için aktif agent listesi.

    Phase 32-v.4: merkezi agent havuzu — isim ↔ ses bağı tek.
    User override `agents` dict'i ezer (isim/ses değişikliği), `modes`
    dict'i ezer (slot atamaları). User'da yoksa default fallback.

    Returns:
        list of dicts [{slot, agent_id, name, role, voice_id}] —
        slot=0,1,2 sırası.
    """
    defaults = _agent_profile_defaults()
    user = load_agent_profiles()

    # Merkezi agent havuzu: user'ın varsa onu, yoksa default
    agents_pool = user["agents"] if user.get("agents") else defaults["agents"]

    # Mode mapping: user'da varsa onu, yoksa default
    user_mode_slots = user.get("modes", {}).get(mode)
    mode_slots = user_mode_slots if user_mode_slots else defaults["modes"].get(mode, [])

    out: list[dict[str, Any]] = []
    for i, slot_def in enumerate(mode_slots):
        if not isinstance(slot_def, dict):
            continue
        agent_id = slot_def.get("agent_id", "")
        role = slot_def.get("role", "")
        agent = agents_pool.get(agent_id)
        if not agent:
            # Agent havuzda yok — atla (UI uyarı verebilir)
            log.warning(
                "tts.agent_profiles.missing_agent",
                mode=mode,
                slot=i,
                agent_id=agent_id,
            )
            continue
        out.append(
            {
                "slot": i,
                "agent_id": agent_id,
                "name": agent.get("name", agent_id),
                "role": role,
                "voice_id": agent.get("voice_id", ""),
            }
        )
    return out




# ── Phase 32-v.4: TR sayı/ordinal/yüzde yazıya çevirme ─────────────────
#
# Anglofon TTS voice'lar TR cümle içindeki sayıları ya İngilizce ya da
# yanlış TR fonetikle okur ("2026" → "twenty-twenty-six" yerine "iki bin
# yirmi altı" olmalı). Prompt'a "yazıyla yaz" diyoruz ama Claude bazen
# atlıyor. Bu katman deterministik garanti.

_TR_DIGITS = ["sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TR_TEENS = [
    "on",
    "on bir",
    "on iki",
    "on üç",
    "on dört",
    "on beş",
    "on altı",
    "on yedi",
    "on sekiz",
    "on dokuz",
]
_TR_TENS = [
    "",
    "on",
    "yirmi",
    "otuz",
    "kırk",
    "elli",
    "altmış",
    "yetmiş",
    "seksen",
    "doksan",
]

# Ordinal eki — son sesli harfe göre vokal uyumu:
# a/ı → ıncı, e/i → inci, o/u → uncu, ö/ü → üncü
_ORDINAL_SUFFIXES = {
    "a": "ıncı",
    "ı": "ıncı",
    "e": "inci",
    "i": "inci",
    "o": "uncu",
    "u": "uncu",
    "ö": "üncü",
    "ü": "üncü",
}


def _tr_number_to_words(n: int) -> str:
    """0-999.999.999 arası int → Türkçe yazı.

    Negatif ve ondalık desteklenmez (yıl/ordinal kullanım için yeterli).
    Örnekler: 9→"dokuz", 73→"yetmiş üç", 2026→"iki bin yirmi altı".
    """
    if n == 0:
        return _TR_DIGITS[0]
    if n < 0 or n > 999_999_999:
        return str(n)  # range dışı, ham bırak

    parts: list[str] = []

    # Milyar (1_000_000_000+) desteklenmez, max 999_999_999

    millions = n // 1_000_000
    n %= 1_000_000
    if millions:
        if millions == 1:
            parts.append("bir milyon")
        else:
            parts.append(_tr_number_to_words(millions) + " milyon")

    thousands = n // 1000
    n %= 1000
    if thousands:
        # 1000 → "bin" (özel), 2000+ → "iki bin", "üç bin", ...
        if thousands == 1:
            parts.append("bin")
        else:
            parts.append(_tr_number_to_words(thousands) + " bin")

    hundreds = n // 100
    n %= 100
    if hundreds:
        # 100 → "yüz", 200+ → "iki yüz", ...
        if hundreds == 1:
            parts.append("yüz")
        else:
            parts.append(_TR_DIGITS[hundreds] + " yüz")

    if n >= 20:
        tens = n // 10
        ones = n % 10
        if ones:
            parts.append(f"{_TR_TENS[tens]} {_TR_DIGITS[ones]}")
        else:
            parts.append(_TR_TENS[tens])
    elif n >= 10:
        parts.append(_TR_TEENS[n - 10])
    elif n > 0:
        parts.append(_TR_DIGITS[n])

    return " ".join(parts)


def _tr_ordinal_to_words(n: int) -> str:
    """``9.`` → ``"dokuzuncu"`` formatına çevir (TR ordinal vokal uyumu)."""
    word = _tr_number_to_words(n)
    # Son sesli harfi bul
    vowels = set(_ORDINAL_SUFFIXES.keys())
    last_vowel = ""
    for ch in reversed(word):
        if ch in vowels:
            last_vowel = ch
            break
    if not last_vowel:
        return word + "ncı"  # fallback
    suffix = _ORDINAL_SUFFIXES[last_vowel]
    # Son harfe göre kaynak yumuşaması (yüz → yüzüncü, bin → bininci)
    # Basit: kelime sesli harfle bitiyorsa son sesliyi düşür
    if word.endswith(last_vowel):
        return word[:-1] + suffix
    return word + suffix


# Regex patterns — daha spesifik (yüzde + ordinal) önce match etmeli
_PERCENT_RE = re.compile(r"%\s*(\d{1,3})\b")
_ORDINAL_RE = re.compile(r"\b(\d{1,4})\.(?=\s+[A-ZÇĞİÖŞÜ])")  # "9. Hukuk" → ordinal
_YEAR_RE = re.compile(r"\b(19|20|21)(\d{2})\b")
_NUMBER_RE = re.compile(r"\b(\d{1,9})\b")


def transliterate_numbers_tr(text: str) -> str:
    """Phase 32-v.4: TR sayı/ordinal/yüzde patterns'lerini yazıya çevir.

    Sıra önemli — daha spesifik pattern önce match:
    1. ``%73`` → ``yüzde yetmiş üç``
    2. ``9. Hukuk`` → ``dokuzuncu Hukuk`` (ordinal — sonraki kelime büyük harfle başlamalı)
    3. ``2026`` → ``iki bin yirmi altı`` (yıl — 19xx/20xx/21xx)
    4. ``685`` → ``altı yüz seksen beş`` (kalan ham sayılar)

    Telefon numarası / tarih (`05.03.2026`) gibi yapılar bozulmaz çünkü
    `\b` word-boundary ve "ordinal sonrası büyük harf" filter'ı kullanır.
    """
    if not text:
        return text

    # 1. Yüzde
    def _percent_sub(m: re.Match[str]) -> str:
        return f"yüzde {_tr_number_to_words(int(m.group(1)))}"

    text = _PERCENT_RE.sub(_percent_sub, text)

    # 2. Ordinal ("9. Hukuk Dairesi", "1. Mahkeme")
    def _ordinal_sub(m: re.Match[str]) -> str:
        return _tr_ordinal_to_words(int(m.group(1)))

    text = _ORDINAL_RE.sub(_ordinal_sub, text)

    # 3. Yıl (19xx/20xx/21xx)
    def _year_sub(m: re.Match[str]) -> str:
        return _tr_number_to_words(int(m.group(0)))

    text = _YEAR_RE.sub(_year_sub, text)

    # 4. Kalan ham sayılar (1-999.999.999)
    def _number_sub(m: re.Match[str]) -> str:
        return _tr_number_to_words(int(m.group(1)))

    text = _NUMBER_RE.sub(_number_sub, text)

    return text


def transliterate_short_acronyms(
    text: str,
    *,
    extra: dict[str, str] | None = None,
    apply_numbers: bool = True,
) -> str:
    """EN kısaltma + TR sayı transliterate.

    2 katmanlı pipeline:
      1. **TR Number/Ordinal/Percent** (`transliterate_numbers_tr`):
         "%73"→"yüzde yetmiş üç", "2026"→"iki bin yirmi altı",
         "9. Hukuk"→"dokuzuncu Hukuk".
      2. **EN Acronym Phonetics** (`_ACRONYM_PHONETICS`):
         "Anthropic"→"entropik", "AI"→"ey-ay", "GPT"→"ci-pi-ti".

    Case-insensitive + word-boundary aware. Uzun-önce sıralı (substring
    çakışma defansif).

    Args:
        text: input metin (markdown OK; sadece kelime grupları değişir).
        extra: opsiyonel ek mapping (EN acronym katmanına eklenir).
        apply_numbers: False ise TR sayı katmanı atlanır.

    Returns:
        Transliterated text.
    """
    if not text:
        return text

    # Katman: TR sayı/ordinal/yüzde patterns (Phase 32-v.4)
    if apply_numbers:
        text = transliterate_numbers_tr(text)

    # Katman 3: EN Acronym Phonetics (şirket/model/araç + kısa kısaltma)
    mapping = dict(_ACRONYM_PHONETICS)
    if extra:
        mapping.update(extra)

    # Uzundan kısaya sıra: "DeepMind" varken "Deep" yakalanmasın diye
    # (gerçekte word-boundary korur ama defansif). Aynı uzunlukta
    # deterministic sıralama için secondary key alfabetik.
    sorted_terms = sorted(mapping.items(), key=lambda kv: (-len(kv[0]), kv[0]))

    for term, phonetic in sorted_terms:
        # `re.escape` özel karakterleri (`.`, `+`) güvenli yapar — "llama.cpp"
        # gibi noktalı terimler için kritik.
        pattern = r"\b" + re.escape(term) + r"\b"
        text = re.sub(pattern, phonetic, text, flags=re.IGNORECASE)
    return text


def _inject_xing_header_sync(path: Path) -> bool:
    """Sync core; ``inject_xing_header`` async wrapper'ı bunu çağırır.

    TTS provider'lar (özellikle Edge legacy + bazı CBR MP3 yazıcılar) frame
    zincirinin başında Xing/Info VBR-aware header eklemeden çıkış üretir.
    HTML5 ``<audio preload="metadata">`` bu header yokken duration tahmininde
    başarısız (Chrome 0:05 gösteriyor — gerçek 8:34). ``ffmpeg -c copy
    -write_xing 1`` ile header inject edilince browser süreyi doğru
    hesaplıyor. Pure container rewrite (transcode değil) — 8MB dosya için
    ~0.1 sn maliyet.

    Best-effort: ffmpeg yoksa warn + return False; mp3 etkilenmez.
    Idempotent: çalışmış bir mp3'e yeniden çağırmak güvenli.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log.warning("tts.xing_skip", reason="ffmpeg_not_found", path=str(path))
        return False
    tmp = path.with_suffix(path.suffix + ".xingfix.tmp")
    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(path),
                "-c",
                "copy",
                "-write_xing",
                "1",
                "-f",
                "mp3",  # tmp dosyanın .xingfix.tmp suffix'inden format çıkmıyor
                "-loglevel",
                "error",
                str(tmp),
            ],
            shell=False,
            capture_output=True,
            timeout=60,
        )
        if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            log.warning(
                "tts.xing_failed",
                path=str(path),
                rc=proc.returncode,
                stderr=proc.stderr.decode("utf-8", errors="replace")[:300],
            )
            return False
        os.replace(str(tmp), str(path))
        return True
    except (OSError, subprocess.SubprocessError) as e:
        tmp.unlink(missing_ok=True)
        log.warning("tts.xing_error", path=str(path), err=str(e)[:200])
        return False


async def inject_xing_header(path: Path) -> bool:
    """Async wrapper — see ``_inject_xing_header_sync`` for details."""
    return await asyncio.to_thread(_inject_xing_header_sync, path)


# ── Phase 32-v: Ses mühendisi — ffmpeg loudnorm post-process ────────────


def _measure_loudnorm_pass1(
    path: Path,
    *,
    target_i: float = -16.0,
    true_peak: float = -1.5,
    lra: float = 11.0,
) -> dict[str, str] | None:
    """Phase 35-iii: Pass 1 — measure-only loudnorm; JSON stats döndürür.

    ffmpeg loudnorm filter `print_format=json` ile mp3'ün integrated_I,
    LRA, true_peak, threshold ve offset değerlerini ölçer; output dosya
    yazılmaz (`-f null -`). Sonraki pass'te bu stats'lar `measured_*`
    parametrelerine input olarak verilir — dual-pass loudnorm ±0.1 LUFS
    hassasiyet sağlar (single-pass ±1 LUFS hatası giderilir).

    Returns:
        Dict with keys: input_i, input_lra, input_tp, input_thresh,
        target_offset. None on failure.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log.warning("tts.loudnorm_skip", reason="ffmpeg_not_found", path=str(path))
        return None
    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-nostdin",
                "-i",
                str(path),
                "-af",
                f"loudnorm=I={target_i}:TP={true_peak}:LRA={lra}:print_format=json",
                "-f",
                "null",
                "-",
            ],
            shell=False,
            # Phase 35-x: capture_output=True yerine explicit DEVNULL+PIPE.
            # Dashboard process içinde subprocess.run capture_output stdio
            # pipe deadlock yapıyordu (parent structlog/uvicorn hijack ile
            # subprocess PIPE buffer'ı asılı kalıyor). pass1 measurement
            # stderr'e JSON yazar — sadece stderr'i capture et.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        # ffmpeg loudnorm JSON'u stderr'in son satırlarına yazar
        stderr = proc.stderr.decode("utf-8", errors="replace")
        start = stderr.rfind("{")
        end = stderr.rfind("}")
        if start == -1 or end == -1 or end <= start:
            log.warning("tts.loudnorm_pass1_no_json", path=str(path))
            return None
        try:
            stats = _json.loads(stderr[start : end + 1])
        except _json.JSONDecodeError:
            log.warning("tts.loudnorm_pass1_bad_json", path=str(path))
            return None
        # Beklenen field'lar: input_i, input_lra, input_tp, input_thresh,
        # target_offset. Hepsi string formatta.
        required = {"input_i", "input_lra", "input_tp", "input_thresh", "target_offset"}
        if not required.issubset(stats):
            log.warning(
                "tts.loudnorm_pass1_missing_fields",
                path=str(path),
                present=sorted(stats.keys()),
            )
            return None
        return stats
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("tts.loudnorm_pass1_error", path=str(path), err=str(e)[:200])
        return None


def _apply_loudnorm_sync(
    path: Path,
    *,
    target_i: float = -14.0,  # Phase 35-vii: broadcast-tight (Phase 34-v restore)
    true_peak: float = -1.5,
    lra: float = 5.0,  # Phase 35-vii: sıkı dinamik aralık
    dual_pass: bool = True,  # Phase 35-iii: dual-pass default açık
) -> bool:
    """EBU R128 loudness normalization — broadcast-tight (Phase 35-vii).

    Ses mühendisi rolü: ElevenLabs voice'larının segment çıktıları farklı
    seviyelerde gelir; concat öncesi/sonrası loudnorm integrated loudness'i
    ``target_i`` LUFS'a getirir, true peak ``true_peak`` dB ile clip
    önler, loudness range ``lra`` LU ile dinamik aralığı sabitler.

    Phase 35-iii: Dual-pass (default) — Pass 1 measure, Pass 2 apply
    `measured_*` + `linear=true`. ±0.1 LUFS hassasiyet, segment'ler
    arası varyans neredeyse sıfır. ``dual_pass=False`` ile fallback
    single-pass (Pass 1 hata olursa otomatik).

    Phase 35-vii: target_i -16 → -14 LUFS, lra 11 → 5 LU. Phase 35-i'in
    Apple Podcasts baseline (-16/11) TR-native voice'larda inherent quiet
    sebebiyle final mp3'ü -23 LUFS civarında ölçtürüyordu — hoparlörde
    "fısıltı" hissi. Phase 34-v `0f41303` broadcast-tight değeri
    Filiz/Burak "fısıldar gibi" şikayetini çözmüş, Phase 35-i sessizce
    undo etmişti. Bu restore aynı çözüm — sıkı dinamik aralık fısıltı
    bölümlerini öne çıkarır, speaker'lar arası perceived loudness eşit.

    ffmpeg YOK ise warn + return False; mp3 değişmez. Idempotent değil.

    Returns:
        True if normalization succeeded, False if ffmpeg missing/failed.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        log.warning("tts.loudnorm_skip", reason="ffmpeg_not_found", path=str(path))
        return False

    # Phase 35-iii: Pass 1 — measure (dual-pass mode)
    pass1_stats: dict[str, str] | None = None
    if dual_pass:
        pass1_stats = _measure_loudnorm_pass1(
            path, target_i=target_i, true_peak=true_peak, lra=lra
        )
        # Pass 1 başarısızsa single-pass'a düş (warn log var)

    # Pass 2 (veya single-pass): apply
    if pass1_stats:
        # Dual-pass: linear=true + measured_* input'larla deterministic
        loudnorm_filter = (
            f"loudnorm=I={target_i}:TP={true_peak}:LRA={lra}"
            f":measured_I={pass1_stats['input_i']}"
            f":measured_LRA={pass1_stats['input_lra']}"
            f":measured_TP={pass1_stats['input_tp']}"
            f":measured_thresh={pass1_stats['input_thresh']}"
            f":offset={pass1_stats['target_offset']}"
            f":linear=true:print_format=summary"
        )
    else:
        loudnorm_filter = f"loudnorm=I={target_i}:TP={true_peak}:LRA={lra}"

    tmp = path.with_suffix(path.suffix + ".loudnorm.tmp")
    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-nostdin",
                "-i",
                str(path),
                "-af",
                loudnorm_filter,
                # Phase 35-xxiv: bitrate 96k → 192k CBR. per-segment + final
                # loudnorm = 2x libmp3lame re-encode → 96k codec artifact'ları
                # compound oluyordu (özellikle "s/ş" sibilance + tiz frekanslar).
                # 192k @ mono podcast yayını için endüstri minimum'u (Apple/Spotify
                # 128k mono'yu da kabul eder ama 2x encode için yastık şart).
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                "-ac",
                "1",
                # Phase 35-vii: explicit format. tmp dosya extension'ı
                # `.mp3.loudnorm.tmp` → ffmpeg 8.1 muxer auto-detect reddediyor
                # ("Unable to choose an output format for ...tmp"). `-f mp3`
                # ile container format'ı manuel ver → tmp suffix path semantik
                # korunur, ffmpeg muxer kararı deterministik.
                "-f",
                "mp3",
                "-loglevel",
                "error",
                str(tmp),
            ],
            shell=False,
            # Phase 35-x: capture_output=True (stdout PIPE + stderr PIPE)
            # Windows dashboard process'inde subprocess deadlock yapıyordu —
            # parent process structlog/uvicorn stdio hijack edince çocuk
            # subprocess.run PIPE buffer'larında asılı kalıyor (canlı gözlem:
            # tek ffmpeg subprocess 120s timeout'a kadar hang, manuel terminal
            # aynı argv'yi <1s'de bitirirken). Explicit DEVNULL+PIPE setup pipe
            # routing sorununu çözer; -nostdin ffmpeg'in stdin'i sormamasını
            # garanti eder.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            log.warning(
                "tts.loudnorm_failed",
                path=str(path),
                rc=proc.returncode,
                dual_pass=pass1_stats is not None,
                stderr=proc.stderr.decode("utf-8", errors="replace")[:300],
            )
            return False
        os.replace(str(tmp), str(path))
        log.debug(
            "tts.loudnorm_ok",
            path=str(path),
            dual_pass=pass1_stats is not None,
        )
        return True
    except (OSError, subprocess.SubprocessError) as e:
        tmp.unlink(missing_ok=True)
        log.warning("tts.loudnorm_error", path=str(path), err=str(e)[:200])
        return False


async def apply_loudnorm(path: Path) -> bool:
    """Async wrapper — dual-pass default (Phase 35-iii)."""
    return await asyncio.to_thread(_apply_loudnorm_sync, path)


async def apply_per_segment_loudnorm(segments: list[Path]) -> int:
    """Phase 34-i: Her segment'i ayrı ayrı EBU R128 ``target_i`` LUFS'e normalize et.

    Concat ÖNCE çağrılır → speaker'lar arası loudness farkı yok.
    Concat SONRA tek pass için ``apply_loudnorm`` korunur (peak limiter güvencesi).

    Phase 35-ix: Concurrency 2 → 1 (sequential). 2 paralel ffmpeg subprocess
    Windows'ta libmp3lame shared DLL + subprocess.run capture_output pipe
    buffer deadlock'una yol açıyordu (canlı gözlem: aynı segment 120s
    timeout vurup retry'a düşüyor, manuel ffmpeg <1s'de bitirirken
    dashboard içinden ∞ hang). 34 segment × ~0.7s = 24s sequential —
    paralel marginal hız kazancı yerine deterministik tamamlanma.

    Returns:
        Başarılı normalize edilen segment sayısı (≤ len(segments)).
    """
    if not segments:
        return 0

    sem = asyncio.Semaphore(1)

    async def _guarded(p: Path) -> bool:
        async with sem:
            return await apply_loudnorm(p)

    results = await asyncio.gather(*(_guarded(p) for p in segments), return_exceptions=True)
    return sum(1 for r in results if r is True)


# ── Phase 32-v: Voice override storage (kullanıcı UI'dan seçim yapabilir) ──

# Tek-source of truth: data/voice_overrides.json. Provider-spesifik
# (Phase 35 sonrası yalnız ``elevenlabs`` namespace'i aktif). Schema::
#
#     {
#       "elevenlabs": {
#         "brief":   {"Filiz": "<voice_id>", ...},
#         "youtube": {"Filiz": "<voice_id>", ...}
#       }
#     }
#
# UI: ``/voices`` sayfası → her speaker için dropdown + preview butonu.
# Override yoksa ``PODCAST_VOICES_ELEVENLABS_*`` defaults kullanılır.

VOICE_OVERRIDES_FILENAME = "voice_overrides.json"


def _voice_overrides_path() -> Path:
    """Override JSON dosyasının resolved path'i.

    ``RASATHANE_VOICE_OVERRIDES_PATH`` env ile override edilebilir
    (test izolasyonu için). Default: ``data/voice_overrides.json``
    repo root'a göre.
    """
    env_path = os.environ.get("RASATHANE_VOICE_OVERRIDES_PATH")
    if env_path:
        return Path(env_path)
    # Repo root: packages/llm/src/llm/tts.py → 5 parent up
    here = Path(__file__).resolve()
    return here.parents[4] / "data" / VOICE_OVERRIDES_FILENAME


def load_voice_overrides() -> dict[str, Any]:
    """Voice override JSON dosyasını oku → dict. Yoksa boş dict döner.

    Bozuk JSON / okunamayan dosya → boş dict + warning log (corrupt
    config'in pipeline'ı patlatmasını engelle).
    """
    path = _voice_overrides_path()
    if not path.is_file():
        return {}
    try:
        # Phase 35-xi: `utf-8-sig` BOM tolerant (WinPS Set-Content BOM ekler).
        data = _json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            log.warning("tts.voice_overrides.invalid_root", path=str(path))
            return {}
        return data
    except (OSError, _json.JSONDecodeError) as e:
        log.warning("tts.voice_overrides.read_failed", path=str(path), err=str(e)[:200])
        return {}


def save_voice_overrides(data: dict[str, Any]) -> bool:
    """Override JSON dosyasını atomik yaz (.tmp + os.replace).

    Mevcut config'i ezer; partial update için önce ``load`` + merge yap.
    Returns True on success, False on IO error (warning loglanır).
    """
    path = _voice_overrides_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))
        return True
    except OSError as e:
        log.warning("tts.voice_overrides.write_failed", path=str(path), err=str(e)[:200])
        return False


def _voice_ids_from_agent_profiles(mode: str) -> dict[str, str]:
    """Phase 35-viii bridge: agent_profiles → speaker_name → voice_id dict.

    Stüdyo UI (Phase 35-ii, ``/voices`` sayfası) voice picker save'i
    ``data/agent_profiles.json``'a yapıyor (agent_id → voice_id schema).
    Brief audio pipeline ise `get_active_voice_mapping` üzerinden speaker
    name (Filiz/Mehmet/Burak) keyed mapping bekliyor. Bu helper iki
    schema arası bridge.

    KRİTİK: ``get_active_agent_profiles`` default agents fallback'i yapar
    (user dosyası yokken de İrem/Adam TR/Marcus TR döner). Bu davranış
    "no user override" durumunu maskeler → legacy `voice_overrides.json`
    hiç devreye giremez. Bu yüzden burada `load_agent_profiles` (raw)
    çağırıyoruz: user dosyası yoksa boş dict, var ise sadece user
    seçimleri. "User explicitly set" semantic'i korunur.

    Returns:
        Boş dict if agent_profiles.json yok veya boş schema.
        speaker_name → voice_id dict if user save yapmış.
    """
    user_profiles = load_agent_profiles()
    if not user_profiles:
        return {}
    agents = user_profiles.get("agents") or {}
    slots = (user_profiles.get("modes") or {}).get(mode, [])
    result: dict[str, str] = {}
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        agent_id = slot.get("agent_id")
        agent = agents.get(agent_id) if agent_id else None
        if not agent:
            continue
        name = agent.get("name")
        vid = agent.get("voice_id")
        if name and vid:
            result[name] = vid
    return result


def get_active_voice_mapping(
    *,
    provider: str,
    role: str,
    default_mapping: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Default voice mapping üzerine kullanıcı override'larını uygula.

    Override yalnız ``voice_id`` field'ını değiştirir; diğer ayarlar
    (stability/similarity_boost/style/use_speaker_boost) Phase 35-vii
    per-speaker anchor tuning'inden gelir.

    Phase 35-viii: Source-of-truth zinciri:
      1. ``agent_profiles.json`` (Stüdyo UI Phase 35-ii) — primary
      2. ``voice_overrides.json`` (legacy Phase 35-ii öncesi UI) — fallback
      3. ``default_mapping`` — TR-native sabit (İrem/Adam TR/Marcus TR)

    Args:
        provider: ``"elevenlabs"`` (Phase 35 sonrası tek provider).
            Diğer değerler verilirse default mapping döner.
        role:     ``"brief"`` | ``"youtube"``.
        default_mapping: ``PODCAST_VOICES_ELEVENLABS_BRIEF`` gibi.

    Returns:
        Merged mapping (default ile aynı schema).
    """
    agent_voice_ids = _voice_ids_from_agent_profiles(role)
    legacy_role_overrides = load_voice_overrides().get(provider, {}).get(role, {})
    if not agent_voice_ids and not legacy_role_overrides:
        return default_mapping
    merged: dict[str, dict[str, Any]] = {}
    for speaker, cfg in default_mapping.items():
        merged[speaker] = dict(cfg)
        # Önce Stüdyo UI (agent_profiles), sonra legacy voice_overrides
        new_voice_id = agent_voice_ids.get(speaker) or legacy_role_overrides.get(speaker)
        if new_voice_id:
            merged[speaker]["voice_id"] = new_voice_id
    return merged


# ── Phase 32-iv / 35-i: ElevenLabs cloud TTS provider (tek provider) ────

# Phase 32-v.2: TR-native voice library (Creator tier ile API'ye açık).
#
# ElevenLabs Voice Library'den trending Türk speaker'lar. multilingual_v2
# anglofon premade voice'larıyla "davalı" / "ithalat" / "Alomaliye" gibi
# TR-spesifik kelimeler yanlış okunuyordu (anglofon vokal kalıbı).
# TR-native voice'lar TR fonetik problemi otomatik çözer — "ithalat"
# İT-ha-LAT vurgusuyla doğru okur.
#
# Free tier'da library voice'ları API'den synth 402 verirdi; Creator+
# tier açar. Voice ID'ler ElevenLabs Voice Library trending listesinden
# (2026-05-19), `GET /v1/shared-voices?language=tr&sort=trending`.
ELEVENLABS_TR_NATIVE_VOICES: dict[str, str] = {
    # ── Kadın TR-native (sıralı: sıcak/profesyonel → enerjik/genç) ───
    "İrem": "hy7OAv1nH3Eqqj96Aude",  # middle/istanbul, "Velvet Acoustics & Fair"
    "Elvan": "JgYekNWmelei0oWTtYie",  # middle/standard, "Energetic, Soft and Warm"
    "Cansu": "SMRHdMmNcA5RcHlk7xCP",  # young/standard, "Young and Soft"
    "Ayça": "5RqXmIU9ikjifeWoXHMG",  # young/istanbul, "Young and Energetic"
    "Emma TR": "8D6p2rXeXWggXKx2gWiS",  # middle/standard, "Encouraging, Smooth"
    "Tomris": "WPM2QtArXxz4qN0t9rNk",  # female (üst trending, "Real natural Turkish")
    "Deniz": "KAGDtM2gzDrjWlUp2KNe",  # young/istanbul, "Soft, Friendly Narrator"
    "Nergis": "IgiCa6883ksPGir0tfNK",  # middle/standard, "Strong, Realistic, Clean"
    "Derya": "NNn9dv8zq2kUo7d3JSGG",  # young/standard, "Dynamic and Friendly Narrator"
    # ── Erkek TR-native (sıralı: otoriter/derin → genç/enerjik) ──────
    "Ozan": "kDaVLqYrOl8ui891kCrV",  # young/istanbul, "Calm, Clear, Confident young adult, inspires trust"
    "Burak Namlı": "04SEuljgeCeHgjzEyD4c",  # middle/istanbul, "Deep, Calm and Serious"
    "Fatih Yıldırım": "7VqWGAWwo2HMrylfKrcm",  # middle/istanbul, "Deep, Clear"
    "Marcus TR": "2PwDxni9MpXdYqgALrBh",  # middle/istanbul, "Warm, Clear, Professional"
    "Adam TR": "RXCCWbOxP7Hisa63Xsv5",  # middle/istanbul, "Calm, Relaxing, Informative"
    "Emin": "DsbR47WNEv8o9x37ib9X",  # middle/standard, "Deep, Muffled, Soft"
    "Recep Sağlık": "QAABwpMjK3YR9pYW5FDO",  # old/istanbul, "Mature, Deep, Clear"
    "Mustafa Silici": "fg8pljYEn5ahwjyOQaro",  # middle/istanbul, Voice Actor
    "Fatih Çetinkaya": "DM4ogDUNaqwcuIIRkVZK",  # middle/istanbul, "Storyteller"
    "Cavit Pancar": "Y2T2O1csKPgWgyuKcU0a",  # middle/istanbul, "Epic, Powerful, Historical"
    "Ali": "xROJDAAwVXltxzeQxuFL",  # young/standard, "Energetic, Encouraging, Young"
    "David TR": "5uEJotkO1FzLxXhXsgIv",  # middle/eastern, "Assertive, Charismatic"
    "Hakan Yayla": "23juXLe6iBUtKIH1h9iH",  # middle/istanbul, "Robotic, Imposing Villain"
}

# Anglofon "premade" voice ID'leri (hesaba shipping'le gelen 21 voice).
# Backward-compat + alternatif seçim için tutulur. TR-native voice'lar
# default; kullanıcı /voices dropdown'undan bunları seçebilir.
ELEVENLABS_DEFAULT_VOICES: dict[str, str] = {
    # TR-native (Creator tier ile aktif) — default öncelikli
    **ELEVENLABS_TR_NATIVE_VOICES,
    # Anglofon premade (her tier accessible) — alternatif
    "Sarah": "EXAVITQu4vr4xnSDxMaL",  # kadın, profesyonel
    "Alice": "Xb7hH8MSUJpSbSDYk0k2",  # kadın, educator
    "Matilda": "XrExE9yKIg1WjnnlVkGX",  # kadın, professional
    "Lily": "pFZP5JQG7iQjIQuC4Bku",  # kadın, british
    "Adam": "pNInz6obpgDQGcFmaJgB",  # erkek, dominant
    "Brian": "nPczCjzI2devNBz1zQrb",  # erkek, deep
    "George": "JBFqnCBsd6RMkjVDRZzb",  # erkek, british
    "Daniel": "onwK4e9ZLuTAKqWW03F9",  # erkek, british, broadcaster
    "Liam": "TX3LPaxmHKxFdv7VOQHJ",  # erkek, energetic
    "Eric": "cjVigY5qzO86Huf0OWal",  # erkek, smooth
    "Chris": "iP95p4xoKVk53GoZ742B",  # erkek, charming
}

# Phase 35-xi: Stüdyo voice picker whitelist.
#
# Sadece bu set'teki voice'lar `/api/tts/voices` response'unda gösterilir.
# Mantık: Stüdyo'da seçilebilen her voice brief audio + analiz pipeline'ında
# **garanti çalışmalı** — kullanıcı seçtikten sonra ffmpeg loudnorm
# subprocess'inde hung kalmamalı, mp3 sample rate uyumsuz olmamalı.
#
# Şu an iki kategori:
#   1. ELEVENLABS_TR_NATIVE_VOICES (21 voice) — multilingual_v2 modeliyle
#      TR fonetik native handle eder; Phase 32-v.2'de hepsi test edildi.
#   2. Matilda (anglofon kadın) — Phase 35-x canlı pipeline test'inde
#      ffmpeg loudnorm uyumu doğrulandı (input_i=-15.04 LUFS, normalize 28/28).
#
# Anglofon erkek baritone voice'lar (Bill, Brian, Adam, George, Daniel, vb.)
# Phase 35-x öncesi DEVNULL fix'le hung yapıyordu; teknik olarak şimdi
# çalışabilir AMA validation yapılmadı → whitelist dışı. İleride per-voice
# validation job (kısa ffmpeg loudnorm dene + cache) eklenirse otomatik
# genişletilebilir.
SELECTABLE_VOICE_IDS: frozenset[str] = frozenset(
    [
        *ELEVENLABS_TR_NATIVE_VOICES.values(),
        ELEVENLABS_DEFAULT_VOICES["Matilda"],
    ]
)

# Phase 35-i: ElevenLabs API hard default'lar — `_synthesize_elevenlabs_segment`
# (single-voice library audio) ve unknown-speaker fallback için baseline.
# Phase 35-vii'den itibaren multi-speaker podcast mapping'leri (BRIEF/YOUTUBE)
# bu default'u override eder (per-speaker anchor profili).
_DEFAULT_VOICE_SETTINGS: dict[str, Any] = {
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.0,
    "use_speaker_boost": True,
}

# Phase 35-vii: per-speaker anchor tuning (Phase 34-v 0f41303 değerleri restore).
# Phase 35-i'in `_DEFAULT_VOICE_SETTINGS` spread'i tüm voice'leri style=0.0'a
# (narrator-flat) çekti — kullanıcı raporu "Filiz/Burak masal anlatır gibi +
# Mehmet yarı yarıya kısık" Phase 34-v'in tam çözdüğü sorunla aynı. Anchor
# için style 0.30-0.40 (expression), similarity_boost 0.78 (yüksek voice
# fidelity), stability 0.50-0.55 (tutarlı ama monoton değil).
PODCAST_VOICES_ELEVENLABS_BRIEF: dict[str, dict[str, Any]] = {
    "Filiz": {
        "voice_id": ELEVENLABS_TR_NATIVE_VOICES["İrem"],
        "stability": 0.50,
        "similarity_boost": 0.78,
        "style": 0.40,
        "use_speaker_boost": True,
    },
    "Mehmet": {
        "voice_id": ELEVENLABS_TR_NATIVE_VOICES["Adam TR"],
        "stability": 0.50,
        "similarity_boost": 0.75,
        "style": 0.30,
        "use_speaker_boost": True,
    },
    "Burak": {
        "voice_id": ELEVENLABS_TR_NATIVE_VOICES["Ozan"],
        "stability": 0.55,
        "similarity_boost": 0.78,
        "style": 0.40,
        "use_speaker_boost": True,
    },
}

PODCAST_VOICES_ELEVENLABS_YOUTUBE: dict[str, dict[str, Any]] = {
    "Filiz": {
        "voice_id": ELEVENLABS_TR_NATIVE_VOICES["İrem"],
        "stability": 0.50,
        "similarity_boost": 0.78,
        "style": 0.40,
        "use_speaker_boost": True,
    },
    "Burak": {
        "voice_id": ELEVENLABS_TR_NATIVE_VOICES["Ozan"],
        "stability": 0.55,
        "similarity_boost": 0.78,
        "style": 0.40,
        "use_speaker_boost": True,
    },
    "Esra": {
        "voice_id": ELEVENLABS_TR_NATIVE_VOICES["Tomris"],
        "stability": 0.45,
        "similarity_boost": 0.78,
        "style": 0.50,
        "use_speaker_boost": True,
    },
}

# Resolved at call time so tests can monkeypatch.
ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
ELEVENLABS_MODEL_ID = "eleven_multilingual_v2"
ELEVENLABS_TIMEOUT_SECONDS = 90


async def _synthesize_elevenlabs_segment(
    *,
    text: str,
    output_path: Path,
    voice_id: str,
    api_key: str,
    stability: float,
    similarity_boost: float,
    style: float,
    use_speaker_boost: bool = True,
    model_id: str = ELEVENLABS_MODEL_ID,
) -> None:
    """Tek segment ElevenLabs API çağrısı → MP3 dosyası.

    Endpoint: ``POST /v1/text-to-speech/{voice_id}``. Response audio/mpeg.
    ElevenLabs MP3'ü doğrudan döner.

    Raises:
        RuntimeError: API key yok, network fail, veya non-200 status.
    """
    import httpx

    url = f"{ELEVENLABS_BASE_URL}/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
            "use_speaker_boost": use_speaker_boost,
        },
    }
    async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT_SECONDS) as client:
        response = await client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"ElevenLabs API {response.status_code}: {response.text[:300]}")
        audio_bytes = response.content
    if not audio_bytes:
        raise RuntimeError("ElevenLabs empty audio response")
    await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(output_path.write_bytes, audio_bytes)


def _ffmpeg_concat_sync(segment_paths: list[Path], output_path: Path) -> None:
    """Sync core: ffmpeg ile mp3 segment'leri tek dosyaya concat.

    Strateji: ``ffmpeg -f concat -safe 0 -i list.txt -c copy out.mp3`` —
    transcode yok, sadece container-rewrite. Bütün segment'lerin aynı
    codec/sample rate'i olduğundan emin (ElevenLabs MP3 standart 44.1kHz
    128kbps mono).

    Concat liste dosyası tempfile'da:
        file '<absolute path to seg1.mp3>'
        file '<absolute path to seg2.mp3>'

    Raises RuntimeError ffmpeg fail ederse veya ffmpeg PATH'te yoksa.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg PATH'te yok — multi-voice podcast birleştirilemez")
    if not segment_paths:
        raise ValueError("Empty segment list")

    # Concat list dosyası
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        list_path = Path(f.name)
        for seg in segment_paths:
            # ffmpeg concat demuxer: backslash + single quote escape
            # Windows path'lerde \ → / kullanmak en güvenli yol
            safe_path = str(seg.resolve()).replace("\\", "/")
            f.write(f"file '{safe_path}'\n")

    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                "-loglevel",
                "error",
                str(output_path),
            ],
            shell=False,
            capture_output=True,
            timeout=120,
        )
        if proc.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
            stderr = proc.stderr.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"ffmpeg concat failed (rc={proc.returncode}): {stderr}")
    finally:
        list_path.unlink(missing_ok=True)


def _cleanup_workdir_sync(workdir: Path, segments: list[Path]) -> None:
    """Sync cleanup helper — async cleaner ASYNC240 ihlal eder."""
    import contextlib

    for seg in segments:
        seg.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        workdir.rmdir()


async def synthesize_to_mp3(
    text: str,
    *,
    output_path: Path,
    voice_id: str | None = None,
    stability: float = 0.5,
    similarity_boost: float = 0.75,
    style: float = 0.0,
    use_speaker_boost: bool = True,
    apply_transliteration: bool = True,
) -> Path:
    """Phase 35-i: ElevenLabs ile tek-spiker Türkçe TTS → MP3.

    Önceki Phase 17-iii Edge-TTS path Phase 35-i'de silindi. Bu fonksiyon
    artık ``_synthesize_elevenlabs_segment`` reuse ile çalışır; library
    audio özet (`library.py`) ve deep_analyze tek-spiker fallback
    (`deep_analyze.py:1299`) tarafından çağrılır.

    Args:
        text: TTS girdisi (sade düz metin — markdown link/bold/list yok).
        output_path: target mp3 path (parent dir yoksa oluşturulur).
        voice_id: ElevenLabs voice_id. None ise default Filiz/İrem
            (TR-native kadın, sıcak/profesyonel).
        stability / similarity_boost / style / use_speaker_boost: ElevenLabs
            voice settings — default'lar API hard default'una (0.5 / 0.75 /
            0.0 + speaker boost ON) eşitlendi.
        apply_transliteration: True ise EN kısaltma + TR sayı/ordinal
            transliterasyonu uygulanır (ElevenLabs multilingual_v2 model
            için garanti hattı).

    Returns:
        output_path (absolute).

    Raises:
        RuntimeError: ELEVENLABS_API_KEY env yok veya senthez başarısız.
        ValueError: text boş veya yalnız whitespace.
    """
    if not text or not text.strip():
        raise ValueError("Cannot synthesize empty text")

    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY env tanımlı değil. "
            "https://elevenlabs.io > Profile > API Key."
        )

    if voice_id is None:
        # Default: Filiz / İrem — TR-native kadın, sıcak/profesyonel
        voice_id = ELEVENLABS_TR_NATIVE_VOICES["İrem"]

    if apply_transliteration:
        text = transliterate_short_acronyms(text)

    await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
    await _synthesize_elevenlabs_segment(
        text=text,
        output_path=output_path,
        voice_id=voice_id,
        api_key=api_key,
        stability=stability,
        similarity_boost=similarity_boost,
        style=style,
        use_speaker_boost=use_speaker_boost,
    )

    is_file = await asyncio.to_thread(output_path.is_file)
    bytes_out = await asyncio.to_thread(lambda: output_path.stat().st_size)
    if not is_file or bytes_out == 0:
        raise RuntimeError("ElevenLabs wrote empty/missing file")

    # Phase 32-v: ses mühendisi loudnorm + Xing header (browser duration)
    loudnorm_ok = await apply_loudnorm(output_path)
    xing_ok = await inject_xing_header(output_path)

    log.info(
        "tts.synthesized",
        chars_in=len(text),
        bytes_out=bytes_out,
        voice_id=voice_id,
        loudnorm=loudnorm_ok,
        xing_header=xing_ok,
        path=str(output_path),
    )
    return output_path


async def synthesize_podcast(
    *,
    dialog: list[dict[str, Any]],
    output_path: Path,
    voices: dict[str, dict[str, Any]],
    apply_transliteration: bool = True,
    fallback_voice_id: str | None = None,
) -> Path:
    """Phase 35-i: Multi-konuşmacı podcast — ElevenLabs (tek provider).

    Önceki Phase 17-iii Edge-TTS path ve Phase 32-iii Coqui XTTS-v2 path
    Phase 35-i'de silindi. Bu fonksiyon eski ``synthesize_podcast_elevenlabs``
    rename'idir; tek tüketici-yön caller olarak `core/brief.py` ve
    `core/deep_analyze.py` tarafından çağrılır.

    Pipeline:
      1. ``ELEVENLABS_API_KEY`` env oku; yoksa RuntimeError.
      2. Her dialog satırı → ``transliterate_short_acronyms`` (opsiyonel) →
         ElevenLabs POST → MP3 bytes → tmp dosya.
      3. Per-segment loudnorm (speaker'lar arası loudness eşitleme).
      4. ``ffmpeg -f concat`` ile mp3 segment'leri birleştir.
      5. Final mp3'e ``apply_loudnorm`` (peak limiter) + ``inject_xing_header``
         (browser duration).

    Args:
        dialog: ``[{"speaker": "Filiz", "text": "..."}, ...]``.
        output_path: target MP3 path.
        voices: speaker_name → {voice_id, stability, similarity_boost, style,
            use_speaker_boost}. ``PODCAST_VOICES_ELEVENLABS_BRIEF`` veya
            ``YOUTUBE`` mapping.
        apply_transliteration: True ise EN kısaltmalar TR fonetik yazılışa
            çevrilir (ElevenLabs multilingual_v2 model çoğu durumda doğru
            okur; ama "AI", "MoE" gibi 2-3 harfli kısaltmalar için yardımcı).
        fallback_voice_id: ``voices``'ta tanımsız speaker için preset
            voice_id (default: Sarah — anglofon kadın, premade).

    Returns:
        ``output_path``.

    Raises:
        RuntimeError: ELEVENLABS_API_KEY env yok, network fail, API hatası.
        ValueError: dialog boş veya tüm satırlar invalid.
    """
    if not dialog:
        raise ValueError("Empty dialog list")
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY env tanımlı değil. "
            "https://elevenlabs.io > Profile > API Key."
        )

    if fallback_voice_id is None:
        fallback_voice_id = ELEVENLABS_DEFAULT_VOICES["Sarah"]

    workdir = Path(tempfile.mkdtemp(prefix="rasathane_podcast_11l_"))
    mp3_segments: list[Path] = []
    skipped = 0

    try:
        for i, line in enumerate(dialog):
            speaker_name = (line.get("speaker") or "").strip()
            text = (line.get("text") or "").strip()
            if not text:
                skipped += 1
                log.warning(
                    "podcast_elevenlabs.segment_skip_empty",
                    index=i,
                    speaker=speaker_name,
                )
                continue

            voice_cfg = voices.get(speaker_name)
            if voice_cfg is None:
                log.warning(
                    "podcast_elevenlabs.unknown_speaker",
                    index=i,
                    speaker=speaker_name,
                    falling_back=fallback_voice_id,
                )
                voice_cfg = {
                    "voice_id": fallback_voice_id,
                    **_DEFAULT_VOICE_SETTINGS,
                }

            if apply_transliteration:
                text = transliterate_short_acronyms(text)

            mp3_path = workdir / f"seg_{i:03d}_{speaker_name}.mp3"
            await _synthesize_elevenlabs_segment(
                text=text,
                output_path=mp3_path,
                voice_id=str(voice_cfg.get("voice_id", fallback_voice_id)),
                api_key=api_key,
                stability=float(voice_cfg.get("stability", 0.5)),
                similarity_boost=float(voice_cfg.get("similarity_boost", 0.75)),
                style=float(voice_cfg.get("style", 0.0)),
                use_speaker_boost=bool(voice_cfg.get("use_speaker_boost", True)),
            )
            mp3_segments.append(mp3_path)

        if not mp3_segments:
            raise ValueError("All dialog lines skipped (empty text)")

        await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
        # Phase 34-i: per-segment loudnorm — speaker'lar arası loudness farkı
        # concat öncesi eşitlenir; final pass peak limiter olarak korunur.
        normalized_count = await apply_per_segment_loudnorm(mp3_segments)
        log.info(
            "podcast.per_segment_loudnorm",
            total=len(mp3_segments),
            normalized=normalized_count,
        )

        await asyncio.to_thread(_ffmpeg_concat_sync, mp3_segments, output_path)
        # Phase 35: loudnorm EBU R128 (Apple Podcasts I=-16, LRA=11)
        loudnorm_ok = await apply_loudnorm(output_path)
        xing_ok = await inject_xing_header(output_path)

        bytes_out = await asyncio.to_thread(lambda: output_path.stat().st_size)
        log.info(
            "podcast_elevenlabs.synthesized",
            segments=len(mp3_segments),
            skipped=skipped,
            speakers=list({line.get("speaker") for line in dialog if line.get("speaker")}),
            bytes_out=bytes_out,
            loudnorm=loudnorm_ok,
            xing_header=xing_ok,
            transliteration=apply_transliteration,
            path=str(output_path),
        )
        return output_path
    finally:
        await asyncio.to_thread(_cleanup_workdir_sync, workdir, mp3_segments)
