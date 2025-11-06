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

# 8-color palette indices for strokes (0..7)
PALETTE_RGB: List[Tuple[int, int, int]] = [
    (0, 0, 0),       # 0 black
    (255, 0, 0),     # 1 red
    (0, 200, 0),     # 2 green
    (255, 255, 0),   # 3 yellow
    (0, 0, 255),     # 4 blue
    (255, 0, 255),   # 5 magenta
    (0, 255, 255),   # 6 cyan
    (255, 255, 255), # 7 white
]
# Note: We keep background as white (255,255,255) for PNG.

class BrailleCanvas:
    """A canvas using Unicode Braille characters for 2x4 subpixel drawing per cell.

    width, height are in terminal character cells.
    Subpixel coordinates are in a grid width*2 by height*4.
    """

    def __init__(self, width: int, height: int) -> None:
        self.width = max(1, width)
        self.height = max(1, height)
        self._grid: List[List[int]] = [[0] * self.width for _ in range(self.height)]
        # Per-subpixel color index (-1 = empty). Size: (sub_height x sub_width)
        sh, sw = self.sub_height, self.sub_width
        self._sub_colors: List[List[int]] = [[-1] * sw for _ in range(sh)]
        # Per-cell dominant color cache (-1 = none)
        self._cell_color: List[List[int]] = [[-1] * self.width for _ in range(self.height)]
        # Dirty rows to update on next render (optimize incremental drawing)
        self._dirty_rows: set[int] = set(range(self.height))


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
        sh, sw = self.sub_height, self.sub_width
        self._sub_colors = [[-1] * sw for _ in range(sh)]
        self._cell_color = [[-1] * self.width for _ in range(self.height)]
        self._dirty_rows = set(range(self.height))

    def resize_preserve(self, width: int, height: int) -> None:
        width = max(1, width)
        height = max(1, height)
        # Preserve old sizes to copy both grid and subpixel colors
        old_w, old_h = self.width, self.height
        old_sw, old_sh = old_w * 2, old_h * 4
        new_grid: List[List[int]] = [[0] * width for _ in range(height)]
        min_h = min(self.height, height)
        min_w = min(self.width, width)
        for y in range(min_h):
            new_grid[y][:min_w] = self._grid[y][:min_w]
        self.width = width
        self.height = height
        self._grid = new_grid
        # Resize subpixel colors
        new_sw, new_sh = self.sub_width, self.sub_height
        new_sub: List[List[int]] = [[-1] * new_sw for _ in range(new_sh)]
        copy_h = min(old_sh, new_sh)
        copy_w = min(old_sw, new_sw)
        for sy in range(copy_h):
            new_sub[sy][:copy_w] = self._sub_colors[sy][:copy_w]
        self._sub_colors = new_sub
        # Recompute per-cell dominant colors from subpixel colors
        self._cell_color = [[-1] * self.width for _ in range(self.height)]
        for cy in range(self.height):
            sy0 = cy * 4
            for cx in range(self.width):
                sx0 = cx * 2
                counts = [0] * 8
                for off_sy in range(4):
                    for off_sx in range(2):
                        ci = self._sub_colors[sy0 + off_sy][sx0 + off_sx]
                        if 0 <= ci <= 7:
                            counts[ci] += 1
                self._cell_color[cy][cx] = (max(range(8), key=lambda i: counts[i]) if any(counts) else -1)
        # All rows dirty after resize
        self._dirty_rows = set(range(self.height))


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
        # No color info; recompute dominant color from existing colored subpixels
        self._recompute_cell_color(cell_x, cell_y)
        # Mark row dirty
        self._dirty_rows.add(cell_y)

    def set_subpixel_color(self, sx: int, sy: int, color_idx: int) -> None:
        """Set a colored subpixel at (sx, sy) with palette index color_idx."""
        if sx < 0 or sy < 0 or sx >= self.sub_width or sy >= self.sub_height:
            return
        cell_x = sx // 2
        cell_y = sy // 4
        subcol = sx % 2
        subrow = sy % 4
        mask = DOT_BIT[(subrow, subcol)]
        self._grid[cell_y][cell_x] |= mask
        self._sub_colors[sy][sx] = max(0, min(7, color_idx))
        self._recompute_cell_color(cell_x, cell_y)
        # Mark row dirty
        self._dirty_rows.add(cell_y)

    def _recompute_cell_color(self, cell_x: int, cell_y: int) -> None:
        if cell_x < 0 or cell_y < 0 or cell_x >= self.width or cell_y >= self.height:
            return
        base_sy = cell_y * 4
        base_sx = cell_x * 2
        counts = [0] * 8
        for off_sy in range(4):
            for off_sx in range(2):
                ci = self._sub_colors[base_sy + off_sy][base_sx + off_sx]
                if 0 <= ci <= 7:
                    counts[ci] += 1
        self._cell_color[cell_y][cell_x] = (max(range(8), key=lambda i: counts[i]) if any(counts) else -1)

    def _paint_disc_subpixel(self, sx: int, sy: int, r: int, color_idx: int | None = None) -> None:
        """Paint a small square disc (Chebyshev radius r) centered at (sx,sy).
        If color_idx is provided, also records per-subpixel color; otherwise only bitmask.
        r=0 draws a single subpixel; r=1 draws a 3x3; r=2 draws a 5x5.
        """
        if r <= 0:
            if color_idx is None:
                self.set_subpixel(sx, sy)
            else:
                self.set_subpixel_color(sx, sy, color_idx)
            return
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if color_idx is None:
                    self.set_subpixel(sx + dx, sy + dy)
                else:
                    self.set_subpixel_color(sx + dx, sy + dy, color_idx)

    def draw_polyline_subgrid(self, pts: List[Tuple[float, float]], thickness: int = 1, color_idx: int = 0) -> None:
        """Draw a polyline in subpixel coordinates using a supercover line rasterization.
        thickness is the Chebyshev radius in subpixel units used to visually thicken
        the stroke to reduce stair-stepping on diagonals.
        color_idx: 0..7 palette index for the stroke color (default 0=black).
        """
        if not pts:
            return
        def plot(x: float, y: float) -> None:
            self._paint_disc_subpixel(int(round(x)), int(round(y)), max(0, thickness - 1), color_idx)
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

    def render_to_curses(self, stdscr, color_pairs: List[int] | None = None, full: bool = False) -> None:
        """Blit the braille grid to the curses screen.
        If color_pairs is provided (list of curses.color_pair attrs indexed by 0..7),
        pick the dominant subpixel color per cell and render with that color.
        If full is False, only dirty rows are redrawn for performance.
        """
        base = BRAILLE_BASE
        h = min(self.height, stdscr.getmaxyx()[0])
        w = min(self.width, stdscr.getmaxyx()[1])
        # Determine which rows to draw
        if full:
            y_list = list(range(h))
        else:
            if not self._dirty_rows:
                return
            y_list = sorted([y for y in self._dirty_rows if 0 <= y < h])
            if not y_list:
                return
        # Without colors: fast path as before (draw only selected rows)
        if not color_pairs:
            for y in y_list:
                row = self._grid[y]
                chars = []
                for x in range(w):
                    codepoint = base + row[x]
                    chars.append(chr(codepoint))
                line = "".join(chars)
                try:
                    _, maxx = stdscr.getmaxyx()
                    if len(line) >= maxx:
                        line = line[: maxx - 1]
                    stdscr.addstr(y, 0, line)
                except Exception:
                    pass
            # mark rows clean
            if full:
                self._dirty_rows.clear()
            else:
                self._dirty_rows.difference_update(y_list)
            return
        # With colors: per-cell rendering using cached dominant color per cell
        _, maxx = stdscr.getmaxyx()
        for y in y_list:
            x = 0
            while x < w:
                ch = chr(base + self._grid[y][x])
                color = self._cell_color[y][x]
                attr = color_pairs[color] if 0 <= color <= 7 else 0
                run_start = x
                run_chars = [ch]
                x += 1
                while x < w:
                    ch2 = chr(base + self._grid[y][x])
                    color2 = self._cell_color[y][x]
                    attr2 = color_pairs[color2] if 0 <= color2 <= 7 else 0
                    if attr2 != attr:
                        break
                    run_chars.append(ch2)
                    x += 1
                try:
                    line = "".join(run_chars)
                    if run_start + len(line) >= maxx:
                        line = line[: maxx - run_start - 1]
                    stdscr.addstr(y, run_start, line, attr)
                except Exception:
                    pass
        # mark rows clean
        if full:
            self._dirty_rows.clear()
        else:
            self._dirty_rows.difference_update(y_list)

    def export_png(self, path: str, scale: int = 2, invert_bw: bool = False, invert_white_only: bool = False) -> None:
        """Export current canvas to an RGB PNG at subpixel resolution.

        - path: output file path ending with .png
        - scale: integer scale factor applied to each subpixel (>=1)
        - invert_bw: if True, swap black<->white stroke colors on export (others unchanged)
        - invert_white_only: if True, only invert white->black (black stays black)
        """
        if scale < 1:
            scale = 1
        sw, sh = self.sub_width, self.sub_height
        out_w, out_h = sw * scale, sh * scale

        # Build raw scanlines with PNG filter type 0 (None)
        raw = bytearray()
        bg = (255, 255, 255)  # white background
        for sy in range(sh):
            # One logical subpixel row, horizontally scaled (RGB)
            row = bytearray(out_w * 3)
            dst = 0
            for sx in range(sw):
                ci = self._sub_colors[sy][sx]
                if 0 <= ci <= 7:
                    mapped_ci = ci
                    if invert_white_only:
                        if ci == 7:
                            mapped_ci = 0
                    elif invert_bw:
                        if ci == 0:
                            mapped_ci = 7
                        elif ci == 7:
                            mapped_ci = 0
                    r, g, b = PALETTE_RGB[mapped_ci]
                else:
                    r, g, b = bg
                for _ in range(scale):
                    row[dst] = r; row[dst + 1] = g; row[dst + 2] = b
                    dst += 3
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
        # IHDR: color type 2 (Truecolor)
        bit_depth = 8
        color_type = 2
        ihdr = struct.pack("!IIBBBBB", out_w, out_h, bit_depth, color_type, 0, 0, 0)
        # IDAT
        comp = zlib.compress(bytes(raw), level=9)
        # IEND
        iend = b""

        with open(path, "wb") as f:
            f.write(sig)
            f.write(_chunk(b"IHDR", ihdr))
            f.write(_chunk(b"IDAT", comp))
            f.write(_chunk(b"IEND", iend))
