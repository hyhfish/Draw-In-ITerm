# Draw-In-ITerm (Terminal Whiteboard)

[English](README.md) | [中文](docs/README.zh-CN.md)


A pure-terminal whiteboard for macOS + iTerm2. Draw smooth curves with your mouse using high-resolution Unicode Braille rendering and Catmull–Rom spline smoothing.

- Start with a global command: `draw`
- Draw smooth curves by mouse drag
- Shift + mouse wheel: adjust brush thickness
- Press `s`: export PNG to current directory
- Press `S`: export PNG to a chosen directory (supports `~` and env vars)
- Press `Ctrl+Z`: undo last stroke
- Press `d`: toggle debug info
- Press `c`: clear
- Press `q`: quit

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

- `PYTHONPATH=src python -m draw_iterm`
  - or: `PYTHONPATH=src python -m draw_iterm.cli`


## Hotkeys
- Mouse drag: draw
- Shift + Wheel: adjust brush thickness (1–8)
- s: save PNG to current directory
- S: save PNG to a chosen directory (enter a path; empty = current directory)
- Ctrl+Z: undo last stroke
- d: toggle debug overlay
- c: clear canvas
- q: quit

## Export PNG
- Image content is rendered from the internal 2×4 subpixel grid per terminal cell, then upscaled for clarity
- Default filename: `draw_YYYYmmdd_HHMMSS.png`
- Default scale: 3× (per subpixel). Saved to current directory for `s`, or to your chosen directory for `S`
- The `S` prompt accepts `~` and environment variables; the target directory must already exist
- Configure default save directory via env var `DRAW_ITERM_SAVE_DIR` (e.g., `export DRAW_ITERM_SAVE_DIR="$HOME/Pictures/Draw-In-ITerm"`)
- If the env var is not set, the last directory chosen via `S` is remembered in `~/.config/draw_iterm/config.json`


## Tips
- Works best in iTerm2 with mouse reporting; the app enables necessary modes automatically
- If you don’t see mouse-drag drawing, ensure your terminal supports SGR (1006) or classic mouse reporting


## Notes
- Rendering uses Unicode Braille (2×4 subpixel per character) to achieve much smoother curves in a terminal.
- Spline smoothing uses centripetal Catmull–Rom for stability (no loops/overshoot).
- Resize is handled; canvas content is preserved on window size changes within new bounds.
