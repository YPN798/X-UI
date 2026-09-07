# -*- coding: utf-8 -*-
"""管理页：节点分享链接、测通路、代理池。不经过 X-UI。"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from urllib.parse import parse_qs

from 池 import 池
from 转发 import 测通路

日志 = logging.getLogger("xui桥")

页 = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>业务节点</title>
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
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--线);font-size:13px}
.好{color:var(--绿)} .坏{color:var(--红)}
.徽章{display:inline-block;padding:1px 7px;border-radius:999px;background:#eef2f6;font-size:12px}
pre{white-space:pre-wrap;word-break:break-all;margin:8px 0 0;font:12px/1.4 ui-monospace,Consolas,monospace}
</style>
</head>
<body>
<main>
<h1>业务节点 <button class="灰" id="退" style="float:right">退出</button></h1>
<p class="次">v2rayN 连下面这条节点。dola 走本机桥再进代理池；其它网站走 VPS IP。进程在听不算通，池的上下行增加才算。</p>
<div class="卡" id="节点"></div>
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
    <label>同时验活条数 <input name="check_conc" type="number" min="1" max="64"></label>
    <label>fetch_url <input name="fetch_url" placeholder="GET 返回一行代理串" style="min-width:260px"></label>
    <label>fetch_cmd <input name="fetch_cmd" placeholder="命令 stdout 一行" style="min-width:200px"></label>
    <button type="submit">保存设置</button>
    <button type="button" class="灰" id="补">立刻补池</button>
    <button type="button" class="灰" id="测">测通路</button>
  </form>
  <p class="次" id="测果"></p>
</div>
<div class="卡">
  <form id="加">
    <label>加一条（socks5://用户:密码@主机:端口 或 IP|端口|用户|密码，可多行）
      <textarea name="串" placeholder="socks5://user:pass@1.2.3.4:1080"></textarea>
    </label>
    <p><button type="submit">加入池</button> <button type="button" class="红" id="清空">一键删除全部</button>
    <span class="次" id="加果"></span></p>
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
function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c])); }
function 填(d){
  const n=d.节点||{};
  const 空=!(d.总数);
  document.getElementById("节点").innerHTML =
    "地址 <b>"+esc(n.public_host||"未知")+"</b> · 端口 <b>"+esc(n.node_port)+"</b> · UUID <b>"+esc(n.node_uuid)+"</b>"+
    "<br>Xray "+(n.xray_running?"<span class=好>在跑</span>":"<span class=坏>没跑</span>")+
    " · 节点口 "+(n.node_listen_ok?"<span class=好>在听</span>":"<span class=坏>没听</span>")+
    " · 桥41000 "+(n.bridge_listen_ok?"<span class=好>在听</span>":"<span class=坏>没听</span>")+
    (空?"<br><span class=坏>池是空的：先贴代理，否则 dola 进不了桥</span>":"")+
    "<pre id=链>"+esc(n.vmess||"")+"</pre>"+
    "<p><button type=button class=灰 id=复制>复制分享链接</button></p>";
  const 复=document.getElementById("复制");
  if(复) 复.onclick=()=>{ navigator.clipboard.writeText(n.vmess||""); };
  document.getElementById("概").innerHTML =
    "SOCKS <b>"+esc(d.listen)+"</b> · 管理 <b>"+esc(d.web)+"</b> · 健康 "+(d.健康||0)+"/"+(d.总数||0)+
    " · 验活 <b>"+esc(d.check_host||"www.dola.com")+":"+(d.check_port||443)+"</b>"+
    " · 上行 "+esc(d.上行文||"0 B")+" · 下行 "+esc(d.下行文||"0 B")+
    (d.上次补 ? "<br><span class=次>"+esc(d.上次补)+"</span>" : "");
  const tb=document.getElementById("表");
  tb.innerHTML="";
  (d.池||d.proxies||[]).forEach(p=>{
    try{
      const tr=document.createElement("tr");
      const 态=p.启用?(p.健康?"<span class=好>健康</span>":"<span class=坏>摘除</span>"):"<span class=次>停</span>";
      const 说=p.上次错误||p.上次切换||"";
      tr.innerHTML="<td>"+esc(p.地址)+" <span class=徽章>"+esc(p.方案)+"</span></td><td>"+态+
        "</td><td>"+(p.连接||0)+"</td><td>"+esc(p.上行文||"0 B")+"</td><td>"+esc(p.下行文||"0 B")+
        "</td><td>"+esc(p.来源)+"</td><td class=次></td><td></td>";
      tr.cells[6].textContent=说;
      const b=document.createElement("button");
      b.className="红"; b.textContent="删除";
      b.onclick=async()=>{ await api("/api/del",{id:p.号||p.id}); 刷(); };
      tr.cells[7].appendChild(b);
      tb.appendChild(tr);
    }catch(e){ console.warn(e); }
  });
  try{
    const f=document.getElementById("设");
    if(f.mode) f.mode.value=d.mode||"round_robin";
    if(f.sticky) f.sticky.value=d.sticky==="关"?"":(d.sticky||"");
    if(f.pool_size) f.pool_size.value=d.pool_size;
    if(f.fail_n) f.fail_n.value=d.fail_n;
    if(f.check_interval) f.check_interval.value=d.check_interval;
    if(f.check_conc) f.check_conc.value=d.check_conc||16;
    if(f.fetch_url) f.fetch_url.value=d.fetch_url||"";
    if(f.fetch_cmd) f.fetch_cmd.value=d.fetch_cmd||"";
  }catch(e){ console.warn(e); }
}
async function 刷(){
  try{ 填(await api("/api/status")); }
  catch(e){ console.warn(e); }
}
document.getElementById("设").onsubmit=async e=>{
  e.preventDefault();
  const f=e.target;
  await api("/api/set",{
    mode:f.mode.value, sticky:f.sticky.value,
    pool_size:+f.pool_size.value, fail_n:+f.fail_n.value,
    check_interval:+f.check_interval.value, check_conc:+f.check_conc.value,
    fetch_url:f.fetch_url.value, fetch_cmd:f.fetch_cmd.value
  });
  刷();
};
document.getElementById("加").onsubmit=async e=>{
  e.preventDefault();
  const 框=e.target.querySelector("textarea");
  const 果=document.getElementById("加果");
  const 文=(框&&框.value||"").trim();
  if(!文){ if(果) 果.textContent="先贴一行代理"; return; }
  if(果) 果.textContent="正在加入…";
  try{
    const j=await api("/api/add",{串:文});
    if(j.err){ if(果) 果.innerHTML="<span class=坏>"+esc(j.err)+"</span>"; }
    else { if(果) 果.innerHTML="<span class=好>已加入 "+(j.n||0)+" 条</span>"; if(框) 框.value=""; }
    if((j.n||0)>0 && 框) 框.value="";
  }catch(err){
    if(果) 果.innerHTML="<span class=坏>"+esc(err.message||err)+"</span>";
    return;
  }
  刷();
};
document.getElementById("补").onclick=async()=>{ await api("/api/fill",{}); 刷(); };
document.getElementById("测").onclick=async()=>{
  const el=document.getElementById("测果");
  el.textContent="在测…";
  try{
    const j=await api("/api/probe",{});
    el.innerHTML=j.ok?"<span class=好>"+esc(j.msg||"通")+"</span>":"<span class=坏>"+esc(j.err||"失败")+"</span>";
  }catch(e){ el.innerHTML="<span class=坏>"+esc(e.message)+"</span>"; }
  刷();
};
document.getElementById("清空").onclick=async()=>{
  if(!confirm("确定删除池里全部代理？")) return;
  await api("/api/clear",{});
  刷();
};
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
<title>业务节点登录</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#f4f5f7;font:14px/1.45 "Segoe UI","微软雅黑",sans-serif;color:#1f2328}
.卡{background:#fff;border:1px solid #d0d7de;border-radius:10px;padding:22px 24px;width:320px}
h1{font-size:18px;margin:0 0 8px}
p{color:#6b727c;margin:0 0 14px}
input{width:100%;padding:8px 10px;border:1px solid #d0d7de;border-radius:6px;font:14px inherit}
button{margin-top:12px;width:100%;border:0;border-radius:6px;padding:9px;background:#0969da;color:#fff;cursor:pointer}
.错{color:#cf222e;margin-top:8px;min-height:1.2em}
</style>
</head>
<body>
<div class="卡">
<h1>业务节点</h1>
<p>输入密码后才能改池和看分享链接。</p>
<form id="登">
<input name="pass" type="password" autocomplete="current-password" autofocus>
<button type="submit">进入</button>
<div class="错" id="错"></div>
</form>
</div>
<script>
document.getElementById("登").onsubmit=async e=>{
  e.preventDefault();
  const r=await fetch("/api/login",{method:"POST",credentials:"same-origin",
    headers:{"Content-Type":"application/json"},body:JSON.stringify({pass:e.target.pass.value})});
  const j=await r.json().catch(()=>({}));
  if(r.ok && j.ok){ location.href="/"; return; }
  document.getElementById("错").textContent=j.err||"密码不对";
};
</script>
</body>
</html>
"""

_饼干名 = "dola_node"


def _密(池子: 池) -> str:
    return str(池子.设.get("web_pass") or "").strip()


def _令牌(密: str) -> str:
    return hmac.new(b"dola-node-v1", 密.encode("utf-8"), hashlib.sha256).hexdigest()


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
    return _同(_信里密(头, 体), 密)


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
    return f"Set-Cookie: {_饼干名}={_令牌(密)}; HttpOnly; SameSite=Lax; Path=/; Max-Age=604800\r\n"


def _清饼() -> str:
    return f"Set-Cookie: {_饼干名}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0\r\n"


def _请求主机(头: dict[str, str]) -> str:
    主 = (头.get("x-forwarded-host") or 头.get("host") or "").split(",")[0].strip()
    if 主.startswith("["):
        主 = 主.split("]", 1)[0].lstrip("[")
    elif 主.count(":") == 1:
        主 = 主.rsplit(":", 1)[0]
    if 主 in ("", "0.0.0.0", "127.0.0.1", "localhost", "::", "::1"):
        return ""
    return 主


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


async def 处理管理(读, 写, 池子: 池, 监督=None) -> None:
    try:
        法, 路, 体, 头 = await _读请求(读)
        路 = 路.split("?", 1)[0]
        数据 = _身(体)
        密 = _密(池子)

        if 法 == "POST" and 路 == "/api/login":
            给 = str(数据.get("pass") or "")
            if _同(给, 密):
                _json(写, 200, {"ok": True}, _置饼(密))
            else:
                _json(写, 403, {"ok": False, "err": "密码不对"})
        elif 法 == "POST" and 路 == "/api/logout":
            _json(写, 200, {"ok": True}, _清饼())
        elif not 已登录(头, 数据, 密):
            if 法 == "GET" and 路 in ("/", "/index.html"):
                _html(写, 登页)
            else:
                _json(写, 401, {"ok": False, "err": "要密码"})
        elif 法 == "GET" and 路 in ("/", "/index.html"):
            _html(写, 页)
        elif 法 == "GET" and 路 == "/api/status":
            身 = 池子.总览()
            身["ok"] = True
            身["proxies"] = 身.get("池") or []
            身["节点"] = 监督.快照(_请求主机(头)) if 监督 else {}
            _json(写, 200, 身)
        elif 法 == "POST" and 路 == "/api/add":
            成, 错们 = 0, []
            for 行 in str(数据.get("串") or "").splitlines():
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
            _json(写, 200, {"ok": await 池子.删(str(数据.get("号") or 数据.get("id") or ""))})
        elif 法 == "POST" and 路 == "/api/clear":
            _json(写, 200, {"ok": True, "n": await 池子.清空()})
        elif 法 == "POST" and 路 == "/api/set":
            数据.pop("pass", None)
            数据.pop("web_pass", None)
            await 池子.改设(数据)
            _json(写, 200, {"ok": True})
        elif 法 == "POST" and 路 == "/api/fill":
            _json(写, 200, {"ok": True, "msg": await 池子.补齐()})
        elif 法 == "POST" and 路 == "/api/probe":
            _json(写, 200, await 测通路(池子))
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


async def 开网页(池子: 池, 监督=None) -> asyncio.AbstractServer:
    主 = str(池子.设.get("web") or "0.0.0.0")
    口 = 池子.网页口()

    async def _接(读, 写):
        await 处理管理(读, 写, 池子, 监督)

    服 = await asyncio.start_server(_接, 主, 口)
    日志.info("管理页 http://%s:%s/", 主, 口)
    return 服
