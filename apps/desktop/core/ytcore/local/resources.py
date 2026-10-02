"""Ağır süreçler için anlık bellek bütçesi; engine ML runtime import etmez."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path


def available_bytes() -> int | None:
    if os.name == "nt":

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("load", ctypes.c_ulong),
                ("total_phys", ctypes.c_ulonglong),
                ("avail_phys", ctypes.c_ulonglong),
                ("total_page", ctypes.c_ulonglong),
                ("avail_page", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("avail_virtual", ctypes.c_ulonglong),
                ("avail_extended", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.avail_phys)
        return None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return None


def require_memory(working_bytes: int, reserve_bytes: int = 768 * 1024**2) -> None:
    free = available_bytes()
    if free is None:
        raise RuntimeError("Boş RAM ölçülemedi. Ağır model güvenli biçimde başlatılamadı.")
    if free < working_bytes + reserve_bytes:
        raise RuntimeError(
            f"Model için boş RAM yetersiz: {free / 1024**3:.1f} GB boş, "
            f"{(working_bytes + reserve_bytes) / 1024**3:.1f} GB gerekli. "
            "Diğer uygulamaları kapatıp yeniden deneyin."
        )
