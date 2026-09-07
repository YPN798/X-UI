# -*- coding: utf-8 -*-
"""本机管理页：加减代理池，不经过 X-UI 面板。只听 127.0.0.1。"""

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

from 池 import 池

日志 = logging.getLogger("xui桥")

页 = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>代理池</title>
<style>
:root { --底:#f4f5f7; --板:#fff; --字:#1f2328; --次:#6b727c; --绿:#1a7f37; --红:#cf222e; --蓝:#0969da; --线:#d0d7de; }
*{box-sizing:border-box}
body{margin:0;font:14px/1.45 "Segoe UI","微软雅黑",sans-serif;background:var(--底);color:var(--字)}
main{max-width:920px;margin:24px auto;padding:0 16px}
h1{font-size:20px;margin:0 0 6px}
.次{color:var(--次);margin:0 0 16px}
.卡{background:var(--板);border:1px solid var(--线);border-radius:10px;padding:14px 16px;margin:0 0 14px}
.行{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end}
label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--次)}
input,select,textarea{font:13px/1.4 inherit;padding:7px 9px;border:1px solid var(--线);border-radius:6px;min-width:140px}
textarea{width:100%;min-height:72px}
button{border:0;border-radius:6px;padding:8px 12px;background:var(--蓝);color:#fff;cursor:pointer}
button.灰{background:#57606a}
button.红{background:var(--红)}
a.跳{display:none;float:right;margin-right:8px;text-decoration:none;border-radius:6px;padding:8px 12px;background:#1a7f37;color:#fff}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--线);font-size:13px}
.好{color:var(--绿)} .坏{color:var(--红)}
.徽章{display:inline-block;padding:1px 7px;border-radius:999px;background:#eef2f6;font-size:12px}
</style>
</head>
<body>
<main>
<h1>代理池 <button class="灰" id="退" style="float:right">退出</button><a class="跳" id="去面板" target="_blank" rel="noopener">打开 X-UI 面板</a></h1>
<p class="次">Xray 只连本机 41000。这里改池、换负载，不用重载面板。点绿色按钮进 X-UI。</p>
<div class="卡" id="概"></div>
<div class="卡">
  <form id="设" class="行">
    <label>分发
      <select name="mode">
        <option value="round_robin">按连接轮询</option>
        <option value="least_conn">谁连接少走谁</option>
      </select>
    </label>
    <label>粘住
      <select name="sticky">
        <option value="">关</option>
        <option value="host">按目标主机</option>
      </select>
    </label>
    <label>池目标条数 <input name="pool_size" type="number" min="0" max="64"></label>
    <label>失败几次摘除 <input name="fail_n" type="number" min="1" max="20"></label>
    <label>验活间隔秒 <input name="check_interval" type="number" min="8" max="600"></label>
    <label>fetch_url <input name="fetch_url" placeholder="GET 返回一行代理串" style="min-width:260px"></label>
    <label>fetch_cmd <input name="fetch_cmd" placeholder="命令 stdout 一行" style="min-width:200px"></label>
    <button type="submit">保存设置</button>
    <button type="button" class="灰" id="补">立刻补池</button>
  </form>
</div>
<div class="卡">
  <form id="加">
    <label>加一条（socks5://用户:密码@主机:端口 或 IP|端口|用户|密码，可多行）
      <textarea name="串" placeholder="socks5://user:pass@1.2.3.4:1080"></textarea>
    </label>
    <p><button type="submit">加入池</button></p>
  </form>
</div>
<div class="卡">
  <table>
    <thead><tr><th>地址</th><th>状态</th><th>连接</th><th>上行</th><th>下行</th><th>来源</th><th>说明</th><th></th></tr></thead>
    <tbody id="表"></tbody>
  </table>
</div>
</main>
<script>
async function api(path, body){
  const o = {method: body ? "POST" : "GET", credentials:"same-origin"};
  if(body){ o.headers={"Content-Type":"application/json"}; o.body=JSON.stringify(body); }
  const r = await fetch(path, o);
  if(r.status===401){ location.href="/"; throw new Error("要密码"); }
  const t = await r.text();
  let j; try{ j=JSON.parse(t); }catch(e){ throw new Error(t||r.status); }
  if(!r.ok || j.ok===false) throw new Error(j.err||t);
  return j;
}
function 挂链(u){
  const a=document.getElementById("去面板");
  if(!a||!u) return;
  a.href=u; a.style.display="inline-block";
}
function 填(d){
  挂链(d.panel_url);
  document.getElementById("概").innerHTML =
    "SOCKS <b>"+d.listen+"</b> · 管理 <b>"+d.web+"</b> · 健康 "+d.健康+"/"+d.总数+
    " · 上行 "+(d.上行文||"0 B")+" · 下行 "+(d.下行文||"0 B")+
    (d.上次补 ? "<br><span class=次>"+d.上次补+"</span>" : "");
  const f=document.getElementById("设");
  f.mode.value=d.mode; f.sticky.value=d.sticky==="关"?"":d.sticky;
  f.pool_size.value=d.pool_size; f.fail_n.value=d.fail_n;
  f.check_interval.value=d.check_interval;
  f.fetch_url.value=d.fetch_url||""; f.fetch_cmd.value=d.fetch_cmd||"";
  const tb=document.getElementById("表");
  tb.innerHTML="";
  (d.池||[]).forEach(p=>{
    const tr=document.createElement("tr");
    const 态=p.启用?(p.健康?"<span class=好>健康</span>":"<span class=坏>摘除</span>"):"<span class=次>停</span>";
    tr.innerHTML="<td>"+p.地址+" <span class=徽章>"+p.方案+"</span></td><td>"+态+
      "</td><td>"+p.连接+"</td><td>"+(p.上行文||"0 B")+"</td><td>"+(p.下行文||"0 B")+
      "</td><td>"+p.来源+"</td><td class=次>"+(p.上次错误||p.上次切换||"")+"</td><td></td>";
    const b=document.createElement("button");
    b.className="红"; b.textContent="删除";
    b.onclick=async()=>{ await api("/api/del",{id:p.号}); 刷(); };
    tr.lastChild.appendChild(b);
    tb.appendChild(tr);
  });
}
async function 刷(){ 填(await api("/api/status")); }
document.getElementById("设").onsubmit=async e=>{
  e.preventDefault();
  const f=e.target;
  await api("/api/set",{
    mode:f.mode.value, sticky:f.sticky.value,
    pool_size:+f.pool_size.value, fail_n:+f.fail_n.value,
    check_interval:+f.check_interval.value,
    fetch_url:f.fetch_url.value, fetch_cmd:f.fetch_cmd.value
  });
  刷();
};
document.getElementById("加").onsubmit=async e=>{
  e.preventDefault();
  const 文=e.target.串.value;
  const j=await api("/api/add",{串:文});
  if(j.err) alert(j.err);
  e.target.串.value="";
  刷();
};
document.getElementById("补").onclick=async()=>{ await api("/api/fill",{}); 刷(); };
document.getElementById("退").onclick=async()=>{ await api("/api/logout",{}); location.href="/"; };
刷(); setInterval(刷, 4000);
</script>
</body>
</html>
"""

登页 = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>代理池登录</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#f4f5f7;font:14px/1.45 "Segoe UI","微软雅黑",sans-serif;color:#1f2328}
.卡{background:#fff;border:1px solid #d0d7de;border-radius:10px;padding:22px 24px;width:320px}
h1{font-size:18px;margin:0 0 8px}
p{color:#6b727c;margin:0 0 14px}
input{width:100%;padding:8px 10px;border:1px solid #d0d7de;border-radius:6px;font:14px inherit}
button{margin-top:12px;width:100%;border:0;border-radius:6px;padding:9px;background:#0969da;color:#fff;cursor:pointer}
a.跳{display:none;margin-top:10px;text-align:center;text-decoration:none;border-radius:6px;padding:9px;background:#1a7f37;color:#fff}
.错{color:#cf222e;margin-top:8px;min-height:1.2em}
</style>
</head>
<body>
<div class="卡">
<h1>代理池</h1>
<p>输入密码后才能改池。API 同样要这个密码。</p>
<form id="登">
<input name="pass" type="password" autocomplete="current-password" autofocus>
<button type="submit">进入</button>
<a class="跳" id="去面板" target="_blank" rel="noopener">打开 X-UI 面板</a>
<div class="错" id="错"></div>
</form>
</div>
<script>
fetch("/api/panel").then(r=>r.json()).then(j=>{
  if(j&&j.url){ const a=document.getElementById("去面板"); a.href=j.url; a.style.display="block"; }
}).catch(()=>{});
document.getElementById("登").onsubmit=async e=>{
  e.preventDefault();
  const 密=e.target.pass.value;
  const r=await fetch("/api/login",{method:"POST",credentials:"same-origin",
    headers:{"Content-Type":"application/json"},body:JSON.stringify({pass:密})});
  const j=await r.json().catch(()=>({}));
  if(r.ok && j.ok){ location.href="/"; return; }
  document.getElementById("错").textContent=j.err||"密码不对";
};
</script>
</body>
</html>
"""

_饼干名 = "xui_bridge"


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
    给 = _信里密(头, 体)
    return _同(给, 密)


def _头文(码: int, 类: str, 长: int, 额外: str = "") -> bytes:
    说 = {200: "OK", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 500: "ERR"}.get(码, "ERR")
    return (
        f"HTTP/1.1 {码} {说}\r\n"
        f"Content-Type: {类}\r\n"
        "Cache-Control: no-store\r\n"
        f"Content-Length: {长}\r\n"
        f"{额外}"
        "Connection: close\r\n\r\n"
    ).encode("ascii")


def _json(写: asyncio.StreamWriter, 码: int, 身: dict, 额外: str = "") -> None:
    文 = json.dumps(身, ensure_ascii=False).encode("utf-8")
    写.write(_头文(码, "application/json; charset=utf-8", len(文), 额外) + 文)


def _html(写: asyncio.StreamWriter, 文: str) -> None:
    体 = 文.encode("utf-8")
    写.write(_头文(200, "text/html; charset=utf-8", len(体)) + 体)


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


async def 处理管理(读, 写, 池子: 池) -> None:
    try:
        法, 路, 体, 头 = await _读请求(读)
        路 = 路.split("?", 1)[0]
        数据 = _身(体)
        密 = _密(池子)

        if 法 == "GET" and 路 == "/api/panel":
            _json(写, 200, {"ok": True, "url": 面板地址(头)})
        elif 法 == "POST" and 路 == "/api/login":
            给 = str(数据.get("pass") or "")
            if _同(给, 密):
                _json(写, 200, {"ok": True}, _置饼(密))
            else:
                日志.warning("管理页密码错误")
                _json(写, 403, {"ok": False, "err": "密码不对"})
        elif 法 == "POST" and 路 == "/api/logout":
            _json(写, 200, {"ok": True}, _清饼())
        elif not 已登录(头, 数据, 密):
            if 法 == "GET" and 路 in ("/", "/index.html"):
                _html(写, 登页)
            else:
                _json(写, 401, {"ok": False, "err": "要密码。网页先登录，API 带 X-Pass 或 Authorization: Bearer"})
        elif 法 == "GET" and 路 in ("/", "/index.html"):
            _html(写, 页)
        elif 法 == "GET" and 路 == "/api/status":
            身 = 池子.总览()
            身["panel_url"] = 面板地址(头)
            _json(写, 200, 身)
        elif 法 == "POST" and 路 == "/api/add":
            串 = str(数据.get("串") or "")
            成, 错们 = 0, []
            for 行 in 串.splitlines():
                行 = 行.strip()
                if not 行:
                    continue
                try:
                    await 池子.加(行, 来源="手加")
                    成 += 1
                except ValueError as 错:
                    错们.append(str(错))
            _json(写, 200, {"ok": True, "n": 成, "err": "；".join(错们)})
        elif 法 == "POST" and 路 == "/api/del":
            ok = await 池子.删(str(数据.get("号") or 数据.get("id") or ""))
            _json(写, 200, {"ok": ok})
        elif 法 == "POST" and 路 == "/api/set":
            数据.pop("pass", None)
            数据.pop("web_pass", None)
            await 池子.改设(数据)
            _json(写, 200, {"ok": True})
        elif 法 == "POST" and 路 == "/api/fill":
            说 = await 池子.补齐()
            _json(写, 200, {"ok": True, "msg": 说})
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


def _身(体: bytes) -> dict:
    if not 体:
        return {}
    try:
        数据 = json.loads(体.decode("utf-8"))
        return 数据 if isinstance(数据, dict) else {}
    except Exception:
        q = parse_qs(体.decode("utf-8", "replace"))
        return {k: (v[0] if v else "") for k, v in q.items()}


async def 开网页(池子: 池) -> asyncio.AbstractServer:
    主 = str(池子.设.get("web") or "127.0.0.1")
    口 = 池子.网页口()

    async def _接(读, 写):
        await 处理管理(读, 写, 池子)

    服 = await asyncio.start_server(_接, 主, 口)
    日志.info("管理页 http://%s:%s/", 主, 口)
    return 服
