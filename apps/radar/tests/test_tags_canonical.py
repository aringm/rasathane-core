"""Phase 33-ii: canonical tag namespace tests."""

from store.tags import CANONICAL_TAGS, all_tags, is_valid, normalize


def test_canonical_tags_contains_required_keys():
    required = {
        "tr_hukuk",
        "tr_avukat",
        "tr_ai",
        "dunya_ai",
        "acik_kaynak_ai",
        "legaltech",
        "resmi_mevzuat",
    }
    assert required.issubset(CANONICAL_TAGS.keys())


def test_all_tags_returns_sorted_by_order():
    tags = all_tags()
    orders = [t["order"] for t in tags]
    assert orders == sorted(orders)


def test_normalize_lowercases_and_handles_aliases():
    assert normalize("TR Hukuk") == "tr_hukuk"
    assert normalize("dunya_AI") == "dunya_ai"
    # Bilinmeyen tag normalize edilemez → None
    assert normalize("rastgele_etiket_42") is None


def test_is_valid_canonical():
    assert is_valid("tr_hukuk")
    assert is_valid("acik_kaynak_ai")
    assert not is_valid("invalid_tag")


def test_all_tags_each_has_required_fields():
    for t in all_tags():
        assert "key" in t
        assert "label" in t
        assert "color" in t
        assert "order" in t
