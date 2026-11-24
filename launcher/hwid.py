"""HWID клиента: SHA-256 от серийников железа (алгоритм совпадает с серверным)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys

_APP_TAG = "nexus-v1"
_JUNK = {
    "",
    "none",
    "n/a",
    "na",
    "null",
    "unknown",
    "default string",
    "system serial number",
    "to be filled by o.e.m.",
    "to be filled by oem",
    "0123456789",
    "oem",
    "not applicable",
    "not specified",
}

_cache: str | None = None


def _run(cmd: list[str], timeout: float = 12.0) -> str:
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", timeout=timeout, creationflags=flags
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def _powershell(script: str) -> str:
    return _run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script]
    )


def _clean(value: str) -> str:
    value = re.sub(r"\s+", " ", (value or "").strip()).upper()
    if value.lower() in _JUNK or len(value) < 3:
        return ""
    return value


def _first(*values: str) -> str:
    for value in values:
        cleaned = _clean(value)
        if cleaned:
            return cleaned
    return ""


def _components() -> dict[str, str]:
    board = _first(_powershell("(Get-CimInstance Win32_BaseBoard).SerialNumber"))
    cpu = _first(_powershell("(Get-CimInstance Win32_Processor).ProcessorId"))
    disk = _first(
        _powershell("(Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID='C:'\").VolumeSerialNumber")
    )
    if not disk:
        match = re.search(r"[0-9A-F]{4}-[0-9A-F]{4}", _run(["cmd", "/c", "vol", "C:"]), re.IGNORECASE)
        disk = _clean(match.group(0)) if match else ""
    machine = _clean(
        _powershell("(Get-ItemProperty -Path 'HKLM:\\SOFTWARE\\Microsoft\\Cryptography').MachineGuid")
    )
    return {"board": board, "cpu": cpu, "disk": disk, "machine": machine}


def get_hwid(force: bool = False) -> str:
    """Возвращает 64-символьный hex. Кэшируется в пределах запуска."""
    global _cache
    if _cache and not force:
        return _cache
    if sys.platform != "win32":
        raise RuntimeError("HWID собирается только на Windows")

    parts = _components()
    if not (parts["board"] or parts["cpu"] or parts["disk"]):
        parts = {"machine": parts["machine"] or os.environ.get("COMPUTERNAME", "unknown")}

    raw = "|".join(f"{key}:{value}" for key, value in sorted(parts.items()) if value)
    _cache = hashlib.sha256(f"{_APP_TAG}|{raw}".encode("utf-8")).hexdigest().upper()
    return _cache


if __name__ == "__main__":
    print(json.dumps({"hwid": get_hwid(), "components": _components()}, ensure_ascii=False, indent=2))
