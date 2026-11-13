# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
UI hand-over test (4.10.1): worker threads never call Tk directly.

EDMC's rule (PLUGINS.md, "All tkinter calls in main thread"): the only Tk
call a sub-thread may make is event_generate(), and none at all while EDMC
shuts down. uithread._ui() is the one door from a worker to the window; this
test pins down that

  * a worker queues the update and only calls event_generate (no after()),
  * the update then runs on the main thread when the event is handled,
  * on the main thread _ui() keeps scheduling with after(0) as before,
  * during shutdown nothing is sent and queued updates are dropped,
  * a failing update is logged and does not stop the others,
  * no other function reachable from a worker touches a Tk object.

No window is opened: the frame is a recording stand-in.

    python tests/ui_threads.py      (from the plugin folder)
"""
import ast
import os
import sys
import threading
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for m in ("config", "theme", "myNotebook", "monitor", "l10n", "companion", "plug",
          "EDMCLogging", "ttkHyperlinkLabel"):
    sys.modules[m] = mock.MagicMock()
try:                                  # CI images may lack Tk; no window is opened
    import tkinter  # noqa: F401
except ImportError:
    for m in ("tkinter", "tkinter.filedialog", "tkinter.ttk"):
        sys.modules[m] = mock.MagicMock()

import plugin_pkg  # noqa: E402
load = plugin_pkg.import_plugin()
from SHBOXSEARCH import panel, state, uithread  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


class FakeFrame:
    """Records which thread made which Tk call."""

    def __init__(self):
        self.calls = []
        self.bound = {}

    def _note(self, what):
        self.calls.append((what, threading.current_thread() is threading.main_thread()))

    def after(self, ms, fn):
        self._note("after")
        fn()

    def event_generate(self, seq, when=None):
        self._note("event_generate %s %s" % (seq, when))

    def bind(self, seq, fn, add=None):
        self.bound[seq] = fn

    def winfo_toplevel(self):
        return self                      # stand-in: frame and top level in one


frame = FakeFrame()
panel._frame = frame
uithread._ui_target = frame.winfo_toplevel()
uithread.config.shutting_down = False
frame.bind(uithread._UI_EVENT, uithread._ui_drain)

ran = []


def update(tag):
    ran.append((tag, threading.current_thread() is threading.main_thread()))


# 1. from a worker: queue + event_generate only
w = threading.Thread(target=lambda: uithread._ui(lambda: update("worker")))
w.start()
w.join()
check(frame.calls == [("event_generate %s tail" % uithread._UI_EVENT, False)],
      "worker: one event_generate(when='tail'), no after() - %s" % frame.calls)
check(ran == [], "worker: nothing ran on the worker thread")
check(uithread._ui_queue.qsize() == 1, "worker: update waits in the queue")

# 2. the event handler (main thread) runs it
frame.bound[uithread._UI_EVENT](None)
check(ran == [("worker", True)], "main thread ran the queued update - %s" % ran)
check(uithread._ui_queue.empty(), "queue empty afterwards")

# 3. main thread: after(0) as before
frame.calls.clear()
ran.clear()
uithread._ui(lambda: update("main"))
check(frame.calls == [("after", True), ("after", True)] and ran == [("main", True)],
      "main thread: scheduled with after(0), plus a drain of waiting updates")

# 4. a failing update is logged, the next one still runs
ran.clear()
with mock.patch.object(state.logger, "exception") as logged:
    t = threading.Thread(target=lambda: (uithread._ui(lambda: 1 / 0), uithread._ui(lambda: update("next"))))
    t.start()
    t.join()
    uithread._ui_drain()
check(logged.called and ran == [("next", True)], "failing update logged, next one ran")

# 5. shutdown: nothing sent, queued updates dropped
frame.calls.clear()
ran.clear()
t = threading.Thread(target=lambda: uithread._ui(lambda: update("queued")))
t.start()
t.join()
uithread.config.shutting_down = True
t = threading.Thread(target=lambda: uithread._ui(lambda: update("late")))
t.start()
t.join()
uithread._ui(lambda: update("late main"))
check(len(frame.calls) == 1, "shutting down: no further Tk call - %s" % frame.calls)
uithread._ui_drain()
check(ran == [] and uithread._ui_queue.empty(), "shutting down: queued update dropped, nothing drawn")
uithread.config.shutting_down = False

# 6. no frame yet (before plugin_app): silently nothing
panel._frame = None
uithread._ui(lambda: update("early"))
check(ran == [] and uithread._ui_queue.empty(), "before plugin_app: nothing queued")
panel._frame = frame

# 7. static check over every plugin module: worker entry points reach no Tk
#    object except through _ui. A function is (module, name); a call is a
#    bare name in the same module or "module.name" across modules.
MODULES = sorted(f[:-3] for f in os.listdir(ROOT) if f.endswith(".py"))
funcs = {}
for m in MODULES:
    with open(os.path.join(ROOT, m + ".py"), encoding="utf-8") as fh:
        for n in ast.parse(fh.read()).body:
            if isinstance(n, ast.FunctionDef):
                funcs[(m, n.name)] = n
TK_PREFIX = ("_v_", "_btn_", "_lbl_", "_route_win", "_stats_win", "_probe_win", "_mine_win")
TK_NAMES = {"_frame", "_radius_var", "_carrier_var"}
UI_CALLS = {("uithread", "_ui"), ("uithread", "_ui_drain")}


def target(mod, node):
    """(module, name) a Name or "module.name" expression refers to, or None."""
    if isinstance(node, ast.Name) and (mod, node.id) in funcs:
        return (mod, node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
            and (node.value.id, node.attr) in funcs:
        return (node.value.id, node.attr)
    return None


def tk_name(node):
    nm = node.id if isinstance(node, ast.Name) else \
        node.attr if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
        and node.value.id in MODULES else None
    return nm if nm and (nm in TK_NAMES or nm.startswith(TK_PREFIX)) else None


def direct(mod, fn):
    """Calls and Tk globals used by fn - not counting what is handed to _ui."""
    calls, tk = set(), set()
    local = {a.arg for a in fn.args.args}
    for n in ast.walk(fn):
        if isinstance(n, (ast.Assign, ast.For)):
            for tg in ([n.target] if isinstance(n, ast.For) else n.targets):
                for x in ast.walk(tg):
                    if isinstance(x, ast.Name):
                        local.add(x.id)
    skip = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and target(mod, n.func) == ("uithread", "_ui"):
            skip.update(id(x) for a in n.args for x in ast.walk(a))
    for n in ast.walk(fn):
        if id(n) in skip:
            continue
        if isinstance(n, ast.Call):
            t = target(mod, n.func)
            if t:
                calls.add(t)
            if t != ("uithread", "_ui"):            # functions handed on as arguments
                calls.update(x for x in (target(mod, a) for a in n.args) if x)
        nm = tk_name(n)
        if nm and not (isinstance(n, ast.Name) and n.id in local):
            # a bare truth test ("if _v_status:") is no Tk call
            tk.add(nm)
    return calls, tk


roots = set()
for (mod, _name), fn in funcs.items():          # _run_async(fn, ...) and Thread(target=fn)
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and target(mod, n.func) == ("uithread", "_run_async") and n.args:
            t = target(mod, n.args[0])
            if t:
                roots.add(t)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "Thread":
            for kw in n.keywords:
                t = target(mod, kw.value) if kw.arg == "target" else None
                if t:
                    roots.add(t)
seen, stack, bad = set(), sorted(roots), []
ALLOWED = {("panel", "_set_status"): {"_v_status"}}   # truth test only; the set() goes through _ui
while stack:
    f = stack.pop()
    if f in seen or f in UI_CALLS:
        continue
    seen.add(f)
    calls, tk = direct(f[0], funcs[f])
    tk -= ALLOWED.get(f, set())
    if tk:
        bad.append("%s.%s: %s" % (f[0], f[1], ",".join(sorted(tk))))
    stack.extend(c for c in calls if c not in seen)
check(len(roots) >= 15, "found %d worker entry points" % len(roots))
check(not bad, "no direct Tk access from %d worker-reachable functions%s"
      % (len(seen), (" - " + "; ".join(bad)) if bad else ""))

# 8. real Tk, when a display is there (not on CI): a hidden top level and an
#    unmapped frame - Tk drops virtual events for unmapped widgets, so the
#    event must go to the top level
try:
    import tkinter as real_tk
    root = real_tk.Tk()
except Exception as e:                 # no display / no Tk
    print("  [skip] real Tk not available (%s)" % type(e).__name__)
else:
    root.withdraw()
    panel._frame = real_tk.Frame(root)  # never packed, like before EDMC maps it
    uithread._ui_target = panel._frame.winfo_toplevel()
    uithread._ui_target.bind(uithread._UI_EVENT, uithread._ui_drain, add="+")
    hits = []

    def burst():
        for i in range(200):
            uithread._ui(lambda: hits.append(threading.current_thread() is threading.main_thread()))

    workers = [threading.Thread(target=burst) for _ in range(4)]
    root.after(50, lambda: [x.start() for x in workers])
    root.after(1500, root.quit)
    root.mainloop()
    check(len(hits) == 800 and all(hits),
          "real Tk: %d of 800 updates from 4 workers ran on the main thread" % len(hits))
    root.destroy()

print("ui threads: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
