"""Versioned prompt templates for the rasathane LLM helpers.

Templates live as ``.md`` files in this package; ``llm.prompts.load_prompt``
reads them via ``importlib.resources`` so they ship inside the wheel.

Bu modül kasıtlı olarak Jinja2 dependency getirmez — placeholder
substitution dışında bir özelliğe ihtiyaç olmadığı sürece sadelik
kazanır. Karmaşık şart-mantığı gerekirse Jinja2'ye geçilir.
"""

from __future__ import annotations

import re
from importlib import resources

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def render(template: str, /, **variables: str) -> str:
    """Replace ``{{name}}`` occurrences with ``variables[name]``.

    Single-pass regex substitution: bir değer içine gömülmüş ``{{x}}``
    ikinci tur'da yeniden ikame edilmez (RSS başlığında ``{{url}}``
    geçiyorsa kazara mutate olmaz). Tanımlı olmayan placeholder'lar
    olduğu gibi kalır.
    """
    return _PLACEHOLDER_RE.sub(
        lambda m: variables.get(m.group(1), m.group(0)),
        template,
    )


def load_prompt(name: str) -> str:
    """Return the contents of ``llm/prompts/<name>.md`` as text.

    Raises ``FileNotFoundError`` if the template file does not exist.
    """
    pkg = resources.files("llm.prompts")
    path = pkg.joinpath(f"{name}.md")
    if not path.is_file():
        raise FileNotFoundError(f"prompt template not found: {name}.md")
    return path.read_text(encoding="utf-8")
