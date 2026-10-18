#!/usr/bin/env python3
"""kb_lock.py — межпроцессная блокировка файла и завершение дерева процессов на любой ОС.

POSIX — `fcntl.flock`, Windows — `msvcrt.locking` на первом байте файла-замка. Модуль
`fcntl` в Windows отсутствует, и его безусловный импорт ронял `kb_start.py` и
`kb_service.py` ещё до разбора аргументов (отчёт с Windows, 18.10.2026).
"""
import os
import signal
import subprocess
import sys

try:
    import fcntl
except ImportError:                      # Windows
    fcntl = None
try:
    import msvcrt
except ImportError:                      # POSIX
    msvcrt = None


def try_lock(handle):
    """Неблокирующий захват открытого файла-замка: True — захвачен, False — занят."""
    if fcntl is not None:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (BlockingIOError, PermissionError):
            return False
        except OSError:
            return False
    if msvcrt is not None:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    return True                          # нет механизма — без блокировки, как один процесс


def unlock(handle):
    if fcntl is not None:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        except OSError:
            pass
    elif msvcrt is not None:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


def new_group_kwargs():
    """Аргументы Popen, чтобы процесс и его дети завершались вместе."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def kill_tree(proc):
    """Завершить процесс вместе с детьми (git clone), не оставляя сирот."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired):
        try:
            proc.kill()
        except OSError:
            pass


def utf8_stdio():
    """Вывод скриптов — UTF-8 и на Windows: консоль cp1252 роняла печать кириллицы уже после
    записи файла входа (отчёт с Windows, 18.10.2026). На POSIX ничего не меняет."""
    if os.name != "nt":
        return
    for stream in (sys.stdout, sys.stderr):
        try:
            if (getattr(stream, "encoding", "") or "").lower().replace("-", "") != "utf8":
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


utf8_stdio()
