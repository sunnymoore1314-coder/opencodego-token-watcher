# 项目工作指引（AGENTS.md）

> 项目：OpenCode 用量监测桌面小窗（Windows 通用）
> 本文件是智能体在本项目内工作的总指引。

## 标准文件路径（做任何事前先看对应文件）

| 场景 | 文件 |
|---|---|
| 总设计（源头，变更/争议以此为准） | `docs/superpowers/specs/2026-08-12-opencode-usage-monitor-design.md` |
| 需求清单（可验收条目） | `docs/01-需求/requirements.md` |
| 技术方案（模块接口/算法/打包） | `docs/02-技术/technical.md` |
| UI 设计规范（布局/颜色/字体/交互） | `docs/03-设计规范/ui-spec.md` |
| 开发流程标准（阶段/验证/日志规范） | `docs/04-流程/development-process.md` |
| 文档索引 | `docs/README.md` |
| 开发日志（每日） | `devlogs/YYYY-MM-DD.md` |

## 工作说明（必须遵守）

1. **小步走**：一次会话只推进 1 个阶段（见开发流程标准的阶段表），每阶段验证通过才进下一阶段。禁止一口气做多个阶段。
2. **开始工作时**：
   - 先读 `docs/04-流程/development-process.md` 确认当前阶段
   - 读 `devlogs/` 最近一天日志，接着待办做
3. **收尾时**：把完成事项 + 待办更新到 `devlogs/当天日期.md`（当天文件不存在则创建）
4. **写代码时**：遵循 `docs/02-技术/technical.md` 的模块划分；纯逻辑（聚合/口径/缓存）先写单测再实现；UI 按 `docs/03-设计规范/ui-spec.md`
5. **验证纪律**：每步有验证方式；不声明未验证的完成
6. **需求变更**：先改设计文档，再同步需求/技术/UI 文档，最后才动代码
7. **技术约束**：运行期仅 Python stdlib，零第三方依赖；打包 PyInstaller 单 exe（仅最后阶段安装）
8. **界面语言**：中文
