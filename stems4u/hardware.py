"""Hardware Detection Engine: CPU, RAM, GPU/VRAM e recomendação de modo."""
from __future__ import annotations

import ctypes
import os
import platform
import subprocess
import sys


def _ram_gb() -> float | None:
    try:
        import psutil  # opcional
        return round(psutil.virtual_memory().total / 2**30, 1)
    except ImportError:
        pass
    try:
        if sys.platform == "darwin":
            return round(int(subprocess.check_output(["sysctl", "-n", "hw.memsize"])) / 2**30, 1)
        if sys.platform.startswith("win"):
            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MS()
            st.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return round(st.ullTotalPhys / 2**30, 1)
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except Exception:  # noqa: BLE001
        return None


def _cpu_name() -> str:
    try:
        if sys.platform == "darwin":
            return subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
    except Exception:  # noqa: BLE001
        pass
    return platform.processor() or platform.machine()


def detect() -> dict:
    info = {
        "os": f"{platform.system()} {platform.release()}",
        "macos_version": platform.mac_ver()[0] or None,
        "arch": platform.machine(),
        "cpu": _cpu_name(),
        "cpu_threads": os.cpu_count(),
        "ram_gb": _ram_gb(),
        "torch": None, "device": "cpu", "gpu": None, "vram_gb": None,
    }
    try:
        import torch
        info["torch"] = torch.__version__
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            info.update(device="cuda", gpu=p.name, vram_gb=round(p.total_memory / 2**30, 1))
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            info.update(device="mps", gpu="Apple Silicon (Metal)", vram_gb=info["ram_gb"])
    except ImportError:
        pass
    info["recommendation"] = recommend(info)
    return info


def recommend(info: dict) -> dict:
    dev, vram, ram = info["device"], info.get("vram_gb") or 0, info.get("ram_gb") or 0
    if dev == "cuda" and vram >= 8:
        q, why = "ultra", "GPU NVIDIA com VRAM suficiente."
    elif dev in ("cuda", "mps"):
        q, why = "high", "Aceleração por GPU disponível."
    elif ram >= 12 and (info.get("cpu_threads") or 1) >= 8:
        q, why = "balanced", "Só CPU: modo Equilibrado. Alta Qualidade funciona, mas ~4x mais lento."
    else:
        q, why = "fast", "Só CPU com poucos recursos: modo Rápido recomendado."
    return {"quality": q, "reason": why, "cpu_fallback": True}
