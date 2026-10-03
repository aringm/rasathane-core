"""Yeni Rasathane çıktı kökü, eski kayıt görünürlüğü ve kaynak repo koruması."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from ytcore.config import GOZLEM_KOKU_ADI, GOZLEM_KOKU_LEGACY_ADLARI, _default_output_base


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / "Desktop").mkdir()
    return tmp_path


def data(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "_index").mkdir(exist_ok=True)
    return root


def migration_module():
    script = Path(__file__).parents[1] / "infra/gozlem-koku-goc.py"
    spec = importlib.util.spec_from_file_location("rasathane_output_migration", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clean_default_is_only_rasathane_under_documents(home):
    assert GOZLEM_KOKU_ADI == "Rasathane"
    assert _default_output_base() == home / "Documents" / "Rasathane"


def test_desktop_source_repo_is_never_output(home):
    source = home / "Desktop" / "Rasathane"
    source.mkdir()
    (source / ".git").mkdir()
    (source / "source.py").write_text("source")
    assert _default_output_base() == home / "Documents" / "Rasathane"
    assert (source / "source.py").read_text() == "source"


@pytest.mark.parametrize("name", GOZLEM_KOKU_LEGACY_ADLARI)
def test_existing_legacy_stays_visible_until_explicit_migration(home, name):
    old = data(home / "Desktop" / name)
    assert _default_output_base() == old


def test_empty_new_folder_does_not_hide_old_data(home):
    (home / "Documents" / "Rasathane").mkdir(parents=True)
    old = data(home / "Desktop" / GOZLEM_KOKU_LEGACY_ADLARI[0])
    assert _default_output_base() == old


def test_populated_new_folder_wins_and_legacy_priority_is_recent_first(home):
    for name in GOZLEM_KOKU_LEGACY_ADLARI:
        data(home / "Desktop" / name)
    assert _default_output_base() == home / "Desktop" / "Rasathane  Gözlemevi"
    current = data(home / "Documents" / "Rasathane")
    assert _default_output_base() == current


def test_migration_dry_run_then_atomic_move_leaves_source_repo_untouched(home):
    source_repo = home / "Desktop" / "Rasathane"
    (source_repo / ".git").mkdir(parents=True)
    old = data(home / "Desktop" / GOZLEM_KOKU_LEGACY_ADLARI[0])
    (old / "output.txt").write_text("preserved evidence")
    helper = migration_module()
    planned_source, target = helper.migrate(home)
    assert planned_source == old and not target.exists()
    assert old.is_dir()
    helper.migrate(home, apply=True)
    assert not old.exists()
    assert (target / "output.txt").read_text() == "preserved evidence"
    assert (source_repo / ".git").is_dir()
    assert _default_output_base() == target


@pytest.mark.parametrize("conflict", ["multiple", "filled-target", "source-repo", "target-repo"])
def test_migration_refuses_conflicts_without_changes(home, conflict):
    old = data(home / "Desktop" / GOZLEM_KOKU_LEGACY_ADLARI[0])
    target = home / "Documents" / "Rasathane"
    if conflict == "multiple":
        data(home / "Desktop" / GOZLEM_KOKU_LEGACY_ADLARI[-1])
    elif conflict == "filled-target":
        data(target)
    elif conflict == "source-repo":
        (old / ".git").mkdir()
    else:
        (target / ".git").mkdir(parents=True)
    with pytest.raises(ValueError):
        migration_module().migrate(home, apply=True)
    assert old.exists()


def test_document_source_repo_is_rejected_instead_of_mixed(home):
    (home / "Documents" / "Rasathane" / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match="kaynak repo"):
        _default_output_base()


def test_legacy_named_source_repo_is_not_selected_as_output(home):
    old = data(home / "Desktop" / GOZLEM_KOKU_LEGACY_ADLARI[0])
    (old / ".git").mkdir()
    assert _default_output_base() == home / "Documents" / "Rasathane"


@pytest.mark.parametrize("kind", ["symlink", "junction"])
def test_migration_rejects_redirected_source_before_mutation(home, monkeypatch, kind):
    old = data(home / "Desktop" / GOZLEM_KOKU_LEGACY_ADLARI[0])
    method = "is_symlink" if kind == "symlink" else "is_junction"
    original = getattr(Path, method)
    monkeypatch.setattr(Path, method, lambda self: self == old or original(self))
    with pytest.raises(ValueError, match="Symlink veya junction"):
        migration_module().migrate(home, apply=True)
    assert old.exists()
    assert not (home / "Documents" / "Rasathane").exists()
