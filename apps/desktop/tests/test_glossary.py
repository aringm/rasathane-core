from __future__ import annotations

from pathlib import Path

from ytcore.content.glossary import glossary_few_shot, glossary_yukle, varsayilan_glossary


def test_glossary_yukle(tmp_path: Path):
    p = tmp_path / "g.csv"
    p.write_text("en,tr\ncontract,sözleşme\nplaintiff,davacı\n", encoding="utf-8")
    g = glossary_yukle(p)
    assert ("contract", "sözleşme") in g
    assert len(g) == 2


def test_glossary_yukle_bos_satir_atlar(tmp_path: Path):
    p = tmp_path / "g.csv"
    p.write_text("en,tr\ncontract,sözleşme\n\n,\nx\n", encoding="utf-8")
    assert glossary_yukle(p) == [("contract", "sözleşme")]


def test_glossary_few_shot_bos():
    assert glossary_few_shot([]) == ""


def test_glossary_few_shot_icerik():
    frag = glossary_few_shot([("contract", "sözleşme")])
    assert "contract" in frag and "sözleşme" in frag


def test_varsayilan_glossary_var():
    g = varsayilan_glossary()
    assert len(g) >= 5
    assert ("contract", "sözleşme") in g
