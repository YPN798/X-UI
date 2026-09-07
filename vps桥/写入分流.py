# -*- coding: utf-8 -*-
"""把最低消耗分流写进正在跑的 Xray：3 个 dola 主机走 127.0.0.1:41000。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

径们 = (
    Path("/usr/local/x-ui/bin/config.json"),
    Path("/usr/local/x-ui/bin/config.json.bak"),
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


def _活文件() -> Path:
    for p in 径们:
        if p.name.endswith(".bak"):
            continue
        if p.is_file():
            return p
    return 径们[0]


def 写入(p: Path | None = None) -> str:
    p = p or _活文件()
    if not p.is_file():
        raise FileNotFoundError(f"没有 {p}")
    d = json.loads(p.read_text(encoding="utf-8"))
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
    入站标 = []
    for ib in d.get("inbounds") or []:
        if not isinstance(ib, dict):
            continue
        if ib.get("tag") == "api" or ib.get("protocol") == "dokodemo-door":
            continue
        t = str(ib.get("tag") or "").strip()
        if t:
            入站标.append(t)
    插们 = [{"type": "field", "domain": 域, "outboundTag": "socks-proxy"}]
    if 入站标:
        插们.insert(0, {
            "type": "field",
            "inboundTag": 入站标,
            "port": "443",
            "network": "tcp",
            "outboundTag": "socks-proxy",
        })
    位 = 0
    for i, r in enumerate(rules):
        if r.get("inboundTag") == ["api"] or r.get("outboundTag") == "api":
            位 = i + 1
    for 插 in reversed(插们):
        rules.insert(位, 插)
    rt["rules"] = rules

    for ib in d.get("inbounds") or []:
        if not isinstance(ib, dict):
            continue
        if ib.get("tag") == "api" or ib.get("protocol") == "dokodemo-door":
            continue
        sniff = ib.get("sniffing") if isinstance(ib.get("sniffing"), dict) else {}
        sniff["enabled"] = True
        dest = list(sniff.get("destOverride") or [])
        for x in ("http", "tls", "quic"):
            if x not in dest:
                dest.append(x)
        sniff["destOverride"] = dest
        ib["sniffing"] = sniff

    临时 = p.with_suffix(p.suffix + ".tmp")
    临时.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    临时.replace(p)
    return str(p)


if __name__ == "__main__":
    目标 = 写入()
    print("已写分流", 目标, time.strftime("%H:%M:%S"))
    os.system("pkill -x xray >/dev/null 2>&1 || pkill -f /usr/local/x-ui/bin/xray >/dev/null 2>&1 || true")
