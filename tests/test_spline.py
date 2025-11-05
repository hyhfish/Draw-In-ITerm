import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from draw_iterm.spline import catmull_rom_centripetal


class TestSpline(unittest.TestCase):
    def test_spline_min_points(self):
        self.assertEqual(catmull_rom_centripetal([]), [])
        p = [(1.0, 2.0)]
        self.assertEqual(catmull_rom_centripetal(p), p)

    def test_spline_two_points_linear(self):
        out = catmull_rom_centripetal([(0.0, 0.0), (10.0, 0.0)], samples_per_cell=0.5)
        self.assertEqual(out[0], (0.0, 0.0))
        self.assertEqual(out[-1], (10.0, 0.0))
        self.assertTrue(all(abs(y) < 1e-6 for _, y in out))

if __name__ == '__main__':
    unittest.main()
