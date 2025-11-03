# Draw-In-ITerm

A simple terminal whiteboard that draws while you hold the left mouse button.

- Start from your terminal, no installation required (Python 3 only)
- Draw by pressing and holding the left mouse button and moving the cursor
- Press `c` to clear, `q` to quit

## Quick start

Option A (direct):

```bash
python3 src/draw_in_iterm.py
```

Option B (make executable and run):

```bash
chmod +x src/draw_in_iterm.py
./src/draw_in_iterm.py
```

Tested in iTerm2 and macOS Terminal. Most modern terminals that support mouse
reporting should work. If continuous drag isn’t detected, try iTerm2.


## Install a global `dit` command

Recommended (pipx):

```bash
pipx install .
# If first time using pipx:
# pipx ensurepath
```
Optional: enable iTerm2 pixel backend (needs Pillow):

```bash
# Install with extras in one step OR inject Pillow later
pipx install ".[pixel]"
# or, if already installed:
pipx inject draw-in-iterm pillow
```


Then run anywhere:

```bash
dit
```

Alternative (user-site install):

```bash
python3 -m pip install --user .
# Ensure your user base bin is on PATH, e.g. ~/.local/bin
```

Quick alias (no install):

```bash
alias dit="python3 $(pwd)/src/draw_in_iterm.py"
# Append the alias to your shell rc to persist, e.g. ~/.zshrc or ~/.bashrc
```

## Troubleshooting: no drawing when dragging

If the whiteboard opens but dragging doesn’t draw:

- Check your terminal supports mouse reporting (iTerm2, macOS Terminal).
- If inside tmux, enable mouse: add `set -g mouse on` to `~/.tmux.conf`, then reload (`tmux source-file ~/.tmux.conf`).
- Try again with debug logging enabled and share the log:

```bash
DIT_DEBUG=1 dit
# After exit:
open /tmp/dit_debug.log  # or: cat /tmp/dit_debug.log
```




## 安装与使用（中文）

### 本地安装（开发/调试）
推荐在虚拟环境中本地安装，便于调试与升级：

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -U pip
pip install -e .
```

安装完成后即可启动：

```bash
dit
# 或直接运行模块（等价）：
python -m draw_in_iterm
```

### 全局命令启动（pipx，推荐）
按顺序执行以下命令（macOS/Homebrew 环境）：

```bash
# 1) 安装/确保有 Python 3.11（Pillow 10 兼容）
brew install python@3.11

# 2) 用该 Python 通过 pipx 从当前目录安装本项目
pipx ensurepath
pipx install --python "$(brew --prefix)/bin/python3.11" .

# 3) 验证运行
dit --help
```

可选：启用 iTerm2 像素画后端（需要 Pillow）。如果网络/镜像拉不到 Pillow，可以先不启用，程序会使用字符画模式。

```bash
# 一步到位（带 extras 安装 Pillow）
pipx install --python "$(brew --prefix)/bin/python3.11" ".[pixel]"
# 或者已安装后再注入：
pipx inject draw-in-iterm pillow
```

如未使用 Homebrew，可将 --python 参数改为你的 3.11 解释器路径，例如：`--python /usr/local/bin/python3.11` 或 `--python /opt/homebrew/bin/python3.11`。

### 备选：使用 pip 的 --user（无需 pipx）
```bash
python3 -m pip install --user .
# 请将用户目录下的 bin 加入 PATH（例如：~/.local/bin）
```

随后即可在任何位置运行：

```bash
dit
```
