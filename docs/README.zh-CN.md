# Draw-In-ITerm（终端白板）

[English](../README.md) | 中文

一款在 macOS + iTerm2 中运行的纯终端“白板”。使用高分辨率 Unicode 盲文（Braille）渲染和 Catmull–Rom（centripetal）样条平滑，实现用鼠标绘制平滑曲线。

- 使用全局命令启动：`draw`
- 鼠标拖动绘制平滑曲线
- Shift + 鼠标滚轮：调整笔刷粗细
- 按 `s`：导出 PNG 到当前目录
- 按 `S`：导出 PNG 到选择的目录（支持 `~` 和环境变量）
- 按 `Ctrl+Z`：撤销上一个笔画
- 按 `d`：切换调试信息
- 按 `c`：清屏
- 按 `q`：退出

## 环境要求
- Python 3.10+
- iTerm2（推荐），应用会启用鼠标上报

## 安装（全局命令）
使用以下任一方式（任选其一）：

- pipx（推荐）：
  - `pipx install .`
- pip（可编辑，开发）：
  - `pip install -e .`

安装后运行：

- `draw`

## 卸载
根据安装方式使用对应命令：

- pipx：
  - `pipx uninstall draw-iterm`
- pip（可编辑或常规）：
  - `pip uninstall draw-iterm`

如果卸载后 shell 中仍存在 `draw` 命令，重启 shell（或在 bash/zsh 里运行 `hash -r`）。

## 不安装直接运行（本地开发）
在项目根目录：

- `PYTHONPATH=src python -m draw_iterm`
  - 或：`PYTHONPATH=src python -m draw_iterm.cli`

## 快捷键
- 鼠标拖动：绘制
- Shift + 滚轮：调整笔刷粗细（1–8）
- s：保存 PNG 到当前目录
- S：保存 PNG 到选择的目录（输入路径；空 = 当前目录）
- Ctrl+Z：撤销上一个笔画
- d：切换调试叠加层
- c：清空画布
- q：退出

## 导出 PNG
- 图像内容来自每个终端字符 2×4 子像素的内部网格，并为清晰起见进行放大
- 默认文件名：`draw_YYYYmmdd_HHMMSS.png`
- 默认缩放：每子像素 3×。按 `s` 保存到当前目录；按 `S` 保存到你选择的目录
- `S` 的输入提示支持 `~` 和环境变量；目标目录需已存在
- 可通过环境变量配置默认保存目录：`DRAW_ITERM_SAVE_DIR`（例如：`export DRAW_ITERM_SAVE_DIR="$HOME/Pictures/Draw-In-ITerm"`）
- 若未设置该环境变量，按 `S` 选择的目录会被记住，保存在 `~/.config/draw_iterm/config.json`


## 提示
- 最佳体验是在 iTerm2 下使用鼠标上报；应用会自动启用所需模式
- 若看不到拖动绘制，请确保终端支持 SGR（1006）或经典鼠标上报

## 说明
- 渲染使用 Unicode 盲文（每字符 2×4 子像素），在终端内获得更平滑的曲线
- 样条平滑使用 centripetal Catmull–Rom，稳定、不易产生回环/过冲
- 支持窗口大小改变；在新边界内尽量保留画布内容
