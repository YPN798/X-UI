# -*- coding: utf-8 -*-
"""把最低消耗分流写进 / 撤出 Xray：dola 几个主机走 127.0.0.1:41000。

只改 bin/config.json 是留不住的——x-ui 每次重启都会照着自己数据库里的
模板和入站记录重新生成那个文件，改动就没了。所以这里先改数据库（模板
里的路由 + 每个入站的 sniffing），再改正在跑的那份，最后重启面板。

域名规则要靠 sniffing 才认得出主机名，入站没开嗅探的话，规则永远命不中，
dola 会安安静静地走直连。

关代理时：尽量把模板和入站嗅探恢复成第一次写分流前的备份，并去掉
socks-proxy 出站/规则，避免最低消耗模板里自带的桥分流还留着。
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

径们 = (
    Path("/usr/local/x-ui/bin/config.json"),
    Path("/usr/local/x-ui-yg/bin/config.json"),
)
库们 = (
    Path("/etc/x-ui/x-ui.db"),
    Path("/usr/local/x-ui/x-ui.db"),
    Path("/etc/x-ui-yg/x-ui-yg.db"),
)
原档 = Path("/etc/xui-bridge/xray模板.原")
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
桥标 = "socks-proxy"


def _活文件() -> Path:
    for p in 径们:
        if p.is_file():
            return p
    return 径们[0]


def 找库() -> Path | None:
    for p in 库们:
        if p.is_file():
            return p
    return None


def _备份库(库: Path) -> Path:
    return 库.with_name(库.name + ".桥备份")


def 有桥(d: dict) -> bool:
    for o in d.get("outbounds") or []:
        if isinstance(o, dict) and o.get("tag") == 桥标:
            return True
    rt = d.get("routing") if isinstance(d.get("routing"), dict) else {}
    for r in rt.get("rules") or []:
        if isinstance(r, dict) and r.get("outboundTag") == 桥标:
            return True
    return False


def 打补丁(d: dict) -> dict:
    """往一份 Xray 配置里塞出站、路由规则，并把入站的嗅探打开。"""
    outs = [o for o in (d.get("outbounds") or []) if isinstance(o, dict) and o.get("tag") != 桥标]
    outs.append(出站)
    d["outbounds"] = outs

    rt = d.setdefault("routing", {})
    if not isinstance(rt, dict):
        rt = {}
        d["routing"] = rt
    rt["domainStrategy"] = "IPIfNonMatch"
    rules = [r for r in (rt.get("rules") or []) if isinstance(r, dict)]
    rules = [r for r in rules if r.get("outboundTag") != 桥标]
    插 = {"type": "field", "network": "tcp", "domain": 域, "outboundTag": 桥标}
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


def 去掉补丁(d: dict) -> dict:
    """撤掉桥加的出站和规则。其它路由（直连、屏蔽、warp）不动。"""
    d["outbounds"] = [
        o for o in (d.get("outbounds") or [])
        if not (isinstance(o, dict) and o.get("tag") == 桥标)
    ]
    rt = d.get("routing")
    if isinstance(rt, dict) and isinstance(rt.get("rules"), list):
        rt["rules"] = [
            r for r in rt["rules"]
            if not (isinstance(r, dict) and r.get("outboundTag") == 桥标)
        ]
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


def _落json(p: Path, d: dict) -> None:
    临时 = p.with_suffix(p.suffix + ".tmp")
    临时.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    临时.replace(p)


def 写入(p: Path | None = None) -> str:
    p = p or _活文件()
    if not p.is_file():
        raise FileNotFoundError(f"没有 {p}")
    d = 打补丁(json.loads(p.read_text(encoding="utf-8")))
    _落json(p, d)
    return str(p)


def _表名(库: sqlite3.Connection, 候选: tuple[str, ...]) -> str:
    有 = {行[0] for 行 in 库.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in 候选:
        if t in 有:
            return t
    return ""


def _读模板(库径: Path) -> str:
    if not 库径.is_file():
        return ""
    库 = sqlite3.connect(str(库径))
    try:
        设表 = _表名(库, ("settings", "setting"))
        if not 设表:
            return ""
        行 = 库.execute(
            f"SELECT value FROM {设表} WHERE key='xrayTemplateConfig' LIMIT 1"
        ).fetchone()
        return str(行[0] or "") if 行 else ""
    finally:
        库.close()


def _读嗅探(库径: Path) -> dict[int, str]:
    if not 库径.is_file():
        return {}
    库 = sqlite3.connect(str(库径))
    try:
        入表 = _表名(库, ("inbounds", "inbound"))
        if not 入表:
            return {}
        列 = {行[1] for 行 in 库.execute(f"PRAGMA table_info({入表})")}
        if "sniffing" not in 列:
            return {}
        出: dict[int, str] = {}
        for 号, 旧 in 库.execute(f"SELECT id, sniffing FROM {入表}"):
            出[int(号)] = "" if 旧 is None else str(旧)
        return 出
    finally:
        库.close()


def 原模板文(库: Path | None = None) -> str:
    if 原档.is_file():
        try:
            return 原档.read_text(encoding="utf-8")
        except OSError:
            pass
    if 库 and _备份库(库).is_file():
        return _读模板(_备份库(库))
    return ""


def _存原文(文: str) -> None:
    if not 文 or 原档.is_file():
        return
    try:
        原档.parent.mkdir(parents=True, exist_ok=True)
        原档.write_text(文, encoding="utf-8")
    except OSError:
        pass


def 补数据库(p: Path) -> list[str]:
    """改面板数据库：模板加路由，入站开嗅探。返回做了什么。"""
    说: list[str] = []
    备 = _备份库(p)
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
                    _存原文(str(行[0]))
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


def 恢复数据库(p: Path) -> tuple[list[str], bool]:
    """把模板和入站嗅探尽量恢复成写分流前，并去掉桥出站。"""
    说: list[str] = []
    改了 = False
    原文 = 原模板文(p)
    if 原文:
        try:
            原文 = json.dumps(去掉补丁(json.loads(原文)), ensure_ascii=False, indent=2)
        except ValueError:
            说.append("原模板不是合法 JSON，改走当前模板去桥")
            原文 = ""
    嗅们 = _读嗅探(_备份库(p)) if _备份库(p).is_file() else {}
    库 = sqlite3.connect(str(p))
    try:
        设表 = _表名(库, ("settings", "setting"))
        if 设表:
            行 = 库.execute(
                f"SELECT value FROM {设表} WHERE key='xrayTemplateConfig' LIMIT 1"
            ).fetchone()
            现 = str(行[0] or "") if 行 else ""
            if 原文:
                if 原文 != 现:
                    库.execute(
                        f"UPDATE {设表} SET value=? WHERE key='xrayTemplateConfig'", (原文,)
                    )
                    说.append("模板已恢复成写分流前，并去掉桥出站")
                    改了 = True
                else:
                    说.append("模板已是原设置")
            elif 现:
                try:
                    新 = json.dumps(去掉补丁(json.loads(现)), ensure_ascii=False, indent=2)
                except ValueError:
                    新 = ""
                if 新 and 新 != 现:
                    库.execute(
                        f"UPDATE {设表} SET value=? WHERE key='xrayTemplateConfig'", (新,)
                    )
                    说.append("没有原模板备份，已从当前模板去掉桥分流")
                    改了 = True
                else:
                    说.append("当前模板没有桥分流")
            else:
                说.append("数据库里没有模板")

        入表 = _表名(库, ("inbounds", "inbound"))
        列 = {行[1] for 行 in 库.execute(f"PRAGMA table_info({入表})")} if 入表 else set()
        if 入表 and "sniffing" in 列 and 嗅们:
            改 = 0
            for 号, 旧 in 库.execute(f"SELECT id, sniffing FROM {入表}"):
                if int(号) not in 嗅们:
                    continue
                新 = 嗅们[int(号)]
                if ("" if 旧 is None else str(旧)) != 新:
                    库.execute(f"UPDATE {入表} SET sniffing=? WHERE id=?", (新, 号))
                    改 += 1
            if 改:
                说.append(f"入站嗅探已恢复 {改} 条")
                改了 = True
        库.commit()
    finally:
        库.close()
    return 说, 改了


def 恢复文件(p: Path | None = None) -> tuple[str, bool]:
    p = p or _活文件()
    if not p.is_file():
        raise FileNotFoundError(f"没有 {p}")
    d = json.loads(p.read_text(encoding="utf-8"))
    if not 有桥(d):
        return str(p), False
    _落json(p, 去掉补丁(d))
    return str(p), True


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


def 开分流() -> str:
    说: list[str] = []
    库 = 找库()
    if 库:
        说.extend(补数据库(库))
    else:
        说.append("没找到面板数据库，重启后分流可能会被面板覆盖掉")
    try:
        说.append(f"已写分流 {写入()} {time.strftime('%H:%M:%S')}")
    except FileNotFoundError as 错:
        说.append(str(错))
        return "；".join(说)
    说.append(重启面板())
    return "；".join(说)


def 关分流() -> str:
    说: list[str] = []
    改了 = False
    库 = 找库()
    if 库:
        步, 改 = 恢复数据库(库)
        说.extend(步)
        改了 = 改了 or 改
    else:
        说.append("没找到面板数据库")
    try:
        址, 改 = 恢复文件()
        说.append(f"已从 {址} 去掉桥分流" if 改 else f"{址} 本来就没有桥分流")
        改了 = 改了 or 改
    except FileNotFoundError as 错:
        说.append(str(错))
    if 改了:
        说.append(重启面板())
    else:
        说.append("X-UI 已是原设置，不用重启")
    return "；".join(说)


def 对齐分流(开: bool) -> str:
    return 开分流() if 开 else 关分流()


if __name__ == "__main__":
    # 重启面板会掐掉从这台机器自己代理出去的 SSH，屏幕上的输出就看不到了
    记 = Path("/tmp/写入分流.log")
    行们: list[str] = []

    def 说(句: str) -> None:
        行们.append(句)
        print(句)
        try:
            记.write_text("\n".join(行们) + "\n", encoding="utf-8")
        except OSError:
            pass

    关 = any(a in ("关", "close", "off", "0") for a in sys.argv[1:])
    说(对齐分流(not 关))
