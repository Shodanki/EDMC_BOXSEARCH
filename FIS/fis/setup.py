"""
First start and settings - asked once in the console, remembered in fis.ini.

No command-line parameters for the user: start_fis.bat asks on the very
first start how the FIS should be served (language, this PC only or the home
network too, open the browser) and writes the answers to fis.ini.
fis_settings.bat asks again.

For the home network it also tells you where to find the page (this PC's
addresses) and offers to create the Windows firewall rule - only with your
yes, through Windows' own admin prompt (UAC), limited to the FIS port, the
private profile and the local subnet. The FIS itself never changes firewall
settings silently.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from typing import Callable, Dict, List, Optional

RULE_NAME = "SHBOX FIS"

MSG: Dict[str, Dict[str, str]] = {
    "en": {
        "welcome": "SHBOX FIS - first start. A few questions, asked only once (change later: fis_settings.bat).",
        "lang": "Language of the FIS  [1] English  [2] Deutsch",
        "access": "Who may open the FIS?\n  [1] only this PC\n  [2] this PC and devices in the home network (tablet, second PC) - with access token",
        "browser": "Open the browser when the FIS starts?  [Y/n]",
        "port": "Port (Enter = %d)",
        "db_found": "Plugin database: %s",
        "db_missing": "Plugin database not found at %s\n  Path to shboxsearch.sqlite (Enter = keep)",
        "journal_found": "Game journals: %s",
        "journal_missing": "Journal folder not found at %s\n  Path (Enter = keep)",
        "saved": "Saved in %s",
        "choice": "> ",
        "fw_ok": "Firewall: rule '%s' allows port %d.",
        "fw_missing": "Firewall: no rule for port %d - other devices will not reach the FIS.",
        "fw_ask": "Create the rule now? Windows will ask for admin permission. Only TCP port %d, private networks, local subnet.  [Y/n]",
        "fw_created": "Firewall rule created.",
        "fw_failed": "Rule not created (cancelled or no permission). You can run fis_settings.bat again later.",
        "fw_hint": "Create it later with fis_settings.bat, or allow port %d (TCP, private) in Windows Defender Firewall.",
        "fw_unknown": "Firewall state could not be read (not Windows?).",
        "lan_urls": "Open on other devices (same network):",
        "token_note": "The token is needed once per device; afterwards a cookie remembers it.",
    },
    "de": {
        "welcome": "SHBOX FIS - erster Start. Ein paar Fragen, nur dieses eine Mal (später ändern: fis_settings.bat).",
        "lang": "Sprache des FIS  [1] English  [2] Deutsch",
        "access": "Wer darf das FIS öffnen?\n  [1] nur dieser PC\n  [2] dieser PC und Geräte im Heimnetz (Tablet, zweiter PC) - mit Zugangs-Token",
        "browser": "Browser beim Start öffnen?  [J/n]",
        "port": "Port (Enter = %d)",
        "db_found": "Plugin-Datenbank: %s",
        "db_missing": "Plugin-Datenbank nicht gefunden unter %s\n  Pfad zu shboxsearch.sqlite (Enter = beibehalten)",
        "journal_found": "Spiel-Journale: %s",
        "journal_missing": "Journal-Ordner nicht gefunden unter %s\n  Pfad (Enter = beibehalten)",
        "saved": "Gespeichert in %s",
        "choice": "> ",
        "fw_ok": "Firewall: Regel '%s' erlaubt Port %d.",
        "fw_missing": "Firewall: keine Regel für Port %d - andere Geräte erreichen das FIS nicht.",
        "fw_ask": "Regel jetzt anlegen? Windows fragt nach Admin-Rechten. Nur TCP-Port %d, private Netze, lokales Subnetz.  [J/n]",
        "fw_created": "Firewall-Regel angelegt.",
        "fw_failed": "Regel nicht angelegt (abgebrochen oder keine Rechte). Später erneut mit fis_settings.bat.",
        "fw_hint": "Später mit fis_settings.bat anlegen oder Port %d (TCP, privat) in der Windows-Defender-Firewall freigeben.",
        "fw_unknown": "Firewall-Zustand nicht lesbar (kein Windows?).",
        "lan_urls": "Auf anderen Geräten öffnen (gleiches Netz):",
        "token_note": "Das Token braucht jedes Gerät einmal; danach merkt es sich ein Cookie.",
    },
}


def msg(lang: str, key: str) -> str:
    return MSG.get(lang, MSG["en"]).get(key) or MSG["en"][key]


# ---------------------------------------------------------------- network

def lan_addresses() -> List[str]:
    """This PC's IPv4 addresses in private networks (no packet is sent)."""
    found: List[str] = []
    try:
        # connect() on UDP only picks the outgoing interface
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("192.0.2.1", 9))         # TEST-NET-1, never routed
            found.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found:
                found.append(ip)
    except OSError:
        pass
    return [ip for ip in found if _private(ip)]


def _private(ip: str) -> bool:
    try:
        a, b = (int(x) for x in ip.split(".")[:2])
    except ValueError:
        return False
    return a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168)


def lan_urls(port: int, token: str) -> List[str]:
    q = "?token=%s" % token if token else ""
    urls = ["http://%s:%d/%s" % (ip, port, q) for ip in lan_addresses()]
    urls.append("http://%s:%d/%s" % (socket.gethostname(), port, q))
    return urls


# ---------------------------------------------------------------- firewall

def _netsh(args: List[str]) -> Optional[str]:
    if os.name != "nt":
        return None
    try:
        r = subprocess.run(["netsh"] + args, capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    # UTF-8 on current Windows, otherwise the console code page
    try:
        return r.stdout.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for enc in ("oem", "mbcs"):
        try:
            return r.stdout.decode(enc, errors="replace")
        except LookupError:
            continue
    return r.stdout.decode("latin-1", errors="replace")


# netsh field names, English and German Windows
_K_NAME = ("rule name", "regelname")
_K_ENABLED = ("enabled", "aktiviert")
_K_ACTION = ("action", "aktion")
_K_PROTO = ("protocol", "protokoll")
_K_PORT = ("localport", "lokaler port")
_YES = ("yes", "ja")
_ALLOW = ("allow", "zulassen")
_ANY = ("any", "beliebig")


def _rules(text: str) -> List[Dict[str, str]]:
    rules: List[Dict[str, str]] = []
    cur: Optional[Dict[str, str]] = None
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k in _K_NAME:
            cur = {"name": v}
            rules.append(cur)
        elif cur is not None:
            for key, names in (("enabled", _K_ENABLED), ("action", _K_ACTION),
                               ("proto", _K_PROTO), ("port", _K_PORT)):
                if k in names:
                    cur[key] = v
    return rules


def firewall_rule_ok(port: int, run: Callable = _netsh) -> Optional[str]:
    """
    Name of an enabled inbound rule that allows TCP on this port - ours or
    one you made yourself. "" = none, None = cannot tell. Read only.
    """
    out = run(["advfirewall", "firewall", "show", "rule", "name=all", "dir=in", "verbose"])
    if out is None:
        return None
    for r in _rules(out):
        ports = r.get("port", "").replace(" ", "").split(",")
        if (r.get("enabled", "").lower() in _YES and r.get("action", "").lower() in _ALLOW
                and r.get("proto", "").lower() in ("tcp",) + _ANY
                and (str(port) in ports or _in_range(port, ports))):
            return r["name"]
    return ""


def _in_range(port: int, ports: List[str]) -> bool:
    for p in ports:
        if "-" in p:
            a, _, b = p.partition("-")
            if a.isdigit() and b.isdigit() and int(a) <= port <= int(b):
                return True
    return False


def firewall_rule_command(port: int) -> List[str]:
    """The elevated call: one inbound TCP rule, private profile, local subnet only."""
    netsh_args = ('advfirewall firewall add rule name="%s" dir=in action=allow protocol=TCP '
                  'localport=%d profile=private remoteip=localsubnet' % (RULE_NAME, port))
    ps = ("Start-Process -FilePath netsh -Verb RunAs -Wait -WindowStyle Hidden "
          "-ArgumentList '%s'" % netsh_args.replace("'", "''"))
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps]


def create_firewall_rule(port: int) -> bool:
    """Ask Windows (UAC) to add the rule. Only called after the user said yes."""
    if os.name != "nt":
        return False
    try:
        subprocess.run(firewall_rule_command(port), timeout=120)
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(firewall_rule_ok(port))


# ---------------------------------------------------------------- dialogue

def _ask(inp: Callable[[str], str], out: Callable[[str], None], text: str) -> str:
    out(text)
    try:
        return (inp(msg("en", "choice")) or "").strip()
    except EOFError:
        return ""


def _yes(ans: str, default: bool = True) -> bool:
    a = ans.strip().lower()
    if not a:
        return default
    return a[0] in ("y", "j", "1")


def run_setup(cfg, inp: Callable[[str], str] = input, out: Callable[[str], None] = print) -> None:
    """The questions; answers go into cfg and fis.ini."""
    out(msg("en", "welcome"))
    a = _ask(inp, out, MSG["en"]["lang"])
    cfg.language = "de" if a in ("2", "de", "d") else "en"
    L = cfg.language
    if L == "de":
        out(msg(L, "welcome"))
    a = _ask(inp, out, msg(L, "access"))
    cfg.lan = a == "2"
    cfg.host = "0.0.0.0" if cfg.lan else "127.0.0.1"
    cfg.open_browser = _yes(_ask(inp, out, msg(L, "browser")), True)
    a = _ask(inp, out, msg(L, "port") % cfg.port)
    if a.isdigit() and 1024 <= int(a) <= 65535:
        cfg.port = int(a)
    if os.path.exists(cfg.db_path):
        out(msg(L, "db_found") % cfg.db_path)
    else:
        a = _ask(inp, out, msg(L, "db_missing") % cfg.db_path)
        if a:
            cfg.db_path = a.strip('"')
    if os.path.isdir(cfg.journal_dir):
        out(msg(L, "journal_found") % cfg.journal_dir)
    else:
        a = _ask(inp, out, msg(L, "journal_missing") % cfg.journal_dir)
        if a:
            cfg.journal_dir = a.strip('"')
    cfg.setup_done = True
    if cfg.lan:
        cfg.ensure_token(save=False)
    cfg.save()
    out(msg(L, "saved") % cfg.ini_path)


def check_lan(cfg, inp: Callable[[str], str] = input, out: Callable[[str], None] = print,
              interactive: bool = True, fw_ok: Callable = firewall_rule_ok,
              fw_create: Callable = create_firewall_rule) -> None:
    """LAN mode: firewall rule (ask once) and where the page can be found."""
    L = cfg.language
    ok = fw_ok(cfg.port)
    if ok is None:
        out(msg(L, "fw_unknown"))
    elif ok:
        out(msg(L, "fw_ok") % (ok, cfg.port))
    else:
        out(msg(L, "fw_missing") % cfg.port)
        if interactive and cfg.firewall != "declined":
            if _yes(_ask(inp, out, msg(L, "fw_ask") % cfg.port), True):
                if fw_create(cfg.port):
                    out(msg(L, "fw_created"))
                    cfg.firewall = "ok"
                else:
                    out(msg(L, "fw_failed"))
            else:
                cfg.firewall = "declined"
                out(msg(L, "fw_hint") % cfg.port)
            cfg.save()
        else:
            out(msg(L, "fw_hint") % cfg.port)
    out(msg(L, "lan_urls"))
    for u in lan_urls(cfg.port, cfg.token):
        out("  " + u)
    out(msg(L, "token_note"))


def interactive_console() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False
