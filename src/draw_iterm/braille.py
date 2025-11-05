from __future__ import annotations

from typing import List, Tuple

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

