# Draw-In-ITerm (Terminal Whiteboard)

A pure-terminal whiteboard for macOS + iTerm2. Draw smooth curves with your mouse using high-resolution Unicode Braille rendering and Catmull–Rom spline smoothing.

- Start with a global command: `draw`
- Draw smooth curves by mouse drag
- Press `c` to clear
- Press `q` to quit

## Requirements
- Python 3.10+
- iTerm2 (recommended) with mouse reporting enabled by the app

## Install (global command)
Use one of the following (choose one):

- pipx (recommended):
  - `pipx install .`
- pip editable (dev):
  - `pip install -e .`

After install, run:

- `draw`


## Uninstall
Use the matching command for how you installed it:

- pipx:
  - `pipx uninstall draw-iterm`
- pip (editable or regular):
  - `pip uninstall draw-iterm`

If the `draw` command still exists in your shell after uninstall, restart the shell (or run `hash -r` in bash/zsh).

## Run without install (local dev)
From repo root:

- `PYTHONPATH=src python -m draw_iterm.cli`

## Notes
- Rendering uses Unicode Braille (2×4 subpixel per character) to achieve much smoother curves in a terminal.
- Spline smoothing uses centripetal Catmull–Rom for stability (no loops/overshoot).
- Resize is handled; canvas content is preserved on window size changes within new bounds.
