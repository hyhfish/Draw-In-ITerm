from __future__ import annotations

import curses
import locale
import sys
import time
import re
from typing import List, Tuple

from .braille import BrailleCanvas
from .spline import catmull_rom_centripetal, catmull_rom_centripetal_segment

# Ensure Unicode output
locale.setlocale(locale.LC_ALL, "")


def _enable_mouse_reporting() -> None:
    # Request SGR mouse and any-event tracking, for terminals that support it (iTerm2 does)
    try:
        # Enable classic and SGR mouse modes to maximize compatibility
        sys.stdout.write("\x1b[?1000h")  # X10/normal tracking (press/release)
        sys.stdout.write("\x1b[?1002h")  # Button-event tracking (press + drag)
        sys.stdout.write("\x1b[?1003h")  # Any-event tracking (all movements)
        sys.stdout.write("\x1b[?1006h")  # SGR extended encoding
        sys.stdout.flush()
    except Exception:
        pass


def _disable_mouse_reporting() -> None:
    try:
        sys.stdout.write("\x1b[?1000l")
        sys.stdout.write("\x1b[?1002l")
        sys.stdout.write("\x1b[?1003l")
        sys.stdout.write("\x1b[?1006l")
        sys.stdout.flush()
    except Exception:
        pass



def _try_read_sgr_mouse(stdscr, first_ch: int):
    """Best-effort parse of an SGR (1006) mouse event from the input stream.
    Returns tuple (mx, my, left, released, motion, wheel, wheel_delta, shift_mod, ctrl_mod)
    or None if not parsed. Coordinates are 0-based cells.
    """
    if first_ch != 27:  # ESC
        return None

    buf = ["\x1b"]
    # Try to read the rest of an SGR sequence within a tiny deadline
    deadline = time.time() + 0.20  # ~200ms to robustly assemble SGR sequence
    while time.time() < deadline:
        nxt = stdscr.getch()
        if nxt == -1:
            time.sleep(0.001)
            continue
        # Filter out special KEY_* codes
        if nxt > 255:
            return None
        c = chr(nxt)
        buf.append(c)
        if c in ("M", "m"):
            break
    s = "".join(buf)
    m = re.search(r"\x1b\[<([0-9]+);([0-9]+);([0-9]+)([Mm])", s)
    if not m:
        return None
    btn = int(m.group(1))
    mx = max(0, int(m.group(2)) - 1)
    my = max(0, int(m.group(3)) - 1)
    up = (m.group(4) == "m")
    left = (btn & 3) == 0
    motion = (btn & 32) != 0
    wheel = (btn & 64) != 0 or btn in (64, 65)
    # wheel up=64, down=65; modifiers are additive (shift=4, alt=8, ctrl=16)
    wheel_delta = 0
    if wheel:
        wheel_delta = 1 if (btn & 1) == 1 else -1
    shift_mod = (btn & 4) != 0
    ctrl_mod = (btn & 16) != 0
    return mx, my, left, up, motion, wheel, wheel_delta, shift_mod, ctrl_mod

def _try_read_x10_mouse(stdscr, first_ch: int):
    """Parse classic X10/1002/1003 mouse sequence: ESC [ M cb cx cy
    Returns (mx, my, left, up, motion, wheel, wheel_delta, shift_mod, ctrl_mod) or None.
    """
    if first_ch != 27:
        return None
    # Expect '[' 'M' then three bytes
    deadline = time.time() + 0.10
    buf = []
    # Read next two chars to verify CSI 'M'
    while time.time() < deadline and len(buf) < 2:
        n = stdscr.getch()
        if n == -1:
            time.sleep(0.001)
            continue
        if n > 255:
            return None
        buf.append(chr(n))
    if len(buf) < 2 or not (buf[0] == '[' and buf[1] == 'M'):
        return None
    # Read 3 bytes
    vals = []
    while time.time() < deadline and len(vals) < 3:
        n = stdscr.getch()
        if n == -1:
            time.sleep(0.001)
            continue
        if n > 255:
            return None
        vals.append(n)
    if len(vals) < 3:
        return None
    cb, cx, cy = vals
    btn = cb - 32
    mx = max(0, (cx - 32) - 1)
    my = max(0, (cy - 32) - 1)
    up = (btn & 3) == 3
    left = (btn & 3) == 0
    motion = (btn & 32) != 0
    wheel = (btn & 64) != 0 or btn in (64, 65)
    wheel_delta = 0
    if wheel:
        wheel_delta = 1 if (btn & 1) == 1 else -1
    shift_mod = (btn & 4) != 0
    ctrl_mod = (btn & 16) != 0
    return mx, my, left, up, motion, wheel, wheel_delta, shift_mod, ctrl_mod



def run() -> None:
    curses.wrapper(_main)


def _main(stdscr) -> None:
    curses.curs_set(0)
    curses.noecho()
    curses.cbreak()
    stdscr.nodelay(True)  # non-blocking getch
    stdscr.keypad(True)
    curses.start_color()
    curses.use_default_colors()

    _enable_mouse_reporting()

    # Enable mouse in curses
    curses.mouseinterval(0)
    _pos_flag = getattr(curses, "REPORT_MOUSE_POSITION", 0)
    try:
        _avail_info = curses.mousemask(curses.ALL_MOUSE_EVENTS | _pos_flag)
        # Some curses return (avail, old); others return single int
        _avail = _avail_info[0] if isinstance(_avail_info, tuple) else _avail_info
    except Exception:
        _avail = 0

    mouse_hint = "on" if _avail else "off"

    height, width = stdscr.getmaxyx()
    canvas = BrailleCanvas(width=width, height=height)

    drawing = False
    stroke_pts: List[Tuple[float, float]] = []  # subgrid coords
    debug_mode = True  # 开启调试信息显示（按 d 切换）
    debug_line = ""
    brush = 2  # subpixel thickness (Chebyshev radius = brush-1)
    seg_cursor = 0  # first segment start index not yet emitted

    def to_sub(x: int, y: int) -> Tuple[float, float]:
        # Map cell coords (x,y) to subgrid centered coords
        return x * 2 + 1, y * 4 + 2

    def _emit_new_segments() -> None:
        nonlocal seg_cursor
        # Flush finalized spline segments incrementally to avoid O(N^2)
        if len(stroke_pts) < 4:
            return
        while seg_cursor + 3 < len(stroke_pts):
            p0, p1, p2, p3 = stroke_pts[seg_cursor], stroke_pts[seg_cursor + 1], stroke_pts[seg_cursor + 2], stroke_pts[seg_cursor + 3]
            dense = catmull_rom_centripetal_segment(p0, p1, p2, p3, samples_per_cell=6.0)
            canvas.draw_polyline_subgrid(dense, thickness=brush)
            seg_cursor += 1

    def _preview_tail() -> None:
        # Draw an immediate short line from the last two points for responsiveness
        if len(stroke_pts) >= 2:
            a = stroke_pts[-2]
            b = stroke_pts[-1]
            canvas.draw_polyline_subgrid([a, b], thickness=brush)


    def render():
        # Draw current canvas
        stdscr.erase()
        canvas.render_to_curses(stdscr)
        # Optional: hint line
        hint = (
            f"draw: drag to draw  |  c: clear  |  q: quit  |  mouse:{mouse_hint}  |  d: debug {'on' if debug_mode else 'off'}  |  "
            f"Shift+Wheel: brush={brush}"
        )
        try:
            stdscr.addstr(0, 0, hint[: max(0, width - 1)])
            if debug_mode and debug_line:
                stdscr.addstr(1, 0, debug_line[: max(0, width - 1)])
        except Exception:
            pass
        stdscr.refresh()

    render()

    try:
        while True:
            ch = stdscr.getch()
            if ch == -1:
                # No input; tiny sleep to avoid busy-looping
                time.sleep(0.005)
                continue

            if ch == curses.KEY_RESIZE:
                height, width = stdscr.getmaxyx()
                canvas.resize_preserve(width, height)
                render()
                continue

            if ch == ord("q") or ch == ord("Q"):
                break

            if ch == ord("c") or ch == ord("C"):
                canvas.clear()
                stroke_pts.clear()
                seg_cursor = 0
                render()
                continue

            if ch == ord("d") or ch == ord("D"):
                debug_mode = not debug_mode
                render()
                continue


            if ch == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                except curses.error:
                    continue

                # Clamp to inside window bounds
                my = max(0, min(my, canvas.height - 1))
                mx = max(0, min(mx, canvas.width - 1))

                pressed  = bool(bstate & curses.BUTTON1_PRESSED)
                released = bool(bstate & curses.BUTTON1_RELEASED)
                clicked  = bool(bstate & getattr(curses, "BUTTON1_CLICKED", 0))
                moved    = bool(bstate & getattr(curses, "BUTTON1_MOVED", 0))
                motion   = bool(bstate & getattr(curses, "REPORT_MOUSE_POSITION", 0))
                wheel_up   = bool(bstate & getattr(curses, "BUTTON4_PRESSED", 0))
                wheel_down = bool(bstate & getattr(curses, "BUTTON5_PRESSED", 0))
                wheel = wheel_up or wheel_down
                shift_mod = bool(bstate & getattr(curses, "BUTTON_SHIFT", 0))
                delta = (1 if wheel_down else (-1 if wheel_up else 0))

                # Debug overlay
                debug_line = f"KEY_MOUSE x={mx} y={my} b=0x{bstate:x} p={int(pressed)} r={int(released)} c={int(clicked)} mv={int(moved)} mo={int(motion)} wh={int(wheel)} sh={int(shift_mod)}"

                if wheel:
                    # Shift+Wheel -> brush；其它滚轮忽略
                    if shift_mod and delta != 0:
                        brush = min(8, max(1, brush + delta))
                        render()
                        continue
                    # Other wheel events: ignore for drawing; just refresh
                    render()
                    continue

                if (pressed or clicked) and not drawing:
                    # Start a new stroke only on the first press/click; do not reset on subsequent move events
                    _enable_mouse_reporting()  # reassert tracking modes
                    drawing = True
                    stroke_pts.clear()
                    seg_cursor = 0

                if drawing:
                    sx, sy = to_sub(mx, my)
                    stroke_pts.append((sx, sy))

                    # Incremental: flush finalized CR segments and preview the tail
                    _emit_new_segments()
                    _preview_tail()
                    render()
                else:
                    # No drawing this event; still refresh to show debug line
                    render()

                if released:
                    # If we only saw press and release (no motion), add the release
                    # point so at least a segment/dot is drawn.
                    sx, sy = to_sub(mx, my)
                    if not stroke_pts:
                        stroke_pts.append((sx, sy))
                    elif len(stroke_pts) == 1:
                        stroke_pts.append((sx, sy))
                        dense = catmull_rom_centripetal(stroke_pts, samples_per_cell=6.0)
                        canvas.draw_polyline_subgrid(dense, thickness=brush)
                        render()
                    drawing = False
                    stroke_pts.clear()
                    seg_cursor = 0

            elif ch == 27:  # Fallback: parse raw mouse escape sequences
                ev = _try_read_sgr_mouse(stdscr, ch)
                if not ev:
                    ev = _try_read_x10_mouse(stdscr, ch)
                if not ev:
                    debug_line = "ESC (unknown mouse seq)"
                    render()
                    continue
                mx, my, left, up, motion, wheel, wheel_delta, shift_mod, _ = ev
                # Clamp
                my = max(0, min(my, canvas.height - 1))
                mx = max(0, min(mx, canvas.width - 1))

                debug_line = f"RAW x={mx} y={my} left={int(left)} up={int(up)} mo={int(motion)} wh={int(wheel)} sh={int(shift_mod)}"

                if wheel:
                    if shift_mod and wheel_delta != 0:
                        brush = min(8, max(1, brush + wheel_delta))
                        render()
                        continue
                    render()
                    continue

                if left and not up:
                    if not drawing:
                        _enable_mouse_reporting()  # reassert tracking modes
                        drawing = True
                        stroke_pts.clear()
                        seg_cursor = 0

                if drawing and not up:
                    sx, sy = to_sub(mx, my)
                    stroke_pts.append((sx, sy))
                    _emit_new_segments()
                    _preview_tail()
                    render()
                else:
                    render()

                if left and up:
                    # Append release point to produce a line if there was no motion
                    sx, sy = to_sub(mx, my)
                    if not stroke_pts:
                        stroke_pts.append((sx, sy))
                    elif len(stroke_pts) == 1:
                        stroke_pts.append((sx, sy))
                        dense = catmull_rom_centripetal(stroke_pts, samples_per_cell=6.0)
                        canvas.draw_polyline_subgrid(dense, thickness=brush)
                        render()
                    drawing = False
                    stroke_pts.clear()
                    seg_cursor = 0

    finally:
        _disable_mouse_reporting()

