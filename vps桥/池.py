# -*- coding: utf-8 -*-
"""代理池：挑选、失败计数、拉取补池、落盘。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from 解析 import 本机主机, 拆, 给上游, 规范协议

日志 = logging.getLogger("xui桥")


闪臣码 = {
    1001: "鉴权失败，检查 API Key",
    1002: "参数错误或校验失败",
    1003: "账号不可用，已删除或被禁用",
    1004: "本机公网 IP 不在动态白名单",
    1005: "没有可用的动态流量账号，或流量已用完",
    1006: "安全码不对",
    1007: "白名单条数超上限，先删几条再加",
    2001: "闪臣那边系统处理失败",
}


def 闪臣说(码: int, 话: str) -> str:
    解 = 闪臣码.get(int(码 or 0), "")
    话 = (话 or "").strip()
    if 解 and 解 not in 话:
        return f"{话}（{码}：{解}）" if 话 else f"{码}：{解}"
    return 话 or f"错误码 {码}"


def 解信封(文: str) -> tuple[int, str, Any] | None:
    """闪臣统一返回 {code, message, data}；不是这个形状就返回 None。"""
    串 = (文 or "").strip()
    if not 串.startswith("{"):
        return None
    try:
        包 = json.loads(串)
    except ValueError:
        return None
    if not isinstance(包, dict) or "code" not in 包:
        return None
    try:
        码 = int(包.get("code") or 0)
    except (TypeError, ValueError):
        码 = -1
    return 码, str(包.get("message") or ""), 包.get("data")


def 遮(密: str) -> str:
    密 = str(密 or "")
    if not 密:
        return ""
    return f"{密[:4]}****{密[-4:]}" if len(密) > 8 else "****"


def _白条(一: Any) -> dict[str, str]:
    if not isinstance(一, dict):
        return {"id": "", "ip": str(一 or ""), "备注": ""}
    return {
        "id": str(一.get("id") or 一.get("ID") or ""),
        "ip": str(一.get("ip") or 一.get("IP") or 一.get("address") or ""),
        "备注": str(一.get("remark") or 一.get("note") or ""),
    }


def 人读(n: int) -> str:
    n = max(0, int(n or 0))
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.2f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"

默认 = {
    "listen": "127.0.0.1",
    "port": 41000,
    "web": "0.0.0.0",
    "web_port": 41001,
    "pool_size": 8,
    "mode": "round_robin",
    "sticky": "",
    "fail_n": 3,
    "check_interval": 30,
    "check_conc": 16,
    "check_host": "www.dola.com",
    "check_port": 443,
    "connect_timeout": 8,
    "fetch_url": "",
    "fetch_cmd": "",
    "fetch_scheme": "",
    "auto_rotate": 0,
    "sc_base": "https://global.shanchendaili.com",
    "sc_key": "",
    "sc_code": "",
    "sc_count": 8,
    "sc_time": 0,
    "sc_protocol": "http",
    "sc_cntry": "",
    "sc_state": "",
    "sc_city": "",
    "sc_white": 1,
    "web_pass": "YPN940815...",
    "proxies": [],
}


class 条:
    def __init__(self, 信: dict, 来源: str = "手加") -> None:
        self.号 = str(信.get("号") or uuid.uuid4())[:8]
        self.方案 = 规范协议(信.get("方案") or "socks5")
        self.主机 = str(信.get("主机") or "").strip()
        self.端口 = int(信.get("端口") or 0)
        self.用户 = str(信.get("用户") or "")
        self.密码 = str(信.get("密码") or "")
        self.来源 = 来源
        self.启用 = bool(信.get("启用", True))
        self.健康 = bool(信.get("健康", True))
        self.失败 = int(信.get("失败") or 0)
        self.连接 = 0
        self.上行 = int(信.get("上行") or 0)
        self.下行 = int(信.get("下行") or 0)
        self.上次错误 = str(信.get("上次错误") or "")
        self.上次切换 = str(信.get("上次切换") or "")

    def 键(self) -> str:
        return f"{self.方案}|{self.主机}|{self.端口}|{self.用户}"

    def 脱敏(self) -> str:
        return f"{self.方案}://{self.主机}:{self.端口}"

    def 串(self) -> str:
        return 给上游({
            "方案": self.方案, "主机": self.主机, "端口": self.端口,
            "用户": self.用户, "密码": self.密码,
        })

    def 快照(self) -> dict[str, Any]:
        return {
            "号": self.号,
            "地址": self.脱敏(),
            "方案": self.方案,
            "来源": self.来源,
            "启用": self.启用,
            "健康": self.健康,
            "失败": self.失败,
            "连接": self.连接,
            "上行": self.上行,
            "下行": self.下行,
            "上行文": 人读(self.上行),
            "下行文": 人读(self.下行),
            "上次错误": self.上次错误,
            "上次切换": self.上次切换,
        }


class 池:
    def __init__(self, 径: Path) -> None:
        self.径 = 径
        self.锁 = asyncio.Lock()
        self.轮询 = 0
        self.粘: dict[str, str] = {}
        self.上次补 = ""
        self.设: dict[str, Any] = dict(默认)
        self.条们: list[条] = []
        self.闪臣态: dict[str, Any] = {
            "余额": "", "有套餐": False, "余额说": "",
            "白名单": [], "白名单说": "",
            "本机IP": "", "IP时间": 0.0, "刷时间": "",
        }
        self.读盘()

    def 读盘(self) -> None:
        原 = dict(默认)
        if self.径.is_file():
            try:
                文 = json.loads(self.径.read_text(encoding="utf-8"))
                if isinstance(文, dict):
                    原.update(文)
            except Exception as 错:
                日志.warning("读配置失败 %s：%s", self.径, 错)
        self.设 = {**默认, **{k: 原.get(k, 默认[k]) for k in 默认}}
        self.条们 = []
        for 一 in 原.get("proxies") or []:
            try:
                self._塞(一, 落盘=False)
            except ValueError as 错:
                日志.warning("跳过非法代理：%s", 错)
        self._复流量()

    def 落盘(self) -> None:
        self.径.parent.mkdir(parents=True, exist_ok=True)
        出 = {
            "listen": self.设["listen"],
            "port": int(self.设["port"]),
            "web": self.设["web"],
            "web_port": int(self.设["web_port"]),
            "pool_size": int(self.设["pool_size"]),
            "mode": self.设["mode"],
            "sticky": self.设["sticky"],
            "fail_n": int(self.设["fail_n"]),
            "check_interval": int(self.设["check_interval"]),
            "check_conc": int(self.设.get("check_conc") or 16),
            "check_host": self.设.get("check_host") or "www.dola.com",
            "check_port": int(self.设.get("check_port") or 443),
            "connect_timeout": int(self.设["connect_timeout"]),
            "fetch_url": self.设["fetch_url"],
            "fetch_cmd": self.设["fetch_cmd"],
            "fetch_scheme": self.设.get("fetch_scheme") or "",
            "auto_rotate": int(self.设.get("auto_rotate") or 0),
            "sc_base": self.设.get("sc_base") or 默认["sc_base"],
            "sc_key": self.设.get("sc_key") or "",
            "sc_code": self.设.get("sc_code") or "",
            "sc_count": int(self.设.get("sc_count") or 1),
            "sc_time": int(self.设.get("sc_time") or 0),
            "sc_protocol": self.设.get("sc_protocol") or "http",
            "sc_cntry": self.设.get("sc_cntry") or "",
            "sc_state": self.设.get("sc_state") or "",
            "sc_city": self.设.get("sc_city") or "",
            "sc_white": int(self.设.get("sc_white") or 0),
            "web_pass": self.设["web_pass"],
            "proxies": [一.串() for 一 in self.条们],
        }
        临时 = self.径.with_suffix(self.径.suffix + ".tmp")
        临时.write_text(json.dumps(出, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        临时.replace(self.径)
        self.写状态()

    def 状态径(self) -> Path:
        return self.径.with_name("状态.json")

    def _复流量(self) -> None:
        p = self.状态径()
        if not p.is_file():
            return
        try:
            文 = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return
        旧: dict[str, dict] = {}
        for 一 in 文.get("池") or []:
            if isinstance(一, dict) and 一.get("地址"):
                旧[str(一["地址"])] = 一
        for 一 in self.条们:
            命 = 旧.get(一.脱敏())
            if not 命:
                continue
            一.上行 = int(命.get("上行") or 0)
            一.下行 = int(命.get("下行") or 0)

    def 写状态(self) -> None:
        出 = {
            "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "上次补": self.上次补,
            "模式": self.设["mode"],
            "粘住": self.设["sticky"],
            "池": [一.快照() for 一 in self.条们],
        }
        try:
            self.状态径().write_text(json.dumps(出, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as 错:
            日志.warning("写状态失败：%s", 错)

    def 听口(self) -> int:
        return int(self.设["port"] or 41000)

    def 网页口(self) -> int:
        return int(self.设["web_port"] or 41001)

    def 是自环(self, 主机: str, 端口: int) -> bool:
        if not 本机主机(主机):
            return False
        return int(端口) in {self.听口(), self.网页口()}

    def _塞(self, 串或信, 来源: str = "手加", 落盘: bool = True) -> 条:
        if isinstance(串或信, dict) and 串或信.get("主机"):
            信 = 串或信
        else:
            信 = 拆(str(串或信 or ""))
        主, 口 = str(信.get("主机") or "").strip(), int(信.get("端口") or 0)
        if not 主 or 口 <= 0:
            raise ValueError("代理缺主机或端口")
        if self.是自环(主, 口):
            raise ValueError(f"拒绝自环 {主}:{口}（不能指回桥自己）")
        键 = f"{规范协议(信.get('方案') or 'socks5')}|{主}|{口}|{信.get('用户') or ''}"
        for 已 in self.条们:
            if 已.键() == 键:
                return 已
        一 = 条(信, 来源=来源)
        self.条们.append(一)
        if 落盘:
            self.落盘()
        日志.info("入池 %s 来源=%s", 一.脱敏(), 来源)
        return 一

    async def 加(self, 串: str, 来源: str = "手加") -> 条:
        async with self.锁:
            return self._塞(串, 来源=来源, 落盘=True)

    async def 删(self, 号: str) -> bool:
        async with self.锁:
            前 = len(self.条们)
            self.条们 = [一 for 一 in self.条们 if 一.号 != 号]
            self.粘 = {k: v for k, v in self.粘.items() if v != 号}
            if len(self.条们) != 前:
                self.落盘()
                return True
            return False

    async def 清空(self) -> int:
        async with self.锁:
            n = len(self.条们)
            self.条们 = []
            self.粘 = {}
            if n:
                self.落盘()
            return n

    async def 改设(self, 补: dict[str, Any]) -> None:
        async with self.锁:
            for k in ("mode", "sticky", "fetch_url", "fetch_cmd", "fetch_scheme",
                      "sc_base", "sc_key", "sc_protocol", "sc_cntry", "sc_state", "sc_city"):
                if k in 补 and 补[k] is not None:
                    self.设[k] = str(补[k]).strip() if k.startswith("sc_") else 补[k]
            for k in ("pool_size", "fail_n", "check_interval", "check_conc",
                      "connect_timeout", "auto_rotate", "sc_count", "sc_time", "sc_white"):
                if k in 补 and 补[k] not in (None, ""):
                    self.设[k] = int(补[k])
            # 安全码是只写的：页面永远不回显，留空表示保持原样
            if str(补.get("sc_code") or "").strip():
                self.设["sc_code"] = str(补["sc_code"]).strip()
            self.落盘()

    def 健康们(self) -> list[条]:
        return [一 for 一 in self.条们 if 一.启用 and 一.健康]

    def _挑(self, 候选: list[条]) -> 条:
        模 = str(self.设.get("mode") or "round_robin")
        if 模 == "least_conn":
            return min(候选, key=lambda x: (x.连接, x.号))
        self.轮询 += 1
        return 候选[self.轮询 % len(候选)]

    async def 选(self, 目标: str = "") -> 条 | None:
        async with self.锁:
            候选 = self.健康们()
            if not 候选:
                候选 = [一 for 一 in self.条们 if 一.启用]
            if not 候选:
                return None
            粘住 = str(self.设.get("sticky") or "")
            if 粘住 == "host" and 目标:
                旧号 = self.粘.get(目标)
                for 一 in 候选:
                    if 一.号 == 旧号:
                        return 一
                选中 = self._挑(候选)
                self.粘[目标] = 选中.号
                return 选中
            return self._挑(候选)

    async def 进(self, 一: 条) -> None:
        async with self.锁:
            一.连接 += 1

    async def 出(self, 一: 条) -> None:
        async with self.锁:
            一.连接 = max(0, 一.连接 - 1)
        self.写状态()

    async def 记流量(self, 一: 条, 上行: int = 0, 下行: int = 0) -> None:
        async with self.锁:
            一.上行 += max(0, int(上行 or 0))
            一.下行 += max(0, int(下行 or 0))

    async def 报成(self, 一: 条) -> None:
        async with self.锁:
            一.失败 = 0
            一.健康 = True
            一.上次错误 = ""

    async def 报败(self, 一: 条, 因: str) -> None:
        要补 = False
        async with self.锁:
            一.失败 += 1
            一.上次错误 = (因 or "")[:200]
            阈 = max(1, int(self.设.get("fail_n") or 3))
            if 一.失败 >= 阈:
                一.健康 = False
                一.上次切换 = time.strftime("%Y-%m-%d %H:%M:%S") + " " + 一.上次错误
                self.粘 = {k: v for k, v in self.粘.items() if v != 一.号}
                日志.warning("摘除 %s：%s", 一.脱敏(), 一.上次错误)
                要补 = True
            self.写状态()
        if 要补:
            await self.补齐()

    # ---- 闪臣动态流量接口 ------------------------------------------------

    def 闪臣开(self) -> bool:
        return bool(str(self.设.get("sc_key") or "").strip())

    def 可自动白(self) -> bool:
        return (self.闪臣开() and bool(str(self.设.get("sc_code") or "").strip())
                and bool(int(self.设.get("sc_white") or 0)))

    def _闪臣址(self, 名: str, 参: dict[str, Any]) -> str:
        底 = str(self.设.get("sc_base") or "").strip().rstrip("/") or 默认["sc_base"]
        if not 底.startswith(("http://", "https://")):
            底 = "https://" + 底
        净 = {k: v for k, v in 参.items() if v not in (None, "")}
        return f"{底}/flow-api/{名}?{urlencode(净)}"

    def _闪臣调(self, 名: str, 参: dict[str, Any]) -> tuple[int, str, Any]:
        """调一次接口并拆 {code,message,data} 信封，返回 (码, 人话, 数据)。阻塞。"""
        try:
            求 = Request(self._闪臣址(名, 参), headers={"User-Agent": "xui-bridge"})
            with urlopen(求, timeout=20) as r:
                文 = r.read().decode("utf-8", "replace")
        except Exception as 错:
            return -1, f"连不上闪臣：{错}", None
        包 = 解信封(文)
        if 包 is None:
            return -1, f"闪臣返回看不懂：{(文 or '').strip()[:140]}", None
        码, 话, 数 = 包
        return 码, (话 or "ok") if 码 == 0 else 闪臣说(码, 话), 数

    def 本机出口IP(self) -> str:
        """问一下外面看到的是哪个 IP，白名单要加的就是它。缓存十分钟。"""
        缓 = str(self.闪臣态.get("本机IP") or "")
        if 缓 and time.time() - float(self.闪臣态.get("IP时间") or 0) < 600:
            return 缓
        for 址 in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://ipinfo.io/ip"):
            try:
                求 = Request(址, headers={"User-Agent": "curl/8"})
                with urlopen(求, timeout=8) as r:
                    文 = r.read().decode("utf-8", "replace").strip()
            except Exception:
                continue
            if 文 and len(文) <= 45 and all(c in "0123456789abcdefABCDEF.:" for c in 文):
                self.闪臣态["本机IP"] = 文
                self.闪臣态["IP时间"] = time.time()
                return 文
        return 缓

    def 加白名单(self, ip: str = "", 备注: str = "xui-bridge") -> tuple[bool, str]:
        """ip 留空就让闪臣按请求来源 IP 加，正好是本机出口。阻塞。"""
        if not self.闪臣开():
            return False, "没填 API Key"
        安全码 = str(self.设.get("sc_code") or "").strip()
        if not 安全码:
            return False, "没填安全码，闪臣要求改白名单必须带安全码"
        码, 说, _ = self._闪臣调("whitelist-add.html", {
            "key": str(self.设.get("sc_key") or "").strip(),
            "security_code": 安全码,
            "ip": str(ip or "").strip(),
            "remark": 备注,
        })
        好 = 码 == 0
        self.闪臣态["白名单说"] = f"{time.strftime('%H:%M:%S')} {'已加入白名单' if 好 else 说}"
        (日志.info if 好 else 日志.warning)("加白名单：%s", 说)
        if 好:
            self.查白名单()
        return 好, 说

    def 删白名单(self, 号: str = "", ip: str = "") -> tuple[bool, str]:
        安全码 = str(self.设.get("sc_code") or "").strip()
        if not self.闪臣开() or not 安全码:
            return False, "要先填 API Key 和安全码"
        if not str(号 or "").strip() and not str(ip or "").strip():
            return False, "得给 id 或 ip"
        码, 说, _ = self._闪臣调("whitelist-remove.html", {
            "key": str(self.设.get("sc_key") or "").strip(),
            "security_code": 安全码,
            "id": str(号 or "").strip(),
            "ip": str(ip or "").strip(),
        })
        好 = 码 == 0
        self.闪臣态["白名单说"] = f"{time.strftime('%H:%M:%S')} {'已删除' if 好 else 说}"
        if 好:
            self.查白名单()
        return 好, 说

    def 查余额(self) -> tuple[bool, str]:
        if not self.闪臣开():
            return False, "没填 API Key"
        码, 说, 数 = self._闪臣调("traffic-balance.html", {
            "key": str(self.设.get("sc_key") or "").strip(),
        })
        if 码 != 0 or not isinstance(数, dict):
            self.闪臣态["余额说"] = 说
            return False, 说
        文 = str(数.get("traffic_balance_text") or "").strip()
        if not 文:
            文 = f"{数.get('traffic_balance_gb') or 0} GB"
        self.闪臣态["余额"] = 文
        self.闪臣态["有套餐"] = bool(数.get("has_package"))
        self.闪臣态["余额说"] = "" if 数.get("has_package") else "账号没有生效中的流量套餐"
        return True, 文

    def 查白名单(self) -> tuple[bool, list[dict]]:
        if not self.闪臣开():
            return False, []
        码, 说, 数 = self._闪臣调("whitelist.html", {
            "key": str(self.设.get("sc_key") or "").strip(),
        })
        if 码 != 0:
            self.闪臣态["白名单说"] = 说
            return False, []
        原 = 数.get("whitelist") if isinstance(数, dict) else 数
        列 = [_白条(一) for 一 in (原 or []) if 一]
        self.闪臣态["白名单"] = 列
        return True, 列

    def 刷闪臣(self) -> None:
        """余额、白名单、本机出口 IP 一次刷全。阻塞，需放线程里跑。"""
        if not self.闪臣开():
            return
        self.闪臣态["本机IP"] = self.本机出口IP()
        self.查余额()
        self.查白名单()
        self.闪臣态["刷时间"] = time.strftime("%H:%M:%S")

    def 提取地址(self) -> str:
        """填了闪臣 Key 就按参数自动拼提取地址，否则用手填的 fetch_url。"""
        if not self.闪臣开():
            return str(self.设.get("fetch_url") or "").strip()
        return self._闪臣址("get-ip.html", {
            "key": str(self.设.get("sc_key") or "").strip(),
            "count": max(1, min(500, int(self.设.get("sc_count") or 1))),
            "time": int(self.设.get("sc_time") or 0),
            "protocol": str(self.设.get("sc_protocol") or "http"),
            # 桥是按行读的，只认 user:pass@host:port 且以 \n 分隔
            "type": "text",
            "pattern": 1,
            "textSep": 3,
            "cntry": str(self.设.get("sc_cntry") or "").strip(),
            "state": str(self.设.get("sc_state") or "").strip(),
            "city": str(self.设.get("sc_city") or "").strip(),
        })

    def 提取地址显(self) -> str:
        址, 键 = self.提取地址(), str(self.设.get("sc_key") or "").strip()
        return 址.replace(键, 遮(键)) if 键 and 键 in 址 else 址

    def 拉取方案(self) -> str:
        """闪臣接口的三种文本格式都不带协议，只能按套餐参数定。"""
        if self.闪臣开():
            s5 = str(self.设.get("sc_protocol") or "http").lower() in ("s5", "socks5")
            return "socks5" if s5 else "http"
        return 规范协议(self.设.get("fetch_scheme")) if self.设.get("fetch_scheme") else ""

    def 闪臣快照(self) -> dict[str, Any]:
        本机 = str(self.闪臣态.get("本机IP") or "")
        白 = list(self.闪臣态.get("白名单") or [])
        return {
            "开": self.闪臣开(),
            "有码": bool(str(self.设.get("sc_code") or "").strip()),
            "余额": self.闪臣态.get("余额") or "",
            "有套餐": bool(self.闪臣态.get("有套餐")),
            "余额说": self.闪臣态.get("余额说") or "",
            "白名单": 白,
            "白名单说": self.闪臣态.get("白名单说") or "",
            "本机IP": 本机,
            "已加白": bool(本机) and any(一.get("ip") == 本机 for 一 in 白),
            "刷时间": self.闪臣态.get("刷时间") or "",
            "提取地址": self.提取地址显(),
        }

    # ---- 提取与补池 ------------------------------------------------------

    def 有拉取源(self) -> bool:
        return bool(self.提取地址() or str(self.设.get("fetch_cmd") or "").strip())

    def _取文(self, 址: str, 令: str) -> tuple[str, str]:
        """按地址或命令取一次原始文本，返回 (正文, 出错说明)。"""
        try:
            if 址:
                求 = Request(址, headers={"User-Agent": "xui-bridge"})
                with urlopen(求, timeout=20) as r:
                    return r.read().decode("utf-8", "replace"), ""
            import subprocess
            出 = subprocess.check_output(令, shell=True, timeout=30, stderr=subprocess.STDOUT)
            return 出.decode("utf-8", "replace"), ""
        except Exception as 错:
            return "", str(错)

    def _解代理行(self, 文: str) -> list[dict]:
        指定 = self.拉取方案()
        出 = []
        for 行 in (文 or "").replace("\r", "\n").split("\n"):
            行 = 行.strip()
            if not 行 or 行.startswith("#") or 行.startswith(("{", "[")):
                continue
            try:
                信 = 拆(行)
            except ValueError:
                continue
            if 指定:
                信["方案"] = 指定
            出.append(信)
        return 出

    def 拉取一批(self) -> list[dict]:
        """调一次提取接口，把返回的每一行都解析出来。阻塞，需放线程里跑。"""
        址, 令 = self.提取地址(), str(self.设.get("fetch_cmd") or "").strip()
        if not 址 and not 令:
            return []
        文, 错文 = self._取文(址, 令)
        包 = 解信封(文) if not 错文 else None
        if 包 and 包[0] == 1004 and 址 and self.可自动白():
            好, 白说 = self.加白名单()
            日志.info("提取撞上 1004，自动加白名单：%s", 白说)
            if 好:
                time.sleep(2)
                文, 错文 = self._取文(址, "")
                包 = 解信封(文) if not 错文 else None
        if 错文:
            self.上次补 = f"拉取失败 {time.strftime('%H:%M:%S')} {错文}"
            日志.warning("%s", self.上次补)
            return []
        if 包 and 包[0] != 0:
            self.上次补 = f"接口拒绝 {time.strftime('%H:%M:%S')} {闪臣说(包[0], 包[1])}"
            日志.warning("%s", self.上次补)
            return []
        出 = self._解代理行(文)
        if not 出:
            self.上次补 = (f"拉取无有效行 {time.strftime('%H:%M:%S')}，"
                          f"接口返回：{(文 or '').strip()[:140]}")
            日志.warning("%s", self.上次补)
        return 出

    def 拉取下一条(self) -> dict | None:
        批 = self.拉取一批()
        return 批[0] if 批 else None

    async def 补齐(self) -> str:
        目标 = max(0, int(self.设.get("pool_size") or 0))
        async with self.锁:
            健康数 = len(self.健康们())
        if 目标 <= 0 or 健康数 >= 目标:
            return "池已够，不补"
        if not self.有拉取源():
            说 = "健康不足但没配提取来源（闪臣 Key 或 fetch_url / fetch_cmd），保持现有池"
            self.上次补 = 说
            return 说
        要 = 目标 - 健康数
        成 = 0
        批 = await asyncio.to_thread(self.拉取一批)
        for 信 in 批:
            if 成 >= 要:
                break
            try:
                await self.加(信, 来源="拉取")
                成 += 1
            except ValueError as 错:
                日志.warning("拉取入池失败：%s", 错)
        说 = f"补入 {成} 条，健康 {len(self.健康们())}/{目标}"
        self.上次补 = 说
        日志.info("%s", 说)
        return 说

    async def 换新(self) -> str:
        """丢掉全部拉取来的代理，重新提一批。手动添加的保留不动。"""
        if not self.有拉取源():
            说 = "未配置提取接口，无法换新"
            self.上次补 = 说
            return 说
        批 = await asyncio.to_thread(self.拉取一批)
        if not 批:
            return self.上次补 or "换新失败，保持原池"
        async with self.锁:
            self.条们 = [一 for 一 in self.条们 if 一.来源 != "拉取"]
            self.粘 = {}
            for 信 in 批:
                try:
                    self._塞(信, 来源="拉取", 落盘=False)
                except ValueError as 错:
                    日志.warning("换新入池失败：%s", 错)
            self.落盘()
            数 = len([一 for 一 in self.条们 if 一.来源 == "拉取"])
        说 = f"已换新，拉取来源 {数} 条 {time.strftime('%H:%M:%S')}"
        self.上次补 = 说
        日志.info("%s", 说)
        return 说

    def 总览(self) -> dict[str, Any]:
        return {
            "listen": f"{self.设['listen']}:{self.听口()}",
            "web": f"{self.设['web']}:{self.网页口()}",
            "mode": self.设["mode"],
            "sticky": self.设["sticky"] or "关",
            "pool_size": int(self.设["pool_size"]),
            "fail_n": int(self.设["fail_n"]),
            "check_interval": int(self.设["check_interval"]),
            "check_conc": int(self.设.get("check_conc") or 16),
            "check_host": self.设.get("check_host") or "www.dola.com",
            "check_port": int(self.设.get("check_port") or 443),
            "connect_timeout": int(self.设["connect_timeout"]),
            "fetch_url": self.设["fetch_url"],
            "fetch_cmd": self.设["fetch_cmd"],
            "fetch_scheme": self.设.get("fetch_scheme") or "",
            "auto_rotate": int(self.设.get("auto_rotate") or 0),
            "sc_base": self.设.get("sc_base") or 默认["sc_base"],
            "sc_key": self.设.get("sc_key") or "",
            "sc_count": int(self.设.get("sc_count") or 1),
            "sc_time": int(self.设.get("sc_time") or 0),
            "sc_protocol": self.设.get("sc_protocol") or "http",
            "sc_cntry": self.设.get("sc_cntry") or "",
            "sc_state": self.设.get("sc_state") or "",
            "sc_city": self.设.get("sc_city") or "",
            "sc_white": int(self.设.get("sc_white") or 0),
            "闪臣": self.闪臣快照(),
            "上次补": self.上次补,
            "健康": len(self.健康们()),
            "总数": len(self.条们),
            "上行": sum(一.上行 for 一 in self.条们),
            "下行": sum(一.下行 for 一 in self.条们),
            "上行文": 人读(sum(一.上行 for 一 in self.条们)),
            "下行文": 人读(sum(一.下行 for 一 in self.条们)),
            "池": [一.快照() for 一 in self.条们],
        }
