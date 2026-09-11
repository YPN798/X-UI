# -*- coding: utf-8 -*-
"""桥自己去仓库拉新代码。

跟 update.sh 一个思路：先全下到临时目录、逐个校验语法，全过了才覆盖，
再重启服务。网络抽风下回来半截文件或者 GitHub 的错误页时不会写坏 /opt。

配置里三个开关：
  auto_update     0=关，非 0=开
  update_minutes  多少分钟查一次，默认 5
  update_base     仓库 raw 根地址
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

日志 = logging.getLogger("xui桥")

# 桥自己这几个文件才更新。配置、状态一律不碰
要更的 = (
    "主程序.py", "解析.py", "池.py", "转发.py", "网页.py",
    "更新.py", "写入分流.py", "最低消耗.json",
    "面板.html", "登录.html", "对接.md",
)
装在 = Path("/opt/xui-bridge")
服务名 = "xui-bridge"
# 新版本才有的旁文件。老更新脚本不会拉它们，起来后自己补。
旁文件 = ("面板.html", "登录.html", "对接.md")


def 补一个(名: str, 底: str = "") -> Path:
    """把仓库里的一个文件拉到和 更新.py 同一目录。"""
    底 = (底 or "https://raw.githubusercontent.com/YPN798/X-UI/main").rstrip("/")
    数据 = _下一个(底, 名)
    _校验(名, 数据)
    目标 = Path(__file__).resolve().parent / 名
    目标.write_bytes(数据)
    return 目标


def 补缺旁文件(底: str = "") -> list[str]:
    根 = Path(__file__).resolve().parent
    成 = []
    for 名 in 旁文件:
        p = 根 / 名
        if p.is_file() and p.stat().st_size > 20:
            continue
        try:
            补一个(名, 底)
            成.append(名)
            日志.info("补上了缺的 %s", 名)
        except Exception as 错:
            日志.warning("补 %s 失败：%s", 名, 错)
    return 成


def 本地版本() -> str:
    try:
        import 池 as 池模
        return str(getattr(池模, "版本", "") or "未知")
    except Exception:
        return "未知"


def _下一个(底: str, 名: str, 超时: float = 60) -> bytes:
    # 带时间戳绕开 CDN 缓存，不然常拉回几分钟前的旧内容
    址 = f"{底.rstrip('/')}/{quote('vps桥')}/{quote(名)}?t={int(time.time())}"
    with urlopen(Request(址, headers={"User-Agent": "xui-bridge"}), timeout=超时) as r:
        return r.read()


def 远端版本(底: str) -> str:
    """只下 池.py 看一眼版本号，几十 KB，用来判断值不值得更新。"""
    文 = _下一个(底, "池.py").decode("utf-8", "replace")
    for 行 in 文.splitlines():
        行 = 行.strip()
        if 行.startswith("版本") and "=" in 行:
            值 = 行.split("=", 1)[1].strip()
            return 值.strip('"').strip("'")
    return ""


def _校验(名: str, 数据: bytes) -> None:
    if not 数据.strip():
        raise ValueError(f"{名} 下回来是空的")
    文 = 数据.decode("utf-8", "replace")
    if 名.endswith(".py"):
        ast.parse(文)  # 语法过不了多半是下到了错误页
    elif 名.endswith(".json"):
        json.loads(文)
    elif 名.endswith(".html"):
        低 = 文.lstrip().lower()
        if "<html" not in 低 and "<!doctype" not in 低:
            raise ValueError(f"{名} 不像 HTML")
    elif 名.endswith(".md"):
        if "鉴权" not in 文 and "api" not in 文.lower():
            raise ValueError(f"{名} 不像对接文档")


def 拉一轮(底: str) -> tuple[bool, str]:
    """下载 + 校验 + 覆盖。返回 (有没有换过文件, 说明)。"""
    if not 装在.is_dir():
        return False, f"{装在} 不在，这台机器不是用安装脚本装的，不自动更新"
    旧 = 本地版本()
    try:
        新 = 远端版本(底)
    except Exception as 错:
        return False, f"查版本失败：{错}"
    if not 新:
        return False, "远端 池.py 里没找到版本号"
    if 新 == 旧:
        return False, f"已经是最新 {旧}"

    临 = Path(tempfile.mkdtemp(prefix="xui-bridge-更新-"))
    try:
        for 名 in 要更的:
            try:
                数据 = _下一个(底, 名)
                _校验(名, 数据)
            except Exception as 错:
                return False, f"{名} 拉取或校验没过，这轮不动：{错}"
            (临 / 名).write_bytes(数据)
        for 名 in 要更的:
            shutil.copyfile(临 / 名, 装在 / 名)
    finally:
        shutil.rmtree(临, ignore_errors=True)
    return True, f"已更新 {旧} → {新}"


def 重启服务() -> None:
    """自己把自己重启。systemd 拉起新进程，这个进程随后被杀掉。"""
    for 令 in (["systemctl", "restart", 服务名],
               ["rc-service", 服务名, "restart"]):
        if not shutil.which(令[0]):
            continue
        try:
            subprocess.Popen(令, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception as 错:
            日志.warning("重启 %s 失败：%s", 令[0], 错)
    日志.warning("没有 systemctl / rc-service，代码换了但没重启，下次开机才生效")


async def _过会儿重启() -> None:
    # 给面板那条 HTTP 响应留出送达时间，重启会把自己这个进程一起带走
    await asyncio.sleep(2)
    重启服务()


async def 更新一次(池子, 重启: bool = True) -> str:
    底 = str(池子.设.get("update_base") or "").strip() or \
        "https://raw.githubusercontent.com/YPN798/X-UI/main"
    换了, 说 = await asyncio.to_thread(拉一轮, 底)
    if 换了 and 重启:
        说 += "，正在重启桥"
    池子.更新说 = f"{time.strftime('%H:%M:%S')} {说}"
    日志.info("自动更新：%s", 说)
    if 换了 and 重启:
        池子.写状态()
        asyncio.ensure_future(_过会儿重启())
    return 说


async def 自动更新循环(池子, 停: asyncio.Event) -> None:
    # 刚起来别急着查，先让桥把代理跑通；也避开服务反复重启时连环更新
    try:
        await asyncio.wait_for(停.wait(), timeout=120)
        return
    except asyncio.TimeoutError:
        pass
    while not 停.is_set():
        开 = int(池子.设.get("auto_update") or 0)
        分 = 池子.查更分() if hasattr(池子, "查更分") else 5
        if 开:
            try:
                await 更新一次(池子)
            except Exception as 错:
                池子.更新说 = f"{time.strftime('%H:%M:%S')} 更新出错：{错}"
                日志.warning("自动更新出错：%s", 错)
        try:
            # 关着的时候也醒得勤一点，面板改开关后几分钟内就能跟上
            await asyncio.wait_for(停.wait(), timeout=分 * 60 if 开 else 300)
            return
        except asyncio.TimeoutError:
            continue
