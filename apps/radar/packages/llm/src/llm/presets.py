"""Phase 36-ii: Audio preset sistemi.

Default 4 preset (kod sabit) + opsiyonel user preset listesi
(data/audio_presets.json). Analiz sayfasında "Yeniden üret" butonu
preset_id ile çalışır; deep_analyze.audio_only() resolve eder.

BOM defensive (Phase 35-xi pattern) + atomic write.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()


@dataclass
class AudioPreset:
    """Bir ses üretim ayarı paketi (format + prompt + voice override + settings)."""

    id: str
    name: str
    description: str
    format: str  # "panel_3" | "duo_expert_critic" | "solo_narrator" | "debate"
    prompt_variant: str  # prompts/{prompt_variant}.md
    target_minutes: tuple[float, float]
    voices: dict[str, str] = field(default_factory=dict)
    voice_settings: dict[str, dict[str, float]] = field(default_factory=dict)
    is_default: bool = False


DEFAULT_PRESETS: list[AudioPreset] = [
    AudioPreset(
        id="klasik_panel",
        name="Klasik Panel",
        description="Mevcut 3-sesli panel (Filiz/Burak/Esra), 4-7 dk profesyonel haber bülteni tonu.",
        format="panel_3",
        prompt_variant="youtube_podcast_script",
        target_minutes=(4.0, 7.0),
        is_default=True,
    ),
    AudioPreset(
        id="hizli_brifing",
        name="Hızlı Brifing",
        description="Tek-sesli (Filiz) 1-2 dk özet, 3 ana noktayı sıkıştırır.",
        format="solo_narrator",
        prompt_variant="youtube_podcast_script_fast",
        target_minutes=(1.0, 2.0),
        # Spec §4.2: Filiz'i TR-native İrem'e pin'le; kullanıcının
        # agent_profiles.json'daki anglofon override'ları (örn. Matilda)
        # hızlı brifing akışını ezmesin. ID = ELEVENLABS_TR_NATIVE_VOICES["İrem"]
        # (tts.py:1073). Hardcoded — tts.py import circular dependency riskini önler.
        voices={"Filiz": "hy7OAv1nH3Eqqj96Aude"},
        is_default=True,
    ),
    AudioPreset(
        id="derin_uzman",
        name="Derin Uzman",
        description="2-sesli (Filiz + Burak) 6-12 dk derin teknik açılım, Esra yok.",
        format="duo_expert_critic",
        prompt_variant="youtube_podcast_script_deep",
        target_minutes=(6.0, 12.0),
        is_default=True,
    ),
    AudioPreset(
        id="elestirel_munazara",
        name="Eleştirel Münazara",
        description="Burak vs Esra dönüşümlü çarpışma, 5-8 dk; Filiz minimal moderatör.",
        format="debate",
        prompt_variant="youtube_podcast_script_debate",
        target_minutes=(5.0, 8.0),
        voice_settings={"Esra": {"style": 0.60}},
        is_default=True,
    ),
]


def _preset_path() -> Path:
    """Workspace-relative `data/audio_presets.json` path'i."""
    # rasathane_mcp paketinde py.typed marker yok — cross-package import
    # uyarısı baseline'da deep_analyze.py'de de var (store/ingestion).
    from rasathane_mcp.core.paths import data_dir

    return Path(data_dir()) / "audio_presets.json"


def _atomic_write_text(path: Path, content: str) -> None:
    """Phase 35-iii pattern: tmp dosyaya yaz, sonra atomik rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def _preset_from_dict(d: dict[str, Any]) -> AudioPreset:
    """Dict'ten AudioPreset üret; tuple konversiyonu burada."""
    return AudioPreset(
        id=d["id"],
        name=d["name"],
        description=d.get("description", ""),
        format=d["format"],
        prompt_variant=d["prompt_variant"],
        target_minutes=(
            float(d["target_minutes"][0]),
            float(d["target_minutes"][1]),
        ),
        voices=dict(d.get("voices", {})),
        voice_settings={
            k: dict(v) for k, v in d.get("voice_settings", {}).items()
        },
        is_default=bool(d.get("is_default", False)),
    )


def load_user_presets(path: Path | None = None) -> list[AudioPreset]:
    """User preset listesi; dosya yok veya bozuksa boş list (sorunsuz)."""
    p = path or _preset_path()
    if not p.is_file():
        return []
    try:
        # Phase 35-xi: utf-8-sig BOM tolerantı
        raw = p.read_text(encoding="utf-8-sig")
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("presets.load_failed", path=str(p), error=str(e))
        return []
    if not isinstance(data, list):
        log.warning("presets.load_wrong_shape", path=str(p))
        return []
    out: list[AudioPreset] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            preset = _preset_from_dict(item)
        except (KeyError, TypeError, ValueError) as e:
            log.warning("presets.item_invalid", error=str(e))
            continue
        # User presets her zaman is_default=False (kodda override etmesin)
        preset.is_default = False
        out.append(preset)
    return out


def save_user_presets(
    presets: list[AudioPreset], path: Path | None = None
) -> None:
    """User preset listesini atomik yaz; is_default=False zorunlu."""
    p = path or _preset_path()
    payload = [
        {
            **asdict(pr),
            "target_minutes": list(pr.target_minutes),
            "is_default": False,
        }
        for pr in presets
    ]
    _atomic_write_text(p, json.dumps(payload, ensure_ascii=False, indent=2))


def get_active_presets(path: Path | None = None) -> list[AudioPreset]:
    """Defaults + user presets, ID unique (default'lar öncelikli)."""
    defaults_by_id = {p.id: p for p in DEFAULT_PRESETS}
    user = load_user_presets(path)
    user_filtered = [p for p in user if p.id not in defaults_by_id]
    return list(DEFAULT_PRESETS) + user_filtered


def resolve_preset(
    preset_id: str, path: Path | None = None
) -> AudioPreset:
    """ID ile preset bul; yoksa `klasik_panel` fallback + warning log."""
    for p in get_active_presets(path):
        if p.id == preset_id:
            return p
    log.warning("preset.unknown_id_fallback", requested=preset_id)
    return DEFAULT_PRESETS[0]
