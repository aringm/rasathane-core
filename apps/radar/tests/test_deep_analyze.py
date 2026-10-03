"""Phase 14: deep-dive analyze tests.

Heavy fetches (yt-dlp transcript, repomix, arxiv API) ve claude
subprocess hepsi mock'lu — sadece orchestration, lockfile pattern,
state machine, ve endpoint behavior'ı test ediliyor.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from rasathane_mcp.core import deep_analyze as core_deep
from rasathane_mcp.dashboard.app import create_app


@pytest.fixture
def app() -> Any:
    return create_app()


@pytest.fixture
async def client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── core_deep helpers ─────────────────────────────────────────────────


def test_compute_job_id_deterministic() -> None:
    """Aynı URL+type → aynı job_id (cache key)."""
    a = core_deep.compute_job_id("https://youtu.be/abc", "youtube")
    b = core_deep.compute_job_id("https://youtu.be/abc", "youtube")
    assert a == b
    assert len(a) == 16
    assert all(c in "0123456789abcdef" for c in a)


def test_compute_job_id_differs_per_url() -> None:
    a = core_deep.compute_job_id("https://youtu.be/x", "youtube")
    b = core_deep.compute_job_id("https://youtu.be/y", "youtube")
    assert a != b


def test_lookup_status_returns_not_found_when_dir_missing(tmp_path: Path) -> None:
    status = core_deep.lookup_status(archive_root=tmp_path, job_id="0123456789abcdef")
    assert status == {"job_id": "0123456789abcdef", "status": "not_found"}


def test_lookup_status_returns_done_with_result_md(tmp_path: Path) -> None:
    job_id = "abcdef0123456789"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "result.md").write_text("# Analiz\n\nİçerik", encoding="utf-8")
    (target / "meta.json").write_text(
        json.dumps({"url": "https://x", "type": "youtube", "title": "T"}),
        encoding="utf-8",
    )

    status = core_deep.lookup_status(archive_root=tmp_path, job_id=job_id)
    assert status["status"] == "done"
    assert "İçerik" in status["result"]
    assert status["meta"]["title"] == "T"


def test_lookup_status_returns_running_with_fresh_lockfile(tmp_path: Path) -> None:
    job_id = "1111222233334444"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / ".lock").write_text(
        json.dumps({"started_at": datetime.now(UTC).isoformat(), "pid": 1}),
        encoding="utf-8",
    )

    status = core_deep.lookup_status(archive_root=tmp_path, job_id=job_id)
    assert status["status"] == "running"
    assert "elapsed_sec" in status


def test_lookup_status_ignores_stale_lockfile_returns_not_found(
    tmp_path: Path,
) -> None:
    """Phase 17-i: stale threshold 1200 sn → 25 dk önce → stale."""
    job_id = "5555666677778888"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    stale = (datetime.now(UTC) - timedelta(seconds=1500)).isoformat()
    (target / ".lock").write_text(json.dumps({"started_at": stale, "pid": 1}), encoding="utf-8")

    status = core_deep.lookup_status(archive_root=tmp_path, job_id=job_id)
    assert status["status"] == "not_found"


def test_lookup_status_returns_failed_with_last_error(tmp_path: Path) -> None:
    job_id = "9999aaaabbbbcccc"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / ".last-error.txt").write_text(
        "transcript_unavailable: yt-dlp failed", encoding="utf-8"
    )

    status = core_deep.lookup_status(archive_root=tmp_path, job_id=job_id)
    assert status["status"] == "failed"
    assert "transcript_unavailable" in status["error"]


# ── orchestrator (run_deep_analyze) ───────────────────────────────────


@pytest.mark.asyncio
async def test_run_deep_analyze_unsupported_url_returns_unsupported(
    tmp_path: Path,
) -> None:
    out = await core_deep.run_deep_analyze(
        "https://example.com/random",
        archive_root=tmp_path,
    )
    assert out["status"] == "unsupported"
    assert out["job_id"] is None


@pytest.mark.asyncio
async def test_run_deep_analyze_returns_already_exists_when_cached(
    tmp_path: Path,
) -> None:
    """result.md varsa + force=False → cache hit dön."""
    url = "https://youtu.be/cached"
    job_id = core_deep.compute_job_id(url, "youtube")
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "result.md").write_text("önceki", encoding="utf-8")

    out = await core_deep.run_deep_analyze(url, archive_root=tmp_path)
    assert out["status"] == "already_exists"
    assert out["job_id"] == job_id


@pytest.mark.asyncio
async def test_run_deep_analyze_youtube_writes_multi_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 17-i: YouTube path 2 stage çağırır — transcript_clean + summary.

    transcript.md + summary.md atomik yazılır. Stage A (transcript_clean)
    + Stage B (summary) ikisi de claude'a gider — claude 2x çağrılır.
    Stage A long-context instruction-following için claude'a geri taşındı
    (uzun TR transkriptlerde local LLM özetleme eğilimine giriyordu).
    """
    from dataclasses import dataclass

    @dataclass
    class FakeMeta:
        title: str = "Test Video"
        channel: str = "Test Channel"
        duration_seconds: int = 600
        video_id: str = "abc123"

    @dataclass
    class FakeTranscript:
        text: str = "ham eee transkript yani şey içeriği"
        source: str = "ytdlp"

    async def fake_fetch_metadata(_url):
        return FakeMeta()

    async def fake_fetch_transcript(_url):
        return FakeTranscript()

    claude_calls = {"n": 0}

    async def fake_claude(prompt, *, timeout_seconds=None):
        claude_calls["n"] += 1
        if claude_calls["n"] == 1:
            # Stage A: transcript_clean — ham transkripti içermeli
            assert "ham eee transkript" in prompt
            return "## Konu\n\nTemizlenmiş transkript.\n"
        # Stage B: summary — temizlenmiş transkripti input olarak almalı
        assert "Test Video" in prompt
        assert "Temizlenmiş transkript" in prompt
        return "### Konunun özü\nMock analiz çıktısı.\n"

    monkeypatch.setattr("ingestion.youtube.fetch_metadata", fake_fetch_metadata)
    # Phase 21-i: default whisper off → fetch_subs_via_ytdlp kullanılır
    monkeypatch.setattr("ingestion.youtube.fetch_subs_via_ytdlp", fake_fetch_transcript)
    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.synthesize_with_claude", fake_claude)

    url = "https://youtu.be/test1"
    out = await core_deep.run_deep_analyze(url, archive_root=tmp_path)

    assert out["status"] == "done"
    # Stage A + Stage B = claude 2x; mindmap ayrı endpoint
    assert claude_calls["n"] == 2
    job_id = out["job_id"]
    job_path = tmp_path / "deep" / job_id

    # transcript.md (clean) + summary.md (analiz) ikisi de var
    transcript_path = job_path / "transcript.md"
    summary_path = job_path / "summary.md"
    assert transcript_path.is_file()
    assert summary_path.is_file()
    assert "Temizlenmiş transkript" in transcript_path.read_text(encoding="utf-8")
    assert "Mock analiz çıktısı" in summary_path.read_text(encoding="utf-8")

    # Phase 28-ii: mindmap.html artık core'dan çıkmadığı için yok
    assert not (job_path / "mindmap.html").is_file()
    # Eski result.md YouTube için yazılmamalı
    assert not (job_path / "result.md").is_file()
    # Phase 21-i: audio core'dan çıktı
    assert not (job_path / "audio.mp3").is_file()

    # Meta extras
    meta = json.loads((job_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["title"] == "Test Video"
    assert meta["transcript_source"] == "ytdlp"
    assert "transcript_clean_chars" in meta
    assert "summary_chars" in meta


# ── Phase 21-i: ayrı sesli özet endpoint ─────────────────────────────


@pytest.mark.asyncio
async def test_run_audio_only_returns_summary_missing_when_no_dir(
    tmp_path: Path,
) -> None:
    """archive/deep/{job_id}/ yoksa → summary_missing."""
    out = await core_deep.run_audio_only_for_existing_job(
        archive_root=tmp_path, job_id="0123456789abcdef"
    )
    assert out["status"] == "summary_missing"


@pytest.mark.asyncio
async def test_run_audio_only_returns_already_exists_when_audio_present(
    tmp_path: Path,
) -> None:
    """audio.mp3 varsa cache döner."""
    job_id = "abcdef0123456789"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "summary.md").write_text("özet", encoding="utf-8")
    (target / "audio.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 50)

    out = await core_deep.run_audio_only_for_existing_job(archive_root=tmp_path, job_id=job_id)
    assert out["status"] == "already_exists"
    assert out["audio_url"].endswith("/audio.mp3")
    assert out["bytes"] > 0


@pytest.mark.asyncio
async def test_run_audio_only_generates_mp3_for_youtube_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 32-ii: YouTube için 3-konuşmacı podcast modu (Filiz/Burak/Esra)."""
    job_id = "1111aaaa22223333"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "summary.md").write_text("Özet metni", encoding="utf-8")
    (target / "transcript.md").write_text("Temizlenmiş", encoding="utf-8")
    (target / "meta.json").write_text(
        '{"type": "youtube", "title": "Vid", "channel": "Ch"}', encoding="utf-8"
    )

    async def fake_claude(prompt, *, timeout_seconds=None):
        # Yeni prompt: youtube_podcast_script.md — 3 konuşmacı bekliyor
        assert "Vid" in prompt
        assert "Filiz" in prompt or "panel" in prompt.lower()
        return (
            "[\n"
            '  {"speaker": "Filiz", "text": "Bugün izlediğimiz video Vid."},\n'
            '  {"speaker": "Burak", "text": "Ch kanalında yayınlandı, konu önemli."},\n'
            '  {"speaker": "Esra", "text": "Ancak şu noktayı atlamış."}\n'
            "]"
        )

    async def fake_podcast(*, dialog, output_path, voices, fallback_voice="x"):
        assert len(dialog) == 3
        speakers = {d["speaker"] for d in dialog}
        assert speakers == {"Filiz", "Burak", "Esra"}
        assert set(voices.keys()) == {"Filiz", "Burak", "Esra"}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\xff\xfb" + b"\x00" * 256)
        return output_path

    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.synthesize_with_claude", fake_claude)
    monkeypatch.setattr("llm.tts.synthesize_podcast", fake_podcast)

    out = await core_deep.run_audio_only_for_existing_job(archive_root=tmp_path, job_id=job_id)
    assert out["status"] == "done"
    assert out["mode"] == "podcast"
    assert out["segments"] == 3
    assert (target / "audio.mp3").is_file()
    # Yeni format: JSON dialog (eski txt yerine)
    assert (target / "audio_script.json").is_file()
    script_json = (target / "audio_script.json").read_text(encoding="utf-8")
    assert "Filiz" in script_json
    assert "Burak" in script_json
    assert "Esra" in script_json


@pytest.mark.asyncio
async def test_run_mindmap_only_for_existing_job_writes_mindmap_html(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 28-ii: mindmap artık ayrı endpoint — `run_mindmap_only_for_existing_job`
    summary.md'den markmap HTML üretir."""
    job_id = "f0ed1234abcdef99"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "summary.md").write_text("### Özet\nMock analiz.", encoding="utf-8")
    (target / "transcript.md").write_text("Temizlenmiş transkript", encoding="utf-8")
    (target / "meta.json").write_text(
        json.dumps({"type": "youtube", "title": "MM Test", "channel": "Ch"}),
        encoding="utf-8",
    )

    async def fake_claude(_prompt, *, timeout_seconds=None):
        return "# MM Test\n\n## 📌 Ana konu\n- Alt fikir\n  - Detay\n"

    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.synthesize_with_claude", fake_claude)

    result = await core_deep.run_mindmap_only_for_existing_job(archive_root=tmp_path, job_id=job_id)
    assert result["status"] == "done"
    mindmap_path = target / "mindmap.html"
    assert mindmap_path.is_file()
    html = mindmap_path.read_text(encoding="utf-8")
    # Phase 28-v: ESM module pipeline (autoloader değil)
    assert "/+esm" in html
    assert "markmap-lib" in html
    assert "markmap-view" in html
    assert 'id="mm-md"' in html
    # Markdown ağacı gömülü
    assert "📌 Ana konu" in html
    assert "MM Test" in html


@pytest.mark.asyncio
async def test_run_mindmap_only_strips_code_fences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 17-ii / 28-ii: claude bazen ``` ile sarar; soyup atmalı."""
    job_id = "ee1122ee44ccff00"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "summary.md").write_text("özet", encoding="utf-8")
    (target / "meta.json").write_text(
        json.dumps({"type": "youtube", "title": "X", "channel": "Y"}),
        encoding="utf-8",
    )

    async def fake_claude(_prompt, *, timeout_seconds=None):
        return "```markdown\n# Root\n\n## Branch\n- Leaf\n```"

    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.synthesize_with_claude", fake_claude)

    result = await core_deep.run_mindmap_only_for_existing_job(archive_root=tmp_path, job_id=job_id)
    assert result["status"] == "done"
    html = (target / "mindmap.html").read_text(encoding="utf-8")
    # Code fence backticks template script bloğunda olmamalı (markmap fence'i parse etmez)
    # Sadece HTML için </script> escape'i veya inline JS kalabilir; backticks template'inde değil
    assert "```markdown" not in html
    assert "```\n#" not in html


@pytest.mark.asyncio
async def test_lookup_status_done_with_youtube_artifacts(
    tmp_path: Path,
) -> None:
    """Phase 17-i: lookup_status YouTube job'unu summary.md ile 'done' sayar
    + artifacts dict her dosya için URL döner."""
    job_id = "abcdef9876543210"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "transcript.md").write_text("clean transcript", encoding="utf-8")
    (target / "summary.md").write_text("# Analiz", encoding="utf-8")

    status = core_deep.lookup_status(archive_root=tmp_path, job_id=job_id)
    assert status["status"] == "done"
    assert "Analiz" in status["result"]
    artifacts = status["artifacts"]
    assert artifacts["transcript"] == f"/archive/deep/{job_id}/transcript.md"
    assert artifacts["summary"] == f"/archive/deep/{job_id}/summary.md"
    # mindmap/audio yok henüz
    assert "mindmap" not in artifacts
    assert "audio" not in artifacts


@pytest.mark.asyncio
async def test_lookup_status_legacy_result_md_still_done(
    tmp_path: Path,
) -> None:
    """Backward compat: eski jobs result.md ile bitirdi → done sayılır."""
    job_id = "legacy0123456789"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "result.md").write_text("eski sonuç", encoding="utf-8")

    status = core_deep.lookup_status(archive_root=tmp_path, job_id=job_id)
    assert status["status"] == "done"
    assert "eski sonuç" in status["result"]
    assert status["artifacts"]["legacy_result"].endswith("/result.md")


@pytest.mark.asyncio
async def test_run_deep_analyze_writes_last_error_on_transcript_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Transcript None döner → last-error.txt yazılır, status failed."""
    from dataclasses import dataclass

    @dataclass
    class FakeMeta:
        title: str = "X"
        channel: str = "Y"
        duration_seconds: int = 60
        video_id: str = "v"

    async def fake_fetch_metadata(_url):
        return FakeMeta()

    async def fake_fetch_transcript(_url):
        return None  # both yt-dlp + whisper failed

    monkeypatch.setattr("ingestion.youtube.fetch_metadata", fake_fetch_metadata)
    # Phase 21-i: default whisper off → fetch_subs_via_ytdlp kullanılır
    monkeypatch.setattr("ingestion.youtube.fetch_subs_via_ytdlp", fake_fetch_transcript)

    out = await core_deep.run_deep_analyze("https://youtu.be/notranscript", archive_root=tmp_path)
    assert out["status"] == "failed"
    assert "transcript_unavailable" in out["detail"]

    job_id = out["job_id"]
    last_error_path = tmp_path / "deep" / job_id / ".last-error.txt"
    assert last_error_path.is_file()
    # Lockfile temizlenmeli
    lockfile = tmp_path / "deep" / job_id / ".lock"
    assert not lockfile.exists()


@pytest.mark.asyncio
async def test_run_deep_analyze_in_progress_when_lockfile_fresh(
    tmp_path: Path,
) -> None:
    """Fresh lockfile → in_progress döndür, claude'a gitme."""
    url = "https://youtu.be/locked"
    job_id = core_deep.compute_job_id(url, "youtube")
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / ".lock").write_text(
        json.dumps({"started_at": datetime.now(UTC).isoformat(), "pid": 1}),
        encoding="utf-8",
    )

    out = await core_deep.run_deep_analyze(url, archive_root=tmp_path)
    assert out["status"] == "in_progress"


# ── Phase 18: GitHub + arXiv multi-artifact ──────────────────────────


@pytest.mark.asyncio
async def test_run_deep_analyze_github_writes_2_stage_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 21-i: GitHub için 2-stage core pipeline (summary + mindmap).

    Audio Phase 21-i'de ayrı endpoint'e taşındı; bu test core path'i
    doğrular: claude 2 kez çağrılır, audio.mp3 yazılmaz.
    """
    from dataclasses import dataclass

    @dataclass
    class FakeRepo:
        full_name: str = "anthropics/claude-code"
        description: str | None = "Agentic coding tool"
        primary_language: str | None = "TypeScript"
        stars: int = 1234
        forks: int = 56
        default_branch: str = "main"
        url: str = "https://github.com/anthropics/claude-code"

    async def fake_fetch(_url):
        return FakeRepo()

    async def fake_repomix(_url, *, output_path, project_root, timeout_seconds):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("# README\n\nfake repomix dump", encoding="utf-8")
        return output_path

    outputs = [
        "## Repo özeti\nAnalitik özet.",  # summary
        "# anthropics/claude-code\n## Mimari\n- React",  # mindmap
    ]
    i = {"n": 0}

    async def fc(_p, *, timeout_seconds=None):
        v = outputs[i["n"]]
        i["n"] += 1
        return v

    monkeypatch.setattr("ingestion.github.fetch_repo_metadata", fake_fetch)
    monkeypatch.setattr("ingestion.github.run_repomix", fake_repomix)
    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.synthesize_with_claude", fc)

    out = await core_deep.run_deep_analyze(
        "https://github.com/anthropics/claude-code", archive_root=tmp_path
    )
    assert out["status"] == "done"
    # Phase 28-ii: 1-stage core (summary only); mindmap ayrı endpoint
    assert i["n"] == 1

    job_id = out["job_id"]
    job_path = tmp_path / "deep" / job_id
    assert (job_path / "summary.md").is_file()
    # Phase 28-ii: mindmap core'dan çıktı, ayrı buton
    assert not (job_path / "mindmap.html").is_file()
    # Phase 21-i: audio core'dan çıktı
    assert not (job_path / "audio.mp3").is_file()
    # Transcript yok (GitHub için anlamsız)
    assert not (job_path / "transcript.md").is_file()
    # Eski result.md de yazılmamalı (multi-artifact mode)
    assert not (job_path / "result.md").is_file()

    meta = json.loads((job_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["full_name"] == "anthropics/claude-code"
    assert meta["mindmap_chars"] == 0  # Phase 28-ii: not generated in core


@pytest.mark.asyncio
async def test_run_deep_analyze_arxiv_writes_2_stage_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 21-i: arXiv için 2-stage core pipeline (summary + mindmap).

    Phase 25-ii: PDF fetch helper'ı None dönsün → abstract path (legacy)
    test edilsin. Yeni full-PDF path için ayrı test var.

    Phase 27.5: Atom API çağrısının `follow_redirects=True` ve `https://`
    URL kullandığı assert edilir (arxiv.org 2024+ HTTP→HTTPS redirect).
    """

    async def fake_pdf_fetch(_arxiv_id):
        return None

    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.fetch_arxiv_pdf_text", fake_pdf_fetch)

    import httpx

    fake_atom = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Test Paper Title</title>
    <summary>Bu bir test abstract'ıdır. Önemli bulgular vardır.</summary>
    <author><name>A. Author</name></author>
    <author><name>B. Coauthor</name></author>
  </entry>
</feed>
"""

    captured: dict = {"client_kwargs": None, "url": None}

    class FakeResp:
        text = fake_atom
        status_code = 200

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *_a, **kw):
            captured["client_kwargs"] = kw

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, url):
            captured["url"] = url
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    outputs = [
        "## arXiv özeti",
        "# Test Paper\n## Sorun\n- Açık",
    ]
    i = {"n": 0}

    async def fc(_p, *, timeout_seconds=None):
        v = outputs[i["n"]]
        i["n"] += 1
        return v

    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.synthesize_with_claude", fc)

    out = await core_deep.run_deep_analyze(
        "https://arxiv.org/abs/2511.01234", archive_root=tmp_path
    )
    assert out["status"] == "done"
    # Phase 28-ii: 1-stage core (summary only); mindmap ayrı endpoint
    assert i["n"] == 1

    job_id = out["job_id"]
    job_path = tmp_path / "deep" / job_id
    assert (job_path / "summary.md").is_file()
    # Phase 28-ii: mindmap core'dan çıktı
    assert not (job_path / "mindmap.html").is_file()
    assert not (job_path / "audio.mp3").is_file()  # Phase 21-i: ayrı endpoint

    meta = json.loads((job_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["title"] == "Test Paper Title"
    assert meta["arxiv_id"] == "2511.01234"
    assert "A. Author" in meta["authors"]

    # Phase 27.5 regression coverage: Atom API HTTPS + redirect-follow şart
    assert captured["url"] is not None
    assert captured["url"].startswith("https://export.arxiv.org/api/query"), (
        f"Atom API URL must use https:// (arxiv 2024+ redirect 301), got: {captured['url']}"
    )
    assert captured["client_kwargs"] is not None
    assert captured["client_kwargs"].get("follow_redirects") is True, (
        "httpx.AsyncClient must use follow_redirects=True for arxiv 301 redirects"
    )
    # Phase 27.5b: descriptive User-Agent şart (arxiv 1 req/3 sn politikası
    # UA'sız client'ları daha sıkı throttle ediyor)
    headers = captured["client_kwargs"].get("headers") or {}
    assert "User-Agent" in headers, (
        "httpx.AsyncClient must send descriptive User-Agent for arxiv API"
    )
    assert "Rasathane" in headers["User-Agent"]


@pytest.mark.asyncio
async def test_run_deep_analyze_arxiv_retries_on_429(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 27.5b: arxiv API 429 (rate-limit) → exponential backoff retry,
    sonra başarılı yanıt → done."""

    async def fake_pdf_fetch(_arxiv_id):
        return None

    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.fetch_arxiv_pdf_text", fake_pdf_fetch)

    # asyncio.sleep'i instant'a mock'la (test hız)
    import asyncio

    async def instant_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)

    import httpx

    fake_atom = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Retry Paper</title>
    <summary>Bu paper 2 deneme sonra geldi.</summary>
    <author><name>X. Author</name></author>
  </entry>
</feed>
"""

    call_log: list[int] = []

    class FakeResp429:
        status_code = 429
        text = "Too Many Requests"

        def raise_for_status(self):
            raise httpx.HTTPStatusError("429", request=None, response=self)

    class FakeRespOk:
        status_code = 200
        text = fake_atom

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, _url):
            call_log.append(1)
            # 1. 429, 2. 429, 3. 200
            if len(call_log) <= 2:
                return FakeResp429()
            return FakeRespOk()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    outputs = ["## özet", "# mindmap"]
    i = {"n": 0}

    async def fc(_p, *, timeout_seconds=None):
        v = outputs[i["n"]]
        i["n"] += 1
        return v

    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.synthesize_with_claude", fc)

    out = await core_deep.run_deep_analyze(
        "https://arxiv.org/abs/2511.99999", archive_root=tmp_path
    )
    assert out["status"] == "done", f"Expected done after retry, got {out}"
    assert len(call_log) == 3, f"Expected 3 attempts (2x429 + 1x200), got {len(call_log)}"


@pytest.mark.asyncio
async def test_run_deep_analyze_arxiv_fails_after_persistent_429(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """3 denemenin hepsi 429 → arxiv_rate_limited hatası."""

    async def fake_pdf_fetch(_arxiv_id):
        return None

    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.fetch_arxiv_pdf_text", fake_pdf_fetch)

    import asyncio

    async def instant_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)

    import httpx

    class FakeResp429:
        status_code = 429
        text = "Too Many Requests"

        def raise_for_status(self):
            raise httpx.HTTPStatusError("429", request=None, response=self)

    class FakeClient:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, _url):
            return FakeResp429()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    out = await core_deep.run_deep_analyze(
        "https://arxiv.org/abs/2511.88888", archive_root=tmp_path
    )
    assert out["status"] == "failed"
    assert "arxiv_rate_limited" in out.get("detail", "")


# ── endpoints ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_deep_post_unsupported_returns_422(
    client: AsyncClient,
) -> None:
    async with client:
        r = await client.post("/api/analyze/deep", json={"url": "https://example.com/random"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_analyze_deep_post_returns_202_with_job_id(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Yeni iş → background'a alınır + 202 + job_id."""
    captured: dict[str, Any] = {"called": False}

    async def fake_run(_url, **_kw):
        captured["called"] = True
        return {"job_id": "x", "status": "done"}

    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.run_deep_analyze", fake_run)

    async with client:
        r = await client.post("/api/analyze/deep", json={"url": "https://youtu.be/new1"})

    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert len(body["job_id"]) == 16
    assert body["detected_type"] == "youtube"


@pytest.mark.asyncio
async def test_analyze_deep_get_invalid_job_id_returns_404(
    client: AsyncClient,
) -> None:
    async with client:
        r = await client.get("/api/analyze/deep/notavalidjobid")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_analyze_deep_get_returns_lookup_status(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Polling endpoint lookup_status payload'unu döner."""

    def fake_lookup(*, archive_root, job_id):
        return {"job_id": job_id, "status": "running", "elapsed_sec": 42}

    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.lookup_status", fake_lookup)

    async with client:
        r = await client.get("/api/analyze/deep/0123456789abcdef")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running"
    assert body["elapsed_sec"] == 42


# ── Phase 21-i: ayrı sesli özet endpoint ─────────────────────────────


@pytest.mark.asyncio
async def test_analyze_deep_audio_post_invalid_job_id_returns_404(
    client: AsyncClient,
) -> None:
    async with client:
        r = await client.post("/api/analyze/deep/notavalidjobid/audio")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_analyze_deep_audio_post_missing_summary_returns_404(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Job dizini yok → 404 summary_missing."""
    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", tmp_path)
    async with client:
        r = await client.post("/api/analyze/deep/0123456789abcdef/audio")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_analyze_deep_audio_post_returns_already_exists_when_cached(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """audio.mp3 zaten varsa → 200 already_exists."""
    job_id = "abcdef0123456789"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "summary.md").write_text("özet", encoding="utf-8")
    (target / "audio.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 100)

    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", tmp_path)

    async with client:
        r = await client.post(f"/api/analyze/deep/{job_id}/audio")

    # Endpoint decorator status_code=202; cache hit'te de aynı
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "already_exists"
    assert body["audio_url"].endswith("/audio.mp3")


@pytest.mark.asyncio
async def test_analyze_deep_audio_post_queues_when_summary_present(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """summary var, audio yok → 202 queued + background task."""
    job_id = "fedcba9876543210"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "summary.md").write_text("özet", encoding="utf-8")

    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", tmp_path)

    invoked = {"n": 0}

    async def fake_audio_only(*, archive_root, job_id):
        invoked["n"] += 1
        return {"status": "done"}

    monkeypatch.setattr(
        "rasathane_mcp.core.deep_analyze.run_audio_only_for_existing_job", fake_audio_only
    )

    async with client:
        r = await client.post(f"/api/analyze/deep/{job_id}/audio")

    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["job_id"] == job_id


# ── Phase 28-ii: ayrı zihin haritası endpoint ────────────────────────


@pytest.mark.asyncio
async def test_analyze_deep_mindmap_post_invalid_job_id_returns_404(
    client: AsyncClient,
) -> None:
    async with client:
        r = await client.post("/api/analyze/deep/notavalidjobid/mindmap")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_analyze_deep_mindmap_post_missing_summary_returns_404(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", tmp_path)
    async with client:
        r = await client.post("/api/analyze/deep/0123456789abcdef/mindmap")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_analyze_deep_mindmap_post_returns_already_exists_when_cached(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mindmap.html zaten varsa → 202 already_exists (cache hit)."""
    job_id = "1122334455667788"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "summary.md").write_text("özet", encoding="utf-8")
    (target / "mindmap.html").write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", tmp_path)

    async with client:
        r = await client.post(f"/api/analyze/deep/{job_id}/mindmap")

    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "already_exists"
    assert body["mindmap_url"].endswith("/mindmap.html")


@pytest.mark.asyncio
async def test_analyze_deep_mindmap_post_queues_when_summary_present(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = "8877665544332211"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "summary.md").write_text("özet", encoding="utf-8")

    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", tmp_path)

    invoked = {"n": 0}

    async def fake_mindmap_only(*, archive_root, job_id):
        invoked["n"] += 1
        return {"status": "done"}

    monkeypatch.setattr(
        "rasathane_mcp.core.deep_analyze.run_mindmap_only_for_existing_job",
        fake_mindmap_only,
    )

    async with client:
        r = await client.post(f"/api/analyze/deep/{job_id}/mindmap")

    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["job_id"] == job_id


# ── Phase 23: önceki analizler listesi + silme ───────────────────────


def test_list_all_jobs_returns_empty_when_no_dir(tmp_path: Path) -> None:
    """archive/deep/ yoksa boş liste döner — hata yok."""
    assert core_deep.list_all_jobs(archive_root=tmp_path) == []


def test_list_all_jobs_includes_legacy_result_md_jobs(tmp_path: Path) -> None:
    """Phase 14 legacy job (yalnız result.md) liste'de "done" görünsün."""
    job_id = "legacy0123456789"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "result.md").write_text("# Eski Analiz\n", encoding="utf-8")
    (target / "meta.json").write_text(
        json.dumps(
            {
                "url": "https://www.youtube.com/watch?v=old",
                "type": "youtube",
                "title": "Eski Video",
            }
        ),
        encoding="utf-8",
    )

    jobs = core_deep.list_all_jobs(archive_root=tmp_path)
    assert len(jobs) == 1
    job = jobs[0]
    assert job["job_id"] == job_id
    assert job["status"] == "done"
    assert job["title"] == "Eski Video"
    assert job["type"] == "youtube"
    # Legacy result.md → has_legacy_result True, summary False
    assert job["has_legacy_result"] is True
    assert job["has_summary"] is False


def test_list_all_jobs_lists_artifact_status(tmp_path: Path) -> None:
    """Multi-artifact YouTube job: tüm artifact flag'leri ve sıralama."""
    # Eski job: yalnız result.md (mtime düşük olsun)
    old_id = "0000000000000001"
    old = tmp_path / "deep" / old_id
    old.mkdir(parents=True)
    (old / "result.md").write_text("eski", encoding="utf-8")
    # mtime'ı geçmişe çek
    import os as _os

    _os.utime(old / "result.md", (1_700_000_000, 1_700_000_000))

    # Yeni job: tam artifact set
    new_id = "0000000000000002"
    new = tmp_path / "deep" / new_id
    new.mkdir(parents=True)
    (new / "summary.md").write_text("özet", encoding="utf-8")
    (new / "transcript.md").write_text("transkript", encoding="utf-8")
    (new / "mindmap.html").write_text("<html>", encoding="utf-8")
    (new / "audio.mp3").write_bytes(b"\xff\xfb")
    (new / "meta.json").write_text(
        json.dumps({"url": "https://youtu.be/x", "type": "youtube", "title": "Yeni"}),
        encoding="utf-8",
    )

    jobs = core_deep.list_all_jobs(archive_root=tmp_path)
    assert len(jobs) == 2
    # mtime DESC sıralı: yeni önce
    assert jobs[0]["job_id"] == new_id
    assert jobs[1]["job_id"] == old_id

    new_job = jobs[0]
    assert new_job["has_summary"] is True
    assert new_job["has_transcript"] is True
    assert new_job["has_mindmap"] is True
    assert new_job["has_audio"] is True
    assert new_job["has_legacy_result"] is False


def test_list_all_jobs_skips_dot_prefixed_dirs(tmp_path: Path) -> None:
    """`.tmp/` (repomix output) gibi rezerve dizinler atlanır."""
    (tmp_path / "deep" / ".tmp").mkdir(parents=True)
    (tmp_path / "deep" / ".tmp" / "junk.txt").write_text("x", encoding="utf-8")
    real_id = "1234567890abcdef"
    real = tmp_path / "deep" / real_id
    real.mkdir(parents=True)
    (real / "summary.md").write_text("özet", encoding="utf-8")

    jobs = core_deep.list_all_jobs(archive_root=tmp_path)
    assert [j["job_id"] for j in jobs] == [real_id]


def test_delete_job_removes_directory(tmp_path: Path) -> None:
    job_id = "deadbeefcafe1234"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "summary.md").write_text("özet", encoding="utf-8")
    (target / "audio.mp3").write_bytes(b"\xff\xfb")

    result = core_deep.delete_job(archive_root=tmp_path, job_id=job_id)
    assert result == "deleted"
    assert not target.exists()


def test_delete_nonexistent_returns_not_found(tmp_path: Path) -> None:
    result = core_deep.delete_job(archive_root=tmp_path, job_id="0123456789abcdef")
    assert result == "not_found"


def test_delete_running_job_refuses_with_running(tmp_path: Path) -> None:
    """Lockfile taze ise sil reddedilir — arka plan task'i koruma."""
    job_id = "abcd5555eeee0001"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / ".lock").write_text(
        json.dumps({"started_at": datetime.now(UTC).isoformat(), "pid": 1}),
        encoding="utf-8",
    )

    result = core_deep.delete_job(archive_root=tmp_path, job_id=job_id)
    assert result == "running"
    assert target.exists()  # dizin korunur


@pytest.mark.asyncio
async def test_analyze_deep_list_endpoint_returns_jobs(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/analyze/deep — list_all_jobs payload + in_library compose."""
    job_id = "fedcba9876543210"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "summary.md").write_text("özet", encoding="utf-8")
    (target / "meta.json").write_text(
        json.dumps({"url": "https://youtu.be/y", "type": "youtube", "title": "T"}),
        encoding="utf-8",
    )

    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", tmp_path)

    async def fake_lookup(_job_ids):
        # Test'te DB yok — boş map dön
        return {}

    monkeypatch.setattr(
        "rasathane_mcp.core.library.lookup_deep_analysis_library_items",
        fake_lookup,
    )

    async with client:
        r = await client.get("/api/analyze/deep")

    assert r.status_code == 200
    body = r.json()
    assert "jobs" in body
    assert len(body["jobs"]) == 1
    job = body["jobs"][0]
    assert job["job_id"] == job_id
    assert job["title"] == "T"
    assert job["in_library"] is False
    assert job["library_item_id"] is None


@pytest.mark.asyncio
async def test_analyze_deep_list_endpoint_empty_archive(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """archive/deep/ yoksa boş liste; DB lookup hiç çağrılmaz."""
    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", tmp_path)

    called = {"n": 0}

    async def fake_lookup(_job_ids):
        called["n"] += 1
        return {}

    monkeypatch.setattr(
        "rasathane_mcp.core.library.lookup_deep_analysis_library_items",
        fake_lookup,
    )

    async with client:
        r = await client.get("/api/analyze/deep")

    assert r.status_code == 200
    assert r.json() == {"jobs": []}
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_analyze_deep_delete_endpoint_happy(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DELETE /api/analyze/deep/{id} — done job → 200 + dizin silinir."""
    job_id = "0011223344556677"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "summary.md").write_text("özet", encoding="utf-8")

    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", tmp_path)

    async with client:
        r = await client.delete(f"/api/analyze/deep/{job_id}")

    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == job_id
    assert body["status"] == "deleted"
    assert not target.exists()


@pytest.mark.asyncio
async def test_analyze_deep_delete_endpoint_invalid_format_returns_404(
    client: AsyncClient,
) -> None:
    async with client:
        r = await client.delete("/api/analyze/deep/notavalidjobid")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_analyze_deep_delete_endpoint_nonexistent_returns_404(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", tmp_path)
    async with client:
        r = await client.delete("/api/analyze/deep/0123456789abcdef")
    assert r.status_code == 404


# ── Phase 25-ii: arXiv full PDF parse ────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_arxiv_pdf_text_returns_text_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock httpx + pypdf — PDF download + parse happy path."""
    import httpx

    fake_pdf_bytes = b"%PDF-1.4\n...\n%%EOF"

    class FakeResp:
        content = fake_pdf_bytes

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, _url):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    # pypdf'i de mock'la — gerçek PDF byte'ları lazım olmasın
    class FakePage:
        def extract_text(self):
            return "Bu bir PDF metnidir. Önemli bulgular vardır."

    class FakeReader:
        def __init__(self, _stream):
            self.pages = [FakePage(), FakePage()]

    monkeypatch.setattr("pypdf.PdfReader", FakeReader)

    text = await core_deep.fetch_arxiv_pdf_text("2511.01234")
    assert text is not None
    assert "PDF metnidir" in text
    assert "Önemli bulgular" in text


@pytest.mark.asyncio
async def test_fetch_arxiv_pdf_text_returns_none_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Network fail → None (graceful fallback)."""
    import httpx

    class FakeClient:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, _url):
            raise httpx.HTTPError("connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    text = await core_deep.fetch_arxiv_pdf_text("2511.01234")
    assert text is None


@pytest.mark.asyncio
async def test_fetch_arxiv_pdf_text_returns_none_on_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pypdf parse fail (corrupt PDF) → None."""
    import httpx

    class FakeResp:
        content = b"not a real pdf"

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, _url):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    from pypdf.errors import PyPdfError

    def fake_reader(_stream):
        raise PyPdfError("corrupt")

    monkeypatch.setattr("pypdf.PdfReader", fake_reader)

    text = await core_deep.fetch_arxiv_pdf_text("2511.01234")
    assert text is None


@pytest.mark.asyncio
async def test_fetch_arxiv_pdf_text_truncates_at_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Çok uzun PDF → ceiling'e kırpılır + NOT eklenir."""
    import httpx

    class FakeResp:
        content = b"%PDF-1.4..."

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, _url):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    long_text = "X" * (core_deep.ARXIV_PDF_CHAR_CEILING + 5000)

    class FakePage:
        def __init__(self, t):
            self.t = t

        def extract_text(self):
            return self.t

    class FakeReader:
        def __init__(self, _stream):
            self.pages = [FakePage(long_text)]

    monkeypatch.setattr("pypdf.PdfReader", FakeReader)

    text = await core_deep.fetch_arxiv_pdf_text("2511.01234")
    assert text is not None
    # Ceiling kadar X + NOT eki
    assert text.startswith("X" * 100)
    assert "NOT:" in text
    assert "kırpıldı" in text


@pytest.mark.asyncio
async def test_run_arxiv_uses_full_pdf_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 25-ii: PDF fetch başarılıysa text_source=full_pdf, prompt full text alır."""
    import httpx

    fake_atom = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Phase 25 Test Paper</title>
    <summary>Kısa abstract.</summary>
    <author><name>Z. Yazar</name></author>
  </entry>
</feed>
"""

    class FakeResp:
        text = fake_atom
        status_code = 200

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, _url):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    async def fake_pdf_fetch(_arxiv_id):
        return "Full paper content. Methods. Results. Limitations."

    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.fetch_arxiv_pdf_text", fake_pdf_fetch)

    captured_prompts: list[str] = []
    outputs = ["## arXiv özeti", "# Mind\n## A"]
    i = {"n": 0}

    async def fc(prompt, *, timeout_seconds=None):
        captured_prompts.append(prompt)
        v = outputs[i["n"]]
        i["n"] += 1
        return v

    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.synthesize_with_claude", fc)

    out = await core_deep.run_deep_analyze(
        "https://arxiv.org/abs/2511.99999", archive_root=tmp_path
    )
    assert out["status"] == "done"
    job_id = out["job_id"]
    meta = json.loads((tmp_path / "deep" / job_id / "meta.json").read_text("utf-8"))
    assert meta["text_source"] == "full_pdf"
    assert meta["pdf_chars"] > 0
    # Summary prompt full text içermeli
    summary_prompt = captured_prompts[0]
    assert "Full paper content" in summary_prompt
    assert "Methods" in summary_prompt


@pytest.mark.asyncio
async def test_run_arxiv_falls_back_to_abstract_when_pdf_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PDF fetch None döndürürse text_source=abstract_only + abstract prompt'a girer."""
    import httpx

    fake_atom = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Fallback Test</title>
    <summary>Bu abstract fallback olarak kullanılacak.</summary>
    <author><name>A. Author</name></author>
  </entry>
</feed>
"""

    class FakeResp:
        text = fake_atom
        status_code = 200

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *_a, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return None

        async def get(self, _url):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    async def fake_pdf_fail(_arxiv_id):
        return None

    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.fetch_arxiv_pdf_text", fake_pdf_fail)

    captured_prompts: list[str] = []
    outputs = ["## özet", "# mindmap"]
    i = {"n": 0}

    async def fc(prompt, *, timeout_seconds=None):
        captured_prompts.append(prompt)
        v = outputs[i["n"]]
        i["n"] += 1
        return v

    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.synthesize_with_claude", fc)

    out = await core_deep.run_deep_analyze(
        "https://arxiv.org/abs/2511.88888", archive_root=tmp_path
    )
    assert out["status"] == "done"
    job_id = out["job_id"]
    meta = json.loads((tmp_path / "deep" / job_id / "meta.json").read_text("utf-8"))
    assert meta["text_source"] == "abstract_only"
    assert meta["pdf_chars"] == 0
    # Summary prompt abstract'ı içermeli
    assert "fallback olarak" in captured_prompts[0]


# ── Phase 26: WHISPER_API_URL env auto-enable whisper ───────────────


@pytest.mark.asyncio
async def test_run_youtube_subs_only_when_whisper_api_set_but_use_whisper_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 27: WHISPER_API_URL set'li olsa bile use_whisper=False ise
    subs-only path (auto-whisper kaldırıldı, opt-in only).

    Eski Phase 26 davranışı: env varsa effective_whisper=True →
    fetch_transcript. Yeni Phase 27: env'den bağımsız, sadece
    use_whisper flag'ine bakar."""
    monkeypatch.setenv("WHISPER_API_URL", "http://localhost:9000")

    from dataclasses import dataclass

    @dataclass
    class FakeMeta:
        title: str = "SubsPath"
        channel: str = "Ch"
        duration_seconds: int = 600
        video_id: str = "wapi1"

    @dataclass
    class FakeTranscript:
        text: str = "Altyazıdan gelen orijinal dil transkripti."
        source: str = "yt-dlp:tr"

    chain_called = {"fetch_transcript": 0, "fetch_subs_only": 0}

    async def fake_meta(_url):
        return FakeMeta()

    async def fake_transcript(_url):
        chain_called["fetch_transcript"] += 1
        return FakeTranscript()

    async def fake_subs_only(_url):
        chain_called["fetch_subs_only"] += 1
        return FakeTranscript()  # altyazı bulundu (success)

    monkeypatch.setattr("ingestion.youtube.fetch_metadata", fake_meta)
    monkeypatch.setattr("ingestion.youtube.fetch_transcript", fake_transcript)
    monkeypatch.setattr("ingestion.youtube.fetch_subs_via_ytdlp", fake_subs_only)

    async def fake_claude(_prompt, *, timeout_seconds=None):
        return "## Stage çıktı\nTest"

    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.synthesize_with_claude", fake_claude)

    out = await core_deep.run_deep_analyze(
        "https://youtu.be/wapi1", archive_root=tmp_path, use_whisper=False
    )
    assert out["status"] == "done"
    # Phase 27: env yok sayıldı, fetch_subs_only çağrıldı, fetch_transcript atlandı
    assert chain_called["fetch_subs_only"] == 1
    assert chain_called["fetch_transcript"] == 0


@pytest.mark.asyncio
async def test_run_youtube_uses_subs_only_when_whisper_api_not_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WHISPER_API_URL yoksa + use_whisper=False → eski hızlı yol (subs only)."""
    monkeypatch.delenv("WHISPER_API_URL", raising=False)

    from dataclasses import dataclass

    @dataclass
    class FakeMeta:
        title: str = "SubsOnly"
        channel: str = "Ch"
        duration_seconds: int = 300
        video_id: str = "subs1"

    @dataclass
    class FakeTranscript:
        text: str = "Altyazı metni."
        source: str = "yt-dlp"

    chain_called = {"fetch_transcript": 0, "fetch_subs_only": 0}

    async def fake_meta(_url):
        return FakeMeta()

    async def fake_transcript(_url):
        chain_called["fetch_transcript"] += 1
        return FakeTranscript()

    async def fake_subs_only(_url):
        chain_called["fetch_subs_only"] += 1
        return FakeTranscript()

    monkeypatch.setattr("ingestion.youtube.fetch_metadata", fake_meta)
    monkeypatch.setattr("ingestion.youtube.fetch_transcript", fake_transcript)
    monkeypatch.setattr("ingestion.youtube.fetch_subs_via_ytdlp", fake_subs_only)

    async def fake_claude(_prompt, *, timeout_seconds=None):
        return "## çıktı"

    monkeypatch.setattr("rasathane_mcp.core.deep_analyze.synthesize_with_claude", fake_claude)

    out = await core_deep.run_deep_analyze(
        "https://youtu.be/subs1", archive_root=tmp_path, use_whisper=False
    )
    assert out["status"] == "done"
    # Hızlı yol: yalnız subs çağrıldı
    assert chain_called["fetch_subs_only"] == 1
    assert chain_called["fetch_transcript"] == 0


@pytest.mark.asyncio
async def test_analyze_deep_delete_endpoint_running_returns_409(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Çalışan job → 409 + dizin korunur."""
    job_id = "8899aabbccddeeff"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / ".lock").write_text(
        json.dumps({"started_at": datetime.now(UTC).isoformat(), "pid": 1}),
        encoding="utf-8",
    )
    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", tmp_path)

    async with client:
        r = await client.delete(f"/api/analyze/deep/{job_id}")

    assert r.status_code == 409
    assert target.exists()
