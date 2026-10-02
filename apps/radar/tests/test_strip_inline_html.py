"""Phase 34-vi: defensive HTML strip helper tests.

Claude prompt'a "HTML tag yazma" yasağına rağmen ara sıra inline HTML
inject ediyor (özellikle muhakeme.ai cross-link emoji buton'ları).
`strip_inline_html_tags` markdown sentaksını koruyup HTML tag'leri siler.
"""

from rasathane_mcp.core.brief import strip_inline_html_tags


def test_strip_muhakeme_anchor_tag():
    """`<a class="muhakeme-cross" ...>🔍 emsal ara</a>` silinir."""
    md = (
        '[Türkiye Suç Mağduriyeti 2025](https://example.com) '
        '<a class="muhakeme-cross" href="https://muhakeme.ai/emsal?q=X" '
        'target="_blank" rel="noopener" title="muhakeme.ai\'de emsal ara">'
        "🔍 emsal ara</a> duruyor."
    )
    out = strip_inline_html_tags(md)
    assert "<a class=" not in out
    assert "🔍 emsal ara" not in out
    assert "muhakeme.ai/emsal" not in out
    # Markdown link KORUNDU
    assert "[Türkiye Suç Mağduriyeti 2025](https://example.com)" in out
    assert "duruyor." in out


def test_strip_preserves_markdown_link():
    """Markdown `[label](url)` etkilenmez."""
    md = "[normal link](https://x.com) ve **kalın** metin"
    out = strip_inline_html_tags(md)
    assert "[normal link](https://x.com)" in out
    assert "**kalın**" in out


def test_strip_multiple_anchors():
    """Birden çok `<a>...</a>` tag'i temizlenir."""
    md = (
        "[A](https://a) "
        '<a href="https://muhakeme.ai/emsal?q=X" class="muhakeme-cross">'
        "AAA</a>"
        " ve [B](https://b) "
        '<a href="https://muhakeme.ai/emsal?q=Y" class="muhakeme-cross">'
        "BBB</a>"
    )
    out = strip_inline_html_tags(md)
    assert "<a " not in out
    assert "</a>" not in out
    assert out.count("[A]") == 1
    assert out.count("[B]") == 1


def test_strip_handles_orphan_tags():
    """Self-closing veya orphan span/button kapanışları da silinir."""
    md = "metin <span class='foo'>içerik</span> devam <button>X</button> son"
    out = strip_inline_html_tags(md)
    assert "<span" not in out
    assert "</span>" not in out
    assert "<button" not in out
    assert "</button>" not in out
    # İçerik metni korunmuyor (span/button içeriği LLM artifacti, silinir)
    # ama dış metin korundu
    assert "metin" in out
    assert "devam" in out
    assert "son" in out


def test_strip_no_html_passthrough():
    """HTML olmayan markdown değişmez."""
    md = "## Başlık\n\n[link](https://x) **bold** *italic*"
    out = strip_inline_html_tags(md)
    assert out == md


def test_strip_empty_string():
    assert strip_inline_html_tags("") == ""
