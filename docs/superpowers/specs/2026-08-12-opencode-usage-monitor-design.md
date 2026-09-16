# OpenCode 用量监测小窗 — 设计文档

> 2026-09-14 打包交付修订：交付中文名的单文件 exe，内含 Python/Tk 与图标。打包实测发现首启向导按钮重叠、长标题/路径溢出，交付前修复这些启动阻碍：标题缩短、说明换行、跳过按钮独立置于底部。现有 --auto-close 验证模式在无配置时也应自动通过向导并正常退出，避免打包验证挂起。
> 打包截图同时发现主窗将自适应高度再次按固定 182 高缩放，进度条越界且状态居中裁切。修复为先计算内容与换行状态实际高度再绘制，状态左对齐并按需换行，指标按用户选择顺序显示。

> 2026-09-14 数据层修订（优先于下文早期口径）：默认输入显示总输入；本地会话按 time_created 归日，缺失时回退 time_updated。官网 token 为账户级，优先于本机数据。费用仅取官网账单。
> 本次仅修复阶段 2：刷新必须使用设置保存的数据库路径；NULL 指标按零处理；缓存结构损坏时忽略，写缓存失败仍返回已读取数据和中文提示。官网增量缓存绑定 workspace，完整分页后才推进记录标记；标记丢失时覆盖重建当前范围，避免重复累加。费用和 token 日期取并集，请求次数按明细记录数统计。
> 配置读取需校验类型和范围，迁移旧输入字段，保留已实现的窗口尺寸和首次提示状态；原子写使用独立临时文件，避免并发写互相覆盖临时文件。

> 日期：2026-08-12
> 状态：待用户审阅
> 项目目录：`C:\Users\14681\Desktop\go订阅监测\`

## 1. 项目定位

一个 **Windows 通用的桌面悬浮小窗**，实时监测本机 OpenCode/OpenChamber 的 API token 用量（输入 / 输出 / 缓存命中率），支持按 **日 / 周 / 月** 查看，可翻看历史。目标是可打包分发、其他人零配置或少配置即可使用。

差异化：Windows 原生零依赖轻量小窗 + 缓存命中率作为核心指标 + 日/周/月实时聚合（现有开源方案均未覆盖此组合）。

## 2. 技术栈

- **语言 / UI**：Python 3 + tkinter，运行期零第三方依赖（仅 stdlib：`sqlite3/json/os/threading/tkinter/ctypes`）
- **数据源**：本地 SQLite `opencode.db`（OpenChamber 与独立 opencode CLI 共用，天然覆盖全部会话）
- **打包**：PyInstaller 打成单 exe，双击即用
- **开发**：多模块分文件，可直接 `python main.py` 运行

## 3. 架构

```
opencode.db（~/.local/share/opencode/opencode.db）
   │  增量读取（只处理新增会话，秒级）
   ▼
数据层
  ├─ config.py   探测 db 路径 / 读写配置（%APPDATA%）
  ├─ db_reader.py  读 opencode.db → 原始记录（会话级 token 明细）
  ├─ aggregator.py 按日/周/月聚合 + 命中率（纯函数，可单测）
  └─ cache.py     JSON 增量缓存维护
   ▼
UI 层
  ├─ main.py    程序入口（启动向导 → 主窗口）
  └─ ui_window.py  tkinter 小窗
```

- 单进程；UI 主线程 + 一个后台工作线程拉数据，不卡界面
- 聚合逻辑全部为纯函数，独立于 UI 可测试

## 4. 数据层

### 4.1 数据源

- 读取 `opencode.db`（SQLite）。默认路径：`%USERPROFILE%\.local\share\opencode\opencode.db`
- 探测顺序：默认路径 → 常见备选路径 → 用户手动指定（设置窗可改）
- 读取模式为只读（`file:...?mode=ro`），绝不写库
- db 文件被占用/锁定：跳过本次刷新，回退显示缓存数据，提示"稍后自动重试"
- db 缺失/损坏：显示缓存历史；无缓存则显示错误提示 + 打开设置

### 4.2 指标口径（与 opencode stats 一致）

| 指标 | 公式 |
|---|---|
| 输入 tokens | **新鲜输入 inputTokens（不含缓存；2026-08-12 用户确认改为实际发送口径，与 stats 的 Input 列一致）** |
| 输出 tokens | outputTokens |
| 缓存命中率 | cache_read ÷（新鲜输入 + cache_read + cache_write）× 100% |

- 会话按时间戳归入自然日；周 = 周一至周日（周一起算）；月 = 自然月
- 所有会话计入聚合，不按模型/工具拆分（YAGNI）

### 4.3 缓存

- 路径：`%APPDATA%\opencodego-token-watcher\monitor_cache.json`
- 结构：`{"schema": 1, "last_sync": ..., "session_ids": [...], "by_day": {日期: {input, output, cache_read, cache_write}}}`（周/月聚合由 by_day 现场算出；`input` 为总输入口径）
- 刷新策略（阶段 1 实测修正）：`session` 表行数少（本机 75 行），**每次全量读 session 表（毫秒级）**，无需复杂增量；保留 `max(time_updated)` 作为未来增量依据
- 缓存可删除重建；db 损坏时历史仍可从缓存查看（原子写，防半成品覆盖）

## 5. UI 层

### 5.1 主窗口

- 形态：迷你悬浮窗（约 250×150，按内容自适应）
- 行为：**置顶**（可切换）、**半透明**（`-alpha 0.85` 白底半透明；真 Acrylic 经实测在 tkinter+overrideredirect 上导致窗口内容不绘制，弃用）、**可拖拽**、右键菜单
- 刷新：5 分钟自动 + ⟳ 手动

### 5.2 布局

```
┌──────────────────────┐
│ ◀ 8月12日(周二) 日[周][月] ▶ │   ← 粒度标签切换 + 日期导航
│ ──────────────────── │
│ 输入      1.2M        │
│ 输出      89.1K       │
│ 命中率    62.5%       │
│ ▓▓▓▓▓▓▓░░░░░          │   ← 三段式彩色进度条
└──────────────────────┘
```

- **粒度**：日 / 周 / 月 标签切换，标签高亮当前粒度
- **导航**：◀ ▶ 按当前粒度翻历史（日→翻天，周→翻周，月→翻月）；点日期 → 弹月历直接跳转任意日期（切到"日"粒度）
- **指标**：输入 / 输出（缩写格式 1.2K / 1.3M）、命中率百分比 + 进度条
- **颜色**：命中率 ≥70% 绿 / 30~70% 橙 / <30% 红
- **数字格式**：大数缩写（<1000 显示原数字）

### 5.3 首启向导

首次启动（无配置时）弹向导窗：
1. 自动探测 db 路径并显示
2. 用户可：确认 / 手动指路径 / 重新探测
3. 点"开始使用"进入主窗口

### 5.4 右键菜单

刷新 / 切换置顶 / 设置（db 路径、开机自启开关）/ 关于 / 退出

### 5.5 样式

- 玻璃底白色半透明 + 白色边框；主文字深灰 `#1F2937`、标签灰 `#6B7280`
- 数字 Consolas 15 bold，标签 Segoe UI；DPI 感知修复模糊
- 界面语言：中文

## 6. 配置与分发

- 配置路径：`%APPDATA%\OpenCodeUsageMonitor\config.json`
- 配置项：db 路径（留空=自动）、开机自启（写注册表 Run 键）、窗口位置
- 开机自启为**可选**开关，默认关
- 分发：源码单 py 多文件（开发/调试）+ PyInstaller 单 exe（交付，`--onefile --noconsole`）
- 资源文件（如无图标则用 tkinter 默认）全部打进 exe

## 7. 错误处理

| 场景 | 行为 |
|---|---|
| db 不存在 | 向导/设置提示；主窗口显示"未找到数据源" |
| db 被锁定 | 本次跳过，用缓存数据，5 分钟后自动重试 |
| db 损坏/结构变化 | 提示错误 + 打开设置；缓存历史仍可看 |
| 缓存损坏 | 自动重建缓存（重新全量读一次 db） |
| 聚合出现缺失字段 | 缺失字段按 0 处理，不崩溃 |

## 8. 成功标准

1. `python main.py` 双击即出小窗，自动探测到 db 并显示当日用量
2. 日/周/月切换、翻历史、日历跳转全部可用且数字与 `opencode stats` 一致（抽查 3 个日期对比）
3. 命中率三段颜色正确；缩写数字格式正确
4. 置顶/毛玻璃/拖拽/右键菜单/开机自启全部可用
5. 打包成单 exe 后，在未装 Python 的 Windows 上双击可运行
6. 运行期内存占用低（轻量）

## 9. 非目标（YAGNI）

- 不做云端同步 / 多设备
- 不做自动更新
- 不做多语言（仅中文）
- 不做按模型/按会话的细分报表

## 10. 官网费用同步（v2，2026-08-12 用户新增需求）

### 10.1 背景与结论

- 用户要求费用数据以官网 `opencode.ai/workspace/<id>/usage` 为准（官网是服务商账单）。
- 调研结论：官网**无公开 API**；数据链路 = OpenAuth 登录（auth.opencode.ai）→ 加密 session cookie（名 `auth`）→ SolidStart server function（`/_server?id=<hash>`）直连 MySQL。
- 本地 `opencode.db` 的 `cost` 字段是客户端内置价格表估算，与官网账单口径不同（本地 8/12 记 $2.42，官网 $5.50），**不可用作账单**。
- 方案：**主数据（token 量）继续读本地 db（与官方 stats 一致，已验证）；费用以官网为准**——用户提供浏览器登录 cookie，应用定时调官网 server function 拉取费用。

### 10.2 官网接口（逆向自 sst/opencode 仓库 packages/console）

| 函数 | id | 参数 | 返回 |
|---|---|---|---|
| `Billing.usages`（明细表） | `bfd684bfc2e4eed05cd0b518f5e4eafd3f3376e3938abb9e536e7c03df831e5c` | `(workspaceID, page)`，每页 50 | 数组：`timeCreated/model/inputTokens/cacheReadTokens/outputTokens/reasoningTokens/cost(微美分)/sessionID/enrichment.plan` |
| `getCosts`（按月图表） | `15702f3a12ff8bff357f8c2aa154a17e65b746d5f6b96adc9002c86ee0c15205` | `(workspaceID, year, month, tzOffset)`，tzOffset 形如 `+08:00` | `{usage:[{date:"YYYY-MM-DD", model, totalCost, keyId, plan}], keys:[...]}` |

- RPC 协议：`POST https://opencode.ai/_server?id=<id>`，headers：`X-Server-Id: <id>`、`X-Server-Instance: server-fn:0`、`Content-Type: application/json`、`Cookie: <用户 cookie>`；body 为 seroval 序列化 `{"t":"[\"arg1\",arg2]","f":[],"m":[]}`（纯 JSON 参数时 `t` = `JSON.stringify(args)`）。
- 费用单位：**microcents（1e-8 美元）**，`cost / 1e8` 即美元；官网 8/12 的 deepseek $4.58 = 458,000,000 microcents（已验证对上）。
- 按天口径：官网按 `UsageTable.timeCreated` 经 `CONVERT_TZ` 到浏览器时区（tzOffset 参数）分组，与我们本地按 time_updated 归日不同——以官网为准。

### 10.3 应用内集成

- 新增 `src/opencode_cloud.py`：仅 stdlib（urllib），实现 `fetch_usages` / `fetch_costs` / 费用按天聚合 / 错误分类（网络、未登录、服务端）。
- 配置新增：`cloud_workspace_id`（如 `wrk_01KZG6...`）、`cloud_cookie`（浏览器复制）、`cloud_enabled`。
- 数据流：token 量走本地 db（不变）；费用走官网按月拉取 → 缓存 `monitor_cloud.json`（`{by_day:{日期: 总费用+按模型}, last_sync}`）→ 小窗"费用"行显示。
- UI：主窗显示字段增加"费用"（可勾选）；右键菜单"同步官网费用"；设置窗新增"官网同步"分区（workspace ID / cookie 输入 / 测试读取 / 获取指引）。
- 失败兜底：未配置/网络失败显示"—"，不影响本地 token 显示；cookie 过期提示用户更新。

### 10.5 显示要素（2026-08-13 用户确认，官网计价口径）

- **默认四项**：输入总（= 新鲜输入 + 缓存读 + 缓存写，官网 usage 表 input 列口径）、输出总、命中率（缓存读 ÷ 总输入）、费用（官网账单）
- **自定义可选**：新鲜输入、缓存读、缓存写、推理 token、总 token、请求次数（usage.list 记录数）
- 窗口**宽固定高自适应**：高度随要素行数变化（行高 28px + 导航/进度条/状态栏）
- 口径说明：缓存读 9.87 亿/天是真实数据（每次请求重复读取会话上下文，命中率 98.3%），计费主体是新鲜输入+输出；缓存读作为自定义要素默认不显示

### 10.4 验证

- 用用户 cookie 调 `fetch_costs` 拉当月，与官网页面数字对比（8/12 deepseek $4.58 + mimo $0.92 = $5.50）。
- 应用内"测试读取"按钮显示最近 3 天费用，用户肉眼核对。
# v0.3.1 界面完整显示修订（2026-09-16）

- 主监测窗根据已选指标、命中率进度条和状态提示的实际高度自动展开；恢复旧配置中的过小尺寸时也必须先扩展到完整内容高度，不要求用户拖动右下角缩放手柄。
- 主监测窗默认宽度保持轻量，内容超过默认四项时允许自动增高；所有文字、指标、进度条和状态提示必须位于卡片内且互不遮挡。
- 设置窗由单列长页面改为双栏总览：左栏放外观、行为和高级设置，右栏放显示内容、官网同步和关于。默认折叠高级设置时，全部常用 UI 在一个窗口内直接可见，不使用纵向滚动区。
- 设置窗应自动限制在当前屏幕可用范围内并居中放置；保存、取消始终固定可见。
