#!/bin/bash
# 业务机：独立节点。自己管 VMess 和桥，停掉 x-ui，不改面板数据库。
#   bash 安装.sh
#   NODE_PORT=14564 XUI_PROXY='socks5://用户:密码@1.2.3.4:1080' bash 安装.sh
set -euo pipefail
根="$(cd "$(dirname "$0")" && pwd)"
export DEBIAN_FRONTEND=noninteractive
RAW="https://raw.githubusercontent.com/YPN798/X-UI/main/%E8%8A%82%E7%82%B9"

拉(){
  local f="$1" 到="$2"
  if [[ -f "$根/$f" ]]; then
    cp -f "$根/$f" "$到"
  else
    curl -fsSL "$RAW/$f" -o "$到"
  fi
}

if ! command -v python3 >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y python3 curl
  elif command -v yum >/dev/null 2>&1; then
    yum install -y python3 curl
  fi
fi
command -v curl >/dev/null 2>&1 || apt-get install -y curl >/dev/null 2>&1 || true

mkdir -p /opt/dola-node /etc/dola-node
for f in 主程序.py 解析.py 池.py 转发.py 网页.py 监督xray.py 配置.示例.json; do
  拉 "$f" "/opt/dola-node/$f"
done
拉 dola-node.service /etc/systemd/system/dola-node.service

cfg=/etc/dola-node/config.json
if [[ ! -f $cfg ]]; then
  if [[ -f /etc/xui-bridge/config.json ]]; then
    cp -f /etc/xui-bridge/config.json "$cfg"
    echo "沿用旧桥代理池 /etc/xui-bridge/config.json"
  else
    cp -f /opt/dola-node/配置.示例.json "$cfg"
  fi
fi

NODE_PORT="${NODE_PORT:-14564}" XUI_PROXY="${XUI_PROXY:-}" python3 - <<'PY'
import json, os
p = "/etc/dola-node/config.json"
try:
    d = json.load(open(p, encoding="utf-8"))
except Exception:
    d = {}
d.setdefault("listen", "127.0.0.1")
d.setdefault("port", 41000)
d.setdefault("web", "0.0.0.0")
d.setdefault("web_port", 41001)
d.setdefault("web_pass", "YPN940815...")
d.setdefault("node_uuid", "")
d.setdefault("node_listen", "0.0.0.0")
d.setdefault("public_host", "")
port = os.environ.get("NODE_PORT") or ""
if port.isdigit():
    d["node_port"] = int(port)
else:
    d.setdefault("node_port", 14564)
px = (os.environ.get("XUI_PROXY") or "").strip()
lst = list(d.get("proxies") or [])
if px and px not in lst:
    lst.append(px)
d["proxies"] = lst
open(p, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
print("配置", p, "节点口", d.get("node_port"), "池", len(d.get("proxies") or []))
PY

if command -v systemctl >/dev/null 2>&1; then
  systemctl disable --now x-ui >/dev/null 2>&1 || true
  systemctl disable --now xui-bridge >/dev/null 2>&1 || true
fi

systemctl daemon-reload
systemctl enable dola-node
systemctl restart dola-node
sleep 2
systemctl --no-pager --full status dola-node || true
echo
ss -lntp | grep -E '14564|41000|41001|798' || true
echo
echo "=============== 业务节点 ==============="
echo "已停用 x-ui（避免两个 Xray 抢口）"
echo "管理页  http://公网IP:41001/   密码见 /etc/dola-node/config.json 的 web_pass"
echo "节点口  ${NODE_PORT:-14564}（分享链接在管理页，导入 v2rayN）"
echo "桥      127.0.0.1:41000"
echo "池为空时先在管理页贴代理，再点「测通路」"
echo "开 dola 后池的连接/上下行必须增加，才算桥有作用"
echo "========================================"
