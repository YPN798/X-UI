# -*- coding: utf-8 -*-
"""解析代理串。格式与 代理浏览器/代理.py 的 拆() 一致。"""

from __future__ import annotations

from urllib.parse import quote, unquote, urlparse


def 脱敏(串: str) -> str:
    信 = 拆(串) if (串 or "").strip() else {}
    if 信.get("主机") and 信.get("端口"):
        return f"{信.get('方案') or 'http'}://{信['主机']}:{信['端口']}"
    文 = (串 or "").strip()
    return 文[:48] if 文 else "（空）"


def 规范协议(协议: str) -> str:
    文 = (协议 or "http").strip().lower()
    if 文 in ("sk5", "s5", "socks", "socks5h", "sock5", "socks5"):
        return "socks5"
    return "http"


def _像主机端口(段: str) -> bool:
    段 = (段 or "").strip()
    if not 段 or "://" in 段:
        return False
    if 段.count(":") != 1:
        return False
    主, 口 = 段.rsplit(":", 1)
    return bool(主) and 口.isdigit() and 1 <= int(口) <= 65535


def 拆(串: str) -> dict:
    行 = (串 or "").strip()
    if not 行:
        return {"方案": "http", "主机": "", "端口": 0, "用户": "", "密码": ""}
    if "|" in 行 and "://" not in 行:
        段们 = [一.strip() for 一 in 行.split("|")]
        if len(段们) >= 2 and 段们[1].isdigit():
            口 = int(段们[1])
            if 1 <= 口 <= 65535:
                return {
                    "方案": "socks5",
                    "主机": 段们[0],
                    "端口": 口,
                    "用户": 段们[2] if len(段们) > 2 else "",
                    "密码": 段们[3] if len(段们) > 3 else "",
                }
        if len(段们) >= 2 and _像主机端口(段们[0]):
            主, 口 = 段们[0].rsplit(":", 1)
            return {
                "方案": "http",
                "主机": 主,
                "端口": int(口),
                "用户": 段们[1] if len(段们) > 1 else "",
                "密码": 段们[2] if len(段们) > 2 else "",
            }
    if "://" in 行:
        段 = urlparse(行)
        方案 = 规范协议(段.scheme or "http")
        return {
            "方案": 方案,
            "主机": 段.hostname or "",
            "端口": int(段.port or 0),
            "用户": unquote(段.username) if 段.username else "",
            "密码": unquote(段.password) if 段.password else "",
        }
    if "@" in 行:
        前, 后 = 行.split("@", 1)
        if _像主机端口(前) and ":" in 后:
            用户, 密 = 后.split(":", 1)
            主, 口 = 前.rsplit(":", 1)
            return {"方案": "http", "主机": 主, "端口": int(口),
                    "用户": 用户, "密码": 密}
        if _像主机端口(后) and ":" in 前:
            用户, 密 = 前.split(":", 1)
            主, 口 = 后.rsplit(":", 1)
            return {"方案": "http", "主机": 主, "端口": int(口),
                    "用户": 用户, "密码": 密}
    段们 = 行.split(":")
    if len(段们) == 2 and 段们[1].isdigit():
        return {"方案": "socks5", "主机": 段们[0], "端口": int(段们[1]),
                "用户": "", "密码": ""}
    if len(段们) == 4 and 段们[1].isdigit():
        return {"方案": "socks5", "主机": 段们[0], "端口": int(段们[1]),
                "用户": 段们[2], "密码": 段们[3]}
    raise ValueError(
        "代理格式不对。可用：socks5://用户:密码@主机:端口、"
        "IP|端口|用户名|密码、主机:端口:用户:密码"
    )


def 给上游(信: dict) -> str:
    主 = (信.get("主机") or "").strip()
    口 = int(信.get("端口") or 0)
    if not 主 or not 口:
        raise ValueError("代理缺主机或端口")
    方案 = 规范协议(信.get("方案") or "http")
    前 = "socks5" if 方案 == "socks5" else "http"
    户 = (信.get("用户") or "").strip()
    密 = (信.get("密码") or "").strip()
    if 户 or 密:
        return f"{前}://{quote(户, safe='')}:{quote(密, safe='')}@{主}:{口}"
    return f"{前}://{主}:{口}"


def 本机主机(主机: str) -> bool:
    h = (主机 or "").strip().lower().strip("[]")
    return h in {"127.0.0.1", "::1", "localhost", "0.0.0.0", "::"}
