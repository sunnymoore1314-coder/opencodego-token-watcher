"""官网费用同步（opencode.ai）— 仅 stdlib，零第三方依赖。

逆向自 sst/opencode 仓库 packages/console + 实测（2026-08-12）：
- 官网无公开 API；用量数据通过 SolidStart server function（POST /_server?id=<hash>）获取
- 认证：浏览器登录 opencode.ai 后的 Cookie（httpOnly 会话，一年有效）
- RPC 协议：无参函数 POST 无 body；带参函数 body = {"t": <seroval树>, "f": 31, "m": []}
  （f 是位掩码数字；t 是对象树 {t:类型, s:值}，0=数字 1=字符串 2=布尔 9=数组）
- 响应：seroval 流（;0x<hexlen>;JS 表达式，$R[n] 引用），用 _SerovalParser 求值
- cost 单位 microcents = 1e-8 美元（官网 8/12 deepseek $5.43 = 543,000,000，已验证）
- 月份索引 0-based（JS Date）；按天按 CONVERT_TZ 到本地时区
"""
from __future__ import annotations

import datetime
import json
import re
import sys
import threading
import math
import urllib.error
import urllib.request

from src import config
from src.cache import save_cache, valid_day, valid_stats

BASE_URL = "https://opencode.ai"
# server function id（构建产物提取；官网改版可能失效，失效时重新提取）
FN_USAGES = "bfd684bfc2e4eed05cd0b518f5e4eafd3f3376e3938abb9e536e7c03df831e5c"
FN_COSTS = "15702f3a12ff8bff357f8c2aa154a17e65b746d5f6b96adc9002c86ee0c15205"
FN_WORKSPACES = "def39973159c7f0483d8793a822b8dbb10d067e12c65455fcb4608459ba0234f"
PAGE_SIZE = 50
FEATURES = 31  # seroval 位掩码（默认值，无 disabledFeatures）
CLOUD_CACHE_SCHEMA = 5
_sync_lock = threading.Lock()
TOKEN_FIELDS = ("input", "output", "cache_read", "cache_write", "reasoning", "requests")


def _month_start(months: int) -> datetime.date:
    if type(months) is not int or months < 1:
        raise CloudError("config", "同步月份数必须为正整数")
    today = datetime.date.today()
    index = today.year * 12 + today.month - months
    year, month = divmod(index, 12)
    return datetime.date(year, month + 1, 1)


class CloudError(Exception):
    """官网请求失败。kind: network / auth / server / parse / config。"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def tz_offset_str() -> str:
    """本地时区偏移，如 +08:00（官网 CONVERT_TZ 需要的格式）。"""
    now = datetime.datetime.now()
    off = now.astimezone().utcoffset() or datetime.timedelta(0)
    total = int(off.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"{sign}{total // 3600:02d}:{total % 3600 // 60:02d}"


def _parse_time(value) -> datetime.datetime | None:
    """官网 timeCreated 解析：ISO/MySQL 格式 → 本地时区 datetime。"""
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    dt = None
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone()


# ---------- seroval 参数序列化 ----------
def _seroval_node(v):
    """参数 → seroval 树节点（类型码：0=数字 1=字符串 2=布尔/null 9=数组）。"""
    if v is None:
        return {"t": 2, "s": 0}
    if v is True:
        return {"t": 2, "s": 2}
    if v is False:
        return {"t": 2, "s": 3}
    if isinstance(v, (int, float)):
        return {"t": 0, "s": v}
    if isinstance(v, str):
        return {"t": 1, "s": v}
    if isinstance(v, list):
        return {"t": 9, "l": len(v), "a": [_seroval_node(x) for x in v]}
    raise TypeError(f"官网参数不支持的类型: {type(v)}")


# ---------- seroval 流解析（响应） ----------
class _SerovalParser:
    """seroval 流求值：;0x<hex>;JS 表达式，$R[n]=引用。支持对象/数组/字符串/
    数字/布尔/null/new Date/$R 引用。"""

    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.refs = {}

    def _ws(self):
        while self.pos < len(self.text) and self.text[self.pos] in " \t\n\r":
            self.pos += 1

    def parse(self):
        # 找主结果引用：$R["server-fn:0"] 或 $R[0]（数字键）
        self.pos = 0
        m = re.search(r'\$R\[(\d+)\]=\[', self.text)
        root = int(m.group(1)) if m else 0
        if root not in self.refs:
            # 定位 root 赋值位置并递归求值
            self.pos = 0
            i = self.text.find("$R[%d]=" % root)
            if i < 0:
                return None
            self.pos = i + len("$R[%d]=" % root)
            self.refs[root] = self._value()
        return self.refs.get(root)

    def _value(self):
        self._ws()
        t = self.text
        if self.pos >= len(t):
            return None
        c = t[self.pos]
        if c == "{":
            return self._object()
        if c == "[":
            return self._array()
        if c == '"':
            return self._string()
        if t.startswith("new Date(", self.pos):
            self.pos += len("new Date(")
            v = self._string()
            self._ws()
            if self.pos < len(t) and t[self.pos] == ")":
                self.pos += 1
            return v
        if t.startswith("!0", self.pos):
            self.pos += 2
            return True
        if t.startswith("!1", self.pos):
            self.pos += 2
            return False
        if t.startswith("null", self.pos):
            self.pos += 4
            return None
        if t.startswith("undefined", self.pos):
            self.pos += 9
            return None
        if c == "$":
            m = re.match(r"\$R\[(\d+)\]=", t[self.pos:])
            if m:
                n = int(m.group(1))
                if n not in self.refs:
                    self.pos += m.end()
                    self.refs[n] = self._value()  # 递归求值嵌套定义
                else:
                    m2 = re.match(r"\$R\[(\d+)\]", t[self.pos:])
                    if m2:
                        self.pos += m2.end()
                return self.refs.get(n)
            m2 = re.match(r"\$R\[(\d+|\"[^\"]*\")\]", t[self.pos:])
            if m2:
                self.pos += m2.end()
                key = m2.group(1)
                key = int(key) if key.isdigit() else key
                return self.refs.get(key)
        m = re.match(r"-?\d+(\.\d+)?", t[self.pos:])
        if m:
            self.pos += m.end()
            return float(m.group(0)) if "." in m.group(0) else int(m.group(0))
        # 未知 token：跳过到分隔符（至少推进 1 字符防死循环）
        while self.pos < len(t) and t[self.pos] not in ",}])":
            self.pos += 1
        if self.pos >= len(t):
            return None
        self.pos += 1
        return None

    def _string(self):
        t = self.text
        self.pos += 1
        out = []
        while self.pos < len(t):
            c = t[self.pos]
            if c == "\\":
                out.append(t[self.pos + 1])
                self.pos += 2
                continue
            if c == '"':
                self.pos += 1
                break
            out.append(c)
            self.pos += 1
        return "".join(out)

    def _array(self):
        t = self.text
        self.pos += 1
        out = []
        while True:
            self._ws()
            if self.pos >= len(t):
                break
            if t[self.pos] == "]":
                self.pos += 1
                break
            out.append(self._value())
            self._ws()
            if self.pos < len(t) and t[self.pos] == ",":
                self.pos += 1
        return out

    def _object(self):
        t = self.text
        self.pos += 1
        obj = {}
        while True:
            self._ws()
            if self.pos >= len(t):
                break
            if t[self.pos] == "}":
                self.pos += 1
                break
            if t[self.pos] == '"':
                key = self._string()
            else:
                m = re.match(r"[A-Za-z_$][A-Za-z0-9_$]*", t[self.pos:])
                key = m.group(0) if m else ""
                self.pos += max(len(key), 1)  # 强制推进防死循环
            self._ws()
            if self.pos < len(t) and t[self.pos] == ":":
                self.pos += 1
            obj[key] = self._value()
            self._ws()
            if self.pos < len(t) and t[self.pos] == ",":
                self.pos += 1
        return obj


def _parse_stream(raw: bytes) -> list[dict]:
    """seroval 流 → 记录列表。"""
    text = raw.decode("utf-8", errors="replace")
    try:
        value = _SerovalParser(text).parse()
    except Exception:
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        out = []
        for key in ("usage", "keys"):
            v = value.get(key)
            if isinstance(v, list):
                out.extend(x for x in v if isinstance(x, dict))
        return out
    return []


# ---------- 一键登录（OAuth 本地回调 → auth cookie） ----------
def _oauth_callback(code: str, state: str | None) -> str:
    """模拟浏览器回调 opencode.ai/auth/callback，提取 Set-Cookie 里的 auth 值。"""
    import http.client
    conn = http.client.HTTPSConnection("opencode.ai", timeout=20)
    path = f"/auth/callback?code={code}"
    if state:
        path += f"&state={state}"
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read().decode("utf-8", errors="replace")[:300]
    headers = resp.getheaders()
    conn.close()
    if resp.status != 200:
        raise CloudError("auth", f"官网回调失败 HTTP {resp.status}: {body}")
    for k, v in headers:
        if k.lower() == "set-cookie":
            m = re.search(r"auth=([^;]+)", v)
            if m:
                return m.group(1)
    raise CloudError("auth", f"回调未返回 cookie（HTTP {resp.status} {body[:100]}）")


_OAUTH_SERVER = None
_OAUTH_PORT = 8899
_OAUTH_RESULTS: dict = {}
_OAUTH_LAST: dict = {}   # state → code（任何回调都记录，旧标签页也能完成）


def _ensure_oauth_server() -> int:
    """启动常驻回调服务（软件运行期间只起一次），返回端口。"""
    import http.server
    import threading
    import urllib.parse

    global _OAUTH_SERVER, _OAUTH_PORT
    if _OAUTH_SERVER is not None:
        return _OAUTH_PORT

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            state = params.get("state", [None])[0]
            code = params.get("code", [None])[0]
            if code:
                _OAUTH_LAST["any"] = code  # 宽容：任何授权页的 code 都记
            if state:
                _OAUTH_RESULTS[state] = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h1>登录成功，可以关闭此页面</h1>".encode("utf-8"))

        def log_message(self, *args):
            pass

    for port in range(_OAUTH_PORT, _OAUTH_PORT + 10):
        try:
            srv = http.server.HTTPServer(("127.0.0.1", port), _Handler)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            _OAUTH_SERVER = srv
            _OAUTH_PORT = port
            return port
        except OSError:
            continue
    raise CloudError("auth", "无法启动本地回调服务")


def start_oauth_login(timeout: int = 180) -> str:
    """一键登录：常驻回调服务 + 浏览器授权 → 返回 auth cookie 值。

    授权页在 Chrome/Edge 打开，用户登录/授权后自动跳回本地回调端口，
    收到 code 后模拟官网回调换取 auth cookie。
    """
    import random
    import string
    import subprocess
    import time

    port = _ensure_oauth_server()
    state = "oc_" + datetime.datetime.now().strftime("%H%M%S%f") + "".join(
        random.choices(string.ascii_lowercase, k=4))
    _OAUTH_RESULTS.pop(state, None)
    auth_url = (
        "https://auth.opencode.ai/authorize?client_id=app"
        f"&redirect_uri=http%3A%2F%2F127.0.0.1%3A{port}%2Fcallback"
        f"&response_type=code&state={state}"
    )
    from src import chrome_cdp
    browser, _ = chrome_cdp._find_browser()
    if browser:
        subprocess.Popen([browser, auth_url])
    else:
        import webbrowser
        webbrowser.open(auth_url)
    _OAUTH_LAST.pop("any", None)
    deadline = time.time() + timeout
    code = None
    while time.time() < deadline:
        if state in _OAUTH_RESULTS and _OAUTH_RESULTS[state] is not None:
            code = _OAUTH_RESULTS[state]
            break
        if _OAUTH_LAST.get("any"):  # 旧标签页授权也会完成
            code = _OAUTH_LAST["any"]
            break
        time.sleep(0.5)
    if not code:
        raise CloudError("auth", "登录超时或未完成，请重试")
    return _oauth_callback(code, state)


# ---------- 代理（Windows 系统代理：Sakuracat 等工具开启时自动走） ----------
_OPENER = None


def _opener():
    """构建带 Windows 系统代理的 opener（缓存复用）。直连不可用时官网必须走代理。"""
    global _OPENER
    if _OPENER is not None:
        return _OPENER
    handlers = []
    if sys.platform == "win32":
        try:
            import winreg
            k = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
            try:
                enabled, _ = winreg.QueryValueEx(k, "ProxyEnable")
                server, _ = winreg.QueryValueEx(k, "ProxyServer")
            finally:
                winreg.CloseKey(k)
            if enabled and server:
                proxy = "http://" + server
                handlers.append(urllib.request.ProxyHandler(
                    {"http": proxy, "https": proxy}))
        except OSError:
            pass
    _OPENER = urllib.request.build_opener(*handlers)
    return _OPENER


# ---------- RPC ----------
def _rpc(fn_id: str, args: list, cookie: str) -> object:
    """调用官网 server function。

    协议（2026-08-12 逆向确认）：
    - 无参函数：POST 无 body（带 body 会 500）
    - 带参函数：body = {"t": <seroval树>, "f": 31, "m": []}
    - 响应：seroval 流，_parse_stream 提取记录
    """
    headers = {
        "X-Server-Id": fn_id,
        "X-Server-Instance": "server-fn:0",
        "Cookie": cookie,
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/workspace",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    if args:
        body = {"t": _seroval_node(args), "f": FEATURES, "m": []}
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    else:
        data = None
    req = urllib.request.Request(f"{BASE_URL}/_server?id={fn_id}", data=data,
                                 method="POST", headers=headers)
    try:
        with _opener().open(req, timeout=20) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403) or (e.code == 302):
            raise CloudError("auth", "未登录或 cookie 已过期，请在官网重新登录后更新 cookie")
        if e.code >= 500:
            raise CloudError("server", f"官网服务异常（HTTP {e.code}），请稍后重试")
        raise CloudError("server", f"官网返回错误（HTTP {e.code}）")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise CloudError("network", f"无法连接官网：{e.reason if hasattr(e, 'reason') else e}")
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _parse_stream(raw)


def fetch_workspace_id(cookie: str) -> str | None:
    """用登录 cookie 查用户第一个 workspace id（一键登录后自动填入）。"""
    data = _rpc(FN_WORKSPACES, [], cookie)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0].get("id")
    return None


def fetch_costs(workspace_id: str, cookie: str, year: int, month: int,
                tz_offset: str | None = None) -> dict:
    """按月拉取费用（getCosts）。month 0-based（JS Date）。返回 {usage, keys}。"""
    tz = tz_offset or tz_offset_str()
    data = _rpc(FN_COSTS, [workspace_id, year, month, tz], cookie)
    if isinstance(data, dict) and "usage" in data:
        return data
    if isinstance(data, list):
        return {"usage": [r for r in data if isinstance(r, dict) and "date" in r],
                "keys": [r for r in data if isinstance(r, dict) and "displayName" in r]}
    raise CloudError("parse", "官网返回数据格式异常")


def fetch_usages(workspace_id: str, cookie: str, page: int = 0) -> list:
    """拉取用量明细（usage.list，每页 50 条）。"""
    data = _rpc(FN_USAGES, [workspace_id, page], cookie)
    if not isinstance(data, list):
        raise CloudError("parse", "官网返回数据格式异常")
    return data


def month_costs(workspace_id: str, cookie: str, months: int = 2) -> dict[str, dict]:
    """拉取最近 N 个月费用，按天聚合。

    返回 {"YYYY-MM-DD": {"total": 美元, "by_model": {模型名: 美元}}}。
    """
    _month_start(months)  # 校验范围参数
    today = datetime.date.today()
    result: dict[str, dict] = {}
    for i in range(months):
        y, m = (today.year, today.month - i)
        while m <= 0:
            y -= 1
            m += 12
        data = fetch_costs(workspace_id, cookie, y, m - 1, None)  # 0-based
        if not isinstance(data.get("usage"), list):
            raise CloudError("parse", "官网费用数据格式异常")
        for row in data.get("usage", []):
            if not isinstance(row, dict):
                raise CloudError("parse", "官网费用数据格式异常")
            day = row.get("date")
            raw_cost = row.get("totalCost") or 0
            if type(raw_cost) not in (int, float) or not math.isfinite(raw_cost) or raw_cost < 0:
                raise CloudError("parse", "官网费用数据格式异常")
            cost_usd = raw_cost / 1e8
            model = row.get("model") or "(未知)"
            if not day:
                continue
            if not valid_day(day):
                raise CloudError("parse", "官网费用日期格式异常")
            entry = result.setdefault(day, {"total": 0.0, "by_model": {}})
            entry["total"] += cost_usd
            entry["by_model"][model] = entry["by_model"].get(model, 0.0) + cost_usd
    return result


def month_tokens(workspace_id: str, cookie: str, months: int = 2,
                 max_pages: int = 300, first_id: str | None = None) -> dict[str, dict]:
    """串行分页拉取官网 usage.list，按天聚合 token（本地时区归日）。

    first_id：上次同步的最新记录 id（page 0 第一条）。新数据都在 page 0 前几页，
    遇到 first_id 即停止（增量，秒级）；None 表示首次全量。
    返回按天聚合 dict，并含 "first_id"（本次最新记录 id，供下次增量）。
    官网是账户级（含所有客户端/API key），本地 db 只是单机 CLI——以此为准。
    """
    import time
    months_ago = _month_start(months)
    if type(max_pages) is not int or max_pages < 1:
        raise CloudError("config", "分页上限必须为正整数")
    result: dict = {"first_id": None, "_incremental": False}
    rows_total = 0
    stop = False
    seen = set()
    for page in range(max_pages):
        rows = None
        for _try in range(3):
            try:
                rows = fetch_usages(workspace_id, cookie, page)
                break
            except CloudError as e:
                if e.kind != "network" or _try == 2:
                    raise
                time.sleep(1)
        if not rows:
            stop = True
            break
        for row in rows:
            if not isinstance(row, dict):
                raise CloudError("parse", "官网明细数据格式异常")
            if result["first_id"] is None:
                result["first_id"] = row.get("id")  # 本次最新记录
            if first_id and row.get("id") == first_id:
                result["_incremental"] = True
                stop = True
                break
            record_id = row.get("id")
            if record_id is not None and not isinstance(record_id, str):
                raise CloudError("parse", "官网明细记录标记格式异常")
            if record_id:
                if record_id in seen:
                    continue
                seen.add(record_id)
            dt = _parse_time(row.get("timeCreated"))
            if dt is None:
                raise CloudError("parse", "官网明细时间格式异常")
            day = dt.date()
            if day < months_ago:
                stop = True
                break
            rows_total += 1
            key = day.isoformat()
            numbers = {field: row.get(field) or 0 for field in (
                "inputTokens", "outputTokens", "cacheReadTokens", "cacheWrite5mTokens",
                "cacheWrite1hTokens", "reasoningTokens")}
            if any(type(value) is not int or value < 0 for value in numbers.values()):
                raise CloudError("parse", "官网 token 数据格式异常")
            entry = result.setdefault(key, {"input": 0, "output": 0,
                                            "cache_read": 0, "cache_write": 0,
                                            "reasoning": 0, "requests": 0})
            entry["input"] += numbers["inputTokens"]
            entry["output"] += numbers["outputTokens"]
            entry["cache_read"] += numbers["cacheReadTokens"]
            entry["cache_write"] += numbers["cacheWrite5mTokens"] + numbers["cacheWrite1hTokens"]
            entry["reasoning"] += numbers["reasoningTokens"]
            entry["requests"] += 1
            if not valid_stats(entry):
                raise CloudError("parse", "官网 token 数据格式异常")
        if stop:
            break
    if not stop:
        raise CloudError("server", "官网明细超过分页上限，本次未更新缓存，请缩小同步范围")
    result["_rows"] = rows_total
    return result


def sync_month(workspace_id: str, cookie: str, months: int = 2) -> dict:
    """串行同步并提交完整结果，避免同时刷新重复累加和写缓存竞态。"""
    with _sync_lock:
        return _sync_month(workspace_id, cookie, months)


def _sync_month(workspace_id: str, cookie: str, months: int) -> dict:
    old = load_cloud_cache()
    if old.get("schema") != CLOUD_CACHE_SCHEMA or old.get("workspace_id") != workspace_id:
        old = {"by_day": {}}
    old_by_day = old.get("by_day", {})
    old_first_id = old.get("first_id")

    costs = month_costs(workspace_id, cookie, months=months)
    tokens = month_tokens(workspace_id, cookie, months=months,
                          first_id=old_first_id)
    new_first_id = tokens.pop("first_id", None) or old_first_id
    tokens.pop("_rows", None)
    incremental = tokens.pop("_incremental", False)
    start = _month_start(months).isoformat()

    # 日期并集：零费用的请求也有 token；全量重建只覆盖当前范围，保留更早历史。
    by_day: dict = {}
    for day in old_by_day.keys() | costs.keys() | tokens.keys():
        old_entry = old_by_day.get(day, {})
        cost_entry = costs.get(day, old_entry)
        new_t = tokens.get(day, {})
        old_t = old_entry.get("tokens", {})
        if incremental:
            merged_t = {k: old_t.get(k, 0) + new_t.get(k, 0) for k in TOKEN_FIELDS}
        elif day >= start:
            merged_t = dict(new_t)
        else:
            merged_t = dict(old_t)
        by_day[day] = {"total": cost_entry.get("total", 0.0),
                       "by_model": dict(cost_entry.get("by_model", {})), "tokens": merged_t}
    try:
        save_cloud_cache(by_day, first_id=new_first_id, workspace_id=workspace_id)
    except OSError as e:
        raise CloudError("cache", f"无法保存官网缓存: {e}") from e
    return {"by_day": by_day,
            "last_sync": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}


# ---------- 缓存 ----------
def get_cloud_cache_path():
    return config.get_data_dir() / "monitor_cloud.json"


def load_cloud_cache():
    """读缓存。返回 {"by_day": {...}, "last_sync": str|None}，损坏/缺失返回空结构。"""
    try:
        with open(get_cloud_cache_path(), encoding="utf-8") as f:
            data = json.load(f)
        if (isinstance(data, dict) and data.get("schema") in (1, 2, 3, 4, CLOUD_CACHE_SCHEMA)
                and isinstance(data.get("by_day"), dict)
                and all(data.get(key) is None or isinstance(data[key], str)
                        for key in ("last_sync", "first_id", "workspace_id"))
                and all(valid_day(day) and _valid_cloud_entry(entry)
                        for day, entry in data["by_day"].items())):
            data.setdefault("last_sync", None)
            return data
    except (OSError, ValueError):
        pass
    return {"by_day": {}, "last_sync": None}


def _valid_cloud_entry(entry) -> bool:
    if not isinstance(entry, dict) or not valid_stats({"cost": entry.get("total")}):
        return False
    models = entry.get("by_model", {})
    return (isinstance(models, dict)
            and all(isinstance(model, str) and valid_stats({"cost": cost})
                    for model, cost in models.items())
            and valid_stats(entry.get("tokens", {})))


def save_cloud_cache(by_day: dict, first_id: str | None = None,
                     workspace_id: str | None = None) -> None:
    """原子写缓存。"""
    data = {
        "schema": CLOUD_CACHE_SCHEMA,
        "last_sync": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "first_id": first_id,
        "workspace_id": workspace_id,
        "by_day": by_day,
    }
    save_cache(get_cloud_cache_path(), data)
