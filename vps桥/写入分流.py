# -*- coding: utf-8 -*-
"""把最低消耗分流写进 Xray：dola 几个主机走 127.0.0.1:41000。

只改 bin/config.json 是留不住的——x-ui 每次重启都会照着自己数据库里的
模板和入站记录重新生成那个文件，改动就没了。所以这里先改数据库（模板
里的路由 + 每个入站的 sniffing），再改正在跑的那份，最后重启面板。

域名规则要靠 sniffing 才认得出主机名，入站没开嗅探的话，规则永远命不中，
dola 会安安静静地走直连。
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

径们 = (
    Path("/usr/local/x-ui/bin/config.json"),
    Path("/usr/local/x-ui/bin/config.json.bak"),
)
库们 = (
    Path("/etc/x-ui/x-ui.db"),
    Path("/usr/local/x-ui/x-ui.db"),
    Path("/etc/x-ui-yg/x-ui-yg.db"),
)
域 = [
    "full:www.dola.com",
    "full:dola.com",
    "full:wss-normal-i18n.dola.com",
    "domain:dola.com",
]
出站 = {
    "tag": "socks-proxy",
    "protocol": "socks",
    "settings": {"servers": [{"address": "127.0.0.1", "port": 41000}]},
}
嗅 = {"enabled": True, "destOverride": ["http", "tls", "quic"]}


def _活文件() -> Path:
    for p in 径们:
        if p.name.endswith(".bak"):
            continue
        if p.is_file():
            return p
    return 径们[0]


def 找库() -> Path | None:
    for p in 库们:
        if p.is_file():
            return p
    return None


def 打补丁(d: dict) -> dict:
    """往一份 Xray 配置里塞出站、路由规则，并把入站的嗅探打开。"""
    outs = [o for o in (d.get("outbounds") or []) if isinstance(o, dict) and o.get("tag") != "socks-proxy"]
    outs.append(出站)
    d["outbounds"] = outs

    rt = d.setdefault("routing", {})
    if not isinstance(rt, dict):
        rt = {}
        d["routing"] = rt
    rt["domainStrategy"] = "IPIfNonMatch"
    rules = [r for r in (rt.get("rules") or []) if isinstance(r, dict)]
    rules = [r for r in rules if r.get("outboundTag") != "socks-proxy"]
    插 = {"type": "field", "network": "tcp", "domain": 域, "outboundTag": "socks-proxy"}
    位 = 0
    for i, r in enumerate(rules):
        if r.get("inboundTag") == ["api"] or r.get("outboundTag") == "api":
            位 = i + 1
    rules.insert(位, 插)
    rt["rules"] = rules

    for ib in d.get("inbounds") or []:
        if not isinstance(ib, dict):
            continue
        if ib.get("tag") == "api" or ib.get("protocol") == "dokodemo-door":
            continue
        ib["sniffing"] = _并嗅(ib.get("sniffing"))
    return d


def _并嗅(旧) -> dict:
    出 = dict(旧) if isinstance(旧, dict) else {}
    出["enabled"] = True
    dest = list(出.get("destOverride") or [])
    for x in 嗅["destOverride"]:
        if x not in dest:
            dest.append(x)
    出["destOverride"] = dest
    return 出


def 写入(p: Path | None = None) -> str:
    p = p or _活文件()
    if not p.is_file():
        raise FileNotFoundError(f"没有 {p}")
    d = 打补丁(json.loads(p.read_text(encoding="utf-8")))
    临时 = p.with_suffix(p.suffix + ".tmp")
    临时.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    临时.replace(p)
    return str(p)


def _表名(库: sqlite3.Connection, 候选: tuple[str, ...]) -> str:
    有 = {行[0] for 行 in 库.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in 候选:
        if t in 有:
            return t
    return ""


def 补数据库(p: Path) -> list[str]:
    """改面板数据库：模板加路由，入站开嗅探。返回做了什么。"""
    说: list[str] = []
    备 = p.with_name(p.name + ".桥备份")
    if not 备.is_file():
        shutil.copy2(p, 备)
        说.append(f"数据库已备份到 {备}")
    库 = sqlite3.connect(str(p))
    try:
        设表 = _表名(库, ("settings", "setting"))
        if 设表:
            行 = 库.execute(
                f"SELECT value FROM {设表} WHERE key='xrayTemplateConfig' LIMIT 1"
            ).fetchone()
            if 行 and 行[0]:
                try:
                    模 = json.dumps(打补丁(json.loads(行[0])), ensure_ascii=False, indent=2)
                    库.execute(
                        f"UPDATE {设表} SET value=? WHERE key='xrayTemplateConfig'", (模,)
                    )
                    说.append("模板里的分流已更新")
                except ValueError:
                    说.append("模板不是合法 JSON，没敢动")
            else:
                说.append("数据库里没有模板，只改了正在跑的那份")

        入表 = _表名(库, ("inbounds", "inbound"))
        列 = {行[1] for 行 in 库.execute(f"PRAGMA table_info({入表})")} if 入表 else set()
        if 入表 and "sniffing" in 列:
            改 = 0
            for 号, 协议, 旧 in 库.execute(f"SELECT id, protocol, sniffing FROM {入表}"):
                if str(协议 or "") == "dokodemo-door":
                    continue
                try:
                    原 = json.loads(旧) if 旧 else {}
                except ValueError:
                    原 = {}
                新 = _并嗅(原)
                if 新 != 原:
                    库.execute(
                        f"UPDATE {入表} SET sniffing=? WHERE id=?",
                        (json.dumps(新, ensure_ascii=False), 号),
                    )
                    改 += 1
            说.append(f"打开了 {改} 个入站的嗅探" if 改 else "入站嗅探本来就是开的")
        elif 入表:
            说.append("这个面板版本的入站表没有 sniffing 列，跳过")
        库.commit()
    finally:
        库.close()
    return 说


def 重启面板() -> str:
    for 令 in ("systemctl restart x-ui", "rc-service x-ui restart"):
        if os.system(f"{令} >/dev/null 2>&1") == 0:
            return f"已 {令}"
    os.system(
        "pkill -x xray-linux-amd64 >/dev/null 2>&1 || "
        "pkill -f /usr/local/x-ui/bin/xray-linux-amd64 >/dev/null 2>&1 || "
        "pkill -x xray >/dev/null 2>&1 || true"
    )
    return "重启面板失败，只好踢掉 xray 让它自己起来"


if __name__ == "__main__":
    库 = 找库()
    if 库:
        for 句 in 补数据库(库):
            print(句)
    else:
        print("没找到面板数据库，重启后分流可能会被面板覆盖掉")
    print("已写分流", 写入(), time.strftime("%H:%M:%S"))
    print(重启面板())
