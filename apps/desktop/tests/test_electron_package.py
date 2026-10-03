from __future__ import annotations

import json
import tomllib
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]


def test_electron_surumu_ve_nsis_paket_sozlesmesi():
    paket = json.loads((KOK / "gui/package.json").read_text(encoding="utf-8"))
    engine = tomllib.loads((KOK / "pyproject.toml").read_text(encoding="utf-8"))
    assert paket["version"] == engine["project"]["version"]
    assert paket["main"] == "electron/main.cjs"
    assert paket["devDependencies"]["electron"] == "43.7.7"
    assert paket["devDependencies"]["electron-builder"] == "26.15.3"
    assert paket["build"]["appId"] == "ai.muhakeme.rasathane"
    assert paket["build"]["asar"] is True
    assert paket["build"]["electronFuses"] == {
        "runAsNode": False,
        "enableCookieEncryption": True,
        "enableNodeOptionsEnvironmentVariable": False,
        "enableNodeCliInspectArguments": False,
        "enableEmbeddedAsarIntegrityValidation": True,
        "onlyLoadAppFromAsar": True,
        "grantFileProtocolExtraPrivileges": False,
    }
    assert paket["build"]["artifactName"] == "Rasathane-Setup-${version}-x64.${ext}"
    assert paket["build"]["win"]["target"] == [{"target": "nsis", "arch": ["x64"]}]
    assert paket["build"]["nsis"]["deleteAppDataOnUninstall"] is False
    assert paket["build"]["extraResources"] == [
        {"from": "../LICENSE", "to": "licenses/AGPL-3.0.txt"},
        {"from": "../../../NOTICE.md", "to": "licenses/NOTICE.md"},
        {"from": "../infra/THIRD-PARTY.md", "to": "licenses/THIRD-PARTY.md"},
        {"from": "../infra/vendor/licenses", "to": "licenses/runtime"},
        {
            "from": "../infra/vendor/tooling",
            "to": "tooling",
            "filter": [
                "**/*",
                "!typst-licenses/archives/**",
                "!typst-licenses/font-source/**",
                "!typst-licenses/pdfjs/*.tar.gz",
                "!typst-licenses/build-supplement.py",
            ],
        },
        {"from": "../infra/dist/worker", "to": "worker"},
        {
            "from": "../infra/dist/ytanaliz-sidecar.exe",
            "to": "sidecar/ytanaliz-sidecar.exe",
        },
        {
            # GGUF weights ilk kurulumda SHA256 doğrulanır; büyük NSIS paketine gömülmez.
            "from": "../infra/vendor/motor",
            "to": "motor",
            "filter": [
                "bin/**",
                "modeller/ner/**",
                "modeller/asr/**",
                "motor-manifest.json",
            ],
        },
    ]


def test_paketlenen_ikon_yollari_diskte_var():
    """Marka geçişinde yanlış/eksik ikonla paketleme sessizce yeşil kalmasın."""
    paket = json.loads((KOK / "gui/package.json").read_text(encoding="utf-8"))
    gui = KOK / "gui"

    build_res = gui / paket["build"]["directories"]["buildResources"]
    assert build_res.is_dir(), f"buildResources dizini yok: {build_res}"

    for anahtar, yol in (
        ("win.icon", paket["build"]["win"]["icon"]),
        ("nsis.installerIcon", paket["build"]["nsis"]["installerIcon"]),
        ("nsis.uninstallerIcon", paket["build"]["nsis"]["uninstallerIcon"]),
    ):
        hedef = gui / yol
        assert hedef.is_file(), f"{anahtar} diskte yok: {hedef}"


def test_electron_guvenlik_ve_sidecar_yasam_dongusu_kodda_sabit():
    main = (KOK / "gui/electron/main.cjs").read_text(encoding="utf-8")
    assert 'const SCHEME = "rasathane"' in main
    assert "protocol.registerSchemesAsPrivileged" in main
    assert "nodeIntegration: false" in main
    assert "contextIsolation: true" in main
    assert "sandbox: true" in main
    assert "setPermissionRequestHandler" in main
    assert 'spawnSync("taskkill"' in main
    assert 'path.join(process.resourcesPath, "sidecar", "ytanaliz-sidecar.exe")' in main
    assert 'process.argv.includes("--smoke-test")' in main


def test_electron_csp_ve_fuse_sertlestirmesi_var():
    html = (KOK / "gui/ui/index.html").read_text(encoding="utf-8")
    paket = json.loads((KOK / "gui/package.json").read_text(encoding="utf-8"))
    fuse = paket["build"]["electronFuses"]
    assert "Content-Security-Policy" in html
    # Kabuk boş aday portu seçer; CSP hepsine izin vermezse seçilen portta fetch bloklanır.
    for port in (8765, 8766, 8767, 8768):
        assert f"http://127.0.0.1:{port}" in html
    assert "object-src 'none'" in html
    assert fuse["runAsNode"] is False
    assert fuse["enableNodeOptionsEnvironmentVariable"] is False
    assert fuse["enableEmbeddedAsarIntegrityValidation"] is True
    assert fuse["onlyLoadAppFromAsar"] is True
