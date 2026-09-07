# -*- coding: utf-8 -*-
"""本机 SOCKS5 入站，经池里挑的上游转出去。"""

from __future__ import annotations

import asyncio
import base64
import logging
import socket
import struct

from 池 import 池, 条
from 解析 import 本机主机

日志 = logging.getLogger("xui桥")


async def _读准(读: asyncio.StreamReader, n: int) -> bytes:
    数据 = await 读.readexactly(n)
    return 数据


async def _对拷(甲: asyncio.StreamReader, 乙: asyncio.StreamWriter, 记=None) -> None:
    累 = 0
    try:
        while True:
            块 = await 甲.read(65536)
            if not 块:
                break
            乙.write(块)
            await 乙.drain()
            累 += len(块)
            if 记 is not None and 累 >= 262144:
                await 记(累)
                累 = 0
    except (asyncio.CancelledError, ConnectionError, OSError):
        pass
    finally:
        if 记 is not None and 累:
            try:
                await 记(累)
            except Exception:
                pass
        try:
            乙.close()
        except Exception:
            pass


async def _连(主机: str, 端口: int, 秒: float):
    return await asyncio.wait_for(
        asyncio.open_connection(主机, 端口),
        timeout=max(2.0, 秒),
    )


async def 经上游连(一: 条, 目标主: str, 目标口: int, 秒: float):
    """连上游，再 CONNECT 到目标。返回 (读, 写)。"""
    读, 写 = await _连(一.主机, 一.端口, 秒)
    try:
        if 一.方案 == "socks5":
            await _socks5握手(读, 写, 一, 目标主, 目标口)
        else:
            await _http握手(读, 写, 一, 目标主, 目标口)
    except Exception:
        try:
            写.close()
            await 写.wait_closed()
        except Exception:
            pass
        raise
    return 读, 写


async def _socks5握手(读, 写, 一: 条, 目标主: str, 目标口: int) -> None:
    if 一.用户 or 一.密码:
        写.write(b"\x05\x01\x02")
    else:
        写.write(b"\x05\x01\x00")
    await 写.drain()
    答 = await _读准(读, 2)
    if 答[0] != 5:
        raise OSError("上游不是 SOCKS5")
    if 答[1] == 2:
        户 = (一.用户 or "").encode("utf-8")
        密 = (一.密码 or "").encode("utf-8")
        写.write(b"\x01" + bytes([len(户)]) + 户 + bytes([len(密)]) + 密)
        await 写.drain()
        认 = await _读准(读, 2)
        if 认[1] != 0:
            raise OSError("上游 SOCKS5 账密失败")
    elif 答[1] != 0:
        raise OSError(f"上游 SOCKS5 方法拒绝 {答[1]}")
    写.write(_socks5请求(目标主, 目标口))
    await 写.drain()
    头 = await _读准(读, 4)
    if 头[1] != 0:
        raise OSError(f"上游 CONNECT 失败 {头[1]}")
    atyp = 头[3]
    if atyp == 1:
        await _读准(读, 4 + 2)
    elif atyp == 3:
        n = (await _读准(读, 1))[0]
        await _读准(读, n + 2)
    elif atyp == 4:
        await _读准(读, 16 + 2)
    else:
        raise OSError(f"上游 ATYP 不明 {atyp}")


def _socks5请求(主机: str, 端口: int) -> bytes:
    口 = struct.pack("!H", int(端口))
    try:
        return b"\x05\x01\x00\x01" + socket.inet_aton(主机) + 口
    except OSError:
        pass
    try:
        return b"\x05\x01\x00\x04" + socket.inet_pton(socket.AF_INET6, 主机) + 口
    except OSError:
        pass
    名 = 主机.encode("idna")
    if len(名) > 255:
        raise OSError("目标主机名过长")
    return b"\x05\x01\x00\x03" + bytes([len(名)]) + 名 + 口


async def _http握手(读, 写, 一: 条, 目标主: str, 目标口: int) -> None:
    行 = [f"CONNECT {目标主}:{目标口} HTTP/1.1", f"Host: {目标主}:{目标口}"]
    if 一.用户 or 一.密码:
        票 = base64.b64encode(f"{一.用户}:{一.密码}".encode("utf-8")).decode("ascii")
        行.append(f"Proxy-Authorization: Basic {票}")
    行.append("Proxy-Connection: keep-alive")
    行.append("")
    行.append("")
    写.write("\r\n".join(行).encode("ascii", "replace"))
    await 写.drain()
    缓冲 = b""
    while b"\r\n\r\n" not in 缓冲 and len(缓冲) < 8192:
        块 = await 读.read(1024)
        if not 块:
            break
        缓冲 += 块
    首 = 缓冲.split(b"\r\n", 1)[0].decode("ascii", "replace")
    if " 200" not in 首:
        raise OSError(f"上游 HTTP CONNECT 失败 {首[:80]}")


async def 验一条(一: 条, 秒: float) -> None:
    """只验上游握手：经它 CONNECT 1.1.1.1:443。"""
    读, 写 = await 经上游连(一, "1.1.1.1", 443, 秒)
    try:
        写.close()
        await 写.wait_closed()
    except Exception:
        pass


async def 处理客户(读: asyncio.StreamReader, 写: asyncio.StreamWriter, 池子: 池) -> None:
    选: 条 | None = None
    try:
        头 = await _读准(读, 2)
        if 头[0] != 5:
            raise OSError("只接受 SOCKS5")
        n = 头[1]
        await _读准(读, n)
        写.write(b"\x05\x00")
        await 写.drain()
        求 = await _读准(读, 4)
        if 求[0] != 5 or 求[1] != 1:
            写.write(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            await 写.drain()
            return
        atyp = 求[3]
        if atyp == 1:
            目标主 = socket.inet_ntoa(await _读准(读, 4))
        elif atyp == 3:
            n = (await _读准(读, 1))[0]
            目标主 = (await _读准(读, n)).decode("idna", "replace")
        elif atyp == 4:
            目标主 = socket.inet_ntop(socket.AF_INET6, await _读准(读, 16))
        else:
            raise OSError("ATYP 不支持")
        目标口 = struct.unpack("!H", await _读准(读, 2))[0]
        if 本机主机(目标主) and 目标口 in {池子.听口(), 池子.网页口()}:
            raise OSError("拒绝连回桥自身")

        秒 = float(池子.设.get("connect_timeout") or 8)
        上次 = ""
        上: tuple | None = None
        for _ in range(2):
            选 = await 池子.选(目标主)
            if 选 is None:
                raise OSError("代理池是空的")
            try:
                上 = await 经上游连(选, 目标主, 目标口, 秒)
                await 池子.报成(选)
                break
            except Exception as 错:
                上次 = str(错)
                await 池子.报败(选, 上次)
                选 = None
                上 = None
        if 上 is None:
            raise OSError(上次 or "没有可用上游")

        写.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        await 写.drain()
        await 池子.进(选)
        try:
            上读, 上写 = 上

            async def 记上(n: int) -> None:
                await 池子.记流量(选, 上行=n)

            async def 记下(n: int) -> None:
                await 池子.记流量(选, 下行=n)

            await asyncio.gather(_对拷(读, 上写, 记上), _对拷(上读, 写, 记下))
        finally:
            await 池子.出(选)
    except Exception as 错:
        日志.debug("客户断开：%s", 错)
        try:
            写.write(b"\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00")
            await 写.drain()
        except Exception:
            pass
    finally:
        try:
            写.close()
            await 写.wait_closed()
        except Exception:
            pass


async def 开socks(池子: 池) -> asyncio.AbstractServer:
    主 = str(池子.设.get("listen") or "127.0.0.1")
    口 = 池子.听口()

    async def _接(读, 写):
        await 处理客户(读, 写, 池子)

    服 = await asyncio.start_server(_接, 主, 口)
    日志.info("SOCKS5 听 %s:%s", 主, 口)
    return 服


async def 验活循环(池子: 池, 停: asyncio.Event) -> None:
    while not 停.is_set():
        间隔 = max(8, int(池子.设.get("check_interval") or 30))
        秒 = float(池子.设.get("connect_timeout") or 8)
        并发 = max(1, min(64, int(池子.设.get("check_conc") or 16)))
        门 = asyncio.Semaphore(并发)
        拷 = [一 for 一 in list(池子.条们) if 一.启用]

        async def 验(一: 条) -> None:
            async with 门:
                if 停.is_set():
                    return
                try:
                    await 验一条(一, 秒)
                    await 池子.报成(一)
                except Exception as 错:
                    await 池子.报败(一, str(错))

        if 拷:
            await asyncio.gather(*(验(一) for 一 in 拷))
        try:
            await 池子.补齐()
        except Exception as 错:
            日志.warning("补池失败：%s", 错)
        池子.写状态()
        try:
            await asyncio.wait_for(停.wait(), timeout=间隔)
        except asyncio.TimeoutError:
            pass
