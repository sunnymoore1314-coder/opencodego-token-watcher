"""冒烟验证：数据层聚合 vs opencode stats 输出（阶段 2 验证标准）。

用法: python tools/smoke.py [--days N] [--db 路径] [--offline] [--cli 路径]
可选: 环境变量 OPENCODE_CLI 指向 opencode.exe，否则从 PATH 查找。
"""
import datetime
import argparse
import os
import re
import subprocess
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.aggregator import aggregate_by_day
from src.db_reader import DbError, fetch_sessions, open_db

def parse_stats_number(text: str, label: str) -> float | None:
    """从 stats 表格行提取数字，如 `│Input        20.2M │` → 20_200_000。"""
    m = re.search(rf"│{label}\s+([\d,]+(?:\.\d+)?)\s*([MK]?)\s*│", text)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    if m.group(2) == "K":
        n *= 1_000
    elif m.group(2) == "M":
        n *= 1_000_000
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description="只读聚合验证；可选与 opencode stats 比较")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--db", help="指定 opencode.db，默认使用配置或自动探测")
    parser.add_argument("--offline", action="store_true", help="只验证本地聚合，不运行 CLI")
    parser.add_argument("--cli", help="指定 opencode CLI 路径")
    args = parser.parse_args()
    days = args.days
    if days < 1:
        parser.error("--days 必须大于 0")

    # 1) 我们的聚合
    db_path = config.detect_db(args.db or config.load_config().get("db_path"))
    if not db_path:
        print("FAIL: 未找到 opencode.db")
        return 1
    try:
        conn = open_db(db_path)
        try:
            sessions = fetch_sessions(conn)
        finally:
            conn.close()
    except DbError as e:
        print(f"FAIL: {e}")
        return 1

    start_ms = int(datetime.datetime.combine(
        datetime.date.today() - datetime.timedelta(days=days - 1),
        datetime.time.min,
    ).timestamp() * 1000)
    recent = [s for s in sessions if (s.get("time_created") or s.get("time_updated") or 0) >= start_ms]
    by_day = aggregate_by_day(recent)
    fresh = sum(s.input for s in by_day.values())
    out = sum(s.output for s in by_day.values())
    cr = sum(s.cache_read for s in by_day.values())
    cw = sum(s.cache_write for s in by_day.values())
    for day, stats in sorted(by_day.items()):
        print(f"{day}: fresh_input={stats.input} output={stats.output} "
              f"cache_read={stats.cache_read} cache_write={stats.cache_write}")
    print(f"TOTAL: fresh_input={fresh} output={out} cache_read={cr} cache_write={cw}")

    # 2) stats 基准
    cli_name = args.cli or os.environ.get("OPENCODE_CLI") or shutil.which("opencode")
    if args.offline or not cli_name:
        print("LOCAL: PASS; STATS: SKIP（仅验证本地聚合，未与 opencode stats 对账）")
        return 0
    try:
        r = subprocess.run([cli_name, "stats", "--days", str(days)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"STATS: FAIL: {e}")
        return 1
    if r.returncode != 0:
        print(f"STATS: FAIL（CLI 退出码 {r.returncode}）: {r.stderr.strip()}")
        return 1
    text = r.stdout

    ref = {
        "fresh_input": parse_stats_number(text, "Input"),
        "output": parse_stats_number(text, "Output"),
        "cache_read": parse_stats_number(text, "Cache Read"),
        "cache_write": parse_stats_number(text, "Cache Write"),
    }

    got = {"fresh_input": fresh, "output": out, "cache_read": cr, "cache_write": cw}
    ok = True
    print(f"对比 opencode stats --days {days}：")
    for k, want in ref.items():
        g = got[k]
        if want is None:
            match = False
        elif want == 0:
            match = g == 0  # 基准为 0 时直接比对（避免除零）
        else:
            # stats 显示精度 1 位小数（±0.05M），3% 容差可覆盖显示误差
            match = abs(g - want) / want < 0.03
        ok &= bool(match)
        print(f"  {k:12s} 我们={g:>14,}  stats={want if want is None else f'{want:,.0f}'}  {'PASS' if match else 'FAIL'}")
    rate = f"{cr / (fresh + cr + cw) * 100:.1f}%" if fresh + cr + cw else "—"
    print("总输入口径:", f"{fresh + cr + cw:,}", f"(命中率 {rate})")
    print("SMOKE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
