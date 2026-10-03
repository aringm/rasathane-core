from __future__ import annotations

import subprocess
from pathlib import Path

from ytcore.output.git_commit import analiz_commit_guvenli


def _init_repo(p: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=p, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=p, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=p, check=True)


def test_commit_repo_icinde(tmp_path):
    _init_repo(tmp_path)
    klasor = tmp_path / "analiz1"
    klasor.mkdir()
    (klasor / "00_index.json").write_text("{}", encoding="utf-8")
    assert analiz_commit_guvenli(tmp_path, klasor, "analiz: x") is True
    log = subprocess.run(["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True)
    assert "analiz: x" in log.stdout


def test_commit_repo_degilse_graceful(tmp_path):
    # git repo DEĞİL -> crash YOK, False (hattı çökertmez)
    klasor = tmp_path / "analiz1"
    klasor.mkdir()
    (klasor / "00_index.json").write_text("{}", encoding="utf-8")
    assert analiz_commit_guvenli(tmp_path, klasor, "analiz: x") is False


def test_commit_git_calistirilamaz_graceful(tmp_path, monkeypatch):
    # Re-review HIGH: git çağrı-ortası erişilemezse (OSError) hat çökmemeli
    import ytcore.output.git_commit as gc

    monkeypatch.setattr(gc, "_git_repo_mu", lambda p: True)

    def _raise(*a, **k):
        raise FileNotFoundError("git PATH'te yok")

    monkeypatch.setattr(gc.subprocess, "run", _raise)
    klasor = tmp_path / "analiz1"
    klasor.mkdir()
    assert gc.analiz_commit_guvenli(tmp_path, klasor, "analiz: x") is False


def test_commit_klasor_repo_esit_skip(tmp_path):
    # Re-review LOW: klasor == repo -> 'git add -- .' tüm repoyu stage etmemeli
    _init_repo(tmp_path)
    assert analiz_commit_guvenli(tmp_path, tmp_path, "analiz: x") is False


def test_commit_onceden_stagelenen_dosyayi_supurmez(tmp_path):
    # HIGH (denetim): commit pathspec'e scope'lu olmalı — kullanıcının önceden stage'lediği
    # ALAKASIZ dosya analiz commit'ine GİRMEMELİ ('git add -A' yasağıyla aynı ruh).
    _init_repo(tmp_path)
    # ilk commit (HEAD olsun) + sonra alakasız bir dosyayı stage et
    (tmp_path / "README").write_text("repo", encoding="utf-8")
    subprocess.run(["git", "add", "README"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "GIZLI.txt").write_text("token=SECRET", encoding="utf-8")
    subprocess.run(["git", "add", "GIZLI.txt"], cwd=tmp_path, check=True, capture_output=True)
    # analiz klasörü ayrı
    klasor = tmp_path / "analiz1"
    klasor.mkdir()
    (klasor / "00_index.json").write_text("{}", encoding="utf-8")
    assert analiz_commit_guvenli(tmp_path, klasor, "analiz: x") is True
    # son commit yalnız analiz1/ içermeli; GIZLI.txt commit'e GİRMEMELİ (hâlâ staged kalır)
    dosyalar = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    ).stdout
    assert "analiz1/00_index.json" in dosyalar.replace("\\", "/")
    assert "GIZLI.txt" not in dosyalar
    # GIZLI.txt hâlâ index'te (commit'lenmedi)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=tmp_path, capture_output=True, text=True
    ).stdout
    assert "GIZLI.txt" in staged


def test_commit_gitignore_yolu_commitlemez(tmp_path):
    # review tur-5 LOW: gitignore'lu output (örn repo-içi tmp/) oto-commit'lenmemeli — git add
    # -- <ignored> returncode!=0 → graceful False (8e17b07 sızıntısının kalıcı koruması).
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("tmp/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "gitignore"], cwd=tmp_path, check=True, capture_output=True
    )
    klasor = tmp_path / "tmp" / "analiz1"
    klasor.mkdir(parents=True)
    (klasor / "00_index.json").write_text("{}", encoding="utf-8")
    # gitignore'lu yol → commit YAPILMAMALI (graceful False).
    assert analiz_commit_guvenli(tmp_path, klasor, "analiz: sizinti") is False
    log = subprocess.run(["git", "log", "--oneline"], cwd=tmp_path, capture_output=True, text=True)
    assert "analiz: sizinti" not in log.stdout  # ignored çıktı commit'lenmedi
