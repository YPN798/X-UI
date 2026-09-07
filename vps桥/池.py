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
from urllib.request import Request, urlopen

from 解析 import 本机主机, 拆, 给上游, 规范协议

日志 = logging.getLogger("xui桥")


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
    "connect_timeout": 8,
    "fetch_url": "",
    "fetch_cmd": "",
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
            "connect_timeout": int(self.设["connect_timeout"]),
            "fetch_url": self.设["fetch_url"],
            "fetch_cmd": self.设["fetch_cmd"],
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
            for k in ("mode", "sticky", "fetch_url", "fetch_cmd"):
                if k in 补 and 补[k] is not None:
                    self.设[k] = 补[k]
            for k in ("pool_size", "fail_n", "check_interval", "check_conc", "connect_timeout"):
                if k in 补 and 补[k] not in (None, ""):
                    self.设[k] = int(补[k])
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

    def 拉取下一条(self) -> dict | None:
        址 = str(self.设.get("fetch_url") or "").strip()
        令 = str(self.设.get("fetch_cmd") or "").strip()
        文 = ""
        try:
            if 址:
                求 = Request(址, headers={"User-Agent": "xui-bridge"})
                with urlopen(求, timeout=15) as r:
                    文 = r.read().decode("utf-8", "replace")
            elif 令:
                import subprocess
                文 = subprocess.check_output(
                    令, shell=True, timeout=30, stderr=subprocess.STDOUT,
                ).decode("utf-8", "replace")
            else:
                return None
        except Exception as 错:
            self.上次补 = f"拉取失败 {time.strftime('%H:%M:%S')} {错}"
            日志.warning("%s", self.上次补)
            return None
        for 行 in (文 or "").splitlines():
            行 = 行.strip()
            if not 行 or 行.startswith("#"):
                continue
            try:
                return 拆(行)
            except ValueError:
                continue
        self.上次补 = f"拉取无有效行 {time.strftime('%H:%M:%S')}"
        return None

    async def 补齐(self) -> str:
        目标 = max(0, int(self.设.get("pool_size") or 0))
        async with self.锁:
            健康数 = len(self.健康们())
        if 目标 <= 0 or 健康数 >= 目标:
            return "池已够，不补"
        if not str(self.设.get("fetch_url") or "").strip() and not str(self.设.get("fetch_cmd") or "").strip():
            说 = "健康不足但未配置 fetch_url / fetch_cmd，保持现有池"
            self.上次补 = 说
            return 说
        要 = 目标 - 健康数
        成 = 0
        for _ in range(要):
            信 = await asyncio.to_thread(self.拉取下一条)
            if not 信:
                break
            try:
                await self.加(给上游(信), 来源="拉取")
                成 += 1
            except ValueError as 错:
                日志.warning("拉取入池失败：%s", 错)
        说 = f"补入 {成} 条，健康 {len(self.健康们())}/{目标}"
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
            "connect_timeout": int(self.设["connect_timeout"]),
            "fetch_url": self.设["fetch_url"],
            "fetch_cmd": self.设["fetch_cmd"],
            "上次补": self.上次补,
            "健康": len(self.健康们()),
            "总数": len(self.条们),
            "上行": sum(一.上行 for 一 in self.条们),
            "下行": sum(一.下行 for 一 in self.条们),
            "上行文": 人读(sum(一.上行 for 一 in self.条们)),
            "下行文": 人读(sum(一.下行 for 一 in self.条们)),
            "池": [一.快照() for 一 in self.条们],
        }
