# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
5.1.0 SV1 (user 25.11.): connection problems with the game's servers, from
the game's own network log - shared by the plugin's overlay (situation
column) and the FIS (ship bar).

The game writes ``netLog.*.log`` into the ``Logs`` folder next to its
``EliteDangerous64.exe`` (``Products\\<product>\\Logs``). Least privilege,
as CONTRIBUTING says:

- only the newest netLog, only its end (from where the last read stopped),
  read only, and only while the game runs;
- the folder from the running game's own path (asked from Windows by the
  process name) or from the ``netlog_dir`` setting - drives are never
  searched;
- nothing is stored or sent: only counts and times stay in memory; the
  log's addresses and names are never kept.

What counts (from the outage of 22.11.2026): the mission server silent for
20 s and more ("First packet received ... for a while (23.9s)" - 332 times
in three hours), "n machines overdue", "TransmitJournal: error on receive";
an explicit "connection lost" / "disconnected" line means lost. Three
silences within ten minutes are "connection problems since hh:mm"; ten
quiet minutes while the game keeps writing clear it again.
"""

from __future__ import annotations

import calendar
import glob
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

__all__ = ["NetWatch", "find_logs_dir", "newest_netlog", "lines"]

SILENT_MIN_S = 20.0           # a silence shorter than this is normal traffic
WINDOW_S = 10 * 60            # problems counted over this window ...
TROUBLE_AT = 3                # ... from this many on
CLEAR_S = 10 * 60             # quiet this long (the log still growing) clears it
READ_MAX = 1 << 20            # never more than 1 MiB per read (a first read starts near the end)

_TS = re.compile(r"^\{(\d\d):(\d\d):(\d\d)GMT")
_SILENT = re.compile(r"First packet received from .*for a while \((\d+(?:\.\d+)?)s\)")
_OVERDUE = re.compile(r"\b(\d+) machines overdue")
_RTT = re.compile(r"avgsrtt=(\d+)")
_LOST = re.compile(r"connection lost|lost connection|disconnected from server|connectionlost", re.I)
_NAME = re.compile(r"netLog\.(\d{4})-(\d\d)-(\d\d)T(\d\d)(\d\d)(\d\d)")


def newest_netlog(folder: Optional[str]) -> Optional[str]:
    """The newest netLog of the game's Logs folder, or None."""
    if not folder or not os.path.isdir(folder):
        return None
    files = sorted(glob.glob(os.path.join(folder, "netLog.*.log")))
    return files[-1] if files else None


def _game_exe() -> Optional[str]:
    """The full path of the running EliteDangerous64.exe (Windows), or None."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)                       # TH32CS_SNAPPROCESS
        if not snap or snap == wintypes.HANDLE(-1).value:
            return None
        pid = None
        try:
            e = Entry()
            e.dwSize = ctypes.sizeof(Entry)
            ok = k32.Process32FirstW(snap, ctypes.byref(e))
            while ok:
                if e.szExeFile.lower() == "elitedangerous64.exe":
                    pid = e.th32ProcessID
                    break
                ok = k32.Process32NextW(snap, ctypes.byref(e))
        finally:
            k32.CloseHandle(snap)
        if pid is None:
            return None
        h = k32.OpenProcess(0x1000, False, pid)                           # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return None
            return buf.value
        finally:
            k32.CloseHandle(h)
    except Exception:
        return None


def find_logs_dir(setting: Optional[str] = None) -> Tuple[Optional[str], bool]:
    """(the game's Logs folder, the game runs). The setting wins when it
    names a folder; else the folder next to the running game. Without the
    game running there is nothing to read (None, False)."""
    exe = _game_exe()
    running = exe is not None
    if setting and os.path.isdir(setting):
        return setting, running
    if exe:
        folder = os.path.join(os.path.dirname(exe), "Logs")
        if os.path.isdir(folder):
            return folder, True
    return None, running


def _file_start(path: str) -> Optional[float]:
    """The netLog's start from its name (local time) as Unix time."""
    m = _NAME.search(os.path.basename(path))
    if not m:
        return None
    try:
        return time.mktime(tuple(int(x) for x in m.groups()) + (0, 0, -1))   # type: ignore[arg-type]
    except (OverflowError, ValueError):
        return None


class NetWatch:
    """Reads the newest netLog from where it stopped and keeps what the
    lines say about the connection (counts and times only)."""

    def __init__(self) -> None:
        self.path: Optional[str] = None
        self.offset = 0
        self.start: Optional[float] = None
        self.events: List[Tuple[float, str]] = []     # (time, "silent" | "overdue" | "error" | "lost")
        self.longest = 0.0
        self.rtt: Optional[int] = None
        self.last_line: Optional[float] = None
        self._day = 0.0

    def _ts(self, line: str) -> Optional[float]:
        m = _TS.match(line)
        if not m or self.start is None:
            return None
        h, mi, s = (int(x) for x in m.groups())
        g = time.gmtime(self.start + self._day)
        ts = float(calendar.timegm((g.tm_year, g.tm_mon, g.tm_mday, h, mi, s, 0, 0, 0)))
        if ts < self.start + self._day - 12 * 3600:     # past midnight GMT
            self._day += 86400
            ts += 86400
        return ts

    def feed_line(self, line: str) -> None:
        """One line of the netLog."""
        ts = self._ts(line)
        if ts is None:
            return
        self.last_line = ts
        kind = None
        m = _SILENT.search(line)
        if m and float(m.group(1)) >= SILENT_MIN_S:
            kind = "silent"
            self.longest = max(self.longest, float(m.group(1)))
        elif _OVERDUE.search(line):
            kind = "overdue"
        elif "TransmitJournal: error on receive" in line:
            kind = "error"
        elif _LOST.search(line):
            kind = "lost"
        else:
            r = _RTT.search(line)
            if r:
                self.rtt = int(r.group(1))
        if kind:
            self.events.append((ts, kind))
            del self.events[:-500]

    def read(self, path: Optional[str]) -> int:
        """Read what the netLog gained since the last read; a new file starts
        over. Returns the lines read."""
        if not path:
            return 0
        if path != self.path:
            self.__init__()
            self.path, self.start = path, _file_start(path)
        try:
            size = os.path.getsize(path)
            if size < self.offset:
                self.offset = 0
            if size - self.offset > READ_MAX:
                self.offset = size - READ_MAX
            with open(path, "rb") as fh:
                fh.seek(self.offset)
                chunk = fh.read(size - self.offset)
        except OSError:
            return 0
        end = chunk.rfind(b"\n") + 1
        self.offset += end
        n = 0
        for raw in chunk[:end].splitlines():
            self.feed_line(raw.decode("utf-8", "replace"))
            n += 1
        return n

    def state(self, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """None while the connection is fine, else {"state": "trouble" |
        "lost", "since", "count" (in the window), "longest", "rtt"}."""
        now = self.last_line if now is None else now
        if now is None or not self.events:
            return None
        last_kind_ts = self.events[-1][0]
        if any(k == "lost" for t, k in self.events if now - t <= CLEAR_S):
            lost_ts = max(t for t, k in self.events if k == "lost")
            return {"state": "lost", "since": lost_ts, "count": 1, "longest": self.longest, "rtt": self.rtt}
        if now - last_kind_ts > CLEAR_S:
            return None                               # quiet long enough: fine again
        recent = [t for t, _k in self.events if now - t <= WINDOW_S]
        if len(recent) < TROUBLE_AT:
            return None
        since = recent[0]                             # the streak: back while gaps stay under CLEAR_S
        for t, _k in reversed(self.events):
            if since - t > CLEAR_S:
                break
            since = min(since, t)
        return {"state": "trouble", "since": since, "count": len(recent), "longest": round(self.longest, 1),
                "rtt": self.rtt}


def lines(state: Optional[Dict[str, Any]], line_max: int = 44) -> List[Tuple[str, str]]:
    """The overlay's lines (text, colour key) for a state; none while fine."""
    if not state:
        return []
    hhmm = time.strftime("%H:%M", time.localtime(state["since"]))
    if state["state"] == "lost":
        return [(("GAME SERVER  connection lost %s" % hhmm)[:line_max], "alert")]
    bits = ["%d silences in 10 min" % state["count"]]
    if state.get("rtt"):
        bits.append("rtt %d ms" % state["rtt"])
    return [(("GAME SERVER  connection problems since %s" % hhmm)[:line_max], "warn"),
            (("      " + " · ".join(bits))[:line_max], "dim")]
