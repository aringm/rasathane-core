from __future__ import annotations

import subprocess
from pathlib import Path


def _git_repo_mu(path: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
        )
        return r.returncode == 0 and r.stdout.strip() == "true"
    except Exception:
        return False


def analiz_commit_guvenli(repo: Path, klasor: Path, mesaj: str) -> bool:
    """Analiz-başına git commit — GRACEFUL (hattı asla çökertmez).

    GÜVENLİK: 'git add -A/./--all' YASAK — yalnız belirli klasör eklenir.
    - repo bir git work-tree değilse: skip (False).
    - klasor repo dışındaysa (cross-drive/ValueError): skip (False).
    - eklenecek değişiklik yoksa / kimlik tanımsızsa: commit returncode != 0 -> False (crash YOK).
    """
    if not _git_repo_mu(repo):
        return False
    try:
        rel = klasor.relative_to(repo)
    except ValueError:
        return False
    if rel == Path("."):
        # klasor == repo: 'git add -- .' tüm repoyu stage ederdi (git add . eşdeğeri) — YASAK.
        return False
    try:
        add = subprocess.run(
            ["git", "-C", str(repo), "add", "--", str(rel)], capture_output=True, text=True
        )
        if add.returncode != 0:
            return False
        # GÜVENLİK: commit'i de pathspec'e scope'la ('-- <rel>'). Pathspec'siz 'git commit'
        # repodaki TÜM stage'lenmiş değişiklikleri alır → kullanıcının önceden stage'lediği
        # alakasız dosyalar analiz commit'ine süpürülürdü ('git add -A' yasağıyla aynı ruh).
        commit = subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", mesaj, "--", str(rel)],
            capture_output=True,
            text=True,
        )
        return commit.returncode == 0
    except OSError:
        # git çağrı-ortası erişilemez (PATH'ten kalktı / izin) -> hattı çökertme (graceful).
        return False
