# -*- coding: utf-8 -*-
"""本机管理页 + 机器 API。页面是旁边两个 html，接口给服务器读写用。"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs

from 池 import 国名表, 池, 版本, 洗国库, 默随机国库

日志 = logging.getLogger("xui桥")
旁 = Path(__file__).resolve().parent


def _读页(名: str, 垫: str) -> str:
    p = 旁 / 名
    if (not p.is_file()) or p.stat().st_size < 20:
        try:
            from 更新 import 补一个
            补一个(名)
        except Exception as 错:
            日志.warning("补 %s 失败：%s", 名, 错)
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return 垫


页 = _读页("面板.html", "<!DOCTYPE html><meta charset=utf-8><title>桥</title><p>缺 面板.html，重新跑一次更新。")
登页 = _读页("登录.html", "<!DOCTYPE html><meta charset=utf-8><title>登录</title><p>缺 登录.html")
对接文 = _读页("对接.md", "# 缺 对接.md，重新跑一次更新。")

_饼干名 = "xui_bridge"

接口表 = (
    {"method": "GET", "path": "/api", "desc": "接口目录、鉴权和全部字段说明"},
    {"method": "GET", "path": "/api/docs", "desc": "对接文档 Markdown，和 /docs 同一份"},
    {"method": "GET", "path": "/docs", "desc": "对接文档网页，无需登录"},
    {"method": "GET", "path": "/api/health", "desc": "轻量探活：版本、监听、健康数。不含密钥"},
    {"method": "GET", "path": "/api/status", "desc": "完整状态，含池和设置。兼容旧字段 proxies"},
    {"method": "GET", "path": "/api/config", "desc": "只读当前设置，不含整池"},
    {"method": "GET", "path": "/api/pool", "desc": "只读代理池"},
    {"method": "GET", "path": "/api/regions", "desc": "当前随机国库"},
    {"method": "POST", "path": "/api/regions", "desc": "整表替换随机国库",
     "body": {"地区": ["JP", "KR", "SG"]}},
    {"method": "POST", "path": "/api/regions/add", "desc": "往随机库加国家",
     "body": {"码": "TW"}},
    {"method": "POST", "path": "/api/regions/del", "desc": "从随机库去掉国家",
     "body": {"码": "TW"}},
    {"method": "GET", "path": "/api/panel", "desc": "同机 X-UI 面板地址，无需登录"},
    {"method": "POST", "path": "/api/set", "desc": "改设置，只改传入的字段。返回最新 config",
     "body": {"sc_cntry": "JP", "pool_size": 30, "auto_rotate": 300}},
    {"method": "POST", "path": "/api/fill", "desc": "按目标条数补池"},
    {"method": "POST", "path": "/api/rotate", "desc": "丢掉拉取来的代理，按当前地区重新提一批"},
    {"method": "POST", "path": "/api/add", "desc": "手动加代理。串=多行文本，或 proxies=数组",
     "body": {"proxies": ["socks5://user:pass@1.2.3.4:1080"]}},
    {"method": "POST", "path": "/api/del", "desc": "按号删一条", "body": {"id": "…"}},
    {"method": "POST", "path": "/api/clear", "desc": "清空整池"},
    {"method": "POST", "path": "/api/sc/setup", "desc": "写入提取源并自动开跑",
     "body": {"provider": "auto", "key": "闪臣key", "code": "安全码", "go_key": ""}},
    {"method": "POST", "path": "/api/sc/white", "desc": "把本机或指定 IP 加进闪臣白名单",
     "body": {"ip": "", "备注": "xui-bridge"}},
    {"method": "POST", "path": "/api/sc/unwhite", "desc": "从白名单删除", "body": {"id": "", "ip": ""}},
    {"method": "POST", "path": "/api/sc/refresh", "desc": "刷新余额和白名单"},
    {"method": "POST", "path": "/api/update", "desc": "立刻检查并更新桥代码"},
    {"method": "GET", "path": "/api/stats", "desc": "每日流量：今日消耗 + 最近 60 天表"},
    {"method": "POST", "path": "/api/traffic/reset", "desc": "累计流量从现在重新算（日表保留）"},
    {"method": "POST", "path": "/api/passwd", "desc": "改管理密码", "body": {"web_pass": "新密码"}},
    {"method": "POST", "path": "/api/login", "desc": "网页登录，种 Cookie"},
    {"method": "POST", "path": "/api/logout", "desc": "清 Cookie"},
)


def 接口目录() -> dict:
    return {
        "ok": True,
        "版本": 版本,
        "文档": "/docs",
        "文档原文": "/api/docs",
        "鉴权": {
            "方式": [
                "Authorization: Bearer <web_pass>",
                "X-Pass: <web_pass>",
                "Cookie（网页登录后）",
            ],
            "说明": "机器调用用前两种。不要把密码写进 URL。",
            "免鉴权": ["GET /", "GET /docs", "GET /login", "GET /api/panel",
                      "GET /api/docs", "POST /api/login", "POST /api/logout", "OPTIONS /api/*"],
        },
        "接口": [dict(一) for 一 in 接口表],
        "字段": {
            "health": ["版本", "listen", "web", "健康", "总数", "供应商", "这批地区", "上次补", "上次换新"],
            "池条目": ["号", "地址", "方案", "来源", "启用", "健康", "失败", "连接",
                      "上行", "下行", "上行文", "下行文", "出口", "上次错误", "上次切换"],
            "日表条目": ["日", "上行", "下行", "合计", "上行文", "下行文", "合计文"],
            "可写": ["mode", "sticky", "fetch_url", "fetch_cmd", "fetch_scheme",
                    "sc_base", "sc_key", "sc_protocol", "sc_cntry", "sc_state", "sc_city",
                    "provider", "go_base", "go_key", "go_url", "go_user", "go_host",
                    "pool_size", "fail_n", "check_interval", "check_conc", "connect_timeout",
                    "auto_rotate", "sc_count", "sc_time", "sc_white", "go_port",
                    "auto_update", "update_minutes", "sc_code", "go_pass", "随机国库"],
            "出厂随机国库": list(默随机国库),
            "国名": dict(国名表),
        },
    }


def 健康视图(池子: 池) -> dict:
    return {
        "ok": True,
        "版本": 版本,
        "listen": f"{池子.设['listen']}:{池子.听口()}",
        "web": f"{池子.设['web']}:{池子.网页口()}",
        "健康": len(池子.健康们()),
        "总数": len(池子.条们),
        "供应商": 池子.当前源() or "无",
        "这批地区": 池子.这批地区,
        "上次补": 池子.上次补,
        "上次换新": 池子.上次换新,
    }


def 池视图(池子: 池) -> dict:
    return {
        "ok": True,
        "健康": len(池子.健康们()),
        "总数": len(池子.条们),
        "这批地区": 池子.这批地区,
        "池": [一.快照() for 一 in 池子.条们],
    }


def 地区视图(池子: 池 | None = None) -> dict:
    库 = 池子.国库() if 池子 else list(默随机国库)
    return {
        "ok": True,
        "随机国库": 库,
        "地区": [{"码": 码, "名": 国名表.get(码, 码)} for 码 in 库],
        "名": dict(国名表),
        "默认": list(默随机国库),
    }


def _请国(数据: dict) -> list[str]:
    生 = []
    for k in ("码", "code", "国", "codes", "地区", "随机国库"):
        if 数据.get(k) in (None, ""):
            continue
        v = 数据[k]
        if isinstance(v, list):
            生.extend(v)
        else:
            生.extend(str(v).replace(",", " ").split())
    return 洗国库(生)


def _加行(数据: dict) -> list[str]:
    行们: list[str] = []
    串 = 数据.get("串")
    if 串:
        行们.extend(str(串).splitlines())
    列 = 数据.get("proxies")
    if isinstance(列, str):
        行们.extend(列.splitlines())
    elif isinstance(列, list):
        for 一 in 列:
            if 一:
                行们.append(str(一))
    return [x.strip() for x in 行们 if str(x).strip()]


def _密(池子: 池) -> str:
    return str(池子.设.get("web_pass") or "").strip()


def _令牌(密: str) -> str:
    return hmac.new(b"xui-bridge-v1", 密.encode("utf-8"), hashlib.sha256).hexdigest()


def _cookie值(头: dict[str, str]) -> str:
    for 一 in (头.get("cookie") or "").split(";"):
        k, _, v = 一.strip().partition("=")
        if k == _饼干名:
            return v.strip()
    return ""


def _信里密(头: dict[str, str], 体: dict) -> str:
    授 = (头.get("authorization") or "").strip()
    if 授.lower().startswith("bearer "):
        return 授[7:].strip()
    if 授.lower().startswith("basic "):
        import base64
        try:
            解 = base64.b64decode(授[6:].strip()).decode("utf-8", "replace")
            return 解.split(":", 1)[-1] if ":" in 解 else 解
        except Exception:
            return ""
    return str(头.get("x-pass") or 体.get("pass") or "")


def _同(a: str, b: str) -> bool:
    if not a or not b or len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def 已登录(头: dict[str, str], 体: dict, 密: str) -> bool:
    if not 密:
        return False
    if _同(_cookie值(头), _令牌(密)):
        return True
    给 = _信里密(头, 体).strip()
    return _同(给, 密)


def _跨域() -> str:
    return (
        "Access-Control-Allow-Origin: *\r\n"
        "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
        "Access-Control-Allow-Headers: Authorization, Content-Type, X-Pass\r\n"
        "Access-Control-Max-Age: 86400\r\n"
    )


def _头文(码: int, 类: str, 长: int, 额外: str = "") -> bytes:
    说 = {200: "OK", 204: "No Content", 400: "Bad Request", 401: "Unauthorized",
          403: "Forbidden", 404: "Not Found", 500: "ERR"}.get(码, "ERR")
    return (
        f"HTTP/1.1 {码} {说}\r\n"
        f"Content-Type: {类}\r\n"
        "Cache-Control: no-store\r\n"
        f"Content-Length: {长}\r\n"
        f"{_跨域()}"
        f"{额外}"
        "Connection: close\r\n\r\n"
    ).encode("ascii")


def _json(写: asyncio.StreamWriter, 码: int, 身: dict, 额外: str = "") -> None:
    文 = json.dumps(身, ensure_ascii=False).encode("utf-8")
    写.write(_头文(码, "application/json; charset=utf-8", len(文), 额外) + 文)


def _空(写: asyncio.StreamWriter, 码: int = 204) -> None:
    写.write(_头文(码, "text/plain", 0))


def _html(写: asyncio.StreamWriter, 文: str) -> None:
    体 = 文.encode("utf-8")
    写.write(_头文(200, "text/html; charset=utf-8", len(体)) + 体)


def _裸(写: asyncio.StreamWriter, 类: str, 文: str) -> None:
    体 = 文.encode("utf-8")
    写.write(_头文(200, 类, len(体)) + 体)


def _转义(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _md页(源: str) -> str:
    """只认标题、表格、围栏代码、列表。别的当段落，避免引第三方库。"""
    块: list[str] = []
    行们 = 源.replace("\r\n", "\n").split("\n")
    i, n = 0, len(行们)
    while i < n:
        行 = 行们[i]
        if 行.startswith("```"):
            j = i + 1
            while j < n and not 行们[j].startswith("```"):
                j += 1
            块.append("<pre><code>" + _转义("\n".join(行们[i + 1:j])) + "</code></pre>")
            i = j + 1
            continue
        if 行.startswith("#"):
            级 = min(3, len(行) - len(行.lstrip("#")))
            块.append(f"<h{级}>{_转义(行.lstrip('#').strip())}</h{级}>")
            i += 1
            continue
        if 行.startswith("|") and i + 1 < n and set(行们[i + 1].replace("|", "").replace("-", "").replace(":", "").strip()) <= {"", " "}:
            表 = []
            while i < n and 行们[i].startswith("|"):
                格 = [c.strip() for c in 行们[i].strip("|").split("|")]
                if not all(set(x.replace("-", "").replace(":", "")) <= {""} for x in 格):
                    表.append(格)
                i += 1
            if 表:
                头, *身 = 表
                h = "<table><thead><tr>" + "".join(f"<th>{_转义(x)}</th>" for x in 头) + "</tr></thead><tbody>"
                for 一 in 身:
                    h += "<tr>" + "".join(f"<td>{_转义(x)}</td>" for x in 一) + "</tr>"
                块.append(h + "</tbody></table>")
            continue
        if 行.startswith("- ") or 行.startswith("* "):
            项 = []
            while i < n and (行们[i].startswith("- ") or 行们[i].startswith("* ")):
                项.append(行们[i][2:])
                i += 1
            块.append("<ul>" + "".join(f"<li>{_转义(x)}</li>" for x in 项) + "</ul>")
            continue
        if 行.strip() == "---":
            块.append("<hr>")
            i += 1
            continue
        if 行.strip():
            块.append("<p>" + _转义(行) + "</p>")
        i += 1
    身 = "\n".join(块)
    return (
        "<!DOCTYPE html><html lang=zh-CN><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width, initial-scale=1'>"
        "<title>桥对接文档</title><style>"
        "body{margin:0;background:#0b1016;color:#e7eef6;"
        "font:15px/1.55 'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif}"
        "main{max-width:980px;margin:0 auto;padding:28px 22px 72px}"
        "h1{font-size:28px;margin:0 0 8px} h2{margin:28px 0 10px;font-size:20px}"
        "h3{margin:22px 0 8px;font-size:16px}"
        "p,li{color:#c6d4e4} a{color:#3d9cf0}"
        "table{width:100%;border-collapse:collapse;margin:10px 0 18px;font-size:13px}"
        "th,td{border:1px solid #243041;padding:7px 8px;text-align:left;vertical-align:top}"
        "th{color:#8b9bb0;font-weight:600}"
        "pre{background:#0d141c;border:1px solid #243041;border-radius:8px;"
        "padding:12px;overflow:auto;font:12px/1.5 ui-monospace,Consolas,monospace}"
        "hr{border:0;border-top:1px solid #243041;margin:22px 0}"
        ".top{display:flex;gap:12px;align-items:center;margin-bottom:18px}"
        ".top a{color:#e7eef6;text-decoration:none;border:1px solid #243041;"
        "border-radius:8px;padding:6px 10px}"
        "</style></head><body><main>"
        "<div class=top><a href=/>控制台</a><a href=/api/docs>原文 Markdown</a></div>"
        f"{身}</main></body></html>"
    )


def _置饼(密: str) -> str:
    return (
        f"Set-Cookie: {_饼干名}={_令牌(密)}; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800\r\n"
    )


def _清饼() -> str:
    return f"Set-Cookie: {_饼干名}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0\r\n"


_面板缓存: dict = {"t": 0.0, "port": "", "path": "/", "https": False}
_库们 = (
    "/etc/x-ui/x-ui.db",
    "/etc/x-ui-yg/x-ui-yg.db",
    "/usr/local/x-ui/x-ui.db",
)


def _请求主机(头: dict[str, str]) -> str:
    主 = (头.get("x-forwarded-host") or 头.get("host") or "").split(",")[0].strip()
    if 主.startswith("["):
        主 = 主.split("]", 1)[0].lstrip("[")
    elif 主.count(":") == 1:
        主 = 主.rsplit(":", 1)[0]
    if 主 in ("", "0.0.0.0", "127.0.0.1", "localhost", "::", "::1"):
        for p in ("/usr/local/x-ui/xip",):
            try:
                行 = Path(p).read_text(encoding="utf-8").splitlines()
                if 行 and 行[0].strip():
                    return 行[0].strip()
            except Exception:
                pass
    return 主


def _读面板() -> tuple[str, str, bool]:
    now = time.time()
    if now - float(_面板缓存["t"]) < 30 and _面板缓存["port"]:
        return str(_面板缓存["port"]), str(_面板缓存["path"]), bool(_面板缓存["https"])
    port, path, https = "", "/", Path("/root/ygkkkca/cert.crt").is_file() or Path("/root/ygkkkca/ca.log").is_file()
    for p in _库们:
        if not os.path.isfile(p):
            continue
        try:
            con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            try:
                表 = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                tbl = "settings" if "settings" in 表 else ("setting" if "setting" in 表 else "")
                if not tbl:
                    continue
                kv = {str(k): ("" if v is None else str(v)) for k, v in con.execute(f"SELECT key, value FROM {tbl}")}
            finally:
                con.close()
        except Exception:
            continue
        port = kv.get("webPort") or kv.get("port") or port
        path = kv.get("webBasePath") or kv.get("basePath") or path
        cert = kv.get("webCertFile") or kv.get("cert") or ""
        if cert and os.path.isfile(cert):
            https = True
        if str(port).isdigit():
            break
    if not str(port).isdigit():
        try:
            文 = subprocess.check_output(["/usr/local/x-ui/x-ui", "setting", "-show"], text=True, timeout=5)
        except Exception:
            文 = ""
        for 行 in 文.replace("\r", "\n").split("\n"):
            low = 行.lower()
            if "webbase" in low or "path" in low:
                词 = 行.split()
                if 词:
                    path = 词[-1]
            elif "port" in low:
                for 词 in reversed(行.replace(":", " ").split()):
                    if 词.isdigit():
                        port = 词
                        break
    if not str(path).startswith("/"):
        path = "/" + str(path).lstrip("/")
    _面板缓存.update({"t": now, "port": str(port), "path": path, "https": https})
    return str(port), path, https


def 面板地址(头: dict[str, str]) -> str:
    主 = _请求主机(头)
    port, path, https = _读面板()
    if not 主 or not str(port).isdigit():
        return ""
    if path == "/":
        path = ""
    return f"{'https' if https else 'http'}://{主}:{port}{path}"


async def _读请求(读: asyncio.StreamReader) -> tuple[str, str, bytes, dict[str, str]]:
    头 = b""
    while b"\r\n\r\n" not in 头:
        块 = await 读.read(1024)
        if not 块:
            break
        头 += 块
        if len(头) > 65536:
            break
    行, _, 其余 = 头.partition(b"\r\n")
    部, _, 体0 = 其余.partition(b"\r\n\r\n")
    首 = 行.decode("ascii", "replace").split()
    法 = 首[0] if 首 else "GET"
    路 = 首[1] if len(首) > 1 else "/"
    头们: dict[str, str] = {}
    长 = 0
    for 一 in 部.split(b"\r\n"):
        if b":" not in 一:
            continue
        k, v = 一.split(b":", 1)
        名 = k.decode("ascii", "replace").strip().lower()
        值 = v.decode("latin-1", "replace").strip()
        头们[名] = 值
        if 名 == "content-length":
            try:
                长 = int(值)
            except ValueError:
                长 = 0
    体 = 体0
    while len(体) < 长:
        体 += await 读.read(长 - len(体))
    return 法, 路, 体[:长], 头们


def _身(体: bytes) -> dict:
    if not 体:
        return {}
    try:
        数据 = json.loads(体.decode("utf-8"))
        return 数据 if isinstance(数据, dict) else {}
    except Exception:
        q = parse_qs(体.decode("utf-8", "replace"))
        return {k: (v[0] if v else "") for k, v in q.items()}


async def 处理管理(读, 写, 池子: 池) -> None:
    try:
        法, 路, 体, 头 = await _读请求(读)
        路 = 路.split("?", 1)[0].rstrip("/") or "/"
        数据 = _身(体)
        密 = _密(池子)

        if 法 == "OPTIONS" and 路.startswith("/api"):
            _空(写, 204)
        elif 法 == "GET" and 路 == "/api/panel":
            _json(写, 200, {"ok": True, "url": 面板地址(头)})
        elif 法 == "GET" and 路 in ("/", "/index.html"):
            # 页面本身不设门，进不进得去看接口。避免 Cookie 种不上时永远停在登录页。
            _html(写, 页)
        elif 法 == "GET" and 路 == "/login":
            _html(写, 登页)
        elif 法 == "GET" and 路 == "/docs":
            _html(写, _md页(对接文))
        elif 法 == "GET" and 路 == "/api/docs":
            _裸(写, "text/markdown; charset=utf-8", 对接文)
        elif 法 == "POST" and 路 == "/api/login":
            给 = str(数据.get("pass") or "").strip()
            if _同(给, 密):
                _json(写, 200, {"ok": True}, _置饼(密))
            else:
                日志.warning("管理页密码错误")
                _json(写, 403, {"ok": False, "err": "密码不对"})
        elif 法 == "POST" and 路 == "/api/logout":
            _json(写, 200, {"ok": True}, _清饼())
        elif not 已登录(头, 数据, 密):
            _json(写, 401, {"ok": False, "err": "要密码。网页先登录，API 带 X-Pass 或 Authorization: Bearer"})
        elif 法 == "GET" and 路 == "/api":
            _json(写, 200, 接口目录())
        elif 法 == "GET" and 路 == "/api/health":
            _json(写, 200, 健康视图(池子))
        elif 法 == "GET" and 路 == "/api/status":
            身 = 池子.总览()
            身["ok"] = True
            身["panel_url"] = 面板地址(头)
            身["proxies"] = 身.get("池") or []
            _json(写, 200, 身)
        elif 法 == "GET" and 路 == "/api/config":
            身 = 池子.配置快照()
            身["ok"] = True
            _json(写, 200, 身)
        elif 法 == "GET" and 路 == "/api/pool":
            _json(写, 200, 池视图(池子))
        elif 法 == "GET" and 路 == "/api/regions":
            _json(写, 200, 地区视图(池子))
        elif 法 == "POST" and 路 == "/api/regions":
            列 = _请国(数据)
            if not 列:
                _json(写, 400, {"ok": False, "err": "没有有效的国家码"})
            else:
                await 池子.改设({"随机国库": 列})
                身 = 地区视图(池子)
                身["msg"] = "随机国库已换成 " + "、".join(列)
                _json(写, 200, 身)
        elif 法 == "POST" and 路 == "/api/regions/add":
            列 = _请国(数据)
            if not 列:
                _json(写, 400, {"ok": False, "err": "没有有效的国家码，例如 JP"})
            else:
                现, 新 = await 池子.加国(列)
                身 = 地区视图(池子)
                身["msg"] = ("已加入 " + "、".join(新)) if 新 else "这些国家本来就在库里"
                身["新加"] = 新
                _json(写, 200, 身)
        elif 法 == "POST" and 路 == "/api/regions/del":
            列 = _请国(数据)
            if not 列:
                _json(写, 400, {"ok": False, "err": "没有有效的国家码"})
            else:
                现, 删, 说 = await 池子.删国(列)
                if 说:
                    _json(写, 400, {**地区视图(池子), "ok": False, "err": 说})
                else:
                    身 = 地区视图(池子)
                    身["msg"] = ("已去掉 " + "、".join(删)) if 删 else "库里没有这些国家"
                    身["删除"] = 删
                    _json(写, 200, 身)
        elif 法 == "POST" and 路 == "/api/add":
            成, 错们 = 0, []
            for 行 in _加行(数据):
                try:
                    await 池子.加(行, 来源="手加")
                    成 += 1
                except ValueError as 错:
                    错们.append(str(错))
            _json(写, 200, {"ok": True, "n": 成, "err": "；".join(错们), "pool": 池视图(池子)})
        elif 法 == "POST" and 路 == "/api/del":
            号 = str(数据.get("号") or 数据.get("id") or "")
            if not 号:
                _json(写, 400, {"ok": False, "err": "缺少 id"})
            else:
                ok = await 池子.删(号)
                _json(写, 200, {"ok": ok, "id": 号, "pool": 池视图(池子)})
        elif 法 == "POST" and 路 == "/api/clear":
            n = await 池子.清空()
            _json(写, 200, {"ok": True, "n": n})
        elif 法 == "POST" and 路 == "/api/set":
            数据.pop("pass", None)
            数据.pop("web_pass", None)
            await 池子.改设(数据)
            身 = 池子.配置快照()
            身["ok"] = True
            身["msg"] = "已保存"
            _json(写, 200, 身)
        elif 法 == "POST" and 路 == "/api/passwd":
            新 = str(数据.get("web_pass") or 数据.get("新") or "").strip()
            if len(新) < 4:
                _json(写, 400, {"ok": False, "err": "新密码至少 4 位"})
            else:
                await 池子.改设({"web_pass": 新})
                _json(写, 200, {"ok": True, "msg": "密码已改，下次请求用新密码"}, _置饼(新))
        elif 法 == "POST" and 路 == "/api/fill":
            说 = await 池子.补齐()
            _json(写, 200, {"ok": True, "msg": 说, "health": 健康视图(池子)})
        elif 法 == "POST" and 路 == "/api/rotate":
            说 = await 池子.换新()
            _json(写, 200, {"ok": True, "msg": 说, "health": 健康视图(池子)})
        elif 法 == "POST" and 路 == "/api/update":
            from 更新 import 更新一次
            说 = await 更新一次(池子)
            _json(写, 200, {"ok": True, "msg": 说})
        elif 法 == "GET" and 路 == "/api/stats":
            身 = 池子.日统计()
            身["ok"] = True
            _json(写, 200, 身)
        elif 法 == "POST" and 路 == "/api/traffic/reset":
            _json(写, 200, {"ok": True, "msg": await 池子.清流量()})
        elif 法 == "POST" and 路 == "/api/sc/setup":
            步 = await 池子.一键开跑(
                str(数据.get("key") or 数据.get("sc_key") or "").strip(),
                str(数据.get("code") or 数据.get("sc_code") or "").strip(),
                str(数据.get("provider") or "").strip(),
                str(数据.get("go_key") or "").strip(),
                str(数据.get("go_user") or "").strip(),
                str(数据.get("go_pass") or "").strip(),
            )
            _json(写, 200, {"ok": True, "步": 步, "msg": "\n".join(步), "config": 池子.配置快照()})
        elif 法 == "POST" and 路 == "/api/sc/white":
            好, 说 = await asyncio.to_thread(
                池子.加白名单, str(数据.get("ip") or ""),
                str(数据.get("备注") or 数据.get("remark") or "xui-bridge"),
            )
            _json(写, 200, {"ok": True, "好": 好, "msg": 说})
        elif 法 == "POST" and 路 == "/api/sc/unwhite":
            好, 说 = await asyncio.to_thread(
                池子.删白名单, str(数据.get("id") or ""), str(数据.get("ip") or ""),
            )
            _json(写, 200, {"ok": True, "好": 好, "msg": 说})
        elif 法 == "POST" and 路 == "/api/sc/refresh":
            await asyncio.to_thread(池子.刷闪臣)
            _json(写, 200, {"ok": True, "闪臣": 池子.闪臣快照()})
        else:
            _json(写, 404, {"ok": False, "err": "没有这个接口"})
        await 写.drain()
    except Exception as 错:
        日志.warning("管理页：%s", 错)
        try:
            _json(写, 500, {"ok": False, "err": str(错)})
            await 写.drain()
        except Exception:
            pass
    finally:
        try:
            写.close()
            await 写.wait_closed()
        except Exception:
            pass


async def 开网页(池子: 池) -> asyncio.AbstractServer:
    主 = str(池子.设.get("web") or "127.0.0.1")
    口 = 池子.网页口()

    async def _接(读, 写):
        await 处理管理(读, 写, 池子)

    服 = await asyncio.start_server(_接, 主, 口)
    日志.info("管理页 http://%s:%s/", 主, 口)
    return 服
