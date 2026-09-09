# -*- coding: utf-8 -*-
"""本机 SOCKS5 入站，经池里挑的上游转出去。"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import socket
import ssl
import struct
import time

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
            if 记 is not None and 累 >= 4096:
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


def _域名字节(主机: str) -> bytes:
    """域名转字节。idna 对下划线、超长标签等会抛错，退回原样发送。"""
    try:
        名 = 主机.encode("idna")
    except Exception:
        名 = 主机.encode("utf-8", "replace")
    if len(名) > 255:
        raise OSError("目标主机名过长")
    return 名


async def _连(主机: str, 端口: int, 秒: float):
    return await asyncio.wait_for(
        asyncio.open_connection(主机, 端口),
        timeout=max(2.0, 秒),
    )


async def _按方案握(读, 写, 一: 条, 方案: str, 目标主: str, 目标口: int) -> None:
    if 方案 == "socks5":
        await _socks5握手(读, 写, 一, 目标主, 目标口)
    elif 方案 == "socks4":
        await _socks4握手(读, 写, 一, 目标主, 目标口)
    else:
        await _http握手(读, 写, 一, 目标主, 目标口)


async def 经上游连(一: 条, 目标主: str, 目标口: int, 秒: float):
    """连上游，再 CONNECT 到目标。返回 (读, 写)。

    闪臣文本行不带协议。标成 http 实际是 s5（或反过来）时，换一种再握一次。
    """
    首选 = 一.方案 or "socks5"
    备 = "http" if 首选 == "socks5" else ("socks5" if 首选 == "http" else "")
    最后: Exception | None = None
    for 方案 in (首选, 备) if 备 else (首选,):
        # TCP 都连不上，换个协议再试也是白等一次超时，直接抛给上层换代理
        读, 写 = await _连(一.主机, 一.端口, 秒)
        try:
            await asyncio.wait_for(
                _按方案握(读, 写, 一, 方案, 目标主, 目标口),
                timeout=max(2.0, 秒),
            )
            if 方案 != 首选:
                一.方案 = 方案
                日志.info("上游 %s 实际是 %s，已改过来", 一.脱敏(), 方案)
            return 读, 写
        except Exception as 错:
            最后 = 错
            try:
                写.close()
            except Exception:
                pass
            # 协议认错会很快报错或断开；一直不吭声的换个协议问也是同样不吭声
            if isinstance(错, asyncio.TimeoutError):
                break
    raise 最后 or OSError("上游握手失败")


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
    名 = _域名字节(主机)
    return b"\x05\x01\x00\x03" + bytes([len(名)]) + 名 + 口


async def _socks4握手(读, 写, 一: 条, 目标主: str, 目标口: int) -> None:
    """SOCKS4：目标是 IPv4 就直接发；是域名则用 SOCKS4a（DSTIP 填 0.0.0.1，包尾附域名）。"""
    if ":" in 目标主:
        raise OSError("SOCKS4 不支持 IPv6 目标")
    户 = (一.用户 or "").encode("utf-8", "replace")
    口 = struct.pack("!H", int(目标口))
    try:
        写.write(b"\x04\x01" + 口 + socket.inet_aton(目标主) + 户 + b"\x00")
    except OSError:
        名 = _域名字节(目标主)
        写.write(b"\x04\x01" + 口 + b"\x00\x00\x00\x01" + 户 + b"\x00" + 名 + b"\x00")
    await 写.drain()
    答 = await _读准(读, 8)
    if 答[0] != 0:
        raise OSError(f"上游不是 SOCKS4，版本字节 {答[0]}")
    if 答[1] != 90:
        raise OSError(f"上游 SOCKS4 拒绝，应答码 {答[1]}")


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


async def 验一条(一: 条, 秒: float, 主: str = "www.dola.com", 口: int = 443) -> None:
    """经上游 CONNECT 目标并握手 TLS，默认验 www.dola.com，不是 1.1.1.1。"""
    读, 写 = await 经上游连(一, 主, 口, 秒)
    try:
        if hasattr(写, "start_tls"):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            await asyncio.wait_for(写.start_tls(ctx, server_hostname=主), timeout=秒)
    finally:
        try:
            写.close()
            await 写.wait_closed()
        except Exception:
            pass


出口站们 = (
    ("ip-api.com", "/json/?fields=status,country,countryCode,city,query&lang=zh-CN"),
    ("ipwho.is", "/?fields=success,country,country_code,city,ip"),
)


async def 探出口(一: 条, 秒: float) -> str:
    """经这条代理问一下外面看到的是哪国哪城。走明文 80 口，一次几百字节。"""
    最后 = ""
    for 站, 路 in 出口站们:
        try:
            读, 写 = await 经上游连(一, 站, 80, 秒)
        except Exception as 错:
            最后 = str(错)
            continue
        try:
            写.write((f"GET {路} HTTP/1.1\r\nHost: {站}\r\nUser-Agent: curl/8\r\n"
                      "Connection: close\r\n\r\n").encode("ascii"))
            await 写.drain()
            原 = await asyncio.wait_for(读.read(65536), timeout=max(2.0, 秒))
        except Exception as 错:
            最后 = str(错)
            continue
        finally:
            try:
                写.close()
            except Exception:
                pass
        体 = 原.split(b"\r\n\r\n", 1)[-1]
        try:
            j = json.loads(体.decode("utf-8", "replace").strip() or "{}")
        except ValueError:
            最后 = "出口应答不是 JSON"
            continue
        if not isinstance(j, dict) or (j.get("status") == "fail") or (j.get("success") is False):
            最后 = str(j.get("message") or "出口查询被拒")
            continue
        国 = str(j.get("countryCode") or j.get("country_code") or "").upper()
        名 = str(j.get("country") or "")
        城 = str(j.get("city") or "")
        ip = str(j.get("query") or j.get("ip") or "")
        return " ".join(x for x in (国 or 名, 城, ip) if x)
    raise OSError(最后 or "探不到出口")


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
            目标主 = (await _读准(读, n)).decode("utf-8", "replace")
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
        试过: set[str] = set()
        for _ in range(3):
            选 = await 池子.选(目标主)
            if 选 is None:
                raise OSError("代理池是空的")
            if 选.号 in 试过:
                break
            试过.add(选.号)
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
    上次换 = time.monotonic()
    上次刷 = 0.0
    if 池子.可自动白():
        try:
            _, 说 = await asyncio.to_thread(池子.加白名单)
            日志.info("开机自动加白名单：%s", 说)
        except Exception as 错:
            日志.warning("开机加白名单失败：%s", 错)
    while not 停.is_set():
        间隔 = max(8, int(池子.设.get("check_interval") or 120))
        秒 = float(池子.设.get("connect_timeout") or 8)
        并发 = max(1, min(64, int(池子.设.get("check_conc") or 16)))
        验主 = str(池子.设.get("check_host") or "www.dola.com").strip() or "www.dola.com"
        验口 = int(池子.设.get("check_port") or 443)
        门 = asyncio.Semaphore(并发)
        拷 = [一 for 一 in list(池子.条们) if 一.启用]
        起 = time.monotonic()

        async def 验(一: 条) -> None:
            async with 门:
                if 停.is_set():
                    return
                try:
                    await 验一条(一, 秒, 验主, 验口)
                    await 池子.报成(一)
                except Exception as 错:
                    await 池子.报败(一, str(错))

        # 每个阶段都给上限。任何一步卡住，换新和刷余额就全停了，面板看着像死机
        if 拷:
            轮数 = -(-len(拷) // 并发)
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(验(一) for 一 in 拷)),
                    timeout=轮数 * 秒 * 3 + 30,
                )
            except asyncio.TimeoutError:
                日志.warning("这轮验活超时，先往下走")
        好 = len(池子.健康们())
        池子.上轮验活 = f"{time.strftime('%H:%M:%S')} 验了 {len(拷)} 条，健康 {好}，用了 {time.monotonic() - 起:.0f} 秒"

        换期 = max(0, int(池子.设.get("auto_rotate") or 0))
        现在 = time.monotonic()
        if 池子.闪臣开() and 现在 - 上次刷 >= 60:
            上次刷 = 现在
            try:
                await asyncio.wait_for(asyncio.to_thread(池子.刷闪臣), timeout=90)
            except asyncio.TimeoutError:
                日志.warning("刷闪臣状态超时")
            except Exception as 错:
                日志.warning("刷闪臣状态失败：%s", 错)
        try:
            if 换期 and 现在 - 上次换 >= 换期:
                上次换 = 现在
                await asyncio.wait_for(池子.换新(), timeout=90)
            else:
                await asyncio.wait_for(池子.补齐(), timeout=90)
        except asyncio.TimeoutError:
            日志.warning("补池/换新超时")
        except Exception as 错:
            日志.warning("补池/换新失败：%s", 错)

        # 新进来的线路问一下出口在哪国，面板上才看得出地区是不是真随机
        没探 = [一 for 一 in list(池子.条们) if 一.启用 and 一.健康 and not 一.出口][:64]
        if 没探:
            async def 探(一: 条) -> None:
                async with 门:
                    if 停.is_set():
                        return
                    try:
                        一.出口 = await 探出口(一, 秒)
                    except Exception as 错:
                        一.出口 = "? " + str(错)[:40]
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(探(一) for 一 in 没探)),
                    timeout=(-(-len(没探) // 并发)) * 秒 * 2 + 20,
                )
            except asyncio.TimeoutError:
                日志.warning("探出口超时，剩下的下一轮再探")

        池子.换基 = 上次换
        池子.写状态()
        日志.info("%s；下次换新约 %s 秒后", 池子.上轮验活, 池子.下次换秒())
        try:
            await asyncio.wait_for(停.wait(), timeout=间隔)
        except asyncio.TimeoutError:
            pass
