# -*- coding: utf-8 -*-
"""自己写并拉起 Xray：VMess 入站，仅 dola 走 127.0.0.1:41000。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import socket
import stat
import tempfile
import urllib.request
import uuid
from pathlib import Path

from 池 import 池

日志 = logging.getLogger("xui桥")

域 = [
    "full:www.dola.com",
    "full:dola.com",
    "full:wss-normal-i18n.dola.com",
    "domain:dola.com",
]

候选二进制 = (
    Path("/usr/local/x-ui/bin/xray-linux-amd64"),
    Path("/usr/local/x-ui/bin/xray"),
    Path("/usr/local/bin/xray"),
    Path("/opt/dola-node/xray"),
)


def 节点口(池子: 池) -> int:
    return int(池子.设.get("node_port") or 14564)


def 保证uuid(池子: 池) -> str:
    现 = str(池子.设.get("node_uuid") or "").strip()
    try:
        uuid.UUID(现)
        return 现
    except Exception:
        现 = str(uuid.uuid4())
        池子.设["node_uuid"] = 现
        池子.落盘()
        return 现


_公网缓存 = ""


def 公网(池子: 池, 请求主机: str = "") -> str:
    写 = str(池子.设.get("public_host") or "").strip()
    if 写:
        return 写
    if 请求主机:
        return 请求主机
    global _公网缓存
    if _公网缓存:
        return _公网缓存
    for p in (Path("/usr/local/x-ui/xip"),):
        try:
            行 = p.read_text(encoding="utf-8").splitlines()
            if 行 and 行[0].strip():
                _公网缓存 = 行[0].strip()
                return _公网缓存
        except Exception:
            pass
    return ""


def xray配置(池子: 池) -> dict:
    保 = 保证uuid(池子)
    口 = 节点口(池子)
    听 = str(池子.设.get("node_listen") or "0.0.0.0")
    桥口 = 池子.听口()
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "vmess-in",
                "listen": 听,
                "port": 口,
                "protocol": "vmess",
                "settings": {
                    "clients": [{"id": 保}],
                    "disableInsecureEncryption": False,
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "none",
                    "tcpSettings": {"header": {"type": "none"}},
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls", "quic"],
                },
            }
        ],
        "outbounds": [
            {"tag": "direct", "protocol": "freedom"},
            {
                "tag": "socks-proxy",
                "protocol": "socks",
                "settings": {"servers": [{"address": "127.0.0.1", "port": 桥口}]},
            },
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                {"type": "field", "domain": 域, "outboundTag": "socks-proxy"},
                {"type": "field", "network": "tcp,udp", "outboundTag": "direct"},
            ],
        },
    }


def 写xrayjson(池子: 池, 径: Path) -> Path:
    径.parent.mkdir(parents=True, exist_ok=True)
    文 = json.dumps(xray配置(池子), ensure_ascii=False, indent=2) + "\n"
    临时 = 径.with_suffix(径.suffix + ".tmp")
    临时.write_text(文, encoding="utf-8")
    临时.replace(径)
    return 径


def 找xray() -> Path | None:
    which = shutil.which("xray")
    if which:
        return Path(which)
    for p in 候选二进制:
        if p.is_file() and os.access(p, os.X_OK):
            return p
    return None


def 下xray(到: Path) -> Path:
    到.parent.mkdir(parents=True, exist_ok=True)
    机 = os.uname().machine.lower() if hasattr(os, "uname") else "x86_64"
    档 = "Xray-linux-arm64-v8a.zip" if "arm" in 机 or "aarch" in 机 else "Xray-linux-64.zip"
    址 = f"https://github.com/XTLS/Xray-core/releases/latest/download/{档}"
    日志.info("下载 Xray %s", 址)
    with tempfile.TemporaryDirectory() as tmp:
        包 = Path(tmp) / 档
        urllib.request.urlretrieve(址, 包)
        shutil.unpack_archive(包, tmp)
        源 = Path(tmp) / "xray"
        if not 源.is_file():
            raise FileNotFoundError("压缩包里没有 xray")
        shutil.copy2(源, 到)
    到.chmod(到.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return 到


def 口在听(口: int, 主: str = "127.0.0.1") -> bool:
    if 主 in ("0.0.0.0", "::", ""):
        主 = "127.0.0.1"
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.4)
    try:
        return s.connect_ex((主, int(口))) == 0
    except OSError:
        return False
    finally:
        s.close()


def vmess链接(池子: 池, 主机: str = "") -> str:
    import base64

    主 = (主机 or 公网(池子) or "填写公网IP").strip()
    身 = {
        "v": "2",
        "ps": "dola-node",
        "add": 主,
        "port": str(节点口(池子)),
        "id": 保证uuid(池子),
        "aid": "0",
        "scy": "auto",
        "net": "tcp",
        "type": "none",
        "tls": "",
    }
    文 = json.dumps(身, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "vmess://" + base64.b64encode(文).decode("ascii")


class 监督xray:
    def __init__(self, 池子: 池, 配置径: Path | None = None) -> None:
        self.池子 = 池子
        self.配置径 = 配置径 or Path("/etc/dola-node/xray.json")
        self.进程: asyncio.subprocess.Process | None = None
        self.二进制: Path | None = None

    def 快照(self, 请求主机: str = "") -> dict:
        口 = 节点口(self.池子)
        桥口 = self.池子.听口()
        return {
            "node_port": 口,
            "node_uuid": 保证uuid(self.池子),
            "node_listen": str(self.池子.设.get("node_listen") or "0.0.0.0"),
            "public_host": 公网(self.池子, 请求主机),
            "vmess": vmess链接(self.池子, 公网(self.池子, 请求主机)),
            "xray_running": self.进程 is not None and self.进程.returncode is None,
            "node_listen_ok": 口在听(口),
            "bridge_listen_ok": 口在听(桥口),
            "xray_bin": str(self.二进制 or ""),
            "xray_json": str(self.配置径),
        }

    async def 重启(self) -> None:
        await self.停()
        await self.起()

    async def 停(self) -> None:
        p = self.进程
        self.进程 = None
        if p is None or p.returncode is not None:
            return
        try:
            p.terminate()
            await asyncio.wait_for(p.wait(), timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass

    def _备二进制(self) -> Path:
        已 = 找xray()
        if 已:
            return 已
        if os.name != "posix":
            raise FileNotFoundError("本机没有 xray，Windows 上请自行安装；VPS 安装脚本会下载")
        return 下xray(Path("/opt/dola-node/xray"))

    async def 起(self) -> None:
        写xrayjson(self.池子, self.配置径)
        self.二进制 = await asyncio.to_thread(self._备二进制)
        日志.info("启动 Xray %s -c %s", self.二进制, self.配置径)
        self.进程 = await asyncio.create_subprocess_exec(
            str(self.二进制), "run", "-c", str(self.配置径),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.sleep(0.6)
        if self.进程.returncode is not None:
            err = b""
            if self.进程.stderr:
                err = await self.进程.stderr.read()
            raise RuntimeError(f"Xray 退出 {self.进程.returncode}: {err.decode('utf-8', 'replace')[:400]}")

    async def 守护(self, 停: asyncio.Event) -> None:
        await self.起()
        while not 停.is_set():
            p = self.进程
            if p is None or p.returncode is not None:
                日志.warning("Xray 不在了，1 秒后拉起")
                try:
                    await asyncio.sleep(1)
                    if 停.is_set():
                        break
                    await self.起()
                except Exception as 错:
                    日志.warning("拉起 Xray 失败：%s", 错)
                    await asyncio.sleep(3)
                continue
            try:
                await asyncio.wait_for(停.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass
        await self.停()
