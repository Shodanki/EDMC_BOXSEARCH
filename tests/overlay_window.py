# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2025-2026 Shodanki
"""
The cockpit overlay in the plugin's own window (4.12, D3): the same blocks
as through EDMCModernOverlay, drawn on Tk's main thread only, scaled from
the 1280 x 960 canvas to the screen, gone when they expire, hidden while
the game is not in front; chosen and dropped in the settings.

    python tests/overlay_window.py      (from the plugin folder)
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plugin_pkg  # noqa: E402
load = plugin_pkg.import_plugin()
from SHBOXSEARCH import cockpit, overlaywin, state  # noqa: E402
from SHBOXSEARCH.overlay import CockpitOverlay  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print("  [%s] %s" % ("OK" if ok else "FAIL", what))
    fails += 0 if ok else 1


class FakeCanvas:
    def __init__(self):
        self.texts = []

    def delete(self, what):
        self.texts = []

    def create_text(self, x, y, **kw):
        self.texts.append((round(x), round(y), kw["text"], kw["fill"], kw["font"][1]))


class FakeTop:
    def __init__(self):
        self.shown, self.timers, self.destroyed = None, [], False

    def deiconify(self):
        self.shown = True

    def withdraw(self):
        self.shown = False

    def after(self, ms, fn):
        self.timers.append(fn)

    def destroy(self):
        self.destroyed = True


made = []


def factory(root):
    made.append(threading.current_thread() is threading.main_thread())
    made_win = (FakeTop(), FakeCanvas(), 1920, 1080)
    factory.win = made_win
    return made_win


queue = []
now = [1000.0]
front = [True]
client = overlaywin.WindowClient(queue.append, root=lambda: "root", in_front=lambda: front[0],
                                 window_factory=factory, clock=lambda: now[0])
ov = CockpitOverlay(client=client)

print("drawing through the unchanged CockpitOverlay")
ov.show_briefing({"name": "Synuefe ML-L b41-5", "kind": "target", "star_class": "K", "scoopable": True}, seconds=10)
check(len(queue) == 1 and not made, "stored, one redraw asked for, no window yet")
ov.show_briefing({"name": "Other", "kind": "target"}, seconds=10)
check(len(queue) == 1, "a second block before the redraw: still one redraw")
queue.pop()()                                       # the main thread runs it
top, canvas, w, h = factory.win
check(made == [True], "the window is made on the main thread, on the first redraw")
check(top.shown is True and canvas.texts and canvas.texts[0][2].startswith("BRIEFING > Other"),
      "drawn and shown while the game is in front (%r)" % (canvas.texts[:1],))
x0, y0 = overlaywin.CANVAS_W, overlaywin.CANVAS_H
bx, by = ov._origin("brief")                       # where ModernOverlay would put it
check(canvas.texts[0][0] == round(bx * 1920 / x0) and canvas.texts[0][1] == round(by * 1080 / y0),
      "the 1280 x 960 canvas scaled to 1920 x 1080 (%d,%d -> %r)" % (bx, by, canvas.texts[0][:2]))
check(canvas.texts[0][4] == round(10 * 1080 / 960), "the font scaled with the screen (small = 10 pt at 960)")
check(len(top.timers) == 1, "one timer for expiry and focus")

print("expiry, removal, focus")
now[0] += 11
top.timers.pop()()
check(canvas.texts == [] and client.lines() == {} and top.shown is False,
      "after its ttl the block is gone and the window hidden")
ov.show_briefing({"name": "Third", "kind": "arrival"}, seconds=10)
front[0] = False
queue.pop()()
check(top.shown is False and canvas.texts, "game not in front: drawn but hidden (Alt+Tab)")
front[0] = True
top.timers.pop()()
check(top.shown is True, "back in the game: shown again")
ov.clear("brief")
queue.pop()()
check(client.lines() == {} and canvas.texts == [], "clear sends empty texts: the lines go")

print("worker threads never touch Tk")
queue.clear()
t = threading.Thread(target=lambda: ov.show_briefing({"name": "From a worker"}, seconds=5))
t.start()
t.join()
check(len(queue) == 1 and len(made) == 1, "a worker only stores the text and queues the redraw")
queue.pop()()

print("the settings switch the overlay")
cfg = {}
plugin_pkg.use_settings(cfg)
state.ST.overlay = CockpitOverlay()
cfg[state.CFG["overlay_backend"]] = "window"
cockpit._overlay_apply_settings()
own = isinstance(state.ST.overlay.client, overlaywin.WindowClient)
check(own == overlaywin.supported(), "own window chosen (where the system can click through)")
if own:
    c = state.ST.overlay.client
    cfg[state.CFG["overlay_backend"]] = "modern"
    cockpit._overlay_apply_settings()
    check(state.ST.overlay.client is None and c.lines() == {}, "back to ModernOverlay: own window closed")

print("real Tk (when a display is there)")
try:
    import tkinter as tk
    rt = tk.Tk()
except Exception as e:
    print("  [skip] no Tk display (%s)" % type(e).__name__)
else:
    rt.withdraw()
    real = overlaywin.WindowClient(lambda fn: rt.after(0, fn), root=lambda: rt, in_front=lambda: False)
    real.send_message("shbox-test-0", "SHBOX test line", "#7CFF6B", 16, 96, ttl=2, size="small")
    rt.after(400, rt.quit)
    rt.mainloop()
    win = real._win
    check(win is not None and win[0].winfo_exists() and win[1].find_all(),
          "a real window drawn (%sx%s), hidden while the game is not in front" % (win[2], win[3]) if win else "no window")
    real.close()
    check(real._win is None, "closed again")
    rt.destroy()

print("overlay window: %s" % ("all OK" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
