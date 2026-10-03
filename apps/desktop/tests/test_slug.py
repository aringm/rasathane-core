from __future__ import annotations

from ytcore.text.slug import slugify


def test_turkish_chars_removed():
    assert slugify("Çğıöşü ÇĞİÖŞÜ") == "cgiosu-cgiosu"


def test_kebab_ascii():
    assert slugify("Yapay Zeka & Hukuk: 2026!") == "yapay-zeka-hukuk-2026"


def test_collapse_and_trim():
    assert slugify("  çok   boşluk  ") == "cok-bosluk"


def test_empty_fallback():
    assert slugify("") == "icerik"
    assert slugify("!!!") == "icerik"
