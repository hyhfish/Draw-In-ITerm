#!/usr/bin/env python3
"""
Draw-In-ITerm: A simple terminal whiteboard that captures and draws while the
left mouse button is held down. Works in modern terminals that support mouse
reporting (tested in iTerm2 and macOS Terminal).

Controls:
  - Hold Left Mouse Button and move: draw
  - c: clear
  - q: quit

Usage:
  python3 src/draw_in_iterm.py

Notes:
  - If your terminal doesn't continuously report mouse movements by default,
    the program attempts to enable "any-motion" and SGR mouse reporting modes.
"""

import curses
import sys
import os
import math
import time
from typing import Set, Tuple, Optional
from io import BytesIO
try:
    from PIL import Image, ImageDraw  # type: ignore
    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False


# Escape codes for enabling/disabling Any-Motion (1003) and SGR (1006) mouse
# tracking. Many terminals support these. We enable as a best-effort to get
# continuous drag events.
# Enable classic xterm mouse modes by default.
# 1000: normal tracking; 1002: button-event tracking; 1003: any-motion.
# Note: 1006 (SGR) is optional because some curses builds can't parse it.
_ENABLE_ANY_MOTION = "\033[?1000h\033[?1002h\033[?1003h"
_DISABLE_ANY_MOTION = "\033[?1000l\033[?1002l\033[?1003l"
# SGR toggles (controlled via env var DIT_SGR=1)
_ENABLE_SGR = "\033[?1006h"
_DISABLE_SGR = "\033[?1006l"

# Some ncurses builds provide BUTTON1_MOVED; use 0 if missing to avoid AttributeError
BUTTON1_MOVED = getattr(curses, "BUTTON1_MOVED", 0)

# Optional debug logging: set DIT_DEBUG=1 to write events to /tmp/dit_debug.log
DEBUG = bool(os.getenv("DIT_DEBUG"))
USE_SGR = os.getenv("DIT_SGR") == "1"

def _dbg(msg: str) -> None:
    if DEBUG:
        try:
            with open("/tmp/dit_debug.log", "a") as f:
                f.write(str(msg) + "\n")
        except Exception:
            pass



def _enable_any_motion_modes() -> None:
    try:
        # Ensure SGR is off unless explicitly requested
        sys.stdout.write(_DISABLE_SGR)
        # Enable classic modes first
        sys.stdout.write(_ENABLE_ANY_MOTION)
        # Optionally enable SGR if requested
        if USE_SGR:
            sys.stdout.write(_ENABLE_SGR)
        sys.stdout.flush()
    except Exception:
        # Non-fatal; rely on curses mousemask only.
        pass


def _is_iterm2() -> bool:
    return os.getenv("TERM_PROGRAM") == "iTerm.app" or bool(os.getenv("ITERM_SESSION_ID"))


def _disable_any_motion_modes() -> None:
    try:
        sys.stdout.write(_DISABLE_ANY_MOTION)
        sys.stdout.write(_DISABLE_SGR)
        sys.stdout.flush()
    except Exception:
        pass

# --- Braille canvas (2x4 microdots per cell) for smoother strokes ---
# Bit layout within a braille cell (U+2800 base):
# (x=0,y=0)->dot1 bit0, (0,1)->dot2 bit1, (0,2)->dot3 bit2, (1,0)->dot4 bit3,
# (1,1)->dot5 bit4, (1,2)->dot6 bit5, (0,3)->dot7 bit6, (1,3)->dot8 bit7
_BRAILLE_BASE = 0x2800


def _braille_bit(px: int, py: int) -> int:
    if px == 0:
        return (1 << [0, 1, 2, 6][py])
    else:
        return (1 << [3, 4, 5, 7][py])


class BrailleCanvas:
    def __init__(self, stdscr: "curses._CursesWindow", top_margin: int = 1) -> None:
        self.top = top_margin
        self.resize(stdscr)

    def resize(self, stdscr: "curses._CursesWindow") -> None:
        max_y, max_x = stdscr.getmaxyx()
        self.ch = max(0, max_y - self.top)
        self.cw = max_x
        self.h = self.ch * 4
        self.w = self.cw * 2
        self.cells = [[0 for _ in range(self.cw)] for _ in range(self.ch)]
        self.dirty: Set[Tuple[int, int]] = set()

    def clear(self, stdscr: "curses._CursesWindow") -> None:
        for y in range(self.ch):
            for x in range(self.cw):
                if self.cells[y][x]:
                    self.cells[y][x] = 0
                    self.dirty.add((y, x))
        self.commit(stdscr)

    def _mark_dot(self, hy: int, hx: int) -> None:
        if 0 <= hy < self.h and 0 <= hx < self.w:
            cy, cx = hy // 4, hx // 2
            py, px = hy % 4, hx % 2
            bit = _braille_bit(px, py)
            old = self.cells[cy][cx]
            new = old | bit
            if new != old:
                self.cells[cy][cx] = new
                self.dirty.add((cy, cx))

    def cell_to_hires(self, my: int, mx: int) -> Tuple[int, int]:
        # Return microdot center of the target terminal cell within the canvas
        return (max(0, (my - self.top) * 4 + 2),
                max(0, mx * 2 + 1))

    def draw_line(self, hy0: int, hx0: int, hy1: int, hx1: int, thickness: int = 0) -> None:
        """Smoother stroke on the 2x4 braille microdot grid.
        - Use circular stamping (euclidean) instead of diamond to reduce angular corners.
        - Oversample along the segment to avoid visible steps on diagonals.
        Control oversampling via env DIT_BRAILLE_OS (default: 3).
        """
        r = max(0, thickness)
        oversample = max(1, int(os.getenv("DIT_BRAILLE_OS", "3")))
        steps = max(1, max(abs(hy1 - hy0), abs(hx1 - hx0)) * oversample)
        dy = hy1 - hy0
        dx = hx1 - hx0
        rr2 = r * r
        for i in range(steps + 1):
            t = i / steps
            y = int(round(hy0 + dy * t))
            x = int(round(hx0 + dx * t))
            # circular stamp around (y, x)
            if r == 0:
                self._mark_dot(y, x)
            else:
                for ty in range(-r, r + 1):
                    for tx in range(-r, r + 1):
                        if tx * tx + ty * ty <= rr2:
                            self._mark_dot(y + ty, x + tx)

    def commit(self, stdscr: "curses._CursesWindow", force: bool = False) -> None:
        for (cy, cx) in list(self.dirty):
            ch = self.cells[cy][cx]
            try:
                stdscr.addstr(self.top + cy, cx, chr(_BRAILLE_BASE + ch) if ch else " ")
            except curses.error:
                pass
        self.dirty.clear()

    def redraw_all(self, stdscr: "curses._CursesWindow") -> None:
        for y in range(self.ch):
            for x in range(self.cw):
                ch = self.cells[y][x]
                try:
                    stdscr.addstr(self.top + y, x, chr(_BRAILLE_BASE + ch) if ch else " ")
                except curses.error:
                    pass

# --- iTerm2 Pixel canvas backend (OSC 1337 Inline Images) ---
class PixelCanvas:
    def __init__(self, stdscr: "curses._CursesWindow", top_margin: int = 1) -> None:
        self.top = top_margin
        # pixels-per-cell; can be tuned via env for quality/speed
        # Increase default internal resolution for smoother downscaling
        self.ppcx = int(os.getenv("DIT_PPCX", "8"))
        self.ppcy = int(os.getenv("DIT_PPCY", "16"))
        self.color = (255, 255, 255, 255)  # white pen
        # background: default opaque to avoid iTerm2 transparent tiling artifacts
        transparent = os.getenv("DIT_TRANSPARENT", "0").lower() in ("1", "true", "yes")
        self.bg = (0, 0, 0, 0) if transparent else (0, 0, 0, 255)
        # drawing brush mode: 'line' (default) or 'stamp'
        self.brush_mode = os.getenv("DIT_BRUSH", "line").lower()
        # supersample factor for anti-aliased strokes (1=off, e.g. 2 or 3 enables AA)
        self.ss = max(1, int(os.getenv("DIT_SS", "1")))
        # commit mode: full-frame for best quality (DIT_FULLFRAME=1) or dirty-rect patches (default)
        self.fullframe = os.getenv("DIT_FULLFRAME", "0").lower() in ("1", "true", "yes")
        # simple frame cap to reduce lag from excessive imgcat calls
        self._min_interval = 1.0 / max(1, int(os.getenv("DIT_MAX_FPS", "45")))
        self._last_flush = 0.0
        # dirty rectangle in pixel coords: (lx, ty, rx, by), inclusive
        self.dirty: Optional[Tuple[int, int, int, int]] = None
        self.resize(stdscr)

    def resize(self, stdscr: "curses._CursesWindow") -> None:
        max_y, max_x = stdscr.getmaxyx()
        self.ch = max(0, max_y - self.top)
        self.cw = max_x
        self.w = max(1, self.cw * self.ppcx)
        self.h = max(1, self.ch * self.ppcy)
        if _HAVE_PIL:
            self.img = Image.new("RGBA", (self.w, self.h), self.bg)
            self.draw = ImageDraw.Draw(self.img)
        # full redraw on next commit
        self.dirty = (0, 0, self.w - 1, self.h - 1)

    def clear(self, stdscr: "curses._CursesWindow") -> None:
        if not _HAVE_PIL:
            return
        self.img.paste(self.bg, (0, 0, self.w, self.h))
        # push a full-frame image to avoid patchwork artifacts after clear
        try:
            self._imgcat_full(stdscr)
            self._last_flush = time.monotonic()
            self.dirty = None
        except Exception:
            # fallback to dirty-rect commit if full flush fails
            self.dirty = (0, 0, self.w - 1, self.h - 1)
            self.commit(stdscr, force=True)

    def cell_to_hires(self, my: int, mx: int) -> Tuple[int, int]:
        # Return pixel center of the target cell inside the canvas region
        return (max(0, (my - self.top) * self.ppcy + self.ppcy // 2),
                max(0, mx * self.ppcx + self.ppcx // 2))

    def draw_line(self, py0: int, px0: int, py1: int, px1: int, thickness: int = 1) -> None:
        """Draw a stroke. Default 'line' brush to avoid wavy stair-steps.
        Set DIT_BRUSH=stamp to use circular stamping instead.
        """
        if not _HAVE_PIL:
            return
        width = max(1, 1 + thickness * 2)
        if self.brush_mode == "stamp":
            # circular brush stamping for a softer look
            dx = px1 - px0
            dy = py1 - py0
            dist = (dx * dx + dy * dy) ** 0.5
            step = max(1.0, width * 0.5)
            n = max(1, int(dist / step))
            r = max(1, width // 2)
            for i in range(n + 1):
                t = 0 if n == 0 else i / n
                x = int(round(px0 + dx * t))
                y = int(round(py0 + dy * t))
                self.draw.ellipse((x - r, y - r, x + r, y + r), fill=self.color)
            # ensure endpoints are solid
            self.draw.ellipse((px0 - r, py0 - r, px0 + r, py0 + r), fill=self.color)
            self.draw.ellipse((px1 - r, py1 - r, px1 + r, py1 + r), fill=self.color)
        else:
            # Default: straighter diagonals. If supersampling is enabled, draw AA into ROI
            if self.ss > 1:
                self._draw_line_supersampled(py0, px0, py1, px1, width)
                return
            self.draw.line([(px0, py0), (px1, py1)], fill=self.color, width=width)
            r = max(1, width // 2)
            self.draw.ellipse((px0 - r, py0 - r, px0 + r, py0 + r), fill=self.color)
            self.draw.ellipse((px1 - r, py1 - r, px1 + r, py1 + r), fill=self.color)
        pad = max(1, width // 2 + 2)
        lx = min(px0, px1) - pad
        rx = max(px0, px1) + pad
        ty = min(py0, py1) - pad
        by = max(py0, py1) + pad
        self._mark_dirty(lx, ty, rx, by)
    def _draw_line_supersampled(self, py0: int, px0: int, py1: int, px1: int, width: int) -> None:
        """Anti-aliased stroke using local supersampling.
        Draw into a small hi-res ROI (scale=self.ss) and downsample with LANCZOS,
        then paste back to the main canvas. Keeps cost bounded to the dirty area.
        """
        ss = max(2, self.ss)
        r = max(1, width // 2)
        pad = max(2, r + 3)
        lx = max(0, min(px0, px1) - pad)
        rx = min(self.w, max(px0, px1) + pad)
        ty = max(0, min(py0, py1) - pad)
        by = min(self.h, max(py0, py1) + pad)
        if lx >= rx or ty >= by:
            return
        roi = self.img.crop((lx, ty, rx, by))
        up = roi.resize((roi.width * ss, roi.height * ss), resample=Image.NEAREST)
        d = ImageDraw.Draw(up)
        d.line([( (px0 - lx) * ss, (py0 - ty) * ss ),
                ( (px1 - lx) * ss, (py1 - ty) * ss )], fill=self.color, width=width * ss)
        # end caps
        er = max(1, r * ss)
        d.ellipse(((px0 - lx) * ss - er, (py0 - ty) * ss - er,
                   (px0 - lx) * ss + er, (py0 - ty) * ss + er), fill=self.color)
        d.ellipse(((px1 - lx) * ss - er, (py1 - ty) * ss - er,
                   (px1 - lx) * ss + er, (py1 - ty) * ss + er), fill=self.color)
        down = up.resize((roi.width, roi.height), resample=Image.LANCZOS)
        self.img.paste(down, (lx, ty))
        self._mark_dirty(lx, ty, rx, by)

        self._mark_dirty(lx, ty, rx, by)

    def _mark_dirty(self, lx: int, ty: int, rx: int, by: int) -> None:
        lx = max(0, lx); ty = max(0, ty)
        rx = min(self.w - 1, rx); by = min(self.h - 1, by)
        if lx > rx or ty > by:
            return
        if self.dirty is None:
            self.dirty = (lx, ty, rx, by)
        else:
            dlx, dty, drx, dby = self.dirty
            self.dirty = (min(dlx, lx), min(dty, ty), max(drx, rx), max(dby, by))

    def _imgcat_full(self, stdscr: "curses._CursesWindow") -> None:
        # Encode entire image as PNG and print using iTerm2 inline image protocol
        if not _HAVE_PIL:
            return
        try:
            from base64 import b64encode
            bio = BytesIO()
            self.img.save(bio, format="PNG", compress_level=1)
            data = b64encode(bio.getvalue()).decode("ascii")
            # Move cursor to canvas origin (top+1 row, col 1)
            sys.stdout.write(f"\x1b[{self.top + 1};1H")
            # width/height are in cells; stretch to fit the canvas area exactly
            sys.stdout.write("\x1b]1337;File=inline=1;preserveAspectRatio=0")
            sys.stdout.write(f";width={self.cw};height={self.ch}")
            sys.stdout.write(":" + data + "\x07")
            sys.stdout.flush()
        except Exception as e:
            _dbg(f"imgcat_error={e}")

    def _imgcat_rect(self, stdscr: "curses._CursesWindow", top_cell: int, left_cell: int, cols: int, rows: int, crop_img: "Image.Image") -> None:
        # Show a cropped patch at given cell position/size
        try:
            from base64 import b64encode
            bio = BytesIO()
            crop_img.save(bio, format="PNG", compress_level=1)
            data = b64encode(bio.getvalue()).decode("ascii")
            # Move cursor to the patch origin in terminal cells
            sys.stdout.write(f"\x1b[{self.top + 1 + top_cell};{1 + left_cell}H")
            sys.stdout.write("\x1b]1337;File=inline=1;preserveAspectRatio=0")
            sys.stdout.write(f";width={cols};height={rows}")
            sys.stdout.write(":" + data + "\x07")
            sys.stdout.flush()
        except Exception as e:
            _dbg(f"imgcat_rect_error={e}")

    def commit(self, stdscr: "curses._CursesWindow", force: bool = False) -> None:
        if not _HAVE_PIL or self.dirty is None:
            return
        now = time.monotonic()
        if not force and (now - self._last_flush) < self._min_interval:
            return
        # In full-frame mode, always push the entire image for best visual consistency
        if self.fullframe:
            self._imgcat_full(stdscr)
            self._last_flush = now
            self.dirty = None
            return
        lx, ty, rx, by = self.dirty
        # snap to cell boundaries for stable placement
        left_cell = max(0, lx // self.ppcx)
        top_cell = max(0, ty // self.ppcy)
        right_cell = min(self.cw - 1, rx // self.ppcx)
        bottom_cell = min(self.ch - 1, by // self.ppcy)
        if right_cell < left_cell or bottom_cell < top_cell:
            self.dirty = None
            return
        # pixel bounds for this patch
        left_px = left_cell * self.ppcx
        top_px = top_cell * self.ppcy
        right_px = min(self.w, (right_cell + 1) * self.ppcx)
        bottom_px = min(self.h, (bottom_cell + 1) * self.ppcy)
        crop = self.img.crop((left_px, top_px, right_px, bottom_px))
        cols = right_cell - left_cell + 1
        rows = bottom_cell - top_cell + 1
        self._imgcat_rect(stdscr, top_cell, left_cell, cols, rows, crop)
        self._last_flush = now
        self.dirty = None

    def redraw_all(self, stdscr: "curses._CursesWindow") -> None:
        self._imgcat_full(stdscr)
        # consider this a fresh frame; avoid carrying over full-screen dirty
        self.dirty = None
        self._last_flush = time.monotonic()


def _draw_instructions(stdscr: "curses._CursesWindow") -> None:
    try:
        stdscr.addstr(0, 0, "Draw-In-ITerm — Hold Left to draw | 1-4: thickness | c: clear | q: quit")
    except curses.error:
        # Ignore if terminal is too small
        pass

# legacy character drawing helpers removed (pixel/braille backends in use)


def _main(stdscr: "curses._CursesWindow") -> None:
    curses.curs_set(0)
    stdscr.nodelay(False)
    stdscr.keypad(True)

    # Enable mouse events via curses and (best-effort) raw escape codes.
    curses.mouseinterval(0)
    availmask, oldmask = curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
    _enable_any_motion_modes()

    # Log environment/capabilities
    try:
        termname = curses.termname().decode(errors="ignore") if hasattr(curses, "termname") else "?"
    except Exception:
        termname = "?"
    try:
        has_mouse = curses.has_mouse()  # type: ignore[attr-defined]
    except Exception:
        has_mouse = True
    _dbg(f"TERM={os.getenv('TERM')} termname={termname} has_mouse={has_mouse} availmask={availmask} oldmask={oldmask}")

    use_pixel = _HAVE_PIL and _is_iterm2()
    canvas = PixelCanvas(stdscr, top_margin=1) if use_pixel else BrailleCanvas(stdscr, top_margin=1)
    _dbg(f"backend={'pixel' if use_pixel else 'braille'} ppc={getattr(canvas, 'ppcx', None)}x{getattr(canvas, 'ppcy', None)}")
    stroke = 1  # microdot radius (0..3)
    drawing = False
    last_pt: Optional[Tuple[int, int]] = None  # last drawn hi-res point
    saw_key_mouse = False  # if True, suppress SGR fallback to avoid double handling

    stdscr.clear()
    _draw_instructions(stdscr)
    stdscr.refresh()
    # push an initial full-frame image so subsequent patches are small
    try:
        canvas.redraw_all(stdscr)
    except AttributeError:
        pass

    while True:
        ch = stdscr.getch()
        try:
            _dbg(f"ch={ch} key={curses.keyname(ch).decode('ascii','ignore')}")
        except Exception:
            _dbg(f"ch={ch}")

        if ch in (ord('q'), ord('Q')):
            break
        if ch in (ord('c'), ord('C')):
            last_pt = None
            stdscr.clear()
            _draw_instructions(stdscr)
            # 先刷新文本层，再贴整帧图片，避免图片被后续刷新覆盖
            stdscr.refresh()
            canvas.clear(stdscr)
            continue

        # Stroke thickness shortcuts (microdot radius)
        if ch == ord('1'):
            stroke = 0; continue
        if ch == ord('2'):
            stroke = 1; continue
        if ch == ord('3'):
            stroke = 2; continue
        if ch == ord('4'):
            stroke = 3; continue

        if ch == curses.KEY_RESIZE:
            stdscr.clear()
            _draw_instructions(stdscr)
            stdscr.refresh()
            canvas.resize(stdscr)
            canvas.redraw_all(stdscr)
            continue

        # Fallback path: if curses doesn't emit KEY_MOUSE but terminal sends SGR
        # sequences (CSI < b ; x ; y M|m), try to parse a whole sequence when we
        # see the first ESC.
        if ch == 27 and USE_SGR and not saw_key_mouse:  # ESC path only when SGR requested and no KEY_MOUSE seen
            buf = [ch]
            stdscr.nodelay(True)
            for _ in range(32):
                nx = stdscr.getch()
                if nx == -1:
                    break
                buf.append(nx)
                if nx in (ord('M'), ord('m')):
                    break
            stdscr.nodelay(False)
            s = ''.join(chr(c) for c in buf)
            _dbg(f"sgr_raw={repr(s)}")
            if s.startswith('\x1b[<'):
                try:
                    body = s[3:]
                    endch = body[-1]
                    nums = body[:-1].split(';')
                    if len(nums) >= 3:
                        b = int(nums[0])
                        x = int(nums[1])
                        y = int(nums[2])
                        _dbg(f"sgr_parsed b={b} x={x} y={y} end={endch}")
                        if y >= 1 and x >= 1:
                            cy, cx = y - 1, x - 1  # cells (0-based)
                            hy, hx = canvas.cell_to_hires(cy, cx)
                            if endch == 'm':  # release
                                drawing = False
                                last_pt = None
                                try:
                                    canvas.commit(stdscr, force=True)
                                except TypeError:
                                    canvas.commit(stdscr)
                                stdscr.refresh()
                                continue
                            else:  # 'M' press/move (drag)
                                drawing = True
                                if last_pt is None:
                                    last_pt = (hy, hx)
                                    canvas.draw_line(hy, hx, hy, hx, thickness=stroke)  # seed dot
                                else:
                                    canvas.draw_line(last_pt[0], last_pt[1], hy, hx, thickness=stroke)
                                    last_pt = (hy, hx)
                                canvas.commit(stdscr)
                                stdscr.refresh()
                                continue
                except Exception as e:
                    _dbg(f"sgr_parse_error={e}")
            # Not SGR; ignore
            continue

        if ch == curses.KEY_MOUSE:
            saw_key_mouse = True
            try:
                _, mx, my, _, bstate = curses.getmouse()
            except curses.error:
                continue

            # Log raw state
            _dbg(f"bstate={bstate} mx={mx} my={my}")

            # Avoid drawing over instruction line
            if my < 1:
                continue

            # Stop drawing on release
            if bstate & curses.BUTTON1_RELEASED:
                drawing = False
                last_pt = None
                try:
                    canvas.commit(stdscr, force=True)
                except TypeError:
                    canvas.commit(stdscr)
                stdscr.refresh()
                continue

            # Start or continue drawing on press/drag
            if bstate & (curses.BUTTON1_PRESSED | getattr(curses, "BUTTON1_CLICKED", 0) | getattr(curses, "BUTTON1_DOUBLE_CLICKED", 0) | getattr(curses, "BUTTON1_TRIPLE_CLICKED", 0) | curses.BUTTON1_PRESSED | curses.BUTTON1_PRESSED):
                drawing = True
                hy, hx = canvas.cell_to_hires(my, mx)
                if last_pt is None:
                    last_pt = (hy, hx)
                    canvas.draw_line(hy, hx, hy, hx, thickness=stroke)
                else:
                    canvas.draw_line(last_pt[0], last_pt[1], hy, hx, thickness=stroke)
                    last_pt = (hy, hx)
                canvas.commit(stdscr)
                stdscr.refresh()
                continue

            # Continue drawing while moving with button 1 held
            if drawing and ((bstate & curses.REPORT_MOUSE_POSITION) or (bstate & BUTTON1_MOVED) or (bstate & curses.BUTTON1_PRESSED)):
                hy, hx = canvas.cell_to_hires(my, mx)
                if last_pt is None:
                    last_pt = (hy, hx)
                    canvas.draw_line(hy, hx, hy, hx, thickness=stroke)
                else:
                    canvas.draw_line(last_pt[0], last_pt[1], hy, hx, thickness=stroke)
                    last_pt = (hy, hx)
                canvas.commit(stdscr)
                stdscr.refresh()
                continue


def run() -> None:
    try:
        curses.wrapper(_main)
    finally:
        _disable_any_motion_modes()


if __name__ == "__main__":
    run()

