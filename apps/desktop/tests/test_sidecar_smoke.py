from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest

EXE = Path("infra/dist/ytanaliz-sidecar.exe")


def _surec_agacini_kapat(proc: subprocess.Popen[str]) -> None:
    """PyInstaller onefile bootstrap ve servis child'ını birlikte kapat."""
    if os.name == "nt" and proc.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    elif proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def _port_serbest_mi(port: int) -> bool:
    with socket.socket() as istemci:
        istemci.settimeout(0.2)
        return istemci.connect_ex(("127.0.0.1", port)) != 0


def _bos_port() -> int:
    """Testi sabit 8765'e bağlama: makinede o portu tutan başka uygulama olabilir."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.mark.skipif(not EXE.exists(), reason="sidecar exe build edilmemiş")
def test_exe_selftest_5_5():
    for _ in range(5):
        r = subprocess.run([str(EXE), "selftest"], capture_output=True, text=True, timeout=180)
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout.strip().splitlines()[-1])["selftest"] == "ok"


@pytest.mark.skipif(not EXE.exists(), reason="sidecar exe build edilmemiş")
def test_exe_torch_free_boyut():
    # ≤16GB (#2) exe-tarafı regresyon guard: torch exe'ye GİRMEZSE ~65MB; torch sızsa GB'larca
    # olurdu. build-sidecar.ps1 exclude listesi bozulur/transitif torch sızarsa bu test yakalar.
    boyut_mb = EXE.stat().st_size / 1_000_000
    assert boyut_mb < 200, f"exe {boyut_mb:.0f}MB — torch/ML stack sızmış olabilir (#2 ihlali)"


@pytest.mark.skipif(not EXE.exists(), reason="sidecar exe build edilmemiş")
def test_exe_bilinmeyen_mod_hizli_olur():
    # review tur-1 HIGH: bilinmeyen argv stdio'ya DÜŞMEMELİ — frozen exe'de self-spawn
    # child'ı ('-m ...') anında rc=2 ile ölmeli (180s stdio-blok + stdin çalma yok).
    r = subprocess.run(
        [str(EXE), "-m", "ytcore.router.ner_worker"], capture_output=True, text=True, timeout=60
    )
    assert r.returncode == 2
    assert "bilinmeyen mod" in r.stderr


@pytest.mark.skipif(not EXE.exists(), reason="sidecar exe build edilmemiş")
def test_exe_http_modu_ayaga_kalkar():
    # review tur-1 MED: üretim modları (http/stdio) frozen testte hiç import edilmiyordu —
    # fastmcp/starlette metadata bundle riski. GUI'nin tek yolu http: /gui/health 200 dönmeli.
    import urllib.error
    import urllib.request

    port = _bos_port()
    proc = subprocess.Popen(
        [str(EXE), "http"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        env={**os.environ, "RASATHANE_SIDECAR_PORT": str(port)},
    )
    try:
        son_hata: Exception | None = None
        for _ in range(60):  # cold-start: onefile açılım + import ~10-30s
            if proc.poll() is not None:
                _, err = proc.communicate(timeout=10)
                raise AssertionError(f"http modu erken öldü (rc={proc.returncode}): {err[-1500:]}")
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/gui/health", timeout=2
                ) as y:
                    assert y.status == 200
                    return  # frozen exe'de fastmcp+starlette import & serve ÇALIŞTI
            except (urllib.error.URLError, ConnectionError, OSError) as e:
                son_hata = e
                time.sleep(1)
        raise AssertionError(f"/gui/health 60s içinde yanıt vermedi: {son_hata}")
    finally:
        _surec_agacini_kapat(proc)
        for _ in range(30):
            if _port_serbest_mi(port):
                break
            time.sleep(0.1)
        assert _port_serbest_mi(port), f"frozen sidecar child süreci {port} portunu bırakmadı"
