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
import re
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


_版本行 = re.compile(r'^版本\s*=\s*["\']([^"\']+)["\']')
_提交缓存 = {"时": 0.0, "值": ""}


def _头() -> dict[str, str]:
    return {
        "User-Agent": "xui-bridge",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Accept": "*/*",
    }


def _仓(底: str) -> tuple[str, str]:
    段 = 底.rstrip("/").split("/")
    try:
        i = 段.index("raw.githubusercontent.com")
        return 段[i + 1], 段[i + 2]
    except (ValueError, IndexError):
        return "YPN798", "X-UI"


def _最新提交(底: str) -> str:
    """问 GitHub 当前 main 的 SHA。raw 的 /main/ 经常被 CDN 缓存成旧文件。"""
    now = time.time()
    if _提交缓存["值"] and now - float(_提交缓存["时"] or 0) < 60:
        return str(_提交缓存["值"])
    主, 仓 = _仓(底)
    址 = f"https://api.github.com/repos/{主}/{仓}/commits/main"
    求 = Request(址, headers={**_头(), "Accept": "application/vnd.github+json"})
    with urlopen(求, timeout=20) as r:
        包 = json.loads(r.read().decode("utf-8", "replace"))
    提交 = str(包.get("sha") or "")
    if not 提交:
        raise ValueError("GitHub 没返回提交号")
    _提交缓存["时"] = now
    _提交缓存["值"] = 提交
    return 提交


def _地址们(底: str, 名: str, 提交: str = "") -> list[str]:
    路径 = f"{quote('vps桥')}/{quote(名)}"
    主, 仓 = _仓(底)
    出: list[str] = []
    if 提交:
        出.append(f"https://raw.githubusercontent.com/{主}/{仓}/{提交}/{路径}")
        出.append(f"https://cdn.jsdelivr.net/gh/{主}/{仓}@{提交}/{路径}")
    出.append(f"{底.rstrip('/')}/{路径}")
    出.append(f"https://cdn.jsdelivr.net/gh/{主}/{仓}@main/{路径}")
    # 去重保序
    见: set[str] = set()
    净 = []
    for 一 in 出:
        if 一 not in 见:
            见.add(一)
            净.append(一)
    return 净


# raw 下到 GitHub / jsDelivr 错误页时的痕迹。面板本身就是 HTML，
# 不能再靠「以 <!DOCTYPE 开头」一刀切，否则 面板.html 永远拉不下来。
_错页 = (
    b"404: not found",
    b"couldn't find the requested file",
    b"this is not the web page you are looking for",
    b"repository not found",
    b"<title>404",
    b"failed to fetch",
    b"cannot find package",
)


def _像文件(名: str, 数据: bytes) -> bool:
    if not 数据 or not 数据.strip():
        return False
    低 = 数据[:8000].lower()
    if any(痕 in 低 for 痕 in _错页):
        return False
    if 名.endswith((".html", ".htm")):
        return (b"xui-bridge" in 低
                or "桥控制台".encode("utf-8") in 数据[:8000]
                or b"<html" in 低 or b"<!doctype" in 低)
    头 = 数据.lstrip()[:80].lower()
    return not (头.startswith(b"<!doctype") or 头.startswith(b"<html"))


def _下一个(底: str, 名: str, 超时: float = 60, 提交: str = "") -> bytes:
    错们: list[str] = []
    for 址 in _地址们(底, 名, 提交):
        try:
            with urlopen(Request(址, headers=_头()), timeout=超时) as r:
                数据 = r.read()
        except Exception as 错:
            错们.append(f"{址}：{错}")
            continue
        if _像文件(名, 数据):
            return 数据
        错们.append(f"{址} 返回了网页而不是文件")
    raise OSError("；".join(错们[:3]) or "没有可用的下载地址")


def 远端版本(底: str, 提交: str = "") -> str:
    """只下 池.py 看一眼版本号，用来判断值不值得更新。"""
    文 = _下一个(底, "池.py", 提交=提交).decode("utf-8", "replace")
    for 行 in 文.splitlines():
        m = _版本行.match(行.strip())
        if m:
            return m.group(1)
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
    提交 = ""
    try:
        提交 = _最新提交(底)
    except Exception as 错:
        日志.warning("拿提交号失败，改走 raw/main：%s", 错)
    try:
        新 = 远端版本(底, 提交)
    except Exception as 错:
        return False, f"查版本失败：{错}"
    if not 新:
        return False, "远端 池.py 里没找到版本号"
    if 新 == 旧:
        尾 = f"（提交 {提交[:7]}）" if 提交 else ""
        return False, f"已经是最新 {旧}{尾}"

    临 = Path(tempfile.mkdtemp(prefix="xui-bridge-更新-"))
    try:
        for 名 in 要更的:
            try:
                数据 = _下一个(底, 名, 提交=提交)
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
