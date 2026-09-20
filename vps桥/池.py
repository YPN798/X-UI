# -*- coding: utf-8 -*-
"""代理池：挑选、失败计数、拉取补池、落盘。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse
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


def _白条(一: Any, 源: str = "") -> dict[str, str]:
    if not isinstance(一, dict):
        return {"id": "", "ip": str(一 or ""), "备注": "", "源": 源}
    return {
        "id": str(一.get("id") or 一.get("ID") or ""),
        "ip": str(一.get("ip") or 一.get("IP") or 一.get("address")
                 or 一.get("user_ip") or 一.get("clientIp") or ""),
        "备注": str(一.get("remark") or 一.get("note") or 一.get("mark")
                  or 一.get("content") or ""),
        "源": 源 or str(一.get("源") or ""),
    }


def 人读时(秒: int) -> str:
    秒 = max(0, int(秒 or 0))
    if 秒 < 60:
        return f"{秒} 秒"
    if 秒 < 3600:
        return f"{秒 // 60} 分 {秒 % 60} 秒"
    return f"{秒 // 3600} 时 {(秒 % 3600) // 60} 分"


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
    "pool_size": 50,
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
    "sc_key": "AKic7DLPhEk1t070m8jtaw651swf6f9j",
    "sc_code": "ypn940815",
    "sc_count": 50,
    "sc_time": 2,
    "sc_protocol": "s5",
    # 三格留空=每批闪臣抽一国、1024 抽一国，都从随机国库来，再打乱。钉死了就按钉的提
    "sc_cntry": "",
    "sc_state": "",
    "sc_city": "",
    "sc_white": 1,
    # auto=各源各提，一家出错不挡其他；1024 写死可提，闪臣 / IPIPGO 有凭证才跟
    "provider": "auto",
    "go_base": "https://api.ipipgo.com",
    "go_key": "",
    "go_url": "",
    "go_user": "",
    "go_pass": "",
    "go_host": "proxy.ipipgo.com",
    "go_port": 1080,
    # 1024Proxy：控制台 token 用来自动加白；提取走 white.1024proxy.com
    "p24_base": "https://api.1024proxy.com",
    "p24_white_api": "https://white.1024proxy.com/white/api",
    "p24_token": "",
    "p24_url": "",
    "p24_user": "",
    "p24_pass": "",
    "p24_host": "us.1024proxy.io",
    "p24_port": 3000,
    "p24_time": 30,
    "p24_white": 1,
    "defaults_ver": 24,
    "web_pass": "YPN940815...",
    # 自己去仓库拉新代码。auto_update 0=关，1=开
    "auto_update": 1,
    "update_minutes": 5,
    "update_base": "https://raw.githubusercontent.com/YPN798/X-UI/main",
    # 请国内检测点回连本机节点端口。0=关。wall_port=0 则从 Xray 入站自动认
    "wall_check": 1,
    "wall_minutes": 10,
    "wall_port": 0,
    # 0=关掉桥分流，恢复 X-UI 原设置；1=dola 走 127.0.0.1:41000
    "proxy_on": 1,
    "随机国库": ["JP", "KR", "SG", "TH", "VN", "MY", "PH", "ID", "BR"],
    "proxies": [],
}

# 面板右上角显示，好核对 VPS 上跑的到底是不是最新代码
版本 = "2026-09-20.2"

闪臣主机 = "shanchendaili.com"
ipipgo主机 = "ipipgo.com"
p24主机 = "1024proxy"
# 各源写死，面板和 API 都改不了
闪臣内置键 = "AKic7DLPhEk1t070m8jtaw651swf6f9j"
闪臣内置码 = "ypn940815"
闪臣条数 = 50
闪臣时档 = 2  # 提取规格：1-6 小时。工作池使用时长另算
p24条数 = 50
p24时分 = 30  # 提取规格：粘性 30 分钟。工作池使用时长另算
# 1024 条数/时长写死；地区跟随机国库走，不再用全球 Rand
p24提取根 = "https://white.1024proxy.com/white/api"
# 环境文件不上仓库；VPS 更新也拉不到。从本机环境文件落入，开机写进配置后不再问。
p24内置令 = "36145e476d76242f71d4464f2271a107"


def _像令(值: str) -> str:
    值 = (值 or "").strip().strip('"').strip("'")
    if not 值 or 值.startswith(("http://", "https://")):
        return ""
    return 值


def _从文抠令(文: str) -> str:
    文 = (文 or "").lstrip("\ufeff").strip()
    if not 文:
        return ""
    if 文[:1] in "{[":
        try:
            d = json.loads(文)
        except Exception:
            d = None
        if isinstance(d, dict):
            for k in ("p24_token", "P24_TOKEN", "PROXY1024_TOKEN"):
                值 = _像令(str(d.get(k) or ""))
                if 值:
                    return 值
    键 = {"p24_token", "P24_TOKEN", "PROXY1024_TOKEN", "token"}
    for 行 in 文.splitlines():
        行 = 行.strip()
        if not 行 or 行.startswith("#") or "=" not in 行:
            continue
        k, v = 行.split("=", 1)
        if k.strip() in 键:
            值 = _像令(v)
            if 值:
                return 值
    if "\n" not in 文 and "=" not in 文 and 20 <= len(文) <= 80 and 文.isalnum():
        return 文
    return ""


def _读环境令(另: Path | None = None) -> str:
    for 名 in ("P24_TOKEN", "PROXY1024_TOKEN"):
        值 = _像令(str(os.environ.get(名) or ""))
        if 值:
            return 值
    径们 = [
        Path("/etc/xui-bridge/环境"),
        Path("/etc/xui-bridge/.env"),
        Path("/etc/xui-bridge/config.json"),
        Path("/opt/xui-bridge/环境"),
        Path("/opt/xui-bridge/.env"),
        Path(__file__).resolve().parent / "环境",
        Path(__file__).resolve().parent / ".env",
    ]
    if 另 is not None:
        径们.extend([
            另, 另.parent / "环境", 另.parent / ".env",
            另.parent / "config.json", 另.parent / "配置.json",
        ])
    见: set[Path] = set()
    for p in 径们:
        try:
            p = p.resolve()
        except OSError:
            continue
        if p in 见 or not p.is_file():
            continue
        见.add(p)
        try:
            值 = _从文抠令(p.read_text(encoding="utf-8"))
        except OSError:
            continue
        if 值:
            return 值
    return ""


_抽态 = threading.local()
# 3 分钟换新；满 4 分钟才从名单拿掉。多出的 1 分钟给旧连接收尾，避免硬断
换期秒 = 180
池寿秒 = 240
交叠秒 = 60

# 三格留空时每批从随机国库各抽一国。下面是出厂名单，面板和 API 都能加减。
默随机国库 = (
    "JP", "KR", "SG", "TH", "VN", "MY", "PH", "ID", "BR",
)
随机国库 = 默随机国库
国名表 = {
    "JP": "日本", "KR": "韩国", "SG": "新加坡", "TH": "泰国",
    "VN": "越南", "MY": "马来西亚", "PH": "菲律宾", "ID": "印尼", "BR": "巴西",
    "HK": "中国香港", "TW": "中国台湾", "US": "美国", "GB": "英国", "DE": "德国",
    "FR": "法国", "NL": "荷兰", "IT": "意大利", "ES": "西班牙", "CA": "加拿大",
    "AU": "澳大利亚", "IN": "印度", "PL": "波兰", "SE": "瑞典", "CH": "瑞士",
    "AE": "阿联酋", "TR": "土耳其", "MX": "墨西哥", "AR": "阿根廷", "ZA": "南非",
    "RU": "俄罗斯", "UA": "乌克兰",
}


def 地区文(国: str, 州: str = "", 市: str = "") -> str:
    return "/".join(x for x in (国, 州, 市) if x)


def 规范国码(码: str) -> str:
    码 = str(码 or "").strip().upper()
    return 码 if len(码) == 2 and 码.isalpha() else ""


def 洗国库(生) -> list[str]:
    if isinstance(生, str):
        生 = 生.replace(",", " ").replace(";", " ").split()
    出: list[str] = []
    if isinstance(生, (list, tuple)):
        for 一 in 生:
            码 = 规范国码(一)
            if 码 and 码 not in 出:
                出.append(码)
    return 出


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
        # 换新时先入新一批，旧的标退役：不再接新连接，等已有连接把回包走完
        self.退役 = False
        self.退役于 = 0.0
        # 入池于=单调钟，进程内算寿；入时=墙上时钟，重启后满 4 分钟必下
        self.入池于 = float(信.get("入池于") or 0)
        self.入时 = float(信.get("入时") or 0)
        self.批次 = int(信.get("批次") or 0)

    def 寿秒(self) -> int:
        return 池寿秒

    def 键(self) -> str:
        return f"{self.方案}|{self.主机}|{self.端口}|{self.用户}"

    def 脱敏(self) -> str:
        return f"{self.方案}://{self.主机}:{self.端口}"

    def 串(self) -> str:
        return 给上游({
            "方案": self.方案, "主机": self.主机, "端口": self.端口,
            "用户": self.用户, "密码": self.密码,
        })

    def 档(self, 换代: int = 0, 现在: float | None = None) -> str:
        if self.退役:
            return "退役"
        if not (self.来源 == "拉取" or self.来源.startswith("拉取/")):
            return "手加"
        now = time.time() if 现在 is None else 现在
        已用 = now - (self.入时 or now)
        if self.入时 and 已用 >= self.寿秒():
            return "退役"
        if int(self.批次 or 0) == int(换代 or 0) and 已用 <= 45:
            return "刚提取"
        if int(self.批次 or 0) == int(换代 or 0):
            return "本批"
        return "上批"

    def 快照(self, 换代: int = 0) -> dict[str, Any]:
        now = time.time()
        已用 = max(0, int(now - (self.入时 or now))) if self.入时 else 0
        return {
            "号": self.号,
            "地址": self.脱敏(),
            "方案": self.方案,
            "来源": self.显来源(),
            "退役": self.退役,
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
            "批次": int(self.批次 or 0),
            "入时": self.入时,
            "已用": 已用,
            "已用文": 人读时(已用) if self.入时 else "—",
            "档": self.档(换代, now),
        }

    def 显来源(self) -> str:
        if self.退役:
            return "退役"
        if self.来源.startswith("拉取/"):
            家 = self.来源.split("/", 1)[1]
            return {"shanchen": "闪臣", "ipipgo": "IPIPGO", "1024": "1024"}.get(家, 家)
        return self.来源


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
        self.墙态 = ""
        self.墙说 = ""
        self.墙口 = 0
        self._墙检中 = False
        self.分流说 = ""
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
        self.日流量: dict[str, dict[str, int]] = {}
        self.起算 = time.strftime("%Y-%m-%d %H:%M")
        self._流量落盘 = 0.0
        self._补中 = False
        self._换中 = False
        self.换代 = 0
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
        # 今天线上 time=1 时把工作池收成 1 条。档位仍用每次请求更换 IP，条数保持 100。
        if 旧版 > int(默认["defaults_ver"]):
            要升 = True
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
            if 旧版 < 5:
                self.设["pool_size"] = 默认["pool_size"]
                self.设["sc_count"] = 默认["sc_count"]
                self.设["auto_rotate"] = 默认["auto_rotate"]
            if 旧版 < 6:
                self.设["sc_base"] = 默认["sc_base"]
                self.设["sc_protocol"] = 默认["sc_protocol"]
            if 旧版 < 7:
                self.设["sc_protocol"] = 默认["sc_protocol"]
            if 旧版 < 8:
                self.设["auto_rotate"] = 默认["auto_rotate"]
            if 旧版 < 9:
                self.设["pool_size"] = 默认["pool_size"]
                self.设["sc_count"] = 默认["sc_count"]
            if 旧版 < 10:
                self.设["pool_size"] = 默认["pool_size"]
                self.设["sc_count"] = 默认["sc_count"]
            if 旧版 < 15:
                if 旧版 < 11 or 旧版 > 11:
                    self.设["sc_time"] = 默认["sc_time"]
                    self.设["pool_size"] = 默认["pool_size"]
                    self.设["sc_count"] = 默认["sc_count"]
                if 旧版 < 12 or 旧版 > 12:
                    self.设["sc_count"] = 默认["sc_count"]
                    self.设["pool_size"] = 默认["pool_size"]
                if 旧版 != 13:
                    self.设["sc_time"] = 默认["sc_time"]
                    self.设["sc_count"] = 默认["sc_count"]
                    self.设["pool_size"] = 默认["pool_size"]
                if 旧版 != 14:
                    self.设["sc_time"] = 默认["sc_time"]
                    self.设["sc_count"] = 默认["sc_count"]
                    self.设["pool_size"] = 默认["pool_size"]
            if 旧版 < 16:
                self.设["wall_check"] = 默认["wall_check"]
                self.设["wall_minutes"] = 默认["wall_minutes"]
                self.设["wall_port"] = 默认["wall_port"]
            if 旧版 < 17:
                self.设["proxy_on"] = 0
            if 旧版 < 18:
                self.设["p24_white"] = int(默认["p24_white"])
            if 旧版 < 19:
                self.设["sc_count"] = 默认["sc_count"]
                self.设["pool_size"] = 默认["pool_size"]
                self.设["auto_rotate"] = 默认["auto_rotate"]
                self.设["p24_time"] = 默认["p24_time"]
            if 旧版 < 20:
                self.设["proxy_on"] = 1
            if 旧版 < 21:
                self.设["provider"] = "1024"
                self.设["p24_white"] = 1
            if 旧版 < 22:
                self.设["provider"] = "auto"
                self.设["p24_white"] = 0
                self.设["sc_white"] = 0
            if 旧版 < 23:
                self.设["sc_white"] = 1
                self.设["p24_white"] = 1
            if 旧版 < 24:
                self.设["sc_white"] = 1
                self.设["p24_white"] = 1
            self.设["defaults_ver"] = 默认["defaults_ver"]
        要升 = self._钉死提取() or 要升
        if not str(self.设.get("p24_token") or "").strip():
            令 = _读环境令(self.径) or p24内置令
            if 令:
                self.设["p24_token"] = 令
                要升 = True
        self.条们 = []
        for 一 in 原.get("proxies") or []:
            # 新格式 {"串":..., "来源":...}；老格式和 install.sh 追加的是纯字符串
            源 = "手加"
            if isinstance(一, dict) and 一.get("串"):
                源, 一 = str(一.get("来源") or "手加"), 一["串"]
            # 闪臣的线路只可能是提取来的。补来源之前存下的那批被当成手加，
            # 换新永远清不掉，池子从 30 涨到 56。不管存成什么格式，一律认回拉取
            if 闪臣主机 in str(一) or ipipgo主机 in str(一) or p24主机 in str(一):
                源 = "拉取"
            try:
                self._塞(一, 来源=源, 落盘=False, 入时=0.0)
            except ValueError as 错:
                日志.warning("跳过非法代理：%s", 错)
        self._复流量()
        if 要升:
            日志.info("配置已升到默认 v%s：闪臣 %s 条/1-6小时，1024 %s 条/%s 分钟",
                      self.设["defaults_ver"], 闪臣条数, p24条数, p24时分)
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
            "sc_protocol": self.设.get("sc_protocol") or "s5",
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
            "p24_base": self.设.get("p24_base") or 默认["p24_base"],
            "p24_white_api": self.设.get("p24_white_api") or 默认["p24_white_api"],
            "p24_token": self.设.get("p24_token") or "",
            "p24_url": self.设.get("p24_url") or "",
            "p24_user": self.设.get("p24_user") or "",
            "p24_pass": self.设.get("p24_pass") or "",
            "p24_host": self.设.get("p24_host") or 默认["p24_host"],
            "p24_port": int(self.设.get("p24_port") or 默认["p24_port"]),
            "p24_time": int(self.设.get("p24_time") or 默认["p24_time"]),
            "p24_white": int(self.设.get("p24_white") or 0),
            "defaults_ver": int(self.设.get("defaults_ver") or 默认["defaults_ver"]),
            "web_pass": self.设["web_pass"],
            "auto_update": int(self.设.get("auto_update") or 0),
            "update_minutes": self.查更分(),
            "update_base": self.设.get("update_base") or 默认["update_base"],
            "wall_check": int(self.设.get("wall_check") or 0),
            "wall_minutes": int(self.设.get("wall_minutes") or 10),
            "wall_port": int(self.设.get("wall_port") or 0),
            "proxy_on": int(self.设.get("proxy_on") or 0),
            "随机国库": self.国库(),
            # 来源必须一起存，否则重启后拉取来的全变成手加，换新再也换不掉它们
            "proxies": [{"串": 一.串(), "来源": 一.来源} for 一 in self.条们 if not 一.退役],
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
            try:
                一.入时 = float(命.get("入时") or 0)
            except (TypeError, ValueError):
                一.入时 = 0
            if 一.入时 > 0:
                一.入池于 = time.monotonic() - max(0.0, time.time() - 一.入时)
            try:
                一.批次 = int(命.get("批次") or 0)
            except (TypeError, ValueError):
                一.批次 = 0
        try:
            self.换代 = int(文.get("换代") or 0)
        except (TypeError, ValueError):
            self.换代 = 0
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
        self.墙态 = str(文.get("墙态") or self.墙态)
        self.墙说 = str(文.get("墙说") or self.墙说)
        try:
            self.墙口 = int(文.get("墙口") or 0)
        except (TypeError, ValueError):
            self.墙口 = 0
        日 = 文.get("日流量")
        if isinstance(日, dict):
            桶: dict[str, dict[str, int]] = {}
            for k, v in 日.items():
                if not isinstance(k, str) or len(k) != 10 or not isinstance(v, dict):
                    continue
                桶[k] = {"上行": int(v.get("上行") or 0), "下行": int(v.get("下行") or 0)}
            self.日流量 = 桶

    def 写状态(self) -> None:
        出 = {
            "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "版本": 版本,
            "上次补": self.上次补,
            "上次换新": self.上次换新,
            "这批地区": self.这批地区,
            "上次源": self.上次源,
            "换代": int(self.换代 or 0),
            "上轮验活": self.上轮验活,
            "墙态": self.墙态,
            "墙说": self.墙说,
            "墙口": self.墙口,
            "模式": self.设["mode"],
            "粘住": self.设["sticky"],
            "起算": self.起算,
            "总上行": self.总上行,
            "总下行": self.总下行,
            "日流量": self._日盘(),
            # 键只落盘不上接口，页面看到的还是脱敏地址
            "池": [{**一.快照(self.换代), "键": 一.键()} for 一 in self.条们],
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

    def _塞(self, 串或信, 来源: str = "手加", 落盘: bool = True,
           入时: float | None = None) -> 条:
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
        now = time.monotonic()
        起 = now if 入时 is None else float(入时)
        墙 = time.time()
        for 已 in self.条们:
            if 已.键() == 键:
                已.退役 = False
                已.退役于 = 0.0
                已.来源 = 来源
                已.启用 = True
                已.入池于 = 起
                已.入时 = 墙
                if 来源 == "拉取" or 来源.startswith("拉取/"):
                    已.批次 = int(self.换代 or 0)
                return 已
        一 = 条(信, 来源=来源)
        一.入池于 = 起
        一.入时 = 墙
        if 来源 == "拉取" or 来源.startswith("拉取/"):
            一.批次 = int(self.换代 or 0)
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

    def _钉死提取(self) -> bool:
        """闪臣 Key/安全码/条数/时长，1024 条数/时长，自动加白：一律写死。"""
        前 = (
            self.设.get("sc_key"), self.设.get("sc_code"),
            self.设.get("sc_count"), self.设.get("sc_time"),
            self.设.get("p24_time"), self.设.get("sc_white"), self.设.get("p24_white"),
        )
        self.设["sc_key"] = 闪臣内置键
        self.设["sc_code"] = 闪臣内置码
        self.设["sc_count"] = 闪臣条数
        self.设["sc_time"] = 闪臣时档
        self.设["p24_time"] = p24时分
        self.设["sc_white"] = 1
        self.设["p24_white"] = 1
        后 = (
            self.设.get("sc_key"), self.设.get("sc_code"),
            self.设.get("sc_count"), self.设.get("sc_time"),
            self.设.get("p24_time"), self.设.get("sc_white"), self.设.get("p24_white"),
        )
        return 前 != 后

    async def 改设(self, 补: dict[str, Any]) -> None:
        锁死 = {"sc_key", "sc_code", "sc_count", "sc_time", "p24_time", "sc_white", "p24_white"}
        async with self.锁:
            for k in ("mode", "sticky", "fetch_url", "fetch_cmd", "fetch_scheme",
                      "sc_base", "sc_protocol", "sc_cntry", "sc_state", "sc_city",
                      "provider", "go_base", "go_key", "go_url", "go_user", "go_host",
                      "p24_base", "p24_white_api", "p24_url", "p24_user", "p24_host"):
                if k in 锁死:
                    continue
                if k in 补 and 补[k] is not None:
                    self.设[k] = str(补[k]).strip()
            for k in ("pool_size", "fail_n", "check_interval", "check_conc",
                      "connect_timeout", "auto_rotate",
                      "go_port", "auto_update", "update_minutes",
                      "wall_check", "wall_minutes", "wall_port", "proxy_on",
                      "p24_port"):
                if k in 锁死:
                    continue
                if k in 补 and 补[k] not in (None, ""):
                    self.设[k] = int(补[k])
            # 安全码写死。IPIPGO / 1024 密码只写：页面永远不回显，留空表示保持原样
            if str(补.get("go_pass") or "").strip():
                self.设["go_pass"] = str(补["go_pass"]).strip()
            if str(补.get("p24_token") or "").strip():
                self.设["p24_token"] = str(补["p24_token"]).strip()
            if str(补.get("p24_pass") or "").strip():
                self.设["p24_pass"] = str(补["p24_pass"]).strip()
            if str(补.get("web_pass") or "").strip():
                self.设["web_pass"] = str(补["web_pass"]).strip()
            键或址 = str(补.get("go_key") or "").strip()
            if 键或址.startswith(("http://", "https://")):
                self.设["go_url"] = 键或址
            千令 = str(补.get("p24_token") or "").strip()
            if 千令.startswith(("http://", "https://")):
                self.设["p24_url"] = 千令
                if self.设.get("p24_token") == 千令:
                    self.设["p24_token"] = ""
            if "随机国库" in 补:
                列 = 洗国库(补.get("随机国库"))
                if 列:
                    self.设["随机国库"] = 列
            self._钉死提取()
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

    def 代理开(self) -> bool:
        return bool(int(self.设.get("proxy_on") or 0))

    def 池寿(self, 源: str = "") -> int:
        return 池寿秒

    def 有效换期(self) -> int:
        """3 分钟换新。满 4 分钟才下线，中间 1 分钟给旧连接收尾。"""
        if not self.代理开():
            return 0
        return 换期秒

    def 换说(self) -> str:
        if not self.代理开():
            return "代理已关，X-UI 已恢复原设置"
        return "每 3 分钟换新，最多用 4 分钟（1 分钟交叠防硬断）"

    def 下次换秒(self) -> int:
        """还有多少秒换下一批。没开自动换新返回 -1。"""
        换期 = self.有效换期()
        if not 换期 or not self.换基:
            return -1
        return max(0, int(换期 - (time.monotonic() - self.换基)))

    def 工作数(self) -> int:
        """还没到期的拉取条数。池空就该立刻补，不能等验活跑完。"""
        now = time.monotonic()
        return sum(
            1 for 一 in self.条们
            if self._提取的(一) and not 一.退役 and not self._过期了(一, now)
        )

    def 健康们(self) -> list[条]:
        now = time.monotonic()
        return [一 for 一 in self.条们
                if 一.启用 and 一.健康 and not 一.退役 and not self._过期了(一, now)]

    def 可接们(self) -> list[条]:
        """新连接只走本批。上批有连接的留着收尾，满 4 分钟再拿掉。"""
        新 = self.健康们()
        if not 新:
            return [一 for 一 in self.条们
                    if 一.启用 and not 一.退役 and not self._提取的(一)]
        代 = int(self.换代 or 0)
        本 = [一 for 一 in 新 if (not self._提取的(一)) or int(一.批次 or 0) == 代]
        return 本 or 新

    def _提取的(self, 一: 条) -> bool:
        return (一.来源 == "拉取" or 一.来源.startswith("拉取/")
                or 闪臣主机 in 一.主机 or ipipgo主机 in 一.主机
                or p24主机 in 一.主机)

    def _条源(self, 一: 条) -> str:
        if 一.来源.startswith("拉取/"):
            return 一.来源.split("/", 1)[1]
        if p24主机 in 一.主机:
            return "1024"
        if ipipgo主机 in 一.主机:
            return "ipipgo"
        if 闪臣主机 in 一.主机:
            return "shanchen"
        return ""

    def _拉取来源(self, 源: str) -> str:
        源 = str(源 or "").strip()
        return f"拉取/{源}" if 源 else "拉取"

    def _过期了(self, 一: 条, now: float | None = None) -> bool:
        if not self._提取的(一):
            return False
        寿 = 一.寿秒()
        墙 = float(一.入时 or 0)
        if 墙 > 0:
            return (time.time() - 墙) >= 寿
        起 = float(一.入池于 or 0)
        if 起 > 0:
            now = time.monotonic() if now is None else now
            return (now - 起) >= 寿
        return True

    def 条剩秒(self, 一: 条) -> float | None:
        """拉取线路还能活多久。手加不限。已到期是 0。"""
        if not self._提取的(一):
            return None
        寿 = float(一.寿秒())
        墙 = float(一.入时 or 0)
        if 墙 > 0:
            return max(0.0, 寿 - (time.time() - 墙))
        起 = float(一.入池于 or 0)
        if 起 > 0:
            return max(0.0, 寿 - (time.monotonic() - 起))
        return 0.0

    def _踢过期(self) -> int:
        """满 4 分钟的拉取立刻从名单拿掉。有连接也踢，会话由转发按剩余寿命掐。"""
        now = time.monotonic()
        留: list[条] = []
        丢 = 0
        旧号: set[str] = set()
        for 一 in self.条们:
            if self._提取的(一) and self._过期了(一, now):
                一.退役 = True
                一.退役于 = 一.退役于 or now
                旧号.add(一.号)
                丢 += 1
                continue
            留.append(一)
        if 丢:
            self.粘 = {k: v for k, v in self.粘.items() if v not in 旧号}
            self.条们 = 留
        return 丢

    def _标过期(self) -> int:
        return self._踢过期()

    def _有本批(self) -> bool:
        代 = int(self.换代 or 0)
        return any(
            (not 一.退役) and self._提取的(一) and int(一.批次 or 0) == 代
            for 一 in self.条们
        )

    def _收闲上批(self) -> int:
        """过期空闲立刻拿掉。本批已在时，上批空闲也拿掉。"""
        代 = int(self.换代 or 0)
        now = time.monotonic()
        有本 = self._有本批()
        留: list[条] = []
        丢 = 0
        for 一 in self.条们:
            if not self._提取的(一):
                留.append(一)
                continue
            过期 = self._过期了(一, now)
            上 = int(一.批次 or 0) < 代
            if 一.连接 <= 0 and (过期 or (有本 and 上)):
                丢 += 1
                continue
            留.append(一)
        if 丢:
            活号 = {一.号 for 一 in 留}
            self.粘 = {k: v for k, v in self.粘.items() if v in 活号}
            self.条们 = 留
        return 丢

    def _收旧(self, 宽限: float = 交叠秒) -> int:
        """退役过交叠就从名单拿掉。过期的有连接也拿掉，套接字仍由转发握着。"""
        now = time.monotonic()
        留: list[条] = []
        丢 = 0
        for 一 in self.条们:
            if not 一.退役:
                留.append(一)
                continue
            到期 = 一.退役于 > 0 and (now - 一.退役于) >= 宽限
            if 到期 and (一.连接 <= 0 or self._过期了(一, now)):
                丢 += 1
                continue
            留.append(一)
        if 丢:
            活号 = {一.号 for 一 in 留}
            self.粘 = {k: v for k, v in self.粘.items() if v in 活号}
            self.条们 = 留
        return 丢

    def _挑(self, 候选: list[条]) -> 条:
        模 = str(self.设.get("mode") or "round_robin")
        if 模 == "least_conn":
            return min(候选, key=lambda x: (x.连接, x.号))
        self.轮询 += 1
        return 候选[self.轮询 % len(候选)]

    async def 选(self, 目标: str = "") -> 条 | None:
        async with self.锁:
            self._标过期()
            候选 = self.可接们()
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

    async def 收旧(self) -> int:
        async with self.锁:
            n = self._标过期() + self._收闲上批() + self._收旧()
            if n:
                self.写状态()
            return n

    async def 记流量(self, 一: 条, 上行: int = 0, 下行: int = 0) -> None:
        上, 下 = max(0, int(上行 or 0)), max(0, int(下行 or 0))
        async with self.锁:
            一.上行 += 上
            一.下行 += 下
            self.总上行 += 上
            self.总下行 += 下
            self._记日(上, 下)
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
        return f"流量计数已清零，从 {self.起算} 重新算。每日统计还留着"

    def _今日(self) -> str:
        return time.strftime("%Y-%m-%d")

    def _记日(self, 上: int, 下: int) -> None:
        日 = self._今日()
        桶 = self.日流量.get(日) or {"上行": 0, "下行": 0}
        桶["上行"] += 上
        桶["下行"] += 下
        self.日流量[日] = 桶
        if len(self.日流量) > 60:
            for 旧 in sorted(self.日流量)[:-60]:
                self.日流量.pop(旧, None)

    def _日盘(self) -> dict[str, dict[str, int]]:
        return {k: dict(self.日流量[k]) for k in sorted(self.日流量)[-60:]}

    def 日统计(self) -> dict[str, Any]:
        日 = self._今日()
        今 = self.日流量.get(日) or {"上行": 0, "下行": 0}
        列 = []
        for k in sorted(self.日流量, reverse=True):
            v = self.日流量[k]
            合 = int(v.get("上行") or 0) + int(v.get("下行") or 0)
            列.append({
                "日": k,
                "上行": int(v.get("上行") or 0),
                "下行": int(v.get("下行") or 0),
                "合计": 合,
                "上行文": 人读(v.get("上行") or 0),
                "下行文": 人读(v.get("下行") or 0),
                "合计文": 人读(合),
            })
        今上, 今下 = int(今["上行"]), int(今["下行"])
        return {
            "今日": 日,
            "今日上行": 今上,
            "今日下行": 今下,
            "今日合计": 今上 + 今下,
            "今日上行文": 人读(今上),
            "今日下行文": 人读(今下),
            "今日合计文": 人读(今上 + 今下),
            "累计合计文": 人读(self.总上行 + self.总下行),
            "日表": 列,
        }

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
                还有 = [x for x in self.条们
                       if x.号 != 一.号 and x.启用 and x.健康 and not x.退役]
                if not 还有:
                    日志.warning("最后一条失败仍留着 %s：%s", 一.脱敏(), 一.上次错误)
                else:
                    一.健康 = False
                    一.上次切换 = time.strftime("%Y-%m-%d %H:%M:%S") + " " + 一.上次错误
                    self.粘 = {k: v for k, v in self.粘.items() if v != 一.号}
                    日志.warning("摘除 %s：%s", 一.脱敏(), 一.上次错误)
                    要补 = True
            self.写状态()
        if 要补:
            # 补池要跑一趟闪臣接口，不能让正在等着的那个请求陪着卡
            self._后台补齐()

    def 换着(self) -> bool:
        return bool(self._换中 or self._补中)

    def _后台补齐(self) -> None:
        if self._补中 or self._换中:
            return

        async def 跑() -> None:
            try:
                await self.补齐()
            except Exception as 错:
                日志.warning("后台补池失败：%s", 错)
                self.上次补 = f"补池失败：{错}"
            finally:
                self._补中 = False

        try:
            asyncio.get_running_loop().create_task(跑())
            self._补中 = True
            if not str(self.上次补 or "").startswith("正在"):
                self.上次补 = "正在补池…"
        except RuntimeError:
            pass

    async def 开始补齐(self) -> str:
        if self.换着():
            return self.上次补 or "上一次还在提取，等它结束"
        self._后台补齐()
        return self.上次补 or "正在补池…"

    async def 开始换新(self) -> str:
        if self.换着():
            return self.上次补 or "上一次还在提取，等它结束"
        self._换中 = True
        self.上次补 = "正在轻质换新…"

        async def 跑() -> None:
            try:
                await self._换新本体()
            except Exception as 错:
                日志.warning("后台换新失败：%s", 错)
                self.上次补 = f"换新失败：{错}"
            finally:
                self._换中 = False
                try:
                    self.写状态()
                except Exception:
                    pass

        try:
            asyncio.get_running_loop().create_task(跑())
        except RuntimeError:
            self._换中 = False
            return await self._换新本体()
        return self.上次补

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

    def p24开(self) -> bool:
        # 提取链接已写死，靠本机出口 IP 白名单鉴权，不必再填
        return True

    def 当前源(self) -> str:
        序 = self.源顺序()
        return 序[0] if 序 else ""

    def 源顺序(self) -> list[str]:
        选 = str(self.设.get("provider") or "auto").strip() or "auto"
        闪, 果, 千 = self.闪臣开(), self.ipipgo开(), self.p24开()
        if 选 == "shanchen":
            return ["shanchen"] if 闪 else []
        if 选 == "ipipgo":
            return ["ipipgo"] if 果 else []
        if 选 in ("1024", "p24", "proxy1024"):
            return ["1024"] if 千 else []
        序: list[str] = []
        if self.上次源 == "1024" and 千:
            序.append("1024")
        if self.上次源 == "ipipgo" and 果:
            序.append("ipipgo")
        if self.上次源 == "shanchen" and 闪:
            序.append("shanchen")
        if 千 and "1024" not in 序:
            序.append("1024")
        if 闪 and "shanchen" not in 序:
            序.append("shanchen")
        if 果 and "ipipgo" not in 序:
            序.append("ipipgo")
        return 序

    def 源名(self, 源: str = "") -> str:
        源 = 源 or self.当前源()
        if 源 == "auto":
            return "自动"
        表 = {"shanchen": "闪臣", "ipipgo": "IPIPGO", "1024": "1024"}
        if "+" in 源:
            return "、".join(表.get(x, x) for x in 源.split("+") if x)
        return 表.get(源, "无")

    def 码锁着(self) -> bool:
        """闪臣对连续错的安全码会上锁，越试锁得越久，所以撞过 1006 就先停手。"""
        return time.time() < float(self.闪臣态.get("码锁到") or 0)

    def _要加白的源(self) -> tuple[bool, bool]:
        闪 = bool(闪臣内置键) and bool(闪臣内置码)
        千 = bool(self._1024令())
        return 闪, 千

    def _源活数(self, 源: str) -> int:
        now = time.monotonic()
        代 = int(self.换代 or 0)
        return sum(
            1 for 一 in self.条们
            if self._提取的(一) and not 一.退役
            and not self._过期了(一, now) and self._条源(一) == 源
            and int(一.批次 or 0) == 代
        )

    def _1024令(self) -> str:
        return (str(self.设.get("p24_token") or "").strip()
                or _读环境令(self.径) or p24内置令)

    def 可自动白(self) -> bool:
        return any(self._要加白的源())

    def _闪臣址(self, 名: str, 参: dict[str, Any]) -> str:
        # 海外动态流量走 global 这套 flow-api，不要再用 sch.shanchendaili.com
        底 = 默认["sc_base"]
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

    def _1024调(self, 路: str, 参: dict[str, Any] | None = None) -> tuple[int, str, Any]:
        """控制台接口一律 form + token。返回 (码, 人话, data)，0=成功。"""
        令 = self._1024令()
        if not 令:
            return -1, "没填 1024 控制台 token", None
        底 = str(self.设.get("p24_base") or 默认["p24_base"]).rstrip("/")
        if not 底.startswith(("http://", "https://")):
            底 = "https://" + 底
        路 = str(路 or "")
        if not 路.startswith("/"):
            路 = "/" + 路
        身 = {"lang": "zh", "token": 令}
        for k, v in (参 or {}).items():
            if v not in (None, ""):
                身[k] = v
        try:
            求 = Request(
                底 + 路,
                data=urlencode(身).encode("utf-8"),
                headers={
                    "User-Agent": "xui-bridge",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                },
            )
            with urlopen(求, timeout=20) as r:
                文 = r.read().decode("utf-8", "replace")
        except Exception as 错:
            return -1, f"连不上 1024：{错}", None
        try:
            包 = json.loads(文) if (文 or "").strip().startswith("{") else None
        except ValueError:
            包 = None
        if not isinstance(包, dict):
            return -1, f"1024 返回看不懂：{(文 or '').strip()[:140]}", None
        try:
            码 = int(包.get("code") if 包.get("code") is not None else -1)
        except (TypeError, ValueError):
            码 = -1
        话 = str(包.get("msg") or 包.get("message") or "").strip()
        return 码, 话 or ("ok" if 码 == 0 else f"错误码 {码}"), 包.get("data")

    def _1024子号(self) -> str:
        缓 = str(self.闪臣态.get("p24号") or "").strip()
        if 缓:
            return 缓
        码, _, 数 = self._1024调("/v1/1024/subUsers", {"page": 1, "page_size": 200})
        if 码 != 0:
            return ""
        列 = 数.get("list") if isinstance(数, dict) else 数
        if not isinstance(列, list):
            return ""
        要 = str(self.设.get("p24_user") or "").strip()
        中 = ""
        for 一 in 列:
            if not isinstance(一, dict):
                continue
            号 = str(一.get("id") or "").strip()
            if not 号:
                continue
            if 要 and str(一.get("username") or "") == 要:
                中 = 号
                break
            if not 中:
                中 = 号
        if 中:
            self.闪臣态["p24号"] = 中
        return 中

    def _1024查白(self) -> tuple[bool, list[dict]]:
        码, 说, 数 = self._1024调("/v1/trafficWhiteList")
        if 码 != 0:
            self.闪臣态["白名单说"] = 说
            return False, []
        列 = []
        for 一 in (数 or []) if isinstance(数, list) else []:
            if not isinstance(一, dict):
                continue
            列.append({
                "id": str(一.get("id") or ""),
                "ip": str(一.get("user_ip") or 一.get("ip") or ""),
                "备注": str(一.get("mark") or 一.get("username") or ""),
                "源": "1024",
            })
        return True, 列

    def _1024余额(self) -> str:
        码, 说, 数 = self._1024调("/v1/trafficInfo")
        if 码 != 0 or not isinstance(数, dict):
            self.闪臣态["p24余额说"] = 说
            return ""
        try:
            余 = int(数.get("traffic") or 0)
        except (TypeError, ValueError):
            余 = 0
        文 = 人读(余) if 余 else "0"
        self.闪臣态["p24余额"] = 文
        self.闪臣态["p24余额说"] = ""
        return 文

    def _1024加白(self, ip: str = "", 备注: str = "xui-bridge") -> tuple[bool, str]:
        if not self._1024令():
            return False, "没填控制台 token，登录后从后台复制，登录有滑块验证码不能代登"
        目 = str(ip or "").strip() or self.本机出口IP()
        if not 目:
            return False, "问不到本机出口 IP"
        好, 列 = self._1024查白()
        if 好 and any(一.get("ip") == 目 for 一 in 列):
            return True, f"{目} 已在白名单"
        检码, 检说, 检 = self._1024调("/v1/checkTrafficWhite")
        if 检码 == 0 and isinstance(检, dict) and 检.get("is_cn"):
            return False, "1024 不支持给大陆 IP 加白名单，VPS 必须是海外出口"
        参: dict[str, Any] = {"ips": 目, "mark": 备注 or "xui-bridge"}
        号 = self._1024子号()
        if 号:
            参["account_id"] = 号
        码, 说, _ = self._1024调("/v1/addTrafficWhite", 参)
        已 = 码 == 0 or ("exist" in 说.lower()) or ("已存在" in 说) or ("已经" in 说)
        if 已:
            self._1024查白()
            return True, 说 or f"已加入 {目}"
        if "cn" in 说.lower() or "大陆" in 说:
            return False, 说 or "大陆 IP 加不了"
        return False, 说

    def _1024删白(self, 号: str = "", ip: str = "") -> tuple[bool, str]:
        目 = str(ip or "").strip()
        if not 目:
            for 一 in self.闪臣态.get("白名单") or []:
                if str(一.get("id") or "") == str(号 or "").strip():
                    目 = str(一.get("ip") or "")
                    break
        if not 目:
            return False, "1024 删白名单要 IP"
        码, 说, _ = self._1024调("/v1/delTrafficWhite", {"ips": 目})
        好 = 码 == 0
        if 好:
            self._1024查白()
        return 好, 说

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

    def 查缺加白(self, ip: str = "", 备注: str = "xui-bridge") -> tuple[bool, str]:
        """各源各自查白名单，本机不在才加。一家失败不挡另一家。"""
        目 = str(ip or "").strip() or self.本机出口IP()
        说们: list[str] = []
        好 = False
        闪, 千 = self._要加白的源()
        if 闪:
            已, 列 = self.查白名单()
            if 已 and 目 and any(一.get("ip") == 目 for 一 in 列):
                好 = True
                说们.append(f"闪臣：{目} 已在白名单")
            else:
                一好, 一说 = self._闪臣加白(目, 备注)
                好 = 好 or 一好
                说们.append("闪臣：" + 一说)
        if 千:
            已, 列 = self._1024查白()
            if 已 and 目 and any(一.get("ip") == 目 for 一 in 列):
                好 = True
                说们.append(f"1024：{目} 已在白名单")
            else:
                一好, 一说 = self._1024加白(目, 备注)
                好 = 好 or 一好
                说们.append("1024：" + 一说)
        if not 说们:
            return False, "没配能加白的源（闪臣要 Key+安全码，1024 要控制台 token）"
        说 = "；".join(说们)
        self.闪臣态["白名单说"] = f"{time.strftime('%H:%M:%S')} {说}"
        (日志.info if 好 else 日志.warning)("查缺加白：%s", 说)
        return 好, 说

    def 加白名单(self, ip: str = "", 备注: str = "xui-bridge") -> tuple[bool, str]:
        """ip 留空就按本机出口加。闪臣和 1024 谁配了加谁。阻塞。"""
        return self.查缺加白(ip, 备注)

    def _闪臣加白(self, ip: str = "", 备注: str = "xui-bridge") -> tuple[bool, str]:
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
        if 好:
            self.查白名单()
        return 好, 说

    def 删白名单(self, 号: str = "", ip: str = "") -> tuple[bool, str]:
        if not str(号 or "").strip() and not str(ip or "").strip():
            return False, "得给 id 或 ip"
        家 = ""
        for 一 in self.闪臣态.get("白名单") or []:
            if ((号 and str(一.get("id") or "") == str(号).strip())
                    or (ip and str(一.get("ip") or "") == str(ip).strip())):
                家 = str(一.get("源") or "")
                break
        if 家 == "1024" or (not 家 and self.p24开() and (self.当前源() == "1024" or not self.闪臣开())):
            好, 说 = self._1024删白(号, ip)
        else:
            安全码 = str(self.设.get("sc_code") or "").strip()
            if not self.闪臣开() or not 安全码:
                if self.p24开():
                    好, 说 = self._1024删白(号, ip)
                else:
                    return False, "要先填能改白名单的源"
            else:
                码, 说, _ = self._闪臣调("whitelist-remove.html", {
                    "key": str(self.设.get("sc_key") or "").strip(),
                    "security_code": 安全码,
                    "id": str(号 or "").strip(),
                    "ip": str(ip or "").strip(),
                })
                好 = 码 == 0
                if 好:
                    self.查白名单()
        self.闪臣态["白名单说"] = f"{time.strftime('%H:%M:%S')} {'已删除' if 好 else 说}"
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
        列 = [_白条(一, "闪臣") for 一 in (原 or []) if 一]
        旧千 = [一 for 一 in (self.闪臣态.get("白名单") or []) if 一.get("源") == "1024"]
        self.闪臣态["白名单"] = 列 + 旧千
        return True, 列

    def 刷闪臣(self) -> None:
        """余额、白名单、本机出口 IP 一次刷全。阻塞，需放线程里跑。"""
        if not (self.闪臣开() or self.p24开()):
            return
        self.闪臣态["本机IP"] = self.本机出口IP()
        白: list[dict] = []
        闪余 = ""
        if self.闪臣开():
            try:
                self.查余额()
                闪余 = str(self.闪臣态.get("余额") or "")
                好, 列 = self.查白名单()
                if 好:
                    白.extend(列)
            except Exception as 错:
                日志.warning("刷闪臣失败：%s", 错)
        千余 = ""
        if self._1024令():
            try:
                千余 = self._1024余额()
                好, 列 = self._1024查白()
                if 好:
                    白.extend(列)
            except Exception as 错:
                日志.warning("刷1024失败：%s", 错)
        if 闪余 and 千余:
            self.闪臣态["余额"] = f"闪臣 {闪余}；1024 {千余}"
        elif 千余 and not 闪余:
            self.闪臣态["余额"] = 千余
        if 白:
            self.闪臣态["白名单"] = 白
        elif self._1024令() and not self.闪臣开():
            self.闪臣态["白名单"] = 白
        self.闪臣态["刷时间"] = time.strftime("%H:%M:%S")
        try:
            self.查缺加白()
        except Exception as 错:
            日志.warning("查缺加白失败：%s", 错)

    def 节点端口们(self) -> list[int]:
        """墙检要打的入站端口。填了 wall_port 就用它，否则读 Xray 配置。"""
        指定 = int(self.设.get("wall_port") or 0)
        if 指定 > 0:
            return [指定]
        口: list[int] = []
        for p in (
            Path("/usr/local/x-ui/bin/config.json"),
            Path("/usr/local/x-ui-yg/bin/config.json"),
        ):
            if not p.is_file():
                continue
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(d, dict):
                continue
            for ib in d.get("inbounds") or []:
                if not isinstance(ib, dict):
                    continue
                if ib.get("tag") == "api" or ib.get("protocol") in ("dokodemo-door",):
                    continue
                n = ib.get("port")
                try:
                    n = int(n)
                except (TypeError, ValueError):
                    continue
                if n in (self.听口(), self.网页口()) or n <= 0 or n > 65535:
                    continue
                if n not in 口:
                    口.append(n)
        口.sort(key=lambda n: (0 if n in (443, 8443) else 1 if n in (80, 8080) else 2, n))
        return 口

    def 口在听(self, 口: int) -> bool:
        十六 = f"{int(口):04X}"
        for p in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
            if not p.is_file():
                continue
            try:
                for 行 in p.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
                    段 = 行.split()
                    if len(段) < 4:
                        continue
                    本地 = 段[1]
                    if 段[3] == "0A" and 本地.rsplit(":", 1)[-1].upper() == 十六:
                        return True
            except OSError:
                continue
        主们 = ["127.0.0.1", "::1"]
        缓存 = str(self.闪臣态.get("本机IP") or "")
        if 缓存:
            主们.append(缓存)
        for 主 in 主们:
            try:
                s = socket.create_connection((主, 口), timeout=1.5)
                s.close()
                return True
            except OSError:
                continue
        return False

    def _墙取json(self, 址: str, 秒: float = 20) -> Any:
        求 = Request(址, headers={
            "User-Agent": "xui-bridge",
            "Accept": "application/json",
        })
        with urlopen(求, timeout=秒) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "null")

    def _大陆节点(self) -> list[str]:
        try:
            包 = self._墙取json("https://check-host.net/nodes/hosts")
        except Exception as 错:
            raise OSError(f"拿检测节点失败：{错}") from 错
        表 = 包.get("nodes") if isinstance(包, dict) else 包
        if not isinstance(表, dict):
            return []
        出 = []
        for 名, 信 in 表.items():
            列 = 信 if isinstance(信, (list, tuple)) else [信]
            文 = " ".join(str(x) for x in 列).lower()
            码 = str(列[0] if 列 else "").lower()
            if any(x in 文 for x in (
                "hong kong", "hongkong", "taiwan", "macau", "macao",
                "香港", "台湾", "澳门",
            )):
                continue
            if 码 == "cn" or "china" in 文 or "中国" in 文:
                出.append(str(名))
        return 出[:6]

    def _节点通(self, 值: Any) -> bool | None:
        if 值 is None:
            return None
        if isinstance(值, list) and 值:
            一 = 值[0]
            if isinstance(一, dict):
                if 一.get("error"):
                    return False
                if 一.get("time") is not None:
                    return True
        return False

    def 查墙一次(self) -> str:
        """本机端口在听 + 请大陆节点 TCP 回连。阻塞，放线程里跑。"""
        if self._墙检中:
            return self.墙说 or "正在检查"
        self._墙检中 = True
        try:
            口们 = self.节点端口们()
            if not 口们:
                self.墙态, self.墙口 = "未知", 0
                self.墙说 = f"{time.strftime('%H:%M:%S')} 找不到节点端口，到设置里填「墙检端口」"
                return self.墙说
            口 = 口们[0]
            self.墙口 = 口
            if not self.口在听(口):
                self.墙态 = "本机未听"
                self.墙说 = f"{time.strftime('%H:%M:%S')} 端口 {口} 本机没在听，先查 x-ui / Xray"
                return self.墙说
            ip = self.本机出口IP()
            if not ip:
                self.墙态 = "未知"
                self.墙说 = f"{time.strftime('%H:%M:%S')} 拿不到本机公网 IP"
                return self.墙说
            点 = self._大陆节点()
            if not 点:
                self.墙态 = "未知"
                self.墙说 = f"{time.strftime('%H:%M:%S')} 检测网没有大陆节点，无法判断"
                return self.墙说
            目标 = f"[{ip}]:{口}" if ":" in ip and "." not in ip else f"{ip}:{口}"
            q = "&".join(["host=" + quote(目标)] + [f"node={quote(一)}" for 一 in 点])
            开 = self._墙取json("https://check-host.net/check-tcp?" + q)
            if not isinstance(开, dict) or not 开.get("ok"):
                self.墙态 = "未知"
                self.墙说 = f"{time.strftime('%H:%M:%S')} 检测网没接单：{开}"
                return self.墙说
            号 = str(开.get("request_id") or "")
            if not 号:
                self.墙态 = "未知"
                self.墙说 = f"{time.strftime('%H:%M:%S')} 检测网没给单号"
                return self.墙说
            果: dict = {}
            for _ in range(8):
                time.sleep(2)
                一果 = self._墙取json(f"https://check-host.net/check-result/{号}")
                if isinstance(一果, dict):
                    果 = 一果
                    if all(self._节点通(果.get(一)) is not None for 一 in 点):
                        break
            通 = 败 = 0
            for 一 in 点:
                v = self._节点通(果.get(一))
                if v is True:
                    通 += 1
                elif v is False:
                    败 += 1
            总 = 通 + 败
            if 总 <= 0:
                self.墙态 = "未知"
                self.墙说 = f"{time.strftime('%H:%M:%S')} 国内节点还没回结果 {目标}"
            elif 通 <= 0:
                self.墙态 = "墙"
                self.墙说 = (
                    f"{time.strftime('%H:%M:%S')} 疑似被墙：国内 {通}/{总} 通，"
                    f"{目标} 本机在听"
                )
            else:
                self.墙态 = "通"
                self.墙说 = (
                    f"{time.strftime('%H:%M:%S')} 国内能连：{通}/{总} 通，{目标}"
                )
            日志.info("墙检 %s", self.墙说)
            return self.墙说
        except Exception as 错:
            self.墙态 = "未知"
            self.墙说 = f"{time.strftime('%H:%M:%S')} 墙检查出错：{错}"
            日志.warning("%s", self.墙说)
            return self.墙说
        finally:
            self._墙检中 = False
            try:
                self.写状态()
            except Exception:
                pass

    async def 一键开跑(self, 键: str, 码: str, 供应商: str = "",
                    go_key: str = "", go_user: str = "", go_pass: str = "",
                    p24_token: str = "", p24_user: str = "", p24_pass: str = "",
                    p24_url: str = "") -> list[str]:
        """面板上就这一个按钮：存各家参数、提一批。白名单各源自查自加。"""
        补: dict[str, Any] = {}
        补["provider"] = 供应商 or "auto"
        if go_key:
            补["go_key"] = go_key
        if go_user:
            补["go_user"] = go_user
        if go_pass:
            补["go_pass"] = go_pass
        if p24_token:
            补["p24_token"] = p24_token
        if p24_user:
            补["p24_user"] = p24_user
        if p24_pass:
            补["p24_pass"] = p24_pass
        if p24_url:
            补["p24_url"] = p24_url
        # 第一次开跑才铺默认值。之后再点，高级设置里调过的地区、条数不能被冲掉
        if not self.有拉取源():
            补.update({
                "pool_size": int(默认["pool_size"]),
                "sc_protocol": 默认["sc_protocol"],
                "sc_cntry": 默认["sc_cntry"], "sc_state": 默认["sc_state"],
                "sc_city": 默认["sc_city"],
                "check_interval": int(默认["check_interval"]),
            })
        await self.改设(补)
        if not self.有拉取源():
            return ["闪臣、IPIPGO、1024 都没填，池子保持现状。"]
        步 = [f"提取源：{self.源名()}（选的是 {self.设.get('provider') or 'auto'}）"]
        步.append(f"闪臣写死 {闪臣条数} 条 / 1-6小时")
        if go_key:
            步.append("IPIPGO 凭证已更新")
        if p24_token or p24_user or p24_url:
            步.append("1024 凭证已更新")
        步.append(f"1024 写死 {p24条数} 条 / {p24时分} 分钟")
        步.append("白名单各源自查，不在则自动加，不挡提取")
        步.append(await self.开始换新())
        步.append(self.换说())
        return 步

    def _钉地区(self) -> tuple[str, str, str]:
        return (
            str(self.设.get("sc_cntry") or "").strip(),
            str(self.设.get("sc_state") or "").strip(),
            str(self.设.get("sc_city") or "").strip(),
        )

    def 提取条数(self, 数: int | None = None, 源: str = "") -> int:
        if 数 is not None:
            try:
                return max(1, min(500, int(数)))
            except (TypeError, ValueError):
                pass
        if 源 == "1024":
            return p24条数
        return 闪臣条数

    def 提取地址(self, 国: str | None = None, 州: str | None = None, 市: str | None = None,
                数: int | None = None) -> str:
        """填了闪臣 Key 就按参数自动拼提取地址，否则用手填的 fetch_url。"""
        if not self.闪臣开():
            return str(self.设.get("fetch_url") or "").strip()
        国 = str(self.设.get("sc_cntry") or "").strip() if 国 is None else str(国 or "").strip()
        州 = str(self.设.get("sc_state") or "").strip() if 州 is None else str(州 or "").strip()
        市 = str(self.设.get("sc_city") or "").strip() if 市 is None else str(市 or "").strip()
        return self._闪臣址("get-ip.html", {
            "key": 闪臣内置键,
            "count": self.提取条数(数, "shanchen"),
            "time": 闪臣时档,
            "protocol": str(self.设.get("sc_protocol") or "s5"),
            "type": "json",
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
        elif self.当前源() == "1024":
            址 = self.p24提取地址(国 or 钉[0], 钉[1], 钉[2], self.提取条数())
            键 = ""
        else:
            址 = self.提取地址(国 or None, None, None) if 国 else self.提取地址()
            键 = str(self.设.get("sc_key") or "").strip()
        return 址.replace(键, 遮(键)) if 键 and 键 in 址 else 址

    def 拉取方案(self) -> str:
        """闪臣接口的三种文本格式都不带协议，只能按套餐参数定。"""
        if self.闪臣开() or self.ipipgo开() or self.p24开():
            s5 = str(self.设.get("sc_protocol") or "s5").lower() in ("s5", "socks5")
            return "socks5" if s5 else "http"
        return 规范协议(self.设.get("fetch_scheme")) if self.设.get("fetch_scheme") else ""

    def 闪臣快照(self) -> dict[str, Any]:
        本机 = str(self.闪臣态.get("本机IP") or "")
        白 = list(self.闪臣态.get("白名单") or [])
        return {
            "开": self.闪臣开() or self.ipipgo开() or self.p24开(),
            "闪臣开": self.闪臣开(),
            "ipipgo开": self.ipipgo开(),
            "p24开": self.p24开(),
            "供应商": self.源名(),
            "供应商选": self.设.get("provider") or "auto",
            "go_key": self.设.get("go_key") or "",
            "go_url": self.设.get("go_url") or "",
            "go_user": self.设.get("go_user") or "",
            "有go密": bool(str(self.设.get("go_pass") or "").strip()),
            "p24_url": self.设.get("p24_url") or "",
            "p24_user": self.设.get("p24_user") or "",
            "p24_host": self.设.get("p24_host") or 默认["p24_host"],
            "p24_port": int(self.设.get("p24_port") or 默认["p24_port"]),
            "p24_time": int(self.设.get("p24_time") or 默认["p24_time"]),
            "p24_white": int(self.设.get("p24_white") or 0),
            "有token": bool(self._1024令()),
            "有p24密": bool(str(self.设.get("p24_pass") or "").strip()),
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
            "闪臣已加白": bool(本机) and any(
                一.get("ip") == 本机 and 一.get("源") in ("", "闪臣") for 一 in 白),
            "p24已加白": bool(本机) and any(
                一.get("ip") == 本机 and 一.get("源") == "1024" for 一 in 白),
            "刷时间": self.闪臣态.get("刷时间") or "",
            "提取地址": self.提取地址显(),
            "地区": self.地区说(),
            "锁死": {
                "闪臣条数": 闪臣条数,
                "闪臣时长": "1-6小时",
                "p24条数": p24条数,
                "p24时长": f"{p24时分}分钟",
                "使用": "3分钟换新 / 最多4分钟",
            },
        }

    # ---- 提取与补池 ------------------------------------------------------

    def 有拉取源(self) -> bool:
        return bool(self.闪臣开() or self.ipipgo开() or self.p24开()
                    or str(self.设.get("fetch_url") or "").strip()
                    or str(self.设.get("fetch_cmd") or "").strip())

    def _取文(self, 址: str, 令: str) -> tuple[str, str]:
        """按地址或命令取一次原始文本，返回 (正文, 出错说明)。"""
        try:
            if 址:
                求 = Request(址, headers={"User-Agent": "xui-bridge"})
                with urlopen(求, timeout=8) as r:
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
        说 = ""
        出: list[dict] = []
        if 错文:
            说 = f"拉取失败 {time.strftime('%H:%M:%S')} {错文}"
        elif 包 and 包[0] != 0:
            说 = f"接口拒绝 {time.strftime('%H:%M:%S')} {闪臣说(包[0], 包[1])}"
        else:
            出 = self._解代理包(文)
            if not 出:
                说 = (f"拉取无有效行 {time.strftime('%H:%M:%S')}，"
                      f"接口返回：{(文 or '').strip()[:140]}")
        _抽态.说 = 说
        if 说:
            self.上次补 = 说
            日志.warning("%s", 说)
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
                v = 包.get(k)
                if isinstance(v, list):
                    列 = v
                    break
                if isinstance(v, dict) and (v.get("ip") or v.get("server") or v.get("host") or v.get("sever")):
                    列 = [v]
                    break
                if isinstance(v, str) and v.strip():
                    列 = [v]
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
        # 1024 白名单提取是纯 IP:端口，不能把别家账密填上去
        for 一 in 列:
            主 = str(一.get("主机") or "").lower()
            if ipipgo主机 in 主:
                户 = str(self.设.get("go_user") or "").strip()
                密 = str(self.设.get("go_pass") or "").strip()
            elif p24主机 in 主:
                户 = str(self.设.get("p24_user") or "").strip()
                密 = str(self.设.get("p24_pass") or "").strip()
            else:
                continue
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

    def _1024粘(self) -> bool:
        return True

    def _1024时(self) -> int:
        return p24时分

    def _1024区(self, 国: str) -> str:
        国 = 规范国码(国)
        if 国:
            return 国
        库 = self.国库()
        return 库[0] if 库 else "JP"

    def p24提取地址(self, 国: str = "", 州: str = "", 市: str = "", 数: int | None = None) -> str:
        区 = self._1024区(国)
        n = self.提取条数(数, "1024")
        return (
            f"{p24提取根}?region={quote(区)}&num={n}&time={p24时分}&format=1&type=txt"
        )

    def _1024入口(self, 国: str) -> tuple[str, int]:
        现 = str(self.设.get("p24_host") or "").strip() or 默认["p24_host"]
        口 = int(self.设.get("p24_port") or 0) or int(默认["p24_port"])
        官 = {默认["p24_host"], "hk.1024proxy.io", ""}
        if 现 not in 官:
            return 现, 口
        亚 = {"JP", "KR", "SG", "TH", "VN", "MY", "PH", "ID", "HK", "TW", "IN", "AU", "CN"}
        if (国 or "").upper() in 亚:
            return "hk.1024proxy.io", 口
        return (现 or 默认["p24_host"]), 口

    def _1024账密批(self, 国: str, 州: str, 市: str, 数: int) -> list[dict]:
        户 = str(self.设.get("p24_user") or "").strip()
        密 = str(self.设.get("p24_pass") or "").strip()
        if not (户 and 密):
            return []
        主, 口 = self._1024入口(国)
        方案 = self.拉取方案() or "socks5"
        粘 = self._1024粘()
        时 = self._1024时()
        区 = (国 or "").strip().lower()
        出 = []
        for _ in range(数):
            名 = 户
            if 区 and 区 not in ("rand", "random"):
                名 += f"-region-{区}"
            if 州:
                名 += f"-st-{州}"
            if 市:
                名 += f"-city-{市}"
            if 粘:
                名 += f"-sid-{uuid.uuid4().hex[:8]}-t-{时}"
            出.append({"方案": 方案, "主机": 主, "端口": 口, "用户": 名, "密码": 密})
        return 出

    def _抽1024(self, 国: str, 州: str, 市: str, 数: int) -> list[dict]:
        return self._抽一次(self.p24提取地址(国, 州, 市, 数), "")

    def _抽源(self, 源: str, 国: str, 州: str, 市: str, 数: int) -> list[dict]:
        try:
            if 源 == "ipipgo":
                return self._抽ipipgo(国, 州, 市, 数)
            if 源 == "1024":
                return self._抽1024(国, 州, 市, 数)
            return self._抽地(国, 州, 市, 数)
        except Exception as 错:
            说 = f"拉取失败 {self.源名(源)} 提取出错：{错}"
            _抽态.说 = 说
            self.上次补 = 说
            日志.warning("%s", 说)
            return []

    def 地区说(self) -> str:
        选 = str(self.设.get("provider") or "auto").strip() or "auto"
        钉 = 地区文(*self._钉地区())
        if 选 == "auto":
            if 钉:
                return f"自动各源 · 钉死 {钉}"
            if self.这批地区:
                return f"自动各源 · {self.这批地区}"
            return "闪臣和 1024 各从随机国库抽一国，再打乱"
        if 钉:
            return 钉
        if self.这批地区:
            return f"每批一国 · 这批 {self.这批地区}"
        return "每批一国 · 下次从随机国库抽"

    def _记这批(self, 国: str, 州: str = "", 市: str = "") -> None:
        self.这批地区 = 地区文(国, 州, 市) or "随机"

    def 国库(self) -> list[str]:
        return 洗国库(self.设.get("随机国库")) or list(默随机国库)

    def 国名(self, 码: str) -> str:
        码 = 规范国码(码)
        return 国名表.get(码, 码)

    async def 加国(self, 生) -> tuple[list[str], list[str]]:
        """往随机库加国家。返回 (现在的库, 新加进去的)。"""
        async with self.锁:
            现 = self.国库()
            新 = []
            for 码 in 洗国库(生):
                if 码 not in 现:
                    现.append(码)
                    新.append(码)
            if 新:
                self.设["随机国库"] = 现
                self.落盘()
            return 现, 新

    async def 删国(self, 生) -> tuple[list[str], list[str], str]:
        """从随机库去掉国家。至少留一个。返回 (现在的库, 删掉的, 说明)。"""
        async with self.锁:
            现 = self.国库()
            要 = set(洗国库(生))
            剩 = [x for x in 现 if x not in 要]
            if not 剩:
                return 现, [], "至少留一个国家，随机提取才抽得到"
            删 = [x for x in 现 if x in 要]
            if 删:
                self.设["随机国库"] = 剩
                self.落盘()
            return 剩, 删, ""

    def _随机国序(self, 避开: str = "") -> list[str]:
        库 = self.国库()
        列 = [x for x in 库 if x != 避开]
        random.shuffle(列)
        if 避开 and 避开 in 库:
            列.append(避开)
        return 列 or list(库)

    def _抽地(self, 国: str, 州: str, 市: str, 数: int) -> list[dict]:
        出: list[dict] = []
        见: set[str] = set()
        空 = 0
        while len(出) < 数 and 空 < 3:
            批 = self._抽一次(self.提取地址(国, 州, 市, 数=数 - len(出)), "")
            if not 批:
                空 += 1
                continue
            新 = 0
            for 一 in 批:
                k = f"{一.get('主机')}|{一.get('端口')}|{一.get('用户')}"
                if k in 见:
                    continue
                见.add(k)
                出.append(一)
                新 += 1
                if len(出) >= 数:
                    break
            空 = 0 if 新 else 空 + 1
        return 出

    def _抽满(self, 源: str, 国: str, 州: str, 市: str, 数: int) -> list[dict]:
        """提到指定条数为止。接口一次只给 1 条就连提。这家出错立刻停，不连累别家。"""
        出: list[dict] = []
        见: set[str] = set()
        空 = 0
        while len(出) < 数 and 空 < 2:
            try:
                批 = self._抽源(源, 国, 州, 市, 数 - len(出))
            except Exception as 错:
                日志.warning("%s 抽取出错：%s", self.源名(源), 错)
                break
            if not 批:
                空 += 1
                说 = str(getattr(_抽态, "说", "") or "")
                if (说.startswith(("拉取失败", "接口拒绝", "拉取无有效行"))
                        or "提取出错" in 说):
                    break
                continue
            新 = 0
            for 一 in 批:
                k = f"{一.get('主机')}|{一.get('端口')}|{一.get('用户')}"
                if k in 见:
                    continue
                见.add(k)
                出.append(一)
                新 += 1
                if len(出) >= 数:
                    break
            空 = 0 if 新 else 空 + 1
        return 出

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
        if not 换国 and 旧 and 旧 in self.国库():
            候选.append(旧)
        候选.extend(x for x in self._随机国序(旧) if x not in 候选)
        return [(国, "", "") for 国 in 候选]

    def _抽一源(self, 源: str, 数: int, 换国: bool, 多试地: bool = True
              ) -> tuple[list[dict], str, str]:
        """各源按自己写死的条数提。一家失败不挡其他。"""
        try:
            数 = self.提取条数(数 if 数 and 数 > 0 else None, 源)
            地们 = self._地区候选(换国)
            出 = []
            地 = ""
            试 = 地们 if 多试地 else 地们[:1]
            for 一地 in 试 or [("", "", "")]:
                出 = self._抽源(源, *一地, 数)
                if 出:
                    地 = 地区文(*一地) or "随机"
                    break
            if 出:
                for 一 in 出:
                    一["_源"] = 源
                return 出, 地 or "随机国库", ""
            说 = str(getattr(_抽态, "说", "") or self.上次补
                     or f"{self.源名(源)} 提不到")
            return [], "", 说
        except Exception as 错:
            说 = f"{self.源名(源)} 提取出错：{错}"
            日志.warning("%s", 说)
            return [], "", 说

    def _拉取各源(self, 源们: list[str], 数: int, 换国: bool, 令: str) -> list[dict]:
        """自动：各源并行各提，一家挂了其他照进。"""
        from concurrent.futures import ThreadPoolExecutor, wait

        def 一家(源: str) -> tuple[str, list[dict], str, str]:
            try:
                出, 地, 说 = self._抽一源(源, 数, 换国, 多试地=False)
                return 源, 出, 地, 说
            except Exception as 错:
                return 源, [], "", f"{self.源名(源)} 提取出错：{错}"

        列: list[tuple[str, list[dict], str, str]] = []
        if len(源们) > 1:
            with ThreadPoolExecutor(max_workers=len(源们)) as 工:
                未 = {工.submit(一家, 源): 源 for 源 in 源们}
                好, 慢 = wait(未, timeout=90)
                for f in 好:
                    列.append(f.result())
                for f in 慢:
                    列.append((未[f], [], "", f"{self.源名(未[f])} 超时跳过"))
        else:
            列 = [一家(源们[0])]

        合: list[dict] = []
        见: set[str] = set()
        说们: list[str] = []
        成源: list[str] = []
        成地: list[str] = []
        for 源, 出, 地, 说 in 列:
            if 出:
                n = 0
                for 一 in 出:
                    k = f"{一.get('主机')}|{一.get('端口')}|{一.get('用户')}"
                    if k in 见:
                        continue
                    见.add(k)
                    合.append(一)
                    n += 1
                成源.append(源)
                if 地:
                    成地.append(f"{self.源名(源)} {地}")
                说们.append(f"{self.源名(源)} {n} 条")
            else:
                说们.append(f"{self.源名(源)} 跳过：{(说 or '提不到')[:80]}")
        if 合:
            random.shuffle(合)
            self.上次源 = 成源[0] if len(成源) == 1 else "auto"
            self.这批地区 = "、".join(成地) if 成地 else "多源"
            self.上次补 = "自动：" + "；".join(说们)
            日志.info("%s", self.上次补)
            return 合
        if 令:
            return self._抽一次("", 令)
        self.上次补 = "；".join(说们) or "各家都提不到"
        return []

    def 拉取一批(self, 数: int | None = None, 换国: bool = False) -> list[dict]:
        """自动时各源各提指定条数，一家出错不挡其他。钉死一家则只提那家。"""
        令 = str(self.设.get("fetch_cmd") or "").strip()
        数 = self.提取条数(数)
        源们 = self.源顺序()
        if not 源们:
            址 = self.提取地址(数=数)
            return self._抽一次(址, 令) if 址 or 令 else []

        选 = str(self.设.get("provider") or "auto").strip() or "auto"
        if 选 == "auto" and len(源们) > 1:
            return self._拉取各源(源们, 数, 换国, 令)

        最后 = ""
        for 源 in 源们:
            出, 地, 说 = self._抽一源(源, 数, 换国, 多试地=True)
            if 出:
                self.上次源 = 源
                if 地 and "/" in 地:
                    段 = 地.split("/")
                    self._记这批(段[0], 段[1] if len(段) > 1 else "", 段[2] if len(段) > 2 else "")
                else:
                    self._记这批(地, "", "")
                报 = f"{self.源名(源)} 这批 {self.这批地区}，提到 {len(出)}/{数} 条"
                self.上次补 = 报
                日志.info("%s", 报)
                return 出
            最后 = 说 or self.上次补
        if 令:
            return self._抽一次("", 令)
        self.上次补 = 最后 or "各家都提不到"
        return []

    def 拉取下一条(self) -> dict | None:
        批 = self.拉取一批()
        return 批[0] if 批 else None

    def _先验参(self) -> tuple[float, int, str, int]:
        try:
            秒 = float(self.设.get("connect_timeout") or 8)
        except (TypeError, ValueError):
            秒 = 8
        # 先验封顶 4 秒，死线路别拖整批
        秒 = max(2.0, min(4.0, 秒))
        try:
            并发 = int(self.设.get("check_conc") or 32)
        except (TypeError, ValueError):
            并发 = 32
        并发 = max(16, min(64, 并发))
        主 = str(self.设.get("check_host") or "www.dola.com").strip() or "www.dola.com"
        口 = int(self.设.get("check_port") or 443)
        return 秒, 并发, 主, 口

    async def 先验并入(self, 批: list[dict], 入=None) -> list[dict]:
        """先验；通的立刻回调入池，不用等整批验完。"""
        if not 批:
            return []
        from 转发 import 验一条
        秒, 并发, 主, 口 = self._先验参()
        门 = asyncio.Semaphore(并发)

        async def 验(信: dict) -> dict | None:
            一 = 条(信, 来源="拉取")
            async with 门:
                try:
                    await 验一条(一, 秒, 主, 口)
                except Exception as 错:
                    日志.info("先验未过 %s：%s", 一.脱敏(), 错)
                    return None
            if 入 is not None:
                try:
                    await 入(信)
                except ValueError as 错:
                    日志.warning("入池失败：%s", 错)
                    return None
            return 信

        果 = await asyncio.gather(*(验(一) for 一 in 批))
        return [一 for 一 in 果 if 一]

    async def 先验一批(self, 批: list[dict]) -> list[dict]:
        return await self.先验并入(批)

    async def 补齐(self) -> str:
        if self._换中:
            return self.上次补 or "正在换新，先不补"
        if not self.有拉取源():
            说 = "没配提取来源，保持现有池"
            self.上次补 = 说
            return 说
        return await self._轻质入(换代=False, 换国=False)

    async def 换新(self) -> str:
        if self._换中:
            return self.上次补 or "正在换新"
        self._换中 = True
        try:
            return await self._换新本体()
        finally:
            self._换中 = False

    async def _轻质入(self, 换代: bool, 换国: bool) -> str:
        """各源按自己条数和寿限补。补齐只补缺的，换新各提满额。旧代理留下到寿限。"""
        if 换代:
            self.换代 = int(self.换代 or 0) + 1
        源们 = self.源顺序() if self.有拉取源() else []
        新成 = 0
        提数 = 0
        说们: list[str] = []
        if 换代:
            self.这批地区 = ""
        async with self.锁:
            self._标过期()
            self._收旧()

        收: list[dict] = []

        async def 入信(信: dict) -> None:
            nonlocal 新成
            源 = str(信.pop("_源", "") or "")
            async with self.锁:
                入 = self._塞(信, 来源=self._拉取来源(源), 落盘=False)
                入.健康 = True
                入.失败 = 0
                入.上次错误 = ""
                新成 += 1
                self.写状态()
                self.上次补 = f"轻质换新已入 {新成} 条"

        async def 跑源(源: str) -> None:
            nonlocal 提数
            要 = self.提取条数(源=源)
            if not 换代:
                活 = self._源活数(源)
                要 = 要 - 活
                if 要 <= 0:
                    说们.append(f"{self.源名(源)} 还够 {活} 条，不提")
                    return
            try:
                出, 地, 说 = await asyncio.to_thread(self._抽一源, 源, 要, 换国, True)
            except Exception as 错:
                说们.append(f"{self.源名(源)} 提取出错：{错}")
                return
            提数 += len(出)
            if not 出:
                说们.append(f"{self.源名(源)} 跳过：{(说 or '提不到')[:80]}")
                return
            if 地 and 换代:
                self.这批地区 = (
                    (self.这批地区 + "、") if self.这批地区 else ""
                ) + f"{self.源名(源)} {地}"
            收.extend(出)
            说们.append(f"{self.源名(源)} 入 {len(出)} 条")

        if 源们:
            await asyncio.gather(*(跑源(源) for 源 in 源们))
        random.shuffle(收)
        for 信 in 收:
            await 入信(信)
        丢 = 0
        async with self.锁:
            丢 = self._收闲上批() + self._收旧()
            self.落盘()
            工作 = len([一 for 一 in self.条们 if self._提取的(一) and not 一.退役])
        if 换代:
            self.上次换新 = time.strftime("%Y-%m-%d %H:%M:%S")
        地 = f"，{self.这批地区}" if self.这批地区 else ""
        细 = "；".join(说们)
        说 = (f"{'轻质换新' if 换代 else '轻质补入'}{地}，提 {提数} 入 {新成}，工作 {工作} 条"
              f"{'，到期已下 '+str(丢) if 丢 else ''} {time.strftime('%H:%M:%S')}")
        if 细:
            说 += "。" + 细
        self.上次补 = 说
        (日志.info if 新成 else 日志.warning)("%s", 说)
        return 说

    async def _换新本体(self) -> str:
        if not self.有拉取源():
            说 = "没配提取来源，池子保持现状"
            self.上次补 = 说
            return 说
        return await self._轻质入(换代=True, 换国=True)

    def 总览(self) -> dict[str, Any]:
        if self._踢过期() or self._收闲上批():
            self.写状态()
        列 = [一 for 一 in self.条们 if not (self._提取的(一) and self._过期了(一))]
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
            "sc_protocol": self.设.get("sc_protocol") or "s5",
            "sc_cntry": self.设.get("sc_cntry") or "",
            "sc_state": self.设.get("sc_state") or "",
            "sc_city": self.设.get("sc_city") or "",
            "sc_white": int(self.设.get("sc_white") or 0),
            "go_key": self.设.get("go_key") or "",
            "go_url": self.设.get("go_url") or "",
            "go_user": self.设.get("go_user") or "",
            "p24_url": self.设.get("p24_url") or "",
            "p24_user": self.设.get("p24_user") or "",
            "p24_host": self.设.get("p24_host") or 默认["p24_host"],
            "p24_port": int(self.设.get("p24_port") or 默认["p24_port"]),
            "p24_time": int(self.设.get("p24_time") or 默认["p24_time"]),
            "p24_white": int(self.设.get("p24_white") or 0),
            "闪臣": self.闪臣快照(),
            "版本": 版本,
            "换着": self.换着(),
            "上次补": self.上次补,
            "上次换新": self.上次换新,
            "下次换": self.下次换秒(),
            "换说": self.换说(),
            "这批地区": self.这批地区,
            "随机国库": self.国库(),
            "上次源": self.上次源,
            "供应商": self.当前源() or "无",
            "供应商选": self.设.get("provider") or "auto",
            "auto_update": int(self.设.get("auto_update") or 0),
            "update_minutes": self.查更分(),
            "更新说": self.更新说,
            "上轮验活": self.上轮验活,
            "墙态": self.墙态,
            "墙说": self.墙说,
            "墙口": self.墙口,
            "wall_check": int(self.设.get("wall_check") or 0),
            "wall_minutes": int(self.设.get("wall_minutes") or 10),
            "wall_port": int(self.设.get("wall_port") or 0),
            "proxy_on": int(self.设.get("proxy_on") or 0),
            "分流说": self.分流说,
            "健康": len(self.健康们()),
            "总数": len(列),
            "上行": sum(一.上行 for 一 in 列),
            "下行": sum(一.下行 for 一 in 列),
            "上行文": 人读(sum(一.上行 for 一 in 列)),
            "下行文": 人读(sum(一.下行 for 一 in 列)),
            "总上行文": 人读(self.总上行),
            "总下行文": 人读(self.总下行),
            "起算": self.起算,
            "换代": int(self.换代 or 0),
            "档计": {
                "刚提取": sum(1 for 一 in 列 if 一.档(self.换代) == "刚提取"),
                "本批": sum(1 for 一 in 列 if 一.档(self.换代) == "本批"),
                "上批": sum(1 for 一 in 列 if 一.档(self.换代) == "上批"),
                "退役": sum(1 for 一 in 列 if 一.档(self.换代) == "退役"),
            },
            "池": [一.快照(self.换代) for 一 in 列],
            **self.日统计(),
        }

    def 配置快照(self) -> dict[str, Any]:
        """给机器读设置用，不含整池。"""
        身 = self.总览()
        身.pop("池", None)
        身.pop("日表", None)
        return 身
