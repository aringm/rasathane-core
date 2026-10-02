"""Phase 32-i: audit_log JSONL altyapısı testleri."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from rasathane_mcp.core import audit_log


def test_append_entry_creates_jsonl_file(tmp_path: Path) -> None:
    path = audit_log.append_entry(
        tmp_path,
        actor="user",
        action="source.add",
        target="abc-123",
        target_name="Test Kaynak",
        before=None,
        after={"name": "Test Kaynak"},
        summary="Kaynak eklendi",
    )
    assert path.is_file()
    assert path.suffix == ".jsonl"
    line = path.read_text(encoding="utf-8").strip()
    entry = json.loads(line)
    assert entry["action"] == "source.add"
    assert entry["target_name"] == "Test Kaynak"
    assert entry["actor"] == "user"


def test_append_entry_appends_subsequent_lines(tmp_path: Path) -> None:
    """İkinci append aynı dosyaya yeni satır ekler, ezmez."""
    audit_log.append_entry(tmp_path, actor="user", action="source.pause", target="x", summary="a")
    audit_log.append_entry(tmp_path, actor="user", action="source.unpause", target="x", summary="b")
    path = audit_log.today_log_path(tmp_path)
    lines = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(lines) == 2
    assert lines[0]["action"] == "source.pause"
    assert lines[1]["action"] == "source.unpause"


def test_read_recent_returns_newest_first(tmp_path: Path) -> None:
    """Read son N kaydı en yeni → en eski sırada döner."""
    audit_log.append_entry(tmp_path, actor="user", action="source.add", target="1", summary="first")
    audit_log.append_entry(
        tmp_path, actor="user", action="source.add", target="2", summary="second"
    )
    audit_log.append_entry(tmp_path, actor="user", action="source.add", target="3", summary="third")

    rows = audit_log.read_recent(tmp_path, limit=10)
    assert len(rows) == 3
    assert rows[0]["target"] == "3"
    assert rows[-1]["target"] == "1"


def test_read_recent_action_filter(tmp_path: Path) -> None:
    audit_log.append_entry(tmp_path, actor="user", action="source.add", target="1", summary="add")
    audit_log.append_entry(
        tmp_path, actor="user", action="social.add", target="p1", summary="social"
    )
    audit_log.append_entry(
        tmp_path, actor="user", action="source.delete", target="2", summary="del"
    )

    rows = audit_log.read_recent(tmp_path, action_filter="source")
    assert len(rows) == 2
    assert all(r["action"].startswith("source") for r in rows)


def test_read_recent_actor_filter(tmp_path: Path) -> None:
    audit_log.append_entry(tmp_path, actor="user", action="source.add", target="1", summary="u")
    audit_log.append_entry(tmp_path, actor="agent", action="source.add", target="2", summary="a")

    rows = audit_log.read_recent(tmp_path, actor_filter="agent")
    assert len(rows) == 1
    assert rows[0]["target"] == "2"


def test_read_recent_no_audit_dir_returns_empty(tmp_path: Path) -> None:
    """archive/audit/ yoksa boş liste — hata yok."""
    rows = audit_log.read_recent(tmp_path / "no_archive")
    assert rows == []


def test_read_recent_handles_corrupt_lines(tmp_path: Path) -> None:
    """Bozuk JSONL satırı varsa skip eder, sağlam satırları döner."""
    audit_log.append_entry(tmp_path, actor="user", action="source.add", target="ok", summary="ok")
    path = audit_log.today_log_path(tmp_path)
    with path.open("a", encoding="utf-8") as f:
        f.write("not a json line\n")
        f.write('{"another": "ok", "action": "source.add", "target": "x"}\n')

    rows = audit_log.read_recent(tmp_path, limit=100)
    # 2 valid + 1 bozuk → 2 dönmeli
    assert len(rows) == 2


def test_today_log_path_uses_utc_date(tmp_path: Path) -> None:
    """Path UTC tarihine göre — timezone karışmasın."""
    fixed = datetime(2026, 5, 14, 23, 59, tzinfo=UTC)
    p = audit_log.today_log_path(tmp_path, now=fixed)
    assert p.name == "2026-05-14.jsonl"
