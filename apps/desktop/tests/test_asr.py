from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from ytcore.transcript.asr import _CORE_ROOT, ASRSonuc, SubprocessASR


def test_subprocess_asr_json_sozlesme(tmp_path):
    # Sahte worker: --out yoluna bilinen JSON yazar (torch yok, hızlı).
    fake = tmp_path / "fake_worker.py"
    fake.write_text(
        "import json,sys\n"
        "out=sys.argv[sys.argv.index('--out')+1]\n"
        "open(out,'w',encoding='utf-8').write(json.dumps("
        "{'metin':'merhaba dünya','segmentler':[1,2],'dil':'tr','tier':'whisperx'}))\n",
        encoding="utf-8",
    )
    asr = SubprocessASR(python=sys.executable, worker_modul=str(fake), modul_mu=False)
    r = asr.calistir(Path("ses.wav"), dil="tr", diarize=False)
    assert isinstance(r, ASRSonuc)
    assert r.metin == "merhaba dünya" and r.tier == "whisperx" and r.segment_sayisi == 2


def test_subprocess_asr_hata_surface(tmp_path):
    # Olmayan worker → graceful değil, AÇIK hata (sessiz başarısızlık yok).
    asr = SubprocessASR(
        python=sys.executable, worker_modul=str(tmp_path / "yok.py"), modul_mu=False
    )
    with pytest.raises(RuntimeError):
        asr.calistir(Path("ses.wav"), dil="tr", diarize=False)


def test_subprocess_asr_parent_pythonpath_sizmaz(tmp_path, monkeypatch):
    # Savunma-derinliği (ner.py deseni): kirli/zehirli parent PYTHONPATH worker'a MİRAS
    # VERİLMEZ — yoksa /saldirgan/whisperx.py kötücül modülü shadow-import edilebilirdi.
    saldirgan = str(tmp_path / "saldirgan_yol")
    monkeypatch.setenv("PYTHONPATH", saldirgan)
    # Probe worker: kendisine ULAŞAN PYTHONPATH'i metin alanına yazar (torch yok, hızlı).
    probe = tmp_path / "probe_worker.py"
    probe.write_text(
        "import json,os,sys\n"
        "out=sys.argv[sys.argv.index('--out')+1]\n"
        "open(out,'w',encoding='utf-8').write(json.dumps("
        "{'metin':os.environ.get('PYTHONPATH',''),'segmentler':[],'dil':None,'tier':'x'}))\n",
        encoding="utf-8",
    )
    asr = SubprocessASR(python=sys.executable, worker_modul=str(probe), modul_mu=False)
    r = asr.calistir(Path("ses.wav"), dil="tr", diarize=False)
    worker_yollar = r.metin.split(os.pathsep)
    assert saldirgan not in worker_yollar  # parent miras VERİLMEDİ
    assert str(_CORE_ROOT) in worker_yollar  # core HÂLÂ verilir (worker ytcore'u import edebilir)
