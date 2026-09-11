# -*- coding: utf-8 -*-
"""代理池：挑选、失败计数、拉取补池、落盘。"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
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
    "pool_size": 30,
    "mode": "round_robin",
    "sticky": "",
    "fail_n": 3,
    "check_interval": 120,
    "check_conc": 16,
    "check_host": "www.dola.com",
    "check_port": 443,
    "connect_timeout": 8,
    "fetch_url": "",
    "fetch_cmd": "",
    "fetch_scheme": "",
    "auto_rotate": 300,
    "sc_base": "https://global.shanchendaili.com",
    "sc_key": "",
    "sc_code": "",
    "sc_count": 30,
    "sc_time": 0,
    "sc_protocol": "s5",
    # 三格留空=每批随机一国，一次提够指定条数。钉死了就按钉的提
    "sc_cntry": "",
    "sc_state": "",
    "sc_city": "",
    "sc_white": 1,
    # auto=谁有凭证用谁；两家都填则按上次成功的，失败换另一家
    "provider": "auto",
    "go_base": "https://api.ipipgo.com",
    "go_key": "",
    "go_url": "",
    "go_user": "",
    "go_pass": "",
    "go_host": "proxy.ipipgo.com",
    "go_port": 1080,
    "defaults_ver": 4,
    "web_pass": "YPN940815...",
    # 自己去仓库拉新代码。auto_update 0=关，1=开
    "auto_update": 1,
    "update_minutes": 5,
    "update_base": "https://raw.githubusercontent.com/YPN798/X-UI/main",
    "proxies": [],
}

# 面板右上角显示，好核对 VPS 上跑的到底是不是最新代码
版本 = "2026-09-11.2"

闪臣主机 = "shanchendaili.com"
ipipgo主机 = "ipipgo.com"

# 三格留空时每批从这里抽一个，整批同一国。
# 这 9 个是逐个开浏览器进 dola 人工确认过能正常用的，其余地区都撞区域受限，
# 别凭「闪臣提得到」就往里加，提得到不等于 dola 认。
随机国库 = (
    "JP", "KR", "SG", "TH", "VN", "MY", "PH", "ID", "BR",
)


def 地区文(国: str, 州: str = "", 市: str = "") -> str:
    return "/".join(x for x in (国, 州, 市) if x)


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
        # 经这条代理出去后外面看到的国家/城市/IP，探一次记下来
        self.出口 = str(信.get("出口") or "")

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
            "出口": self.出口,
        }


class 池:
    def __init__(self, 径: Path) -> None:
        self.径 = 径
        self.锁 = asyncio.Lock()
        self.轮询 = 0
        self.粘: dict[str, str] = {}
        self.上次补 = ""
        self.上次换新 = ""
        self.这批地区 = ""
        self.上次源 = ""
        # 验活循环每轮把自己的计时基准放这儿，面板好算还有多久换下一批
        self.换基 = 0.0
        self.上轮验活 = ""
        self.更新说 = ""
        self.设: dict[str, Any] = dict(默认)
        self.条们: list[条] = []
        self.闪臣态: dict[str, Any] = {
            "余额": "", "有套餐": False, "余额说": "",
            "白名单": [], "白名单说": "",
            "本机IP": "", "IP时间": 0.0, "刷时间": "",
        }
        # 累计流量跟着桥走，换新丢代理、重启都不清零
        self.总上行 = 0
        self.总下行 = 0
        self.起算 = time.strftime("%Y-%m-%d %H:%M")
        self._流量落盘 = 0.0
        self._补中 = False
        self.读盘()

    def 读盘(self) -> None:
        原 = dict(默认)
        盘: dict[str, Any] = {}
        if self.径.is_file():
            try:
                文 = json.loads(self.径.read_text(encoding="utf-8"))
                if isinstance(文, dict):
                    盘, 原 = 文, {**原, **文}
            except Exception as 错:
                日志.warning("读配置失败 %s：%s", self.径, 错)
        self.设 = {**默认, **{k: 原.get(k, 默认[k]) for k in 默认}}
        # 只看磁盘上写没写 defaults_ver，不能看合并后的 原——默认值会把缺项填成新版
        try:
            旧版 = int(盘["defaults_ver"]) if "defaults_ver" in 盘 else 0
        except (TypeError, ValueError):
            旧版 = 0
        if not 盘:
            旧版 = int(默认["defaults_ver"])
        要升 = 旧版 < int(默认["defaults_ver"])
        if 要升:
            if 旧版 < 2:
                for k in ("pool_size", "check_interval", "check_conc", "auto_rotate",
                          "sc_count", "sc_time", "sc_white"):
                    self.设[k] = 默认[k]
            # v2 曾把协议写成 http、地区钉死洛杉矶，DOLA 会全部走不通
            是旧默认 = (str(self.设.get("sc_cntry") or ""), str(self.设.get("sc_state") or ""),
                       str(self.设.get("sc_city") or "")) == ("US", "California", "Losangeles")
            if 是旧默认:
                self.设["sc_cntry"] = ""
                self.设["sc_state"] = ""
                self.设["sc_city"] = ""
                self.设["sc_protocol"] = 默认["sc_protocol"]
            # v3 钉的是东京。那也是我们塞的，不是用户挑的，一并放回随机
            if 旧版 < 4 and (str(self.设.get("sc_cntry") or ""), str(self.设.get("sc_state") or ""),
                             str(self.设.get("sc_city") or "")) == ("JP", "Tokyo", ""):
                self.设["sc_cntry"] = self.设["sc_state"] = self.设["sc_city"] = ""
            self.设["defaults_ver"] = 默认["defaults_ver"]
        self.条们 = []
        for 一 in 原.get("proxies") or []:
            # 新格式 {"串":..., "来源":...}；老格式和 install.sh 追加的是纯字符串
            源 = "手加"
            if isinstance(一, dict) and 一.get("串"):
                源, 一 = str(一.get("来源") or "手加"), 一["串"]
            # 闪臣的线路只可能是提取来的。补来源之前存下的那批被当成手加，
            # 换新永远清不掉，池子从 30 涨到 56。不管存成什么格式，一律认回拉取
            if 闪臣主机 in str(一) or ipipgo主机 in str(一):
                源 = "拉取"
            try:
                self._塞(一, 来源=源, 落盘=False)
            except ValueError as 错:
                日志.warning("跳过非法代理：%s", 错)
        self._复流量()
        if 要升:
            日志.info("配置已升到默认 v%s：每批 %s 条，地区 %s/%s/%s，验活 %s 秒，换新 %s 秒",
                      self.设["defaults_ver"], self.设["sc_count"],
                      self.设["sc_cntry"], self.设["sc_state"], self.设["sc_city"],
                      self.设["check_interval"], self.设["auto_rotate"])
            self.落盘()

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
            "provider": self.设.get("provider") or "auto",
            "go_base": self.设.get("go_base") or 默认["go_base"],
            "go_key": self.设.get("go_key") or "",
            "go_url": self.设.get("go_url") or "",
            "go_user": self.设.get("go_user") or "",
            "go_pass": self.设.get("go_pass") or "",
            "go_host": self.设.get("go_host") or 默认["go_host"],
            "go_port": int(self.设.get("go_port") or 默认["go_port"]),
            "defaults_ver": int(self.设.get("defaults_ver") or 默认["defaults_ver"]),
            "web_pass": self.设["web_pass"],
            "auto_update": int(self.设.get("auto_update") or 0),
            "update_minutes": self.查更分(),
            "update_base": self.设.get("update_base") or 默认["update_base"],
            # 来源必须一起存，否则重启后拉取来的全变成手加，换新再也换不掉它们
            "proxies": [{"串": 一.串(), "来源": 一.来源} for 一 in self.条们],
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
        条们 = [一 for 一 in (文.get("池") or []) if isinstance(一, dict)]
        # 按「协议|主机|端口|用户」对，不能按地址——闪臣整池同一个入口，
        # 按地址会让每条都认领同一份历史，总量被放大十几倍
        旧 = {str(一["键"]): 一 for 一 in 条们 if 一.get("键")}
        for 一 in self.条们:
            命 = 旧.get(一.键())
            if not 命:
                continue
            一.上行 = int(命.get("上行") or 0)
            一.下行 = int(命.get("下行") or 0)
            一.出口 = str(命.get("出口") or "")
        self.起算 = str(文.get("起算") or self.起算)
        self.上次补 = str(文.get("上次补") or "")
        self.上次换新 = str(文.get("上次换新") or "")
        self.这批地区 = str(文.get("这批地区") or "")
        self.上次源 = str(文.get("上次源") or "")
        if "总上行" in 文 or "总下行" in 文:
            self.总上行 = int(文.get("总上行") or 0)
            self.总下行 = int(文.get("总下行") or 0)
        else:
            # 旧状态文件没有累计项，用各条之和垫上，别让已有的量凭空消失
            self.总上行 = sum(int(一.get("上行") or 0) for 一 in 条们)
            self.总下行 = sum(int(一.get("下行") or 0) for 一 in 条们)

    def 写状态(self) -> None:
        出 = {
            "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "版本": 版本,
            "上次补": self.上次补,
            "上次换新": self.上次换新,
            "这批地区": self.这批地区,
            "上次源": self.上次源,
            "上轮验活": self.上轮验活,
            "模式": self.设["mode"],
            "粘住": self.设["sticky"],
            "起算": self.起算,
            "总上行": self.总上行,
            "总下行": self.总下行,
            # 键只落盘不上接口，页面看到的还是脱敏地址
            "池": [{**一.快照(), "键": 一.键()} for 一 in self.条们],
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
                      "sc_base", "sc_key", "sc_protocol", "sc_cntry", "sc_state", "sc_city",
                      "provider", "go_base", "go_key", "go_url", "go_user", "go_host"):
                if k in 补 and 补[k] is not None:
                    self.设[k] = str(补[k]).strip()
            for k in ("pool_size", "fail_n", "check_interval", "check_conc",
                      "connect_timeout", "auto_rotate", "sc_count", "sc_time", "sc_white",
                      "go_port", "auto_update", "update_minutes"):
                if k in 补 and 补[k] not in (None, ""):
                    self.设[k] = int(补[k])
            # 安全码 / IPIPGO 密码只写：页面永远不回显，留空表示保持原样
            if str(补.get("sc_code") or "").strip():
                self.设["sc_code"] = str(补["sc_code"]).strip()
                self.闪臣态["码锁到"] = 0.0
            if str(补.get("go_pass") or "").strip():
                self.设["go_pass"] = str(补["go_pass"]).strip()
            键或址 = str(补.get("go_key") or "").strip()
            if 键或址.startswith(("http://", "https://")):
                self.设["go_url"] = 键或址
            self.落盘()

    def 查更分(self) -> int:
        """多少分钟查一次新代码。下限 1 分钟，别把 GitHub 当心跳打。"""
        值 = self.设.get("update_minutes")
        if 值 in (None, ""):
            # 早先的配置写的是小时，别让它升级完变成每小时查一次
            时 = self.设.get("update_hours")
            值 = int(时) * 60 if 时 not in (None, "") else 默认["update_minutes"]
        try:
            return max(1, int(值))
        except (TypeError, ValueError):
            return int(默认["update_minutes"])

    def 有效换期(self) -> int:
        """真正采用的换新间隔（秒）。尊重 IP 时长：长效 IP 不在到期前被换掉。

        sc_time 是闪臣的时长档，不是分钟数：
          0 = 5-30 分钟（默认短效）  2 = 1-6 小时  1 = 每请求一换
        用户把「自动换新秒」设成 300，却选了 1-6 小时，等于每 5 分钟就把
        还没到期的 IP 扔了。这里给一个按档位的下限，取两者较大值。
        """
        设换 = max(0, int(self.设.get("auto_rotate") or 0))
        模 = int(self.设.get("sc_time") or 0)
        if 模 == 1:
            return 0  # 每请求一换，池里就 1 条，用不着定时换新
        if 设换 <= 0:
            return 0  # 用户主动关了自动换新
        下限 = 3600 if 模 == 2 else 300
        return max(设换, 下限)

    def 换说(self) -> str:
        期 = self.有效换期()
        if 期 <= 0:
            模 = int(self.设.get("sc_time") or 0)
            return "每请求一换" if 模 == 1 else "关"
        设换 = max(0, int(self.设.get("auto_rotate") or 0))
        return f"每 {期} 秒" + ("（按 IP 时长抬到下限）" if 期 > 设换 else "")

    def 下次换秒(self) -> int:
        """还有多少秒换下一批。没开自动换新返回 -1。"""
        换期 = self.有效换期()
        if not 换期 or not self.换基:
            return -1
        return max(0, int(换期 - (time.monotonic() - self.换基)))

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
        上, 下 = max(0, int(上行 or 0)), max(0, int(下行 or 0))
        async with self.锁:
            一.上行 += 上
            一.下行 += 下
            self.总上行 += 上
            self.总下行 += 下
        # 长连接以前要攒满 256KB 或断开才写盘，面板会半天不动
        now = time.monotonic()
        if now - float(self._流量落盘 or 0) >= 2:
            self._流量落盘 = now
            self.写状态()

    async def 清流量(self) -> str:
        async with self.锁:
            self.总上行 = self.总下行 = 0
            self.起算 = time.strftime("%Y-%m-%d %H:%M")
            for 一 in self.条们:
                一.上行 = 一.下行 = 0
            self.写状态()
        return f"流量计数已清零，从 {self.起算} 重新算"

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
            # 补池要跑一趟闪臣接口，不能让正在等着的那个请求陪着卡
            self._后台补齐()

    def _后台补齐(self) -> None:
        if self._补中:
            return

        async def 跑() -> None:
            try:
                await self.补齐()
            except Exception as 错:
                日志.warning("后台补池失败：%s", 错)
            finally:
                self._补中 = False

        try:
            asyncio.get_running_loop().create_task(跑())
            self._补中 = True
        except RuntimeError:
            pass

    # ---- 闪臣动态流量接口 ------------------------------------------------

    def 闪臣开(self) -> bool:
        return bool(str(self.设.get("sc_key") or "").strip())

    def ipipgo开(self) -> bool:
        return bool(
            str(self.设.get("go_key") or "").strip()
            or str(self.设.get("go_url") or "").strip()
            or (str(self.设.get("go_user") or "").strip()
                and str(self.设.get("go_pass") or "").strip())
        )

    def 当前源(self) -> str:
        序 = self.源顺序()
        return 序[0] if 序 else ""

    def 源顺序(self) -> list[str]:
        选 = str(self.设.get("provider") or "auto").strip() or "auto"
        闪, 果 = self.闪臣开(), self.ipipgo开()
        if 选 == "shanchen":
            return ["shanchen"] if 闪 else []
        if 选 == "ipipgo":
            return ["ipipgo"] if 果 else []
        序: list[str] = []
        if self.上次源 == "ipipgo" and 果:
            序.append("ipipgo")
        if 闪:
            序.append("shanchen")
        if 果 and "ipipgo" not in 序:
            序.append("ipipgo")
        return 序

    def 源名(self, 源: str = "") -> str:
        return {"shanchen": "闪臣", "ipipgo": "IPIPGO"}.get(源 or self.当前源(), "无")

    def 码锁着(self) -> bool:
        """闪臣对连续错的安全码会上锁，越试锁得越久，所以撞过 1006 就先停手。"""
        return time.time() < float(self.闪臣态.get("码锁到") or 0)

    def 可自动白(self) -> bool:
        return (self.闪臣开() and bool(str(self.设.get("sc_code") or "").strip())
                and bool(int(self.设.get("sc_white") or 0)) and not self.码锁着())

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
        for 址 in ("https://api.ipify.org", "https://ifconfig.me/ip",
                   "https://checkip.amazonaws.com", "https://api.ip.sb/ip"):
            try:
                求 = Request(址, headers={"User-Agent": "curl/8"})
                with urlopen(求, timeout=5) as r:
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
        if 码 == 1006:
            self.闪臣态["码锁到"] = time.time() + 600
            说 += "。已暂停自动重试 10 分钟，重存一次安全码可立刻解除"
        elif 好:
            self.闪臣态["码锁到"] = 0.0
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

    async def 一键开跑(self, 键: str, 码: str, 供应商: str = "",
                    go_key: str = "", go_user: str = "", go_pass: str = "") -> list[str]:
        """面板上就这一个按钮：存两家的参数、加白名单、提一批、开定时换新。"""
        补: dict[str, Any] = {"sc_white": 1}
        if 供应商:
            补["provider"] = 供应商
        if 键:
            补["sc_key"] = 键
        if 码:
            补["sc_code"] = 码
        if go_key:
            补["go_key"] = go_key
        if go_user:
            补["go_user"] = go_user
        if go_pass:
            补["go_pass"] = go_pass
        # 第一次开跑才铺默认值。之后再点，高级设置里调过的地区、条数不能被冲掉
        if not self.有拉取源():
            补.update({
                "sc_count": int(默认["sc_count"]), "pool_size": int(默认["pool_size"]),
                "sc_time": int(默认["sc_time"]), "sc_protocol": 默认["sc_protocol"],
                "sc_cntry": 默认["sc_cntry"], "sc_state": 默认["sc_state"],
                "sc_city": 默认["sc_city"], "auto_rotate": int(默认["auto_rotate"]),
                "check_interval": int(默认["check_interval"]),
            })
        await self.改设(补)
        if not self.有拉取源():
            return ["闪臣和 IPIPGO 都没填，池子保持现状。"]
        步 = [f"提取源：{self.源名()}（选的是 {self.设.get('provider') or 'auto'}）"]
        if 键:
            步.append(f"闪臣 Key {遮(键)}" + ("，安全码已更新" if 码 else ""))
        if go_key:
            步.append("IPIPGO 凭证已更新")
        if self.闪臣开():
            if not str(self.设.get("sc_code") or "").strip():
                步.append("闪臣还没存安全码——加白名单必须要它。")
            else:
                await asyncio.to_thread(self.加白名单)
            await asyncio.to_thread(self.刷闪臣)
            快 = self.闪臣快照()
            步.append(f"闪臣剩余：{快['余额'] or 快['余额说'] or '查不到'}")
            步.append(f"本机出口 IP {快['本机IP'] or '没问到'}："
                      + ("已在闪臣白名单" if 快["已加白"] else "不在闪臣白名单"))
        elif self.ipipgo开():
            本 = self.本机出口IP()
            步.append(f"本机出口 IP {本 or '没问到'}。IPIPGO 要在他们后台把这个 IP 加白名单。")
        步.append(await self.换新())
        步.append(f"自动换新：{self.换说()}，每批 {int(self.设.get('sc_count') or 1)} 条、一国")
        return 步

    def _钉地区(self) -> tuple[str, str, str]:
        return (
            str(self.设.get("sc_cntry") or "").strip(),
            str(self.设.get("sc_state") or "").strip(),
            str(self.设.get("sc_city") or "").strip(),
        )

    def 提取条数(self, 数: int | None = None) -> int:
        if 数 is None:
            数 = int(self.设.get("sc_count") or self.设.get("pool_size") or 1)
        return max(1, min(500, int(数)))

    def 提取地址(self, 国: str | None = None, 州: str | None = None, 市: str | None = None,
                数: int | None = None) -> str:
        """填了闪臣 Key 就按参数自动拼提取地址，否则用手填的 fetch_url。"""
        if not self.闪臣开():
            return str(self.设.get("fetch_url") or "").strip()
        国 = str(self.设.get("sc_cntry") or "").strip() if 国 is None else str(国 or "").strip()
        州 = str(self.设.get("sc_state") or "").strip() if 州 is None else str(州 or "").strip()
        市 = str(self.设.get("sc_city") or "").strip() if 市 is None else str(市 or "").strip()
        return self._闪臣址("get-ip.html", {
            "key": str(self.设.get("sc_key") or "").strip(),
            "count": self.提取条数(数),
            "time": int(self.设.get("sc_time") or 0),
            "protocol": str(self.设.get("sc_protocol") or "s5"),
            # 桥是按行读的，只认 user:pass@host:port 且以 \n 分隔
            "type": "text",
            "pattern": 1,
            "textSep": 3,
            "cntry": 国,
            "state": 州,
            "city": 市,
        })

    def 提取地址显(self) -> str:
        钉 = self._钉地区()
        国 = (self.这批地区.split("/")[0] if self.这批地区 and not any(钉) else "")
        if self.当前源() == "ipipgo":
            址 = self.ipipgo提取地址(国 or 钉[0], 钉[1], 钉[2], self.提取条数())
            键 = str(self.设.get("go_key") or "").strip()
        else:
            址 = self.提取地址(国 or None, None, None) if 国 else self.提取地址()
            键 = str(self.设.get("sc_key") or "").strip()
        return 址.replace(键, 遮(键)) if 键 and 键 in 址 else 址

    def 拉取方案(self) -> str:
        """闪臣接口的三种文本格式都不带协议，只能按套餐参数定。"""
        if self.闪臣开() or self.ipipgo开():
            s5 = str(self.设.get("sc_protocol") or "s5").lower() in ("s5", "socks5")
            return "socks5" if s5 else "http"
        return 规范协议(self.设.get("fetch_scheme")) if self.设.get("fetch_scheme") else ""

    def 闪臣快照(self) -> dict[str, Any]:
        本机 = str(self.闪臣态.get("本机IP") or "")
        白 = list(self.闪臣态.get("白名单") or [])
        return {
            "开": self.闪臣开() or self.ipipgo开(),
            "闪臣开": self.闪臣开(),
            "ipipgo开": self.ipipgo开(),
            "供应商": self.源名(),
            "供应商选": self.设.get("provider") or "auto",
            "go_key": self.设.get("go_key") or "",
            "go_url": self.设.get("go_url") or "",
            "go_user": self.设.get("go_user") or "",
            "有go密": bool(str(self.设.get("go_pass") or "").strip()),
            "有码": bool(str(self.设.get("sc_code") or "").strip()),
            # 只报位数，好让人一眼看出存进去的是不是自己那串
            "码长": len(str(self.设.get("sc_code") or "").strip()),
            "余额": self.闪臣态.get("余额") or "",
            "有套餐": bool(self.闪臣态.get("有套餐")),
            "余额说": self.闪臣态.get("余额说") or "",
            "白名单": 白,
            "白名单说": self.闪臣态.get("白名单说") or "",
            "本机IP": 本机,
            "已加白": bool(本机) and any(一.get("ip") == 本机 for 一 in 白),
            "刷时间": self.闪臣态.get("刷时间") or "",
            "提取地址": self.提取地址显(),
            "地区": self.地区说(),
        }

    # ---- 提取与补池 ------------------------------------------------------

    def 有拉取源(self) -> bool:
        return bool(self.闪臣开() or self.ipipgo开()
                    or str(self.设.get("fetch_url") or "").strip()
                    or str(self.设.get("fetch_cmd") or "").strip())

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

    def _抽一次(self, 址: str, 令: str) -> list[dict]:
        文, 错文 = self._取文(址, 令)
        是闪臣 = "shanchendaili" in (址 or "")
        包 = 解信封(文) if (not 错文 and 是闪臣) else None
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
        出 = self._解代理包(文)
        if not 出:
            self.上次补 = (f"拉取无有效行 {time.strftime('%H:%M:%S')}，"
                          f"接口返回：{(文 or '').strip()[:140]}")
            日志.warning("%s", self.上次补)
        return 出

    def _解代理包(self, 文: str) -> list[dict]:
        出 = self._解代理行(文)
        if 出:
            return self._补账密(出)
        串 = (文 or "").strip()
        if not 串.startswith(("{", "[")):
            return []
        try:
            包 = json.loads(串)
        except ValueError:
            return []
        列: Any = 包
        if isinstance(包, dict):
            列 = None
            for k in ("data", "list", "result", "ips", "rows"):
                if isinstance(包.get(k), list):
                    列 = 包[k]
                    break
            if 列 is None and isinstance(包.get("data"), dict):
                for k in ("list", "ips", "rows"):
                    if isinstance(包["data"].get(k), list):
                        列 = 包["data"][k]
                        break
        if not isinstance(列, list):
            return []
        指定 = self.拉取方案()
        出 = []
        for 一 in 列:
            if isinstance(一, str):
                try:
                    信 = 拆(一)
                except ValueError:
                    continue
            elif isinstance(一, dict):
                主 = 一.get("ip") or 一.get("server") or 一.get("host") or 一.get("sever")
                口 = 一.get("port")
                if not 主 or not 口:
                    continue
                信 = {
                    "方案": 指定 or "socks5",
                    "主机": str(主), "端口": int(口),
                    "用户": str(一.get("account") or 一.get("user") or 一.get("username") or ""),
                    "密码": str(一.get("password") or 一.get("pass") or 一.get("pwd") or ""),
                }
            else:
                continue
            if 指定:
                信["方案"] = 指定
            出.append(信)
        return self._补账密(出)

    def _补账密(self, 列: list[dict]) -> list[dict]:
        户 = str(self.设.get("go_user") or "").strip()
        密 = str(self.设.get("go_pass") or "").strip()
        if not (户 or 密):
            return 列
        for 一 in 列:
            if 户 and not 一.get("用户"):
                一["用户"] = 户
            if 密 and not 一.get("密码"):
                一["密码"] = 密
        return 列

    def _改查询(self, 址: str, 补: dict[str, Any]) -> str:
        u = urlparse(址)
        q = dict(parse_qsl(u.query, keep_blank_values=True))
        for k, v in 补.items():
            if v in (None, ""):
                q.pop(k, None)
            else:
                q[k] = str(v)
        return urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode(q), u.fragment))

    def _ipipgo协议(self) -> tuple[str, str]:
        s5 = (self.拉取方案() or "socks5") == "socks5"
        return ("socks5", "2") if s5 else ("http", "1")

    def ipipgo提取地址(self, 国: str = "", 州: str = "", 市: str = "", 数: int | None = None) -> str:
        数 = self.提取条数(数)
        文协, 数协 = self._ipipgo协议()
        址 = str(self.设.get("go_url") or "").strip()
        键 = str(self.设.get("go_key") or "").strip()
        if 址.startswith(("http://", "https://")):
            u = urlparse(址)
            q = dict(parse_qsl(u.query, keep_blank_values=True))
            补: dict[str, Any] = {"num": 数, "type": q.get("type") or "txt"}
            if "count" in q:
                补["count"] = 数
            原协议 = str(q.get("protocol") or q.get("pt") or "")
            if 原协议 in ("1", "2") or "pt" in q:
                补["protocol"] = 数协
                if "pt" in q:
                    补["pt"] = 数协
            elif 原协议:
                补["protocol"] = 文协
            else:
                补["protocol"] = 数协
            if 国:
                if "regions" in q or "country" not in q:
                    补["regions"] = 国
                if "country" in q or "regions" not in q:
                    补["country"] = 国
                if "cntry" in q:
                    补["cntry"] = 国
                if "cc" in q:
                    补["cc"] = 国
            if 州:
                补["state"] = 州
                if "province" in q:
                    补["province"] = 州
            if 市:
                补["city"] = 市
            if 键 and not any(q.get(k) for k in ("key", "appKey", "app_key")):
                补["key"] = 键
            return self._改查询(址, 补)
        if not 键:
            return ""
        底 = str(self.设.get("go_base") or 默认["go_base"]).rstrip("/")
        参 = {"key": 键, "num": 数, "type": "txt", "lb": "1", "protocol": 数协}
        if 国:
            参["regions"] = 国
            参["country"] = 国
        if 州:
            参["state"] = 州
        if 市:
            参["city"] = 市
        return f"{底}/getip?{urlencode(参)}"

    def _ipipgo账密批(self, 国: str, 数: int) -> list[dict]:
        户 = str(self.设.get("go_user") or "").strip()
        密 = str(self.设.get("go_pass") or "").strip()
        if not (户 and 密):
            return []
        主 = str(self.设.get("go_host") or 默认["go_host"]).strip() or 默认["go_host"]
        方案 = self.拉取方案() or "socks5"
        口 = int(self.设.get("go_port") or 0) or (1080 if 方案 == "socks5" else 8080)
        出 = []
        for _ in range(数):
            sid = uuid.uuid4().hex[:10]
            名 = f"{户}-region-{国}-session-{sid}" if 国 else f"{户}-session-{sid}"
            出.append({"方案": 方案, "主机": 主, "端口": 口, "用户": 名, "密码": 密})
        return 出

    def _抽ipipgo(self, 国: str, 州: str, 市: str, 数: int) -> list[dict]:
        址 = self.ipipgo提取地址(国, 州, 市, 数)
        if 址:
            出 = self._抽一次(址, "")
            if 出:
                return 出
        return self._ipipgo账密批(国, 数)

    def _抽源(self, 源: str, 国: str, 州: str, 市: str, 数: int) -> list[dict]:
        if 源 == "ipipgo":
            return self._抽ipipgo(国, 州, 市, 数)
        return self._抽地(国, 州, 市, 数)

    def 地区说(self) -> str:
        钉 = 地区文(*self._钉地区())
        if 钉:
            return 钉
        if self.这批地区:
            return f"每批一国 · 这批 {self.这批地区}"
        return "每批一国 · 下次提取时随机"

    def _记这批(self, 国: str, 州: str = "", 市: str = "") -> None:
        self.这批地区 = 地区文(国, 州, 市) or "随机"

    def _随机国序(self, 避开: str = "") -> list[str]:
        列 = [x for x in 随机国库 if x != 避开]
        random.shuffle(列)
        if 避开 and 避开 in 随机国库:
            列.append(避开)
        return 列 or list(随机国库)

    def _抽地(self, 国: str, 州: str, 市: str, 数: int) -> list[dict]:
        return self._抽一次(self.提取地址(国, 州, 市, 数=数), "")

    def _地区候选(self, 换国: bool) -> list[tuple[str, str, str]]:
        钉国, 钉州, 钉市 = self._钉地区()
        if 钉国 or 钉州 or 钉市:
            层 = [(钉国, 钉州, 钉市)]
            if 钉市:
                层.append((钉国, 钉州, ""))
            if 钉州:
                层.append((钉国, "", ""))
            见过: set[tuple[str, str, str]] = set()
            出层 = []
            for 一 in 层:
                if 一 not in 见过:
                    见过.add(一)
                    出层.append(一)
            return 出层
        候选: list[str] = []
        旧 = (self.这批地区 or "").split("/")[0]
        if not 换国 and 旧 and 旧 in 随机国库:
            候选.append(旧)
        候选.extend(x for x in self._随机国序(旧) if x not in 候选)
        return [(国, "", "") for 国 in 候选]

    def 拉取一批(self, 数: int | None = None, 换国: bool = False) -> list[dict]:
        """一次提够指定条数。按用户选的源来；自动则谁能提用谁。"""
        令 = str(self.设.get("fetch_cmd") or "").strip()
        数 = self.提取条数(数)
        源们 = self.源顺序()
        if not 源们:
            址 = self.提取地址(数=数)
            return self._抽一次(址, 令) if 址 or 令 else []

        最后 = ""
        for 源 in 源们:
            for 地 in self._地区候选(换国):
                出 = self._抽源(源, *地, 数)
                if 出:
                    self.上次源 = 源
                    self._记这批(*地)
                    说 = f"{self.源名(源)} 这批 {self.这批地区}，一次 {len(出)} 条"
                    self.上次补 = 说
                    日志.info("%s", 说)
                    return 出
                最后 = self.上次补
        if 令:
            return self._抽一次("", 令)
        self.上次补 = 最后 or "两家都提不到"
        return []

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
            说 = "健康不足但没配提取来源（闪臣 / IPIPGO / fetch_url），保持现有池"
            self.上次补 = 说
            return 说
        要 = 目标 - 健康数
        成 = 0
        批 = await asyncio.to_thread(self.拉取一批, 要, False)
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
        批 = await asyncio.to_thread(self.拉取一批, None, True)
        if not 批:
            说 = self.上次补 or "换新失败，保持原池"
            if "换新失败" not in 说:
                说 = f"换新失败 {time.strftime('%H:%M:%S')}：{说}"
            self.上次补 = 说
            日志.warning("%s", 说)
            return 说
        async with self.锁:
            # 闪臣的线路不管标成什么来源都一起换掉，别再让老的赖着
            self.条们 = [一 for 一 in self.条们
                        if 一.来源 != "拉取" and 闪臣主机 not in 一.主机 and ipipgo主机 not in 一.主机]
            self.粘 = {}
            for 信 in 批:
                try:
                    self._塞(信, 来源="拉取", 落盘=False)
                except ValueError as 错:
                    日志.warning("换新入池失败：%s", 错)
            self.落盘()
            数 = len([一 for 一 in self.条们 if 一.来源 == "拉取"])
        self.上次换新 = time.strftime("%Y-%m-%d %H:%M:%S")
        地 = f"，{self.这批地区}" if self.这批地区 else ""
        说 = f"已换新{地}，拉取 {数} 条 {time.strftime('%H:%M:%S')}"
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
            "go_key": self.设.get("go_key") or "",
            "go_url": self.设.get("go_url") or "",
            "go_user": self.设.get("go_user") or "",
            "闪臣": self.闪臣快照(),
            "版本": 版本,
            "上次补": self.上次补,
            "上次换新": self.上次换新,
            "下次换": self.下次换秒(),
            "换说": self.换说(),
            "这批地区": self.这批地区,
            "上次源": self.上次源,
            "供应商": self.当前源() or "无",
            "供应商选": self.设.get("provider") or "auto",
            "auto_update": int(self.设.get("auto_update") or 0),
            "update_minutes": self.查更分(),
            "更新说": self.更新说,
            "上轮验活": self.上轮验活,
            "健康": len(self.健康们()),
            "总数": len(self.条们),
            "上行": sum(一.上行 for 一 in self.条们),
            "下行": sum(一.下行 for 一 in self.条们),
            "上行文": 人读(sum(一.上行 for 一 in self.条们)),
            "下行文": 人读(sum(一.下行 for 一 in self.条们)),
            "总上行文": 人读(self.总上行),
            "总下行文": 人读(self.总下行),
            "起算": self.起算,
            "池": [一.快照() for 一 in self.条们],
        }
