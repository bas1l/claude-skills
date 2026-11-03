"""Is this process, and not another that got its number since, still running? Knows nothing of what it runs.

A process number comes with its creation time, so that a number the system has since given to another
process is not mistaken for ours, and no other process can be ended by mistake. ``os.kill(pid, 0)``
is no test on Windows: signal 0 there means sending Ctrl+C.
"""
from __future__ import annotations

import ctypes
import os
import signal
from typing import Optional

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_PROC_STAT_START_FIELD = 19  # After the closing bracket of the name, counted from 0.


def _windows_identity(pid: int) -> Optional[str]:
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != _STILL_ACTIVE:
            return None
        created, ended, in_kernel, in_user = (wintypes.FILETIME() for _ in range(4))
        if not kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(ended), ctypes.byref(in_kernel), ctypes.byref(in_user)):
            return None
        return f"{created.dwHighDateTime}:{created.dwLowDateTime}"
    finally:
        kernel32.CloseHandle(handle)


def _posix_identity(pid: int) -> Optional[str]:
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as handle:
            return handle.read().rpartition(")")[2].split()[_PROC_STAT_START_FIELD]
    except (OSError, IndexError):
        return None


def identity_of(pid: int) -> Optional[str]:
    """What tells this running process from any other given the same number. None if it is not running."""
    if pid <= 0:
        return None
    return _windows_identity(pid) if os.name == "nt" else _posix_identity(pid)


def is_running(pid: int, identity: Optional[str]) -> bool:
    return identity is not None and identity_of(pid) == identity


def terminate(pid: int, identity: Optional[str]) -> bool:
    """End this process if it is still the same one. True if it was ended here."""
    if not is_running(pid, identity):
        return False
    os.kill(pid, signal.SIGTERM)
    return True
