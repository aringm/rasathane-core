from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import httpx
import pytest
from rasathane.product import api
from rasathane.product.artifacts import recorded_preview
from rasathane.product.service import ProductService
from rasathane.product.store import ProductStore
from ytmcp.server import gui_http_app


@pytest.fixture
def service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProductService:
    service = ProductService(ProductStore(tmp_path / "state"), autostart=False)
    monkeypatch.setattr(api, "_service", service)
    monkeypatch.delenv("RASATHANE_SESSION_TOKEN", raising=False)
    return service


def record(store: ProductStore, path: Path, status: str = "completed", **changes: object) -> str:
    artifact = {
        "path": str(path.resolve()),
        "name": path.name,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        **changes,
    }
    job = store.enqueue("analysis", {"url": "https://example.org/source"})
    store.update_job(
        job["id"], status, result={"klasor": str(path.parent.resolve()), "artifacts": [artifact]}
    )
    return str(job["id"])


async def test_workspace_change_preserves_exact_registered_pdf_preview(
    service: ProductService, tmp_path: Path, tmp_output_base: Path
) -> None:
    old = tmp_path / "old-workspace"
    old.mkdir()
    pdf = old / "04_özeti.pdf"
    content = b"%PDF-1.4 actual immutable registered output"
    pdf.write_bytes(content)
    record(service.store, pdf)
    assert not pdf.is_relative_to(tmp_output_base)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gui_http_app()),
        base_url="http://localhost",
        headers={"Origin": "rasathane://app"},
    ) as client:
        response = await client.get("/gui/dosya", params={"klasor": str(old / "."), "ad": pdf.name})
        assert response.status_code == 200 and response.content == content
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"].startswith("inline;")
        # Aynı dizindeki ilgisiz dosyaya, salt bir parent root izni aktarılmaz.
        sibling = old / "private.pdf"
        sibling.write_bytes(b"not a registered artifact")
        response = await client.get("/gui/dosya", params={"klasor": str(old), "ad": sibling.name})
        assert response.status_code == 403
        for name in ("../old-workspace/04_özeti.pdf", "..\\old-workspace\\04_özeti.pdf"):
            assert (
                await client.get("/gui/dosya", params={"klasor": str(old), "ad": name})
            ).status_code == 400


@pytest.mark.parametrize("status", ["running", "queued", "failed", "cancelled", "interrupted"])
def test_only_completed_analysis_receipts_authorize_preview(
    service: ProductService, tmp_path: Path, status: str
) -> None:
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 output")
    record(service.store, pdf, status)
    assert recorded_preview(service.store, pdf) is None


@pytest.mark.parametrize(
    "changes",
    [{"bytes": 1}, {"sha256": "f" * 64}, {"sha256": "not a hash"}, {"name": "other.pdf"}],
)
def test_exact_size_hash_and_filename_are_required(
    service: ProductService, tmp_path: Path, changes: dict[str, object]
) -> None:
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 output")
    record(service.store, pdf, **changes)
    assert recorded_preview(service.store, pdf) is None


def test_modified_bytes_never_serve_under_old_receipt(
    service: ProductService, tmp_path: Path
) -> None:
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 output")
    record(service.store, pdf)
    pdf.write_bytes(b"%PDF-1.4 edited")  # aynı boyut, farklı hash
    assert recorded_preview(service.store, pdf) is None


def test_snapshot_returns_verified_bytes_even_when_file_changes_later(
    service: ProductService, tmp_path: Path
) -> None:
    pdf = tmp_path / "report.pdf"
    before = b"%PDF-1.4 output"
    pdf.write_bytes(before)
    record(service.store, pdf)
    content = recorded_preview(service.store, pdf)
    pdf.write_bytes(b"different contents")
    assert content == before


def test_registered_symlink_is_rejected(service: ProductService, tmp_path: Path) -> None:
    original = tmp_path / "real.pdf"
    original.write_bytes(b"%PDF-1.4 output")
    alias = tmp_path / "alias.pdf"
    try:
        alias.symlink_to(original)
    except OSError:
        pytest.skip("Bu Windows oturumu dosya symlink oluşturma izni vermiyor.")
    record(service.store, original)
    assert recorded_preview(service.store, alias) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows junction sınırı")
def test_windows_junction_never_transfers_artifact_permission(
    service: ProductService, tmp_path: Path
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    pdf = real / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 output")
    record(service.store, pdf)
    junction = tmp_path / "junction"
    task_env = {
        **os.environ,
        "RASATHANE_TEST_JUNCTION": str(junction),
        "RASATHANE_TEST_JUNCTION_TARGET": str(real),
    }
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "New-Item -ItemType Junction -Path $env:RASATHANE_TEST_JUNCTION "
            "-Value $env:RASATHANE_TEST_JUNCTION_TARGET | Out-Null",
        ],
        env=task_env,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0
    assert junction.is_junction()
    assert recorded_preview(service.store, junction / pdf.name) is None


async def test_old_artifact_still_requires_native_session_and_type_allowlist(
    service: ProductService, tmp_path: Path, tmp_output_base: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 output")
    record(service.store, pdf)
    json_file = tmp_path / "index.json"
    json_file.write_text("{}", encoding="utf-8")
    record(service.store, json_file)
    monkeypatch.setenv("RASATHANE_SESSION_TOKEN", "preview-test-session")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gui_http_app()), base_url="http://localhost"
    ) as client:
        params = {"klasor": str(tmp_path), "ad": pdf.name}
        assert (await client.get("/gui/dosya", params=params)).status_code == 403
        headers = {"Origin": "rasathane://app", "X-Rasathane-Session": "preview-test-session"}
        assert (await client.get("/gui/dosya", params=params, headers=headers)).status_code == 200
        params["ad"] = json_file.name
        assert (await client.get("/gui/dosya", params=params, headers=headers)).status_code == 415
