from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple
from math import sqrt

Point = Tuple[float, float]


def _dist(a: Point, b: Point) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return sqrt(dx * dx + dy * dy)


def catmull_rom_centripetal(points: Sequence[Point], samples_per_cell: float = 2.0) -> List[Point]:
    """Return dense points along a centripetal Catmull–Rom spline through given points.

    - points: control points in subpixel coordinate space
    - samples_per_cell: sampling density (higher -> smoother/denser)
    """
    n = len(points)
    if n == 0:
        return []
    if n == 1:
        return [points[0]]
    if n == 2:
        # simple linear densification
        a, b = points[0], points[1]
        length = _dist(a, b)
        steps = max(1, int(length * samples_per_cell))
        out: List[Point] = []
        for i in range(steps + 1):
            t = i / steps
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        return out

    # pad endpoints for spline
    pts: List[Point] = []
    pts.append(points[0])
    pts.extend(points)
    pts.append(points[-1])

    out: List[Point] = []
    alpha = 0.5  # centripetal

    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        t0 = 0.0
        t1 = t0 + (_dist(p0, p1) ** alpha)
        t2 = t1 + (_dist(p1, p2) ** alpha)
        t3 = t2 + (_dist(p2, p3) ** alpha)
        if t1 == t0:
            t1 += 1e-6
        if t2 == t1:
            t2 += 1e-6
        if t3 == t2:
            t3 += 1e-6
        if t2 == t0:
            t2 += 1e-6
        if t3 == t1:
            t3 += 1e-6

        # choose step count proportional to segment length
        seg_len = _dist(p1, p2)
        steps = max(8, int(seg_len * samples_per_cell))

        def tj_point(t: float) -> Point:
            # Compute interpolated point at parameter t in [t1, t2]
            A1x = (t1 - t) / (t1 - t0) * p0[0] + (t - t0) / (t1 - t0) * p1[0]
            A1y = (t1 - t) / (t1 - t0) * p0[1] + (t - t0) / (t1 - t0) * p1[1]
            A2x = (t2 - t) / (t2 - t1) * p1[0] + (t - t1) / (t2 - t1) * p2[0]
            A2y = (t2 - t) / (t2 - t1) * p1[1] + (t - t1) / (t2 - t1) * p2[1]
            A3x = (t3 - t) / (t3 - t2) * p2[0] + (t - t2) / (t3 - t2) * p3[0]
            A3y = (t3 - t) / (t3 - t2) * p2[1] + (t - t2) / (t3 - t2) * p3[1]

            B1x = (t2 - t) / (t2 - t0) * A1x + (t - t0) / (t2 - t0) * A2x
            B1y = (t2 - t) / (t2 - t0) * A1y + (t - t0) / (t2 - t0) * A2y
            B2x = (t3 - t) / (t3 - t1) * A2x + (t - t1) / (t3 - t1) * A3x
            B2y = (t3 - t) / (t3 - t1) * A2y + (t - t1) / (t3 - t1) * A3y

            Cx = (t2 - t) / (t2 - t1) * B1x + (t - t1) / (t2 - t1) * B2x
            Cy = (t2 - t) / (t2 - t1) * B1y + (t - t1) / (t2 - t1) * B2y
            return (Cx, Cy)

        for s in range(steps + 1):
            t = t1 + (t2 - t1) * (s / steps)
            out.append(tj_point(t))

    return out




def catmull_rom_centripetal_segment(p0: Point, p1: Point, p2: Point, p3: Point, samples_per_cell: float = 2.0) -> List[Point]:
    """Return dense points along the single Catmull–Rom segment between p1 and p2.
    This mirrors the segment computation inside catmull_rom_centripetal() but only
    for one segment, enabling streaming/incremental drawing.
    """
    alpha = 0.5  # centripetal
    t0 = 0.0
    t1 = t0 + (_dist(p0, p1) ** alpha)
    t2 = t1 + (_dist(p1, p2) ** alpha)
    t3 = t2 + (_dist(p2, p3) ** alpha)
    # Guard all denominators used below
    if t1 == t0:
        t1 += 1e-6
    if t2 == t1:
        t2 += 1e-6
    if t3 == t2:
        t3 += 1e-6
    if t2 == t0:
        t2 += 1e-6
    if t3 == t1:
        t3 += 1e-6

    seg_len = _dist(p1, p2)
    steps = max(8, int(seg_len * samples_per_cell))

    def tj_point(t: float) -> Point:
        # Compute interpolated point at parameter t in [t1, t2]
        A1x = (t1 - t) / (t1 - t0) * p0[0] + (t - t0) / (t1 - t0) * p1[0]
        A1y = (t1 - t) / (t1 - t0) * p0[1] + (t - t0) / (t1 - t0) * p1[1]
        A2x = (t2 - t) / (t2 - t1) * p1[0] + (t - t1) / (t2 - t1) * p2[0]
        A2y = (t2 - t) / (t2 - t1) * p1[1] + (t - t1) / (t2 - t1) * p2[1]
        A3x = (t3 - t) / (t3 - t2) * p2[0] + (t - t2) / (t3 - t2) * p3[0]
        A3y = (t3 - t) / (t3 - t2) * p2[1] + (t - t2) / (t3 - t2) * p3[1]

        B1x = (t2 - t) / (t2 - t0) * A1x + (t - t0) / (t2 - t0) * A2x
        B1y = (t2 - t) / (t2 - t0) * A1y + (t - t0) / (t2 - t0) * A2y
        B2x = (t3 - t) / (t3 - t1) * A2x + (t - t1) / (t3 - t1) * A3x
        B2y = (t3 - t) / (t3 - t1) * A2y + (t - t1) / (t3 - t1) * A3y

        Cx = (t2 - t) / (t2 - t1) * B1x + (t - t1) / (t2 - t1) * B2x
        Cy = (t2 - t) / (t2 - t1) * B1y + (t - t1) / (t2 - t1) * B2y
        return (Cx, Cy)

    out: List[Point] = []
    for s in range(steps + 1):
        t = t1 + (t2 - t1) * (s / steps)
        out.append(tj_point(t))
    return out
