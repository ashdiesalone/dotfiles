#!/usr/bin/env python3
"""
Waybar calendar popup — Gruvbox dark, dwm-inspired flat style.
Toggle visibility: run this script; if already running, it kills the existing
instance (so binding it to the clock's on-click acts as a toggle).
"""

import gi
import os
import sys
import signal
import subprocess
import tempfile
from datetime import date

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

LOCK_FILE = os.path.join(tempfile.gettempdir(), "waybar-calendar.pid")

# ── Gruvbox dark palette ────────────────────────────────────────────────────
CSS = b"""
window {
    background-color: #282828;
    border: 1px solid #3c3836;
    border-radius: 0;
}

/* ── header bar ── */
#header {
    background-color: #1d2021;
    border-bottom: 1px solid #3c3836;
    padding: 4px 8px;
}

#month-label {
    color: #d79921;
    font-family: "Maple Mono", "JetBrains Mono", monospace;
    font-size: 12px;
    font-weight: bold;
    letter-spacing: 1px;
}

button {
    background: transparent;
    border: none;
    color: #928374;
    font-family: "Maple Mono", "JetBrains Mono", monospace;
    font-size: 13px;
    padding: 0 8px;
    min-width: 0;
    min-height: 0;
    border-radius: 0;
    box-shadow: none;
}

button:hover {
    background-color: #3c3836;
    color: #d79921;
}

/* ── weekday header row ── */
.weekday {
    color: #928374;
    font-family: "Maple Mono", "JetBrains Mono", monospace;
    font-size: 11px;
    padding: 4px 2px;
}

/* ── day cells ── */
.day {
    color: #ebdbb2;
    font-family: "Maple Mono", "JetBrains Mono", monospace;
    font-size: 12px;
    padding: 3px 2px;
    border-radius: 0;
    border: none;
}

.day:hover {
    background-color: #3c3836;
    color: #fabd2f;
}

/* today highlight */
.day.today {
    background-color: #d79921;
    color: #1d2021;
    font-weight: bold;
}

.day.today:hover {
    background-color: #fabd2f;
    color: #1d2021;
}

/* other-month days */
.day.other-month {
    color: #504945;
}

.day.other-month:hover {
    background-color: #3c3836;
    color: #665c54;
}

/* ── footer ── */
#footer {
    background-color: #1d2021;
    border-top: 1px solid #3c3836;
    padding: 3px 8px;
}

#footer-label {
    color: #504945;
    font-family: "Maple Mono", "JetBrains Mono", monospace;
    font-size: 11px;
}
"""

DAYS_HEADER = ["su", "mo", "tu", "we", "th", "fr", "sa"]

def iso_week(d: date) -> int:
    return d.isocalendar()[1]

def days_in_month(year: int, month: int) -> int:
    if month == 12:
        return (date(year + 1, 1, 1) - date(year, 12, 1)).days
    return (date(year, month + 1, 1) - date(year, month, 1)).days


class CalendarPopup(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.POPUP)
        today = date.today()
        self._today = today
        self._year = today.year
        self._month = today.month

        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_app_paintable(True)

        # Apply CSS
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # Close on Escape or focus loss
        self.connect("key-press-event", self._on_key)
        self.connect("focus-out-event", lambda *_: self._quit())

        self._build_ui()
        self._position_near_cursor()
        self.show_all()
        self.grab_focus()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        self._outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._outer.set_margin_top(0)
        self.add(self._outer)

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        header.set_name("header")

        btn_prev = Gtk.Button(label="◂")
        btn_prev.connect("clicked", lambda _: self._shift(-1))

        self._month_label = Gtk.Label()
        self._month_label.set_name("month-label")
        self._month_label.set_hexpand(True)
        self._month_label.set_halign(Gtk.Align.CENTER)

        btn_next = Gtk.Button(label="▸")
        btn_next.connect("clicked", lambda _: self._shift(1))

        header.pack_start(btn_prev, False, False, 0)
        header.pack_start(self._month_label, True, True, 0)
        header.pack_end(btn_next, False, False, 0)
        self._outer.pack_start(header, False, False, 0)

        # Day-name row
        wd_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        for name in DAYS_HEADER:
            lbl = Gtk.Label(label=name)
            lbl.get_style_context().add_class("weekday")
            lbl.set_size_request(34, -1)
            lbl.set_halign(Gtk.Align.CENTER)
            wd_row.pack_start(lbl, True, True, 0)
        self._outer.pack_start(wd_row, False, False, 0)

        # Grid placeholder
        self._grid_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._outer.pack_start(self._grid_box, False, False, 0)

        # Footer
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        footer.set_name("footer")
        self._footer_label = Gtk.Label()
        self._footer_label.set_name("footer-label")
        self._footer_label.set_halign(Gtk.Align.START)
        footer.pack_start(self._footer_label, True, True, 4)
        self._outer.pack_end(footer, False, False, 0)

        self._refresh_grid()

    def _refresh_grid(self):
        # Clear old grid
        for child in self._grid_box.get_children():
            self._grid_box.remove(child)

        y, m = self._year, self._month
        month_names = [
            "january","february","march","april","may","june",
            "july","august","september","october","november","december"
        ]
        self._month_label.set_text(f"{month_names[m-1]}  {y}")

        first_weekday = date(y, m, 1).weekday()  # 0=Mon … 6=Sun
        # Convert to Sun-first: Sun=0 … Sat=6
        first_weekday = (first_weekday + 1) % 7

        total_days = days_in_month(y, m)
        prev_days = days_in_month(y - 1 if m == 1 else y, 12 if m == 1 else m - 1)

        cells = []
        # Leading cells from previous month
        for i in range(first_weekday - 1, -1, -1):
            cells.append((prev_days - i, "other-month"))
        # Current month
        for d in range(1, total_days + 1):
            tag = "today" if date(y, m, d) == self._today else ""
            cells.append((d, tag))
        # Trailing cells
        extra = 0
        while (len(cells) + extra) % 7 != 0:
            extra += 1
        for d in range(1, extra + 1):
            cells.append((d, "other-month"))

        # Build rows
        row = None
        for i, (day_num, tag) in enumerate(cells):
            if i % 7 == 0:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
                self._grid_box.pack_start(row, False, False, 0)
            btn = Gtk.Button(label=str(day_num))
            btn.get_style_context().add_class("day")
            if tag:
                btn.get_style_context().add_class(tag)
            btn.set_size_request(34, 26)
            btn.set_relief(Gtk.ReliefStyle.NONE)
            btn.set_focus_on_click(False)
            row.pack_start(btn, True, True, 0)

        # Footer text
        week_num = iso_week(date(y, m, 1))
        self._footer_label.set_text(f"week {week_num:02d}  ·  {total_days} days")

        self._grid_box.show_all()

    # ── Navigation ───────────────────────────────────────────────────────────

    def _shift(self, delta: int):
        m = self._month + delta
        y = self._year
        if m < 1:
            m = 12; y -= 1
        elif m > 12:
            m = 1; y += 1
        self._year, self._month = y, m
        self._refresh_grid()
        self.resize(1, 1)  # re-pack

    # ── Positioning ──────────────────────────────────────────────────────────

    def _position_near_cursor(self):
        display = Gdk.Display.get_default()
        seat = display.get_default_seat()
        pointer = seat.get_pointer()
        _, x, y = pointer.get_position()

        # Try to detect monitor geometry to avoid going off-screen
        screen = display.get_default_screen()
        monitor = screen.get_monitor_at_point(x, y)
        geom = screen.get_monitor_geometry(monitor)

        self.realize()
        w, h = self.get_preferred_size()[1].width, self.get_preferred_size()[1].height

        # Default: just above cursor, slightly to the left
        px = x - w // 2
        py = y - h - 8

        # Clamp to monitor
        px = max(geom.x, min(px, geom.x + geom.width - w))
        py = max(geom.y, min(py, geom.y + geom.height - h))

        self.move(px, py)

    # ── Events ───────────────────────────────────────────────────────────────

    def _on_key(self, _, event):
        if event.keyval in (Gdk.KEY_Escape, Gdk.KEY_q):
            self._quit()

    def _quit(self):
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
        Gtk.main_quit()


def main():
    # Toggle logic: kill existing instance if running
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            os.remove(LOCK_FILE)
            sys.exit(0)
        except (ProcessLookupError, ValueError, OSError):
            os.remove(LOCK_FILE)

    # Write our PID
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))

    signal.signal(signal.SIGTERM, lambda *_: (os.path.exists(LOCK_FILE) and os.remove(LOCK_FILE), sys.exit(0)))

    win = CalendarPopup()
    Gtk.main()


if __name__ == "__main__":
    main()
