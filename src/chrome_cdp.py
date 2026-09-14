"""Chrome CDP 读取 cookie（零依赖：socket + 手写 WebSocket 帧）。

用途：一键获取——用户 Chrome 以 --remote-debugging-port 启动后，
通过 CDP Network.getAllCookies 读取 opencode.ai 的 auth cookie（明文）。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import subprocess
import time
import urllib.request

CDP_PORT = 9222
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# ---------- 手写 WebSocket 客户端（RFC6455） ----------
class _WS:
    def __init__(self, host, port, path):
        self._sock = socket.create_connection((host, port), timeout=10)
        self._sock.settimeout(30)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket 握手失败")
            resp += chunk
        if b" 101 " not in resp.split(b"\r\n", 1)[0]:
            raise ConnectionError("WebSocket 握手被拒绝")

    def _send_frame(self, payload: bytes):
        mask = os.urandom(4)
        header = bytearray([0x81])  # text, FIN
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    def _recv_frame(self) -> bytes:
        head = self._recv_exact(2)
        opcode = head[0] & 0x0F
        n = head[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", self._recv_exact(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self._recv_exact(8))[0]
        if head[1] & 0x80:  # masked（服务端不发 mask）
            self._recv_exact(4)
        payload = self._recv_exact(n)
        if opcode == 8:  # close
            raise ConnectionError("连接关闭")
        return payload

    def _recv_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self._sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("连接中断")
            data += chunk
        return data

    def send_json(self, obj: dict):
        self._send_frame(json.dumps(obj).encode("utf-8"))

    def recv_json(self) -> dict:
        return json.loads(self._recv_frame().decode("utf-8"))

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass


# ---------- CDP 操作 ----------
def _find_page_ws() -> str:
    """找 opencode.ai 页面的调试 WebSocket URL（或任意页面）。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=5) as r:
            targets = json.loads(r.read().decode())
        for t in targets:
            if t.get("type") == "page":
                return t["webSocketDebuggerUrl"]
    except Exception:
        pass
    raise ConnectionError("无法连接 Chrome 调试端口")


def get_cookie(host_filter: str = "opencode.ai", name: str = "auth",
               ws_url: str | None = None) -> str | None:
    """通过 CDP 读指定域 cookie（明文）。"""
    url = ws_url or _find_page_ws()
    # ws://127.0.0.1:9222/devtools/page/xxx → path=/devtools/page/xxx
    path = url.split("9222", 1)[-1] if "9222" in url else "/"
    ws = _WS("127.0.0.1", CDP_PORT, path)
    try:
        ws.send_json({"id": 1, "method": "Network.enable"})
        ws.recv_json()
        ws.send_json({"id": 2, "method": "Network.getAllCookies"})
        while True:
            msg = ws.recv_json()
            if msg.get("id") == 2:
                for c in msg.get("result", {}).get("cookies", []):
                    if host_filter in c.get("domain", "") and c.get("name") == name:
                        return c.get("value")
                return None
    finally:
        ws.close()


def chrome_is_running() -> bool:
    """Chrome 调试端口是否可连。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def restart_browser_with_cdp() -> bool:
    """关闭浏览器（Chrome/Edge）并以调试端口重启（恢复上次会话）。返回是否成功。"""
    browser, exe_name = _find_browser()
    if not browser:
        return False
    subprocess.run(["taskkill", "/IM", exe_name, "/F"], capture_output=True)
    time.sleep(1.5)
    subprocess.Popen([
        browser,
        "--remote-debugging-port=9222",
        "--restore-last-session",
        "--no-first-run",
    ])
    for _ in range(30):
        if chrome_is_running():
            return True
        time.sleep(1)
    return False


def _find_browser():
    """返回 (浏览器路径, 进程名)：优先 Chrome，其次 Edge。"""
    candidates = [
        (os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"), "chrome.exe"),
        (os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"), "chrome.exe"),
        (os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"), "chrome.exe"),
        (os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"), "msedge.exe"),
        (os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"), "msedge.exe"),
    ]
    for path, exe in candidates:
        if os.path.isfile(path):
            return path, exe
    return None, None


def _find_chrome() -> str | None:
    browser, _ = _find_browser()
    return browser
