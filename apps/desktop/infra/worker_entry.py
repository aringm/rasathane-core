"""Bağımsız NER/ASR worker; yalnız sabit modül adları çalışır."""

from __future__ import annotations

import importlib
import sys

MODES = {"ner": "ytcore.router.ner_worker", "asr": "ytcore.transcript.asr_worker"}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in MODES:
        print("Geçersiz worker türü.", file=sys.stderr)
        return 2
    sys.argv = [sys.argv[0], *sys.argv[2:]]
    result = importlib.import_module(MODES[mode]).main()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
