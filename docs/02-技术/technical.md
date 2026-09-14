# 技术方案

> 打包交付（2026-09-14）：项目 .build-venv 内安装 PyInstaller，使用现有 spec 内嵌 assets/app.ico，onefile/noconsole。产物复制为根目录 `OpenCode用量监测.exe`；隔离 APPDATA 与工作目录、PATH 不含 Python 验证。--auto-close 在首启向导安排自动跳过，随后主窗经 _exit 正常退出并释放托盘/配置。
> 打包显示修复：render 在绘制卡片前计算指标行数与 Canvas 实测的状态换行高度；内容区和状态区分别布局，避免自动增高后又按固定 182 高缩放。状态文本使用 nw 锚点和可用宽度。

## 2026-09-14 数据层修订（覆盖下文早期说明）

- `pipeline.refresh()` 未传路径时读取配置的 `db_path`；显式路径优先。只读 SQLite URI 使用 `Path.resolve().as_uri()` 转义特殊字符，读取失败也关闭连接。NULL token 按零处理，缓存写入错误以 `(by_day, 中文提示)` 返回。
- 本地缓存 schema 1 校验日期和 `DayStats` 字段类型；旧缓存可缺新增字段，损坏结构返回 None。
- `config.load_config()` 迁移 `input` → `input_total`，过滤未知/重复显示字段；校验主题、数字格式、透明度、刷新分钟数、布尔值、路径、坐标、尺寸，保留 `window_size`/`tips_shown`。JSON 写入使用目标目录内唯一临时文件后原子替换，失败清理临时文件。
- 官网缓存 schema 5 增加 `workspace_id`，旧版/不同 workspace 不用于增量合并。同步串行；写入以目标缓存父目录为准。
- 官网分页使用自然月起点，遇到旧记录标记为增量；到列表末尾/时间范围起点但未遇到标记则按全量覆盖该范围。达到分页上限时报 `CloudError`，不写入不完整数据。分页记录按 id 去重，按天计请求数；费用/token/已有历史取并集，费用覆盖、增量 token 累加、全量 token 覆盖。
- 带参 RPC 实际 body 为 `{"t": <seroval 对象树>, "f": 31, "m": []}`，无参无 body；响应由递归解析器解析 seroval 流。现有函数 id 仅为历史构建值，本次不宣称当前官网连通性。

> 技术决策源头：设计文档第 2/3/4 节。本文件记录实现细节，随实现推进更新。

## 技术栈

- Python 3（开发机：本机可用版本）+ tkinter
- 运行期仅 stdlib：`sqlite3 json os threading tkinter ctypes re time winreg`（winreg 仅 Windows，用于系统主题检测/开机自启）
- 打包：PyInstaller（开发期不装，最后阶段装）

## 模块结构

```
main.py            入口：单实例检查 → 首启向导判断 → 启动主窗口（程序图标）
src/               数据层
  config.py        探测/读写配置（config.json）与缓存路径管理
  db_reader.py     读 opencode.db → 原始会话记录
  aggregator.py    日/周/月聚合 + 命中率（纯函数）
  cache.py         JSON 缓存增量维护
  singleton.py     单实例互斥（CreateMutexW，多开提示"程序已在运行"）
  theme.py         深浅色两套配色（LIGHT/DARK）+ 注册表系统主题检测 + get_palette
src/ui/
  window.py        tkinter 主窗口（布局、交互、右键菜单、置顶/任务栏、半透明）
  wizard.py        首启向导窗（失败三分/跳过/今日用量预览/文档入口）
  settings.py      设置窗（连接/外观/行为/关于，含 Apple 风格透明度滑条）
tests/            纯函数单测（aggregator 为主，不依赖 tkinter/db）
```

## opencode.db 读取（阶段 1 实测确认 2026-08-12）

- 本机路径：`C:\Users\14681\.local\share\opencode\opencode.db`（718MB，WAL 模式，OpenChamber 与 CLI 共用）
- 打开方式：SQLite URI 只读 `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`（实测可用）
- **核心结论：直接读 `session` 表**，官方已按会话聚合好 token 字段，无需解析 message/part 的 JSON

### session 表关键字段（聚合直接用）

| 字段 | 含义 |
|---|---|
| `id` | 会话 id（text） |
| `time_created` / `time_updated` | 毫秒时间戳（本地时区归日） |
| `tokens_input` | 新鲜输入（不含缓存读） |
| `tokens_output` | 输出 |
| `tokens_reasoning` | 推理（计入输出口径与否待定——见口径注） |
| `tokens_cache_read` / `tokens_cache_write` | 缓存读 / 写 |

### 口径验证记录（三方一致）

- `session` 表字段 = `message.data` JSON 累加（3 会话抽样完全一致）
- = `opencode stats --days 7`（Input 20.2M / Output 2.6M / Cache Read 1120.2M 全部吻合）
- stats 的时间范围 = `time_updated >= 7 天前 00:00`（本地时区），按此实现可复现

### 增量策略（实测修正）

- session 表现仅 75 行：**每次刷新全量读 session 表即可（毫秒级）**，无需复杂增量
- 但保留记录 `max(time_updated)` 作为未来的增量依据（表增长后启用）
- 按天归日：`datetime.fromtimestamp(time_updated/1000).date()`（本地时区）

### 已知数据量（本机）

- session 75 / message 6920 / part 28470 / event 95907；message/part 的 JSON 不需要解析

## 聚合算法（纯函数）

- 输入：会话记录列表 `[{session_id, timestamp, input, output, cache_read, cache_write}]`
- 步骤：按 timestamp 归日 → by_day 累加 → 周/月由 by_day 汇总（周一起算，`date.isocalendar()` 对齐）
- 命中率：`cache_read / (input + cache_read + cache_write) * 100`，分母为 0 时显示 "--"（不显示 0%）

## 缓存结构

```json
{
  "schema": 1,
  "last_sync": "2026-08-12T15:30:00+08:00",
  "session_ids": [1001, 1002],
  "by_day": {
    "2026-08-12": {"input": 1234, "output": 89, "cache_read": 900, "cache_write": 10}
  }
}
```

- 写入：原子写（先写临时文件再 rename），避免半成品覆盖（旧会话踩过竞态坑）
- 重建：删缓存 → 全量读一次 db → 重写

## 窗口外观：半透明 / 圆角 / 主题（2026-08-12 定稿）

- **Acrylic 已弃用**：`SetWindowCompositionAttribute`（ACCENT_ENABLE_ACRYLICBLURBEHIND）在 tkinter + overrideredirect 上实测导致内容不绘制（像素统计证实），回退方案即正式方案
- 半透明：`-alpha`（config `window_alpha`，默认 0.78，设置窗可调 0.50~0.95）+ `-transparentcolor` 抠色（圆角外完全透明）
- 圆角：Canvas smooth 多边形圆角矩形（主窗 R=18，卡片内距 4px + 阴影 2px）
- 主题：`src/theme.py` 的 `LIGHT`/`DARK` 两套 Apple 配色；`system_is_dark()` 读注册表 `HKCU\...\Themes\Personalize\AppsUseLightTheme`（0=深色）；`get_palette(theme)` 按 `config.theme`（system/light/dark）返回配色，主窗/设置窗/日历/关于/向导共用
- 主窗布局参数：250×182；导航 y28 / 分隔线 y44 / 指标三行 y66 起行距 28 / 进度条 y136~143 / 状态栏 `anchor=s` y=H-18（文字底距卡片底 14px，Apple 底部留白规范 12-16px）；数字 **Segoe UI 10 常规**（不加粗，用户要求）

## 置顶与任务栏（WS_EX 切换）

- 置顶开：exstyle 加 `WS_EX_TOOLWINDOW`（0x80）→ 小窗不占任务栏
- 置顶关：清 TOOLWINDOW + 加 `WS_EX_APPWINDOW`（0x40000）→ 任务栏出现入口；任务栏按钮只在窗口重新显示时重评估，必须 `ShowWindow(hide) → ShowWindow(show)` 强制刷新，再 `SetWindowPos(FRAMECHANGED)`
- 64 位安全：`Get/SetWindowLongPtrW` 显式声明 HWND/LONG_PTR 类型（否则句柄被截断 32 位静默失败）

## 单实例

- `src/singleton.py`：`CreateMutexW`（restype=HANDLE 防 64 位截断），`GetLastError()==183(ERROR_ALREADY_EXISTS)` 判定已有实例；互斥体名固定 `opencodego-token-watcher-singleton-mutex`，与 exe 名无关
- main.py 在任何窗口创建前检查：已存在 → stderr 打印 + `MessageBoxW`（"程序已在运行"）后 `exit(1)`；句柄存模块级全局，正常退出 `release()`
- `--auto-close` 验证模式跳过单实例检查

## 打包

- 配置路径：`%APPDATA%\opencodego-token-watcher\`（config.json / monitor_cache.json / monitor_cloud.json）
- 命令：`pyinstaller --onefile --noconsole --name opencodego-token-watcher --icon assets/app.ico --add-data "assets/app.ico;assets" main.py`
- 图标：`assets/app.ico`（16~256 七尺寸，上升柱状图绿/蓝/橙）；frozen 时 `main._resource_path()` 从 `sys._MEIPASS` 读取，开发期取项目根
- 打包后冒烟：在干净环境（无 Python）双击运行

## 官网费用同步（2026-08-12 逆向自 sst/opencode 仓库 packages/console）

### 背景

- 用户要求费用以官网为准。本地 db `cost` 是客户端估算（价格表不同），官网才是账单。
- 官网无公开 API；只有登录 cookie 能访问 server function（SolidStart RPC）。

### RPC 协议（实测确认）

- `POST https://opencode.ai/_server?id=<64位hex函数id>`
- Headers：`X-Server-Id: <id>`、`X-Server-Instance: server-fn:0`、`Content-Type: application/json`、`Cookie: <浏览器登录cookie>`、`Origin/Referer: https://opencode.ai`
- Body（seroval 序列化）：`{"t":"[\"arg1\",arg2]","f":[],"m":[]}`——纯 JSON 参数时 `t` 就是 `JSON.stringify(args)`；无参函数 `{"t":"[]","f":[],"m":[]}`
- 响应：`application/json` 直接解析；未登录/参数错时 500 `{"status":500,"unhandled":true,"message":"HTTPError"}`（getActor 内部 redirect 被包装）

### 函数 id（构建产物提取，官网改版可能失效）

| 用途 | id | 参数 | 返回 |
|---|---|---|---|
| 费用明细（usage.list） | `bfd684bfc2e4eed05cd0b518f5e4eafd3f3376e3938abb9e536e7c03df831e5c` | `(workspaceID, page)` 每页 50 | `[{timeCreated, model, inputTokens, cacheReadTokens, outputTokens, reasoningTokens, cost, sessionID, enrichment:{plan}}]` |
| 按月图表（getCosts） | `15702f3a12ff8bff357f8c2aa154a17e65b746d5f6b96adc9002c86ee0c15205` | `(workspaceID, year, month, tzOffset)` | `{usage:[{date:"YYYY-MM-DD", model, totalCost, keyId, plan}], keys:[...]}` |

### 口径与换算

- cost 单位 **microcents = 1e-8 美元**：`usd = cost / 1e8`（官网 8/12 deepseek $4.58 = 458,000,000 ✓）
- 官网按天 = `UsageTable.timeCreated` 经 `CONVERT_TZ(..., tzOffset)` 分组（前端传浏览器时区，如 `+08:00`）；我们按当前月+上月拉取覆盖最近范围
- `enrichment.plan`：`sub`/`lite`/`byok`（订阅/轻量/自带密钥），图表上会显示订阅标记，聚合时不影响

### 模块（src/opencode_cloud.py，仅 stdlib）

- `CloudError(Exception)`：`kind` ∈ `network`/`auth`/`server`/`parse`，中文消息
- `fetch_costs(workspace_id, cookie, year, month, tz_offset)` → `{usage:[...], keys:[...]}`（透传原始字段）
- `fetch_usages(workspace_id, cookie, page=0)` → 明细数组（透传）
- `month_costs(workspace_id, cookie, tz_offset)` → `{"2026-08-12": {"total": 5.5, "by_model": {"deepseek-v4-flash (go)": 4.58, ...}}}`：拉当前月+上月，累加 `totalCost/1e8`
- 请求失败分类：`URLError/TimeoutError` → network；HTTP 500/302 且带登录跳转 → auth（提示 cookie 过期）；其他 → server
- 缓存 `monitor_cloud.json`：`{"schema":1, "last_sync": "...", "by_day": {date: {total, by_model}}}`；原子写；同步失败保留旧数据并记录错误

### 配置（config.json 新增）

- `cloud_workspace_id`（空=未配置）、`cloud_cookie`（完整 Cookie 头或 `auth=...`）、`cloud_enabled`（默认 false）
- cookie 获取指引（设置窗 ⓘ）：浏览器登录 opencode.ai → F12 → Network → 点任意请求 → 复制 Request Headers 里的 Cookie 整行

### UI 集成

- 主窗 `display_fields` 可勾选 `cost`；日/周/月视图显示对应范围内 `by_day.total` 求和，未同步显示 `—`
- 右键菜单"同步官网费用"：调 `month_costs` → 更新缓存 + 重绘；状态栏显示"官网 HH:MM"
- 设置窗"官网同步"分区：workspace ID / cookie 输入（password 显示）+ 测试读取（拉当月显示最近 3 天）+ ⓘ 指引
- 失败不阻塞：本地 token 照常显示，费用行显示"—"
