"""在独立目录、隔离配置和无 Python PATH 中验证单文件 exe。"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile


def main() -> None:
    project = Path(__file__).resolve().parent.parent
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else project / "OpenCode用量监测.exe"
    root = Path(tempfile.mkdtemp(prefix="package-", dir=project / "build"))
    standalone = root / "standalone"
    standalone.mkdir()
    copied = standalone / exe.name
    shutil.copy2(exe, copied)
    env = os.environ.copy()
    env["APPDATA"] = str(root / "profile")
    env["SystemRoot"] = env.get("SystemRoot", env.get("WINDIR", r"C:\Windows"))
    env["PATH"] = str(Path(env["SystemRoot"]) / "System32")
    first = subprocess.run([str(copied), "--auto-close", "3"], cwd=standalone,
                           env=env, timeout=30)
    if first.returncode:
        raise RuntimeError(f"首次启动失败：{first.returncode}")
    cfg_path = root / "profile" / "opencodego-token-watcher" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    print("FIRST_RUN: PASS（向导自动跳过、配置保存、主窗正常退出）", flush=True)

    # 只在验证目录创建模拟数据，不访问真实数据库/个人 Cookie。
    db = root / "sample.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE session (id TEXT, time_created INTEGER, time_updated INTEGER, "
                     "tokens_input INTEGER, tokens_output INTEGER, tokens_reasoning INTEGER, "
                     "tokens_cache_read INTEGER, tokens_cache_write INTEGER, cost REAL)")
        now = int(datetime.datetime.now().timestamp() * 1000)
        conn.execute("INSERT INTO session VALUES (?,?,?,?,?,?,?,?,?)",
                     ("sample", now, now, 100000, 24000, 0, 900000, 0, 0))
    cfg.update(db_path=str(db), tips_shown=True, cloud_enabled=False, window_alpha=0.95)
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    run = subprocess.Popen([str(copied), "--auto-close", "20"], cwd=standalone, env=env)
    print(f"MAIN_WINDOW: pid={run.pid}, profile={root}", flush=True)
    try:
        code = run.wait(timeout=40)
    except subprocess.TimeoutExpired:
        run.kill()
        raise
    if code:
        raise RuntimeError(f"已配置启动失败：{code}")
    data = json.loads((cfg_path.parent / "monitor_cache.json").read_text(encoding="utf-8"))
    stats = next(iter(data["by_day"].values()))
    if stats["input"] != 100000 or stats["output"] != 24000 or stats["cache_read"] != 900000:
        raise RuntimeError("打包后的数据库读取结果不符")
    report = {"exe": str(exe), "standalone": str(copied), "first_run": "PASS",
              "configured_run": "PASS", "exit_code": code,
              "python_on_path": False, "cache_stats": stats,
              "limitations": "本机安装有 Python；不等同于未装 Python 的独立机器验收"}
    (project / "devlogs" / "2026-09-14-package-check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PACKAGE: PASS", flush=True)


if __name__ == "__main__":
    main()
