"""Phase 12-ii: brief generation pipeline tests.

Lockfile + atomic file write + claude subprocess (mocked).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rasathane_mcp.core.brief import (
    LOCKFILE_NAME,
    LOCKFILE_STALE_SECONDS,
    _acquire_lockfile,
    _check_lockfile,
    generate_brief,
    load_brief,
)


@pytest.mark.asyncio
async def test_load_brief_returns_generating_payload_when_lockfile_present(
    tmp_path: Path,
) -> None:
    """Lockfile fresh → ``generating: true`` + elapsed döner."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    target = tmp_path / today
    target.mkdir()
    (target / LOCKFILE_NAME).write_text(
        json.dumps(
            {
                "started_at": datetime.now(UTC).isoformat(),
                "pid": 9999,
                "cmd": "claude",
            }
        ),
        encoding="utf-8",
    )

    result = load_brief(archive_root=tmp_path, date=today)

    assert result["generating"] is True
    assert "started_at" in result
    assert isinstance(result["elapsed_sec"], int)
    assert result["elapsed_sec"] >= 0


def test_check_lockfile_stale_returns_none_and_cleans_up(tmp_path: Path) -> None:
    """Stale lockfile (>10dk) None döner VE diskten silinir.

    Orphan senaryosu (subprocess çakıldı + dashboard restart): read-side
    cleanup olmadan UI bir sonraki generate'e kadar yapay 'generating'
    state'inde takılı kalırdı.
    """
    target = tmp_path / "2026-01-01"
    target.mkdir()
    stale_iso = (datetime.now(UTC) - timedelta(seconds=LOCKFILE_STALE_SECONDS + 60)).isoformat()
    lockfile = target / LOCKFILE_NAME
    lockfile.write_text(
        json.dumps({"started_at": stale_iso, "pid": 1, "cmd": "claude"}),
        encoding="utf-8",
    )

    result = _check_lockfile(target, "2026-01-01")

    assert result is None
    assert not lockfile.is_file()


def test_check_lockfile_corrupt_json_returns_none_and_cleans_up(tmp_path: Path) -> None:
    """Bozuk JSON lockfile silinir; aksi halde ebediyen takılır."""
    target = tmp_path / "2026-01-02"
    target.mkdir()
    lockfile = target / LOCKFILE_NAME
    lockfile.write_text("{ not valid json", encoding="utf-8")

    result = _check_lockfile(target, "2026-01-02")

    assert result is None
    assert not lockfile.is_file()


def test_acquire_lockfile_atomic_concurrent_create(tmp_path: Path) -> None:
    """O_CREAT|O_EXCL guard'ı: ikinci create FileExistsError fırlatır."""
    target = tmp_path / "2026-05-07"

    lockfile = _acquire_lockfile(target)
    assert lockfile.is_file()

    with pytest.raises(FileExistsError):
        _acquire_lockfile(target)


def test_acquire_lockfile_clears_stale(tmp_path: Path) -> None:
    """Stale lockfile (>10dk) varsa silinir, fresh oluşturulur."""
    target = tmp_path / "2026-05-07"
    target.mkdir()
    stale_iso = (datetime.now(UTC) - timedelta(seconds=LOCKFILE_STALE_SECONDS + 60)).isoformat()
    (target / LOCKFILE_NAME).write_text(
        json.dumps({"started_at": stale_iso, "pid": 99999, "cmd": "claude"}),
        encoding="utf-8",
    )

    lockfile = _acquire_lockfile(target)

    assert lockfile.is_file()
    # Yeni içerik fresh started_at olmalı
    data = json.loads(lockfile.read_text(encoding="utf-8"))
    started = datetime.fromisoformat(data["started_at"])
    assert (datetime.now(UTC) - started).total_seconds() < 10


@pytest.mark.asyncio
async def test_generate_brief_409_when_already_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """force=False + bugünün brief'i var → ``already_exists`` error."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    target = tmp_path / today
    target.mkdir()
    (target / "00-brief.md").write_text("# Var olan brief", encoding="utf-8")

    session = MagicMock()

    result = await generate_brief(session, archive_root=tmp_path, force=False)

    assert result.get("error") == "already_exists"
    assert "generated_at" in result


@pytest.mark.asyncio
async def test_generate_brief_writes_atomic_via_tmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successful path: claude stdout → archive/YYYY-MM-DD/00-brief.md."""

    async def fake_synthesize(prompt: str, **kw):  # type: ignore[no-untyped-def]
        return "## Türk Hukuku\n- Test maddesi (Test Source)"

    async def fake_gather(_session):
        # Phase 33-i: tuple (text, articles_list)
        return ("## turk_hukuku\n- Test article", [])

    monkeypatch.setattr("rasathane_mcp.core.brief.synthesize_with_claude", fake_synthesize)
    monkeypatch.setattr("rasathane_mcp.core.brief._gather_articles_grouped", fake_gather)

    session = MagicMock()
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    result = await generate_brief(session, archive_root=tmp_path, force=False)

    assert "started_at" in result
    assert result.get("date") == today

    # Dosya yazıldı, lockfile temizlendi
    brief_path = tmp_path / today / "00-brief.md"
    assert brief_path.is_file()
    assert "Türk Hukuku" in brief_path.read_text(encoding="utf-8")
    assert not (tmp_path / today / LOCKFILE_NAME).is_file()


@pytest.mark.asyncio
async def test_generate_brief_writes_last_error_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Subprocess fail → .last-error.txt yazılır, lockfile temizlenir."""

    async def fake_synthesize(prompt: str, **kw):  # type: ignore[no-untyped-def]
        raise RuntimeError("claude rate limited")

    async def fake_gather(_session):
        # Phase 33-i: tuple (text, articles_list)
        return ("## turk_hukuku\n- Test", [])

    monkeypatch.setattr("rasathane_mcp.core.brief.synthesize_with_claude", fake_synthesize)
    monkeypatch.setattr("rasathane_mcp.core.brief._gather_articles_grouped", fake_gather)

    session = MagicMock()
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    result = await generate_brief(session, archive_root=tmp_path, force=False)

    assert result.get("error") == "generation_failed"
    last_error_path = tmp_path / today / ".last-error.txt"
    assert last_error_path.is_file()
    assert "rate limited" in last_error_path.read_text(encoding="utf-8")
    # Lockfile cleanup
    assert not (tmp_path / today / LOCKFILE_NAME).is_file()


# ── Phase 22-iii: brief audio (sesli okuma) ──────────────────────────


@pytest.mark.asyncio
async def test_generate_brief_audio_returns_brief_missing_when_no_md(
    tmp_path: Path,
) -> None:
    """archive/{date}/00-brief.md yoksa → brief_missing."""
    from rasathane_mcp.core.brief import generate_brief_audio

    out = await generate_brief_audio(archive_root=tmp_path, date="2026-05-08")
    assert out["status"] == "brief_missing"


@pytest.mark.asyncio
async def test_generate_brief_audio_returns_already_exists_when_mp3_present(
    tmp_path: Path,
) -> None:
    """00-brief.mp3 zaten varsa cache döner."""
    from rasathane_mcp.core.brief import generate_brief_audio

    date = "2026-05-08"
    target = tmp_path / date
    target.mkdir(parents=True)
    (target / "00-brief.md").write_text("# Brief\n\nİçerik", encoding="utf-8")
    (target / "00-brief.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 100)

    out = await generate_brief_audio(archive_root=tmp_path, date=date)
    assert out["status"] == "already_exists"
    assert out["audio_url"].endswith("/00-brief.mp3")


@pytest.mark.asyncio
async def test_generate_brief_audio_synthesizes_mp3_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 32-ii: Brief var, mp3 yok → claude 3-konuşmacı podcast JSON → multi-voice TTS.

    Eski test tek-spiker akışını test ediyordu. Yeni akış:
      1. claude → JSON dialog array (Filiz/Mehmet/Burak)
      2. brief.py _parse_podcast_dialog parse eder
      3. synthesize_podcast (multi-voice + ffmpeg concat) mp3 üretir
      4. Debug dosyası 00-brief.audio.json (eski .txt yerine)
    """
    from rasathane_mcp.core.brief import generate_brief_audio

    date = "2026-05-08"
    target = tmp_path / date
    target.mkdir(parents=True)
    (target / "00-brief.md").write_text("# Bugün\n\n## Türk Hukuku\n- AYM kararı", encoding="utf-8")

    async def fake_claude(prompt, *, timeout_seconds=None):
        # Yeni prompt: brief_podcast_script.md — 3 konuşmacı + tarih TR
        assert "AYM" in prompt
        # Tarih TR formatta render edilmeli ("8 Mayıs 2026 Cuma" gibi)
        assert "Mayıs" in prompt
        return (
            "[\n"
            '  {"speaker": "Filiz", "text": "Bugün 8 Mayıs 2026 Cuma."},\n'
            '  {"speaker": "Mehmet", "text": "Anayasa Mahkemesinde önemli bir karar var."},\n'
            '  {"speaker": "Burak", "text": "AI tarafında da gelişmeler oldu."}\n'
            "]"
        )

    async def fake_podcast(*, dialog, output_path, voices, **_kwargs):
        # Multi-voice mock — gerçek ElevenLabs + ffmpeg çağrılmaz (Phase 35-i)
        assert len(dialog) == 3
        speakers = {d["speaker"] for d in dialog}
        assert speakers == {"Filiz", "Mehmet", "Burak"}
        assert set(voices.keys()) == {"Filiz", "Mehmet", "Burak"}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\xff\xfb" + b"\x00" * 200)
        return output_path

    monkeypatch.setattr("rasathane_mcp.core.brief.synthesize_with_claude", fake_claude)
    monkeypatch.setattr("llm.tts.synthesize_podcast", fake_podcast)

    out = await generate_brief_audio(archive_root=tmp_path, date=date)
    assert out["status"] == "done"
    assert out["segments"] == 3
    assert (target / "00-brief.mp3").is_file()
    # Yeni JSON format
    assert (target / "00-brief.audio.json").is_file()
    audio_json = (target / "00-brief.audio.json").read_text(encoding="utf-8")
    assert "Filiz" in audio_json
    assert "Mehmet" in audio_json
    assert "Anayasa" in audio_json


@pytest.mark.asyncio
async def test_generate_brief_audio_invalid_date_format(
    tmp_path: Path,
) -> None:
    """Geçersiz date string → failed."""
    from rasathane_mcp.core.brief import generate_brief_audio

    out = await generate_brief_audio(archive_root=tmp_path, date="not-a-date")
    assert out["status"] == "failed"
    assert "invalid date" in out["detail"]


# ── Phase 24: brief markdown'undan analizlenebilir link çıkarma ──────


def test_extract_analyzable_urls_returns_empty_for_plain_text() -> None:
    """Markdown link içermiyorsa boş liste."""
    from rasathane_mcp.core.brief import extract_analyzable_urls

    assert extract_analyzable_urls("Düz metin, link yok.") == []


def test_extract_analyzable_urls_filters_only_supported_types() -> None:
    """News makalesi linkleri (haber siteleri) atlanır; sadece youtube/
    github/arxiv döner."""
    from rasathane_mcp.core.brief import extract_analyzable_urls

    md = (
        "Bu hafta [Stanford analizi](https://www.youtube.com/watch?v=dQw4w9WgXcQ) "
        "çıktı. [Hukuki Haber](https://hukukihaber.net/site-aidatlari) ise "
        "[anthropic SDK](https://github.com/anthropics/anthropic-sdk-python) "
        "ve [arXiv paper](https://arxiv.org/abs/2511.01234) ile birlikte "
        "[Webrazzi haberi](https://webrazzi.com/2026/05/07/snap)."
    )
    out = extract_analyzable_urls(md)
    types = [item["type"] for item in out]
    assert types == ["youtube", "github", "arxiv"]
    assert all("hukukihaber" not in item["url"] for item in out)
    assert all("webrazzi" not in item["url"] for item in out)


def test_extract_analyzable_urls_dedupes_by_url() -> None:
    """Aynı canonical URL birden fazla geçtiyse ilk geçişin label'ı tutulur."""
    from rasathane_mcp.core.brief import extract_analyzable_urls

    md = (
        "[İlk geçiş](https://www.youtube.com/watch?v=dQw4w9WgXcQ) ve "
        "[ikinci geçiş — aynı video](https://www.youtube.com/watch?v=dQw4w9WgXcQ) "
        "ve [farklı video](https://youtu.be/oHg5SJYRHA0)."
    )
    out = extract_analyzable_urls(md)
    assert len(out) == 2
    assert out[0]["label"] == "İlk geçiş"
    # Phase 35-xxiv: canonical form `youtube.com/watch?v=`
    assert out[0]["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert out[1]["url"] == "https://www.youtube.com/watch?v=oHg5SJYRHA0"


def test_extract_analyzable_urls_strips_trailing_punctuation() -> None:
    """URL'in sonunda nokta/virgül varsa temizlenir."""
    from rasathane_mcp.core.brief import extract_analyzable_urls

    md = "Bağlantı [şurada](https://github.com/anthropics/anthropic-sdk-python)."
    out = extract_analyzable_urls(md)
    # Markdown regex `[^)]+` zaten kapanış parantezini görmez; trailing
    # punctuation paren dışında — yine de güvende olalım: noktalı varyant
    md2 = "Bağlantı: [bak](https://arxiv.org/abs/2511.01234,)"
    out2 = extract_analyzable_urls(md2)
    assert out[0]["url"].endswith("anthropic-sdk-python")
    assert not out2[0]["url"].endswith(",")


def test_extract_analyzable_urls_handles_youtu_be_short_form() -> None:
    """`youtu.be/...` kısa URL formu canonical `watch?v=` formuna çevrilmeli."""
    from rasathane_mcp.core.brief import extract_analyzable_urls

    md = "[Kısa link](https://youtu.be/dQw4w9WgXcQ)"
    out = extract_analyzable_urls(md)
    assert len(out) == 1
    assert out[0]["type"] == "youtube"
    # Phase 35-xxiv: canonicalize → www.youtube.com/watch?v=ID
    assert out[0]["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_extract_analyzable_urls_canonicalizes_github_release_tag() -> None:
    """Phase 35-xxiv: `github.com/X/Y/releases/tag/Z` URL'i canonical repo
    URL'ine `github.com/X/Y` çevrilmeli. repomix --remote ile uyumlu olsun.
    """
    from rasathane_mcp.core.brief import extract_analyzable_urls

    md = "[b9254](https://github.com/ggml-org/llama.cpp/releases/tag/b9254)"
    out = extract_analyzable_urls(md)
    assert len(out) == 1
    assert out[0]["type"] == "github"
    assert out[0]["url"] == "https://github.com/ggml-org/llama.cpp"


def test_extract_analyzable_urls_canonicalizes_arxiv_pdf_to_abs() -> None:
    """Phase 35-xxiv: `arxiv.org/pdf/ID` veya `arxiv.org/pdf/ID.pdf` →
    canonical `arxiv.org/abs/ID`."""
    from rasathane_mcp.core.brief import extract_analyzable_urls

    md = (
        "[paper-pdf](https://arxiv.org/pdf/2511.01234) ve "
        "[same-suffix](https://arxiv.org/pdf/2511.05678.pdf)"
    )
    out = extract_analyzable_urls(md)
    assert {u["url"] for u in out} == {
        "https://arxiv.org/abs/2511.01234",
        "https://arxiv.org/abs/2511.05678",
    }


def test_extract_analyzable_urls_canonicalizes_youtube_shorts() -> None:
    """Phase 35-xxiv: `youtube.com/shorts/ID` → canonical
    `youtube.com/watch?v=ID`."""
    from rasathane_mcp.core.brief import extract_analyzable_urls

    md = "[short](https://www.youtube.com/shorts/dQw4w9WgXcQ)"
    out = extract_analyzable_urls(md)
    assert len(out) == 1
    assert out[0]["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_extract_analyzable_urls_skips_github_reserved_paths() -> None:
    """Phase 35-xxiv: `github.com/topics/llm`, `github.com/marketplace/X`
    repo değil özellik sayfası — listeden düşürülmeli (downstream
    `fetch_repo_metadata` 404 alacaktı)."""
    from rasathane_mcp.core.brief import extract_analyzable_urls

    md = (
        "[topics-llm](https://github.com/topics/llm) ve "
        "[marketplace](https://github.com/marketplace/copilot) ve "
        "[real-repo](https://github.com/anthropics/claude-code)"
    )
    out = extract_analyzable_urls(md)
    # Sadece real-repo kalmalı; reserved owner'lar düşmüş
    assert len(out) == 1
    assert out[0]["url"] == "https://github.com/anthropics/claude-code"


def test_extract_analyzable_urls_skips_invalid_youtube_id() -> None:
    """Phase 35-xxiv: 11-karakter olmayan YouTube ID'leri (mock/test placeholder)
    canonicalize regex'iyle eşleşmez, listeden düşer."""
    from rasathane_mcp.core.brief import extract_analyzable_urls

    md = "[short-id](https://www.youtube.com/watch?v=abc)"
    out = extract_analyzable_urls(md)
    assert out == []


def test_extract_analyzable_urls_derives_label_for_generic_text() -> None:
    """Phase 35-xxiv: Claude bazen anchor metnine "açıldı", "b9254", "abs"
    yazar. Bu generic label'lar URL'den türetilen meaningful versiyona
    fallback etmeli."""
    from rasathane_mcp.core.brief import extract_analyzable_urls

    md = (
        "Yeni sürüm [b9254](https://github.com/ggml-org/llama.cpp) ve "
        "[açıldı](https://github.com/anthropics/claude-code) ve "
        "[abs](https://arxiv.org/abs/2511.99999)"
    )
    out = extract_analyzable_urls(md)
    labels = {u["url"]: u["label"] for u in out}
    # Generic label'lar derived olmalı
    assert labels["https://github.com/ggml-org/llama.cpp"] == "ggml-org/llama.cpp"
    assert labels["https://github.com/anthropics/claude-code"] == "anthropics/claude-code"
    assert labels["https://arxiv.org/abs/2511.99999"] == "arXiv:2511.99999"


def test_extract_analyzable_urls_keeps_meaningful_label() -> None:
    """Phase 35-xxiv: Anlamlı label'lar (>=5 karakter, ne salt-rakam ne
    generic kelime) korunmalı — derive devreye girmemeli."""
    from rasathane_mcp.core.brief import extract_analyzable_urls

    md = (
        "[Anthropic SDK Python](https://github.com/anthropics/anthropic-sdk-python) ve "
        "[Llama 4 technical report](https://arxiv.org/abs/2511.99999)"
    )
    out = extract_analyzable_urls(md)
    labels = {u["url"]: u["label"] for u in out}
    assert labels["https://github.com/anthropics/anthropic-sdk-python"] == "Anthropic SDK Python"
    assert labels["https://arxiv.org/abs/2511.99999"] == "Llama 4 technical report"


def test_load_brief_payload_includes_analyzable_urls(tmp_path: Path) -> None:
    """`_build_brief_payload` analyzable_urls alanı doldurmalı."""
    target = tmp_path / "2026-05-07"
    target.mkdir()
    (target / "00-brief.md").write_text(
        "Bugünün gündemi:\n\n"
        "[YT analiz](https://www.youtube.com/watch?v=dQw4w9WgXcQ) ve "
        "[haber](https://hukukihaber.net/x) ile "
        "[GH repo](https://github.com/anthropics/sdk).\n",
        encoding="utf-8",
    )

    payload = load_brief(archive_root=tmp_path, date="2026-05-07")
    assert "analyzable_urls" in payload
    urls = payload["analyzable_urls"]
    assert len(urls) == 2
    assert {u["type"] for u in urls} == {"youtube", "github"}


# ── Phase 30: list_briefs + force=True audio cleanup ─────────────────


def test_list_briefs_returns_empty_when_archive_missing(tmp_path: Path) -> None:
    """archive_root yoksa boş liste döner (no exception)."""
    from rasathane_mcp.core.brief import list_briefs

    out = list_briefs(tmp_path / "does-not-exist", limit=20)
    assert out == []


def test_list_briefs_skips_dirs_without_brief_md(tmp_path: Path) -> None:
    """``00-brief.md`` olmayan tarihli dizinler atlanır."""
    from rasathane_mcp.core.brief import list_briefs

    (tmp_path / "2026-05-07").mkdir()  # boş dizin
    (tmp_path / "2026-05-08").mkdir()
    (tmp_path / "2026-05-08" / "00-brief.md").write_text("# Var", encoding="utf-8")
    (tmp_path / "not-a-date").mkdir()

    out = list_briefs(tmp_path)
    assert [e["date"] for e in out] == ["2026-05-08"]


def test_list_briefs_sorts_descending_and_flags_audio(tmp_path: Path) -> None:
    """En yeni tarih önce; ``has_audio`` mp3 varlığını yansıtır."""
    from rasathane_mcp.core.brief import list_briefs

    for date in ("2026-05-05", "2026-05-08", "2026-05-07"):
        target = tmp_path / date
        target.mkdir()
        (target / "00-brief.md").write_text(
            f"## Türk Hukuku\n- {date} maddesi: önemli karar açıklandı.",
            encoding="utf-8",
        )
    # Sadece en yeni tarihte audio var
    (tmp_path / "2026-05-08" / "00-brief.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 50)

    out = list_briefs(tmp_path)
    assert [e["date"] for e in out] == ["2026-05-08", "2026-05-07", "2026-05-05"]
    assert out[0]["has_audio"] is True
    assert out[1]["has_audio"] is False


def test_list_briefs_preview_strips_markdown_headers(tmp_path: Path) -> None:
    """``##`` başlık satırları preview'a girmemeli; ilk düz cümle gelir."""
    from rasathane_mcp.core.brief import list_briefs

    target = tmp_path / "2026-05-08"
    target.mkdir()
    (target / "00-brief.md").write_text(
        "## Türk Hukuku\n"
        "\n"
        "- AYM **Anayasa Mahkemesi** kararı [detay](https://example.com) açıklandı.\n",
        encoding="utf-8",
    )

    out = list_briefs(tmp_path)
    assert len(out) == 1
    preview = out[0]["preview"]
    assert "##" not in preview
    assert "Türk Hukuku" not in preview  # başlık atlanmalı
    assert "Anayasa Mahkemesi" in preview  # bold işareti temizlendi
    assert "[detay]" not in preview  # markdown link → label
    assert "detay" in preview


def test_list_briefs_respects_limit(tmp_path: Path) -> None:
    """``limit`` kadar entry döner."""
    from rasathane_mcp.core.brief import list_briefs

    for i in range(5):
        date = f"2026-05-{i + 1:02d}"
        target = tmp_path / date
        target.mkdir()
        (target / "00-brief.md").write_text("içerik", encoding="utf-8")

    out = list_briefs(tmp_path, limit=3)
    assert len(out) == 3
    # En yeni 3'ü
    assert [e["date"] for e in out] == ["2026-05-05", "2026-05-04", "2026-05-03"]


@pytest.mark.asyncio
async def test_generate_brief_force_purges_old_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """force=True regen → eski 00-brief.mp3 + audio.txt + .audio.lock silinir."""

    async def fake_synthesize(prompt: str, **kw):  # type: ignore[no-untyped-def]
        return "## Yeni\n- Yeni içerik"

    async def fake_gather(_session):
        # Phase 33-i: tuple (text, articles_list)
        return ("## turk_hukuku\n- new article", [])

    monkeypatch.setattr("rasathane_mcp.core.brief.synthesize_with_claude", fake_synthesize)
    monkeypatch.setattr("rasathane_mcp.core.brief._gather_articles_grouped", fake_gather)

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    target = tmp_path / today
    target.mkdir()
    # Mevcut brief + ona ait eski audio artifacts
    (target / "00-brief.md").write_text("# Eski brief", encoding="utf-8")
    (target / "00-brief.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 100)
    (target / "00-brief.audio.txt").write_text("Eski script", encoding="utf-8")
    (target / ".audio.lock").write_text("{}", encoding="utf-8")

    session = MagicMock()
    result = await generate_brief(session, archive_root=tmp_path, force=True)

    assert "started_at" in result
    assert (target / "00-brief.md").read_text(encoding="utf-8").startswith("## Yeni")
    # Eski audio artifact'ları silinmiş olmalı
    assert not (target / "00-brief.mp3").is_file()
    assert not (target / "00-brief.audio.txt").is_file()
    assert not (target / ".audio.lock").is_file()


@pytest.mark.asyncio
async def test_generate_brief_no_force_keeps_audio_artifacts(
    tmp_path: Path,
) -> None:
    """force=False + brief var → already_exists, audio dokunulmaz."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    target = tmp_path / today
    target.mkdir()
    (target / "00-brief.md").write_text("# Brief", encoding="utf-8")
    (target / "00-brief.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 50)

    session = MagicMock()
    result = await generate_brief(session, archive_root=tmp_path, force=False)

    assert result.get("error") == "already_exists"
    # Audio korunmalı
    assert (target / "00-brief.mp3").is_file()
