# OpenCodeGO Token Watcher

> 2026-09-14：已重新打包最新修复，`OpenCode用量监测.exe` 可直接双击运行，无需安装 Python，也无需复制源码或 assets。已验证独立目录与不含 Python 的 PATH 下启动、首次向导、模拟数据库读取和正常退出。真实数据库对账、官网线上连通性及另一台未安装 Python 的 Windows 机器尚未验收。

Windows 桌面悬浮小窗：实时监测本机 **OpenCode / OpenChamber** 的 token 用量（输入 / 输出 / 缓存命中率），支持日 / 周 / 月查看与历史翻阅。Apple/macOS 面板风格：白色圆角卡片、半透明（透明度可调）、深浅色主题、可置顶、可拖拽、可锁定位置。

## 快速开始

**方式一：直接运行 exe（推荐，无需装 Python）**

到 [Releases 下载页面](https://github.com/sunnymoore1314-coder/opencodego-token-watcher/releases) 下载 `OpenCode用量监测.exe`，双击启动。请使用 Windows 64 位系统。

```
OpenCode用量监测.exe
```

首次运行会弹"首次使用"向导，自动探测本机 opencode.db（OpenChamber 与 opencode CLI 共用），确认即可使用；找不到时可手动指定路径。

可以只复制这个 exe 到其他文件夹或电脑。未使用过 OpenCode 时可点“跳过（稍后设置）”进入小窗，之后右键 → 设置选择数据库；没有数据源时会给出提示。

**方式二：源码运行（开发/调试，需 Python 3）**

```
python main.py
```

运行期**零第三方依赖**（仅标准库）。

## 使用提示

**首次启动**

首次运行会弹出"首次使用"向导：

1. 自动探测本机 opencode.db，找到即显示今日用量预览，点"开始使用"即可
2. 探测失败时按原因区分三种情况（未安装 opencode / 有目录但无数据 / 数据库被占用或损坏），均可手动选择路径
3. 暂不确定可点"跳过"，稍后随时可从右键菜单 → 设置指定路径

**常用操作**

- 拖动卡片任意位置移动窗口（开启"锁定窗口位置"后不可拖动）
- 拖四角缩放窗口（最小 180×120，最大 600×400），尺寸与位置自动记忆
- 右键卡片呼出菜单：刷新 / 置顶 / 设置 / 关于 / 退出
- 点日期弹月历跳转，◀ ▶ 翻历史；日 / 周 / 月标签切换粒度（周一起算）
- 状态栏显示最近同步时间与自动刷新间隔；数据异常时显示原因与解决指引

**设置说明**（右键 → 设置）

- **连接**：opencode.db 路径 + 浏览… / 重新探测 / 测试读取（验证路径可读并报告会话数）+ ⓘ 说明
- **外观**：主题三选（跟随系统 / 浅色 / 深色）+ 透明度滑块（0.50~0.95，实时预览）
- **行为**：刷新间隔（−/＋ 步进 1~30 分钟）、数字格式（缩写 1.2K / 完整 1,234,567）、启动时置顶、锁定窗口位置、开机自动启动
- **关于**：版本、数据目录 + 打开数据目录

**常见问题**

- **找不到数据源**：右键 → 设置 → 连接，手动指定 opencode.db 路径（默认 `%USERPROFILE%\.local\share\opencode\opencode.db`）
- **取消置顶后窗口不见了**：取消置顶时任务栏会出现程序入口，从任务栏点回即可找回
- **启动提示"程序已在运行"**：程序为单实例，说明已有实例在运行，直接使用已有窗口即可

## 功能

- 📊 实时显示：输入 tokens / 输出 tokens / 缓存命中率（三段式颜色：≥70% 绿 / 30~70% 橙 / <30% 红）
- 📅 日 / 周 / 月 粒度切换（周一起算），◀ ▶ 翻历史，点日期弹月历跳转
- ⟳ 1 分钟自动刷新（设置窗可配 1/2/5/10/30 分钟）+ 右键菜单手动刷新
- 🌗 深浅色主题：跟随系统 / 浅色 / 深色三选，设置窗切换即时换肤
- 🔍 透明度滑条：0.50~0.95（Apple 风格滑块），拖动实时预览
- 📌 置顶 / 半透明 / 拖拽 / 锁定窗口位置（右键菜单可切换置顶；取消置顶时任务栏出现入口可找回）
- 🔁 单实例：重复启动提示"程序已在运行"
- ⚙ 右键菜单 → 设置窗（分四节）：连接（db 路径 + 测试读取 + ⓘ 说明）/ 外观（主题 + 透明度）/ 行为（刷新间隔、数字格式、启动置顶、锁定位置、开机自启）/ 关于（版本、打开数据目录）
- 🗄 数据缓存到 `%APPDATA%\opencodego-token-watcher\`，db 损坏/被占用时仍可查看历史

## 数据口径

| 指标 | 公式 |
|---|---|
| 输入（默认显示） | 总输入 = 新鲜输入 + 缓存读 + 缓存写 |
| 新鲜输入（可选显示） | 实际发送的新鲜 tokens，不含缓存；用于比较 `opencode stats` 的 Input |
| 输出 | 输出 tokens |
| 缓存命中率 | 缓存读 ÷（新鲜输入 + 缓存读 + 缓存写）× 100% |

数据源：本地 `%USERPROFILE%\.local\share\opencode\opencode.db`（**只读**，绝不写库）。

本地会话按创建时间归日，缺失时回退更新时间。启用官网同步后优先显示官网账户级 token，本机数据补缺；费用只使用官网账单。官网缓存绑定 workspace，增量同步按请求记录标记去重，分页未完成时保留旧缓存。缓存损坏时忽略；本地数据已读到但无法保存缓存时仍返回数据并提示。

## 设置

右键菜单 → 设置，弹出 Apple 风格设置窗（400×560，四节）：

| 分节 | 内容 |
|---|---|
| 连接 | db 路径 + 浏览… / 重新探测 / 测试读取 + ⓘ 说明弹窗 |
| 外观 | 主题三选（跟随系统 / 浅色 / 深色）；透明度滑条（0.50~0.95，实时预览） |
| 行为 | 刷新间隔（1/2/5/10/30 分钟）；数字格式（缩写 1.2K / 完整 1,234,567）；启动时置顶；锁定窗口位置；开机自动启动 |
| 关于 | 版本 0.3 · 数据目录 + 打开数据目录 |

## 配置

配置文件：`%APPDATA%\opencodego-token-watcher\config.json`

| 配置项 | 说明 |
|---|---|
| `db_path` | opencode.db 路径（留空 = 自动探测） |
| `autostart` | 开机自启（注册表 Run 键，默认关） |
| `window_pos` | 窗口位置（退出时自动记忆） |
| `theme` | 主题：`system`（跟随系统，默认）/ `light` / `dark` |
| `window_alpha` | 窗口透明度 0.50~0.95（默认 0.78） |
| `refresh_interval` | 自动刷新间隔（分钟，默认 1；可选 1/2/5/10/30） |
| `number_format` | 数字格式：`abbr` 缩写（默认）/ `plain` 完整千分位 |
| `topmost_on_start` | 启动时置顶（默认 true） |
| `lock_position` | 锁定窗口位置，锁定时不可拖动（默认 false） |

## 重新打包 exe

```
python -m venv .build-venv
.build-venv\Scripts\python.exe -m pip install -r requirements-build.txt
powershell -File tools\build.ps1
```

产物为根目录 `OpenCode用量监测.exe`，`dist/opencodego-token-watcher.exe` 保留同内容英文名副本。使用 `python tools/verify_package.py` 可验证独立目录、隔离配置和无 Python PATH 下运行（会显示测试窗口）。

## 测试

```
python -m unittest discover -s tests   # 单测（聚合/缓存/管线）
python tools/smoke.py                  # 使用配置路径或探测数据库，与 PATH 中 CLI 对比
python tools/smoke.py --db "D:\数据\opencode.db" --offline  # 仅验证本地聚合
python tools/verify_ui.py              # UI 渲染与交互断言
```

## 项目文档

详见 `docs/README.md`（需求 / 技术 / UI 规范 / 开发流程），开发日志在 `devlogs/`。

## 目录结构

```
main.py                入口（单实例检查 + 首启向导判断 + 主窗 + 程序图标）
src/
  config.py            配置/探测/开机自启
  db_reader.py         只读 opencode.db
  aggregator.py        日/周/月聚合 + 命中率（纯函数）
  cache.py             JSON 缓存（原子写）
  pipeline.py          数据管线（db→聚合→缓存，失败回退历史）
  singleton.py         单实例互斥（CreateMutexW）
  theme.py             深浅色配色 + 系统主题检测
  ui/window.py         悬浮小窗（Apple 风格圆角卡片）
  ui/wizard.py         首启向导（失败三分/跳过/今日预览/文档入口）
  ui/settings.py       设置窗（连接/外观/行为/关于）
tests/                 单测（含配置容错、聚合、缓存、管线、官网增量和 UI 控件）
tools/                 验证工具（smoke / verify_ui / 截图）
dist/                  打包产物
```
