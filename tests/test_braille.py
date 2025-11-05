import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from draw_iterm.braille import BrailleCanvas, DOT_BIT


class TestBraille(unittest.TestCase):
    def test_set_subpixel_mapping(self):
        c = BrailleCanvas(1, 1)
        expected = [
            (0, 0, DOT_BIT[(0, 0)]),
            (1, 0, DOT_BIT[(1, 0)]),
            (2, 0, DOT_BIT[(2, 0)]),
            (3, 0, DOT_BIT[(3, 0)]),
            (0, 1, DOT_BIT[(0, 1)]),
            (1, 1, DOT_BIT[(1, 1)]),
            (2, 1, DOT_BIT[(2, 1)]),
            (3, 1, DOT_BIT[(3, 1)]),
        ]
        for sr, sc, mask in expected:
            c.clear()
            c.set_subpixel(sc, sr)
            self.assertEqual(c._grid[0][0], mask)

    def test_draw_polyline_fills_multiple_cells(self):
        c = BrailleCanvas(3, 1)
        pts = [(0.0, 2.0), (5.0, 2.0)]
        c.draw_polyline_subgrid(pts)
        self.assertTrue(any(val != 0 for val in c._grid[0][:2]))

if __name__ == '__main__':
    unittest.main()
