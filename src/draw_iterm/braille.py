from __future__ import annotations

from typing import List, Tuple
import struct
import zlib


# Mapping of (subrow, subcol) within a braille cell (4x2) to dot bit index
# Unicode braille dots numbering:
# (row, col): dot -> bit
# (0,0): 1 -> bit0
# (1,0): 2 -> bit1
# (2,0): 3 -> bit2
# (0,1): 4 -> bit3
# (1,1): 5 -> bit4
# (2,1): 6 -> bit5
# (3,0): 7 -> bit6
# (3,1): 8 -> bit7

DOT_BIT = {
    (0, 0): 1 << 0,
    (1, 0): 1 << 1,
    (2, 0): 1 << 2,
    (0, 1): 1 << 3,
    (1, 1): 1 << 4,
    (2, 1): 1 << 5,
    (3, 0): 1 << 6,
    (3, 1): 1 << 7,
}

BRAILLE_BASE = 0x2800

class BrailleCanvas:
    """A canvas using Unicode Braille characters for 2x4 subpixel drawing per cell.

    width, height are in terminal character cells.
    Subpixel coordinates are in a grid width*2 by height*4.
    """

    def __init__(self, width: int, height: int) -> None:
        self.width = max(1, width)
        self.height = max(1, height)
        self._grid: List[List[int]] = [ [0] * self.width for _ in range(self.height) ]

    @property
    def sub_width(self) -> int:
        return self.width * 2

    @property
    def sub_height(self) -> int:
        return self.height * 4

    def clear(self) -> None:
        for y in range(self.height):
            row = self._grid[y]
            for x in range(self.width):
                row[x] = 0

    def resize_preserve(self, width: int, height: int) -> None:
        width = max(1, width)
        height = max(1, height)
        new_grid: List[List[int]] = [ [0] * width for _ in range(height) ]
        min_h = min(self.height, height)
        min_w = min(self.width, width)
        for y in range(min_h):
            new_grid[y][:min_w] = self._grid[y][:min_w]
        self.width = width
        self.height = height
        self._grid = new_grid

    def set_subpixel(self, sx: int, sy: int) -> None:
        """Set a subpixel at subpixel coordinates (sx, sy)."""
        if sx < 0 or sy < 0 or sx >= self.sub_width or sy >= self.sub_height:
            return
        cell_x = sx // 2
        cell_y = sy // 4
        subcol = sx % 2
        subrow = sy % 4
        mask = DOT_BIT[(subrow, subcol)]
        self._grid[cell_y][cell_x] |= mask

    def _paint_disc_subpixel(self, sx: int, sy: int, r: int) -> None:
        """Paint a small square disc (Chebyshev radius r) centered at (sx,sy) in subpixel coords.
        r=0 draws a single subpixel; r=1 draws a 3x3; r=2 draws a 5x5.
        """
        if r <= 0:
            self.set_subpixel(sx, sy)
            return
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                self.set_subpixel(sx + dx, sy + dy)

    def draw_polyline_subgrid(self, pts: List[Tuple[float, float]], thickness: int = 1) -> None:
        """Draw a polyline in subpixel coordinates using a supercover line rasterization.
        thickness is the Chebyshev radius in subpixel units used to visually thicken
        the stroke to reduce stair-stepping on diagonals.
        """
        if not pts:
            return
        def plot(x: float, y: float) -> None:
            self._paint_disc_subpixel(int(round(x)), int(round(y)), max(0, thickness - 1))
        if len(pts) == 1:
            plot(pts[0][0], pts[0][1])
            return
        x0, y0 = pts[0]
        plot(x0, y0)
        for i in range(1, len(pts)):
            x1, y1 = pts[i]
            dx = x1 - x0
            dy = y1 - y0
            steps = int(max(abs(dx), abs(dy)))
            if steps <= 0:
                plot(x1, y1)
            else:
                for s in range(1, steps + 1):
                    t = s / steps
                    plot(x0 + dx * t, y0 + dy * t)
            x0, y0 = x1, y1

    def render_to_curses(self, stdscr) -> None:
        """Blit the braille grid to the curses screen."""
        base = BRAILLE_BASE
        h = min(self.height, stdscr.getmaxyx()[0])
        w = min(self.width, stdscr.getmaxyx()[1])
        for y in range(h):
            row = self._grid[y]
            # Build a line string for performance
            chars = []
            for x in range(w):
                codepoint = base + row[x]
                chars.append(chr(codepoint))
            line = "".join(chars)
            try:
                # Avoid writing into the bottom-right cell which may error on some curses
                maxy, maxx = stdscr.getmaxyx()
                if len(line) >= maxx:
                    line = line[: maxx - 1]
                stdscr.addstr(y, 0, line)
            except Exception:
                # Ignore any addstr errors on edge cases (should be rare after slicing)
                pass

    def export_png(self, path: str, scale: int = 2) -> None:
        """Export current canvas to a grayscale PNG at subpixel resolution.

        - path: output file path ending with .png
        - scale: integer scale factor applied to each subpixel (>=1)
        """
        if scale < 1:
            scale = 1
        sw, sh = self.sub_width, self.sub_height
        out_w, out_h = sw * scale, sh * scale

        # Build raw scanlines with PNG filter type 0 (None)
        raw = bytearray()
        bg = 255  # white background
        fg = 0    # black stroke
        for sy in range(sh):
            # One logical subpixel row, horizontally scaled
            row = bytearray(out_w)
            dst = 0
            for sx in range(sw):
                cell_x = sx // 2
                cell_y = sy // 4
                subcol = sx % 2
                subrow = sy % 4
                mask = DOT_BIT[(subrow, subcol)]
                on = (self._grid[cell_y][cell_x] & mask) != 0
                val = fg if on else bg
                # write horizontally scaled copies
                for _ in range(scale):
                    row[dst] = val
                    dst += 1
            # write vertically scaled copies with filter byte 0
            for _ in range(scale):
                raw.append(0)  # filter type None
                raw.extend(row)

        def _chunk(typ: bytes, data: bytes) -> bytes:
            length = struct.pack("!I", len(data))
            crc = zlib.crc32(typ)
            crc = zlib.crc32(data, crc) & 0xFFFFFFFF
            return length + typ + data + struct.pack("!I", crc)

        # PNG signature
        sig = b"\x89PNG\r\n\x1a\n"
        # IHDR
        ihdr = struct.pack("!IIBBBBB", out_w, out_h, 8, 0, 0, 0, 0)
        # IDAT
        comp = zlib.compress(bytes(raw), level=9)
        # IEND
        iend = b""

        with open(path, "wb") as f:
            f.write(sig)
            f.write(_chunk(b"IHDR", ihdr))
            f.write(_chunk(b"IDAT", comp))
            f.write(_chunk(b"IEND", iend))
