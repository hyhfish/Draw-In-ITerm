from __future__ import annotations

import curses
import locale
import sys
import time
import re
import os
import signal
import json

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
    curses.raw()
    stdscr.nodelay(True)  # non-blocking getch
    stdscr.keypad(True)
    curses.start_color()
    curses.use_default_colors()
    # Initialize 8 basic color pairs for strokes
    COLOR_IDS = [
        curses.COLOR_BLACK,
        curses.COLOR_RED,
        curses.COLOR_GREEN,
        curses.COLOR_YELLOW,
        curses.COLOR_BLUE,
        curses.COLOR_MAGENTA,
        curses.COLOR_CYAN,
        curses.COLOR_WHITE,
    ]
    PAIRS = []
    try:
        for i, cid in enumerate(COLOR_IDS, start=1):
            curses.init_pair(i, cid, -1)
            PAIRS.append(curses.color_pair(i))
    except Exception:
        PAIRS = [0] * 8

    # Avoid OS job-control suspending the app on Ctrl+Z; we handle it as Undo
    try:
        signal.signal(signal.SIGTSTP, signal.SIG_IGN)
    except Exception:
        pass


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
    color_idx = 0  # current brush color (0..7)

    # Default save directory config
    CONFIG_DIR = os.path.join(os.path.expanduser(os.environ.get("XDG_CONFIG_HOME", "~/.config")), "draw_iterm")
    CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

    def _load_default_save_dir():
        # 1) Environment variable override
        env_val = os.environ.get("DRAW_ITERM_SAVE_DIR", "").strip()
        if env_val:
            p = os.path.expandvars(os.path.expanduser(env_val))
            try:
                os.makedirs(p, exist_ok=True)
                return p
            except Exception:
                pass
        # 2) Config file
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            d = (data or {}).get("default_save_dir", "")
            if isinstance(d, str) and d.strip():
                p = os.path.expandvars(os.path.expanduser(d.strip()))
                try:
                    os.makedirs(p, exist_ok=True)
                    return p
                except Exception:
                    return None
        except Exception:
            pass
        return None

    def _remember_default_save_dir(path: str) -> None:
        if not path:
            return
        # If env var is set, do not override user's explicit override
        if os.environ.get("DRAW_ITERM_SAVE_DIR", "").strip():
            return
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"default_save_dir": os.path.expandvars(os.path.expanduser(path))}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # Default brush color helpers
    def _parse_color_index(val) -> int | None:
        try:
            s = str(val).strip().lower()
        except Exception:
            return None
        if not s:
            return None
        names = ["black","red","green","yellow","blue","magenta","cyan","white"]
        if s.isdigit():
            i = int(s)
            return i if 0 <= i <= 7 else None
        if s in names:
            return names.index(s)
        return None

    def _detect_dark_bg_from_env() -> bool | None:
        # Heuristic using COLORFGBG (if provided by terminal)
        s = os.environ.get("COLORFGBG", "")
        if not s:
            return None
        parts = [p for p in re.split(r"[:;]", s) if p.strip().isdigit()]
        if not parts:
            return None
        try:
            bg = int(parts[-1])  # last component is background
        except Exception:
            return None
        return True if bg <= 7 else False

    def _load_default_color() -> int:
        # 1) Env var override
        idx = _parse_color_index(os.environ.get("DRAW_ITERM_DEFAULT_COLOR", ""))
        if idx is not None:
            return idx
        # 2) Config file
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            idx = _parse_color_index((data or {}).get("default_color", ""))
            if idx is not None:
                return idx
        except Exception:
            pass
        # 3) Heuristic: dark bg -> white, light bg -> black
        dark = _detect_dark_bg_from_env()
        if dark is True:
            return 7  # white
        if dark is False:
            return 0  # black
        # 4) Fallback: white (safer on dark terminals)
        return 7
    def _parse_bool(val) -> bool | None:
        try:
            s = str(val).strip().lower()
        except Exception:
            return None
        if s in ("1","true","yes","on"): return True
        if s in ("0","false","no","off"): return False
        return None

    def _load_export_invert_bw() -> bool:
        b = _parse_bool(os.environ.get("DRAW_ITERM_EXPORT_INVERT_BW", ""))
        if b is not None:
            return b
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            v = data.get("export_invert_bw", None)
            if isinstance(v, bool):
                return v
            # allow string truthy/falsy too
            b2 = _parse_bool(v)
            if b2 is not None:
                return b2
        except Exception:
            pass
        return False


    def _load_default_brush() -> int | None:
        # Default brush thickness (1..8). Env var overrides config file.
        def _coerce(val) -> int | None:
            try:
                i = int(str(val).strip())
            except (TypeError, ValueError):
                return None
            return i if 1 <= i <= 8 else None
        i = _coerce(os.environ.get("DRAW_ITERM_DEFAULT_BRUSH", ""))
        if i is not None:
            return i
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            return _coerce(data.get("default_brush"))
        except Exception:
            return None

    def _load_brush_bias() -> float | None:
        # Brush fullness bias (float). Env var overrides config file.
        def _coerce(val) -> float | None:
            try:
                return float(str(val).strip())
            except (TypeError, ValueError):
                return None
        b = _coerce(os.environ.get("DRAW_ITERM_BRUSH_BIAS", ""))
        if b is not None:
            return b
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            return _coerce(data.get("brush_bias"))
        except Exception:
            return None

    default_save_dir = _load_default_save_dir()
    # Initialize brush color with env/config/heuristic
    color_idx = _load_default_color()

    export_invert_bw = _load_export_invert_bw()

    # Apply optional brush defaults (size + fullness)
    _b = _load_default_brush()
    if _b is not None:
        brush = _b
    _bias = _load_brush_bias()
    if _bias is not None:
        canvas.set_brush_bias(_bias)


    strokes: List[Tuple[List[Tuple[float, float]], int, int]] = []  # history of (points, thickness, color_idx)


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
            canvas.draw_polyline_subgrid(dense, thickness=brush, color_idx=color_idx)
            seg_cursor += 1

    def _preview_tail() -> None:
        # Draw an immediate short line from the last two points for responsiveness
        if len(stroke_pts) >= 2:
            a = stroke_pts[-2]
            b = stroke_pts[-1]
            canvas.draw_polyline_subgrid([a, b], thickness=brush, color_idx=color_idx)

    def _redraw_from_history() -> None:
        canvas.clear()
        for pts, th, col in strokes:
            if not pts:
                continue
            if len(pts) <= 2:
                dense = pts
            else:
                dense = catmull_rom_centripetal(pts, samples_per_cell=6.0)
            canvas.draw_polyline_subgrid(dense, thickness=th, color_idx=col)

    def render(full: bool = False):
        # Draw canvas (incremental by default; full=true for resize/clear/undo)
        canvas.render_to_curses(stdscr, PAIRS, full=full)
        # Hint/debug overlay (draw after canvas so it stays on top)
        COLORS_HINT = ["black","red","green","yellow","blue","magenta","cyan","white"]
        hint = (
            f"draw: drag  |  c: clear  |  q: quit  |  s/S: save  |  Ctrl+Z: undo  |  1-8: color={COLORS_HINT[color_idx]}  |  mouse:{mouse_hint}  |  d: debug {'on' if debug_mode else 'off'}  |  "
            f"Shift+Wheel: brush={brush}"
        )
        try:
            stdscr.move(0, 0); stdscr.clrtoeol()
            stdscr.addstr(0, 0, hint[: max(0, width - 1)])
            stdscr.move(1, 0); stdscr.clrtoeol()
            if debug_mode and debug_line:
                stdscr.addstr(1, 0, debug_line[: max(0, width - 1)])
        except Exception:
            pass
        stdscr.refresh()

    render(full=True)

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
                render(full=True)
                continue

            # Ctrl+Z: undo last stroke (or cancel current stroke)
            if ch in (26, getattr(curses, "KEY_SUSPEND", -1)):
                if drawing:
                    drawing = False
                    stroke_pts.clear()
                    seg_cursor = 0
                elif strokes:
                    strokes.pop()
                _redraw_from_history()
                render(full=True)
                continue

            if ch == ord("q") or ch == ord("Q") or ch == 3:
                break

            if ch == ord("c") or ch == ord("C"):
                canvas.clear()
                strokes.clear()
                stroke_pts.clear()
                seg_cursor = 0
                render(full=True)
                continue

            if ch == ord("d") or ch == ord("D"):
                debug_mode = not debug_mode
                render()
                continue

            # Color selection: 1..8 map to 8 palette colors
            if ch in (ord('1'), ord('2'), ord('3'), ord('4'), ord('5'), ord('6'), ord('7'), ord('8')):
                color_idx = ch - ord('1')
                debug_line = f"color -> {color_idx+1}"
                render()  # only overlay changes
                continue

            # Save current canvas to PNG (default dir if configured)
            if ch == ord("s"):
                ts = time.strftime("%Y%m%d_%H%M%S")
                base = default_save_dir or "."
                try:
                    os.makedirs(base, exist_ok=True)
                except Exception:
                    base = "."
                filename = f"draw_{ts}.png"
                path = os.path.join(base, filename)
                scale = 3
                try:
                    canvas.export_png(path, scale=scale, invert_bw=export_invert_bw)
                    note = " (invert BW)" if export_invert_bw else ""
                    debug_line = f"Saved {os.path.abspath(path)} ({canvas.sub_width*scale}x{canvas.sub_height*scale}){note}"
                except Exception as e:
                    debug_line = f"Save failed: {e}"
                render()
                continue

            # Save to user-chosen directory (uppercase S)
            if ch == ord("S"):
                # Prompt for directory path (empty = current directory)
                prompt = "Save directory (empty = current): "
                row = min(2, canvas.height - 1)
                dir_in = ""
                # Temporarily disable mouse reporting so mouse events won't pollute input
                try:
                    _disable_mouse_reporting()
                    try:
                        curses.mousemask(0)
                    except Exception:
                        pass
                    try:
                        curses.flushinp()
                    except Exception:
                        pass

                    stdscr.nodelay(False)
                    curses.echo()
                    curses.curs_set(1)
                    try:
                        stdscr.move(row, 0)
                        stdscr.clrtoeol()
                        stdscr.addstr(row, 0, prompt)
                        stdscr.refresh()
                        b = stdscr.getstr(row, len(prompt), 512)
                        dir_in = b.decode(sys.getfilesystemencoding() or "utf-8").strip()
                    finally:
                        curses.noecho()
                        curses.curs_set(0)
                        stdscr.nodelay(True)
                finally:
                    # Restore mouse reporting
                    try:
                        curses.mousemask(curses.ALL_MOUSE_EVENTS | _pos_flag)
                    except Exception:
                        pass
                    _enable_mouse_reporting()

                dirpath = dir_in or "."
                # Expand ~ and env vars
                dirpath = os.path.expandvars(os.path.expanduser(dirpath))
                if not os.path.isdir(dirpath):
                    debug_line = f"Save failed: not a directory: {dirpath}"
                    render()
                    continue

                ts = time.strftime("%Y%m%d_%H%M%S")
                path = os.path.join(dirpath, f"draw_{ts}.png")
                scale = 3
                try:
                    canvas.export_png(path, scale=scale, invert_bw=export_invert_bw)
                    note = " (invert BW)" if export_invert_bw else ""
                    debug_line = f"Saved {os.path.abspath(path)} ({canvas.sub_width*scale}x{canvas.sub_height*scale}){note}"
                    # Remember this directory as default (unless overridden by env var)
                    default_save_dir = dirpath
                    _remember_default_save_dir(dirpath)
                except Exception as e:
                    debug_line = f"Save failed: {e}"
                render()  # overlay only
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

                # If we were drawing but now receive a movement with no button1 press/move,
                # it likely means the button was released outside the terminal.
                if drawing and not pressed and not moved and not clicked:
                    if stroke_pts:
                        strokes.append((list(stroke_pts), brush, color_idx))
                    drawing = False
                    stroke_pts.clear()
                    seg_cursor = 0
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
                        canvas.draw_polyline_subgrid(dense, thickness=brush, color_idx=color_idx)
                        render()
                    # Finalize current stroke into history
                    if stroke_pts:
                        strokes.append((list(stroke_pts), brush, color_idx))
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

                # If drawing but current event is not left button (e.g., motion with no button),
                # likely the release happened outside. Finalize.
                if drawing and (not left) and (not wheel):
                    if stroke_pts:
                        strokes.append((list(stroke_pts), brush, color_idx))
                    drawing = False
                    stroke_pts.clear()
                    seg_cursor = 0
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
                        canvas.draw_polyline_subgrid(dense, thickness=brush, color_idx=color_idx)
                        render()
                    # Finalize current stroke into history
                    if stroke_pts:
                        strokes.append((list(stroke_pts), brush, color_idx))
                    drawing = False
                    stroke_pts.clear()
                    seg_cursor = 0

    finally:
        _disable_mouse_reporting()

