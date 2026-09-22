#!/bin/bash
# 业务机一键：装桥。分流默认关闭，恢复 X-UI 原设置。不要在出口机上跑。
#   bash 安装.sh
#   XUI_PROXY='socks5://用户:密码@1.2.3.4:1080' bash 安装.sh
set -euo pipefail
根="$(cd "$(dirname "$0")" && pwd)"

装依赖(){
  command -v python3 >/dev/null 2>&1 && command -v sqlite3 >/dev/null 2>&1 && return 0
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y >/dev/null 2>&1 || true
    apt-get install -y python3 sqlite3 >/dev/null
  elif command -v yum >/dev/null 2>&1; then
    yum install -y python3 sqlite >/dev/null
  elif command -v apk >/dev/null 2>&1; then
    apk add python3 sqlite >/dev/null
  fi
}

写池(){
  mkdir -p /etc/xui-bridge
  local cfg=/etc/xui-bridge/config.json
  if [[ -f $cfg && -z ${XUI_PROXY:-} ]]; then
    echo "已有 $cfg，不覆盖代理池"
    return 0
  fi
  if [[ -f $cfg && -n ${XUI_PROXY:-} ]]; then
    XUI_PROXY="$XUI_PROXY" python3 - <<'PY'
import json, os
p = "/etc/xui-bridge/config.json"
px = (os.environ.get("XUI_PROXY") or "").strip()
try:
    d = json.load(open(p, encoding="utf-8"))
except Exception:
    d = {}
d.setdefault("listen", "127.0.0.1")
d.setdefault("port", 41000)
d.setdefault("web", "0.0.0.0")
d.setdefault("web_port", 41001)
d.setdefault("web_pass", "YPN940815...")
lst = list(d.get("proxies") or [])
if px and px not in lst:
    lst.append(px)
d["proxies"] = lst
open(p, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
print("已把 XUI_PROXY 并入", p)
PY
    return 0
  fi
  cp -f "$根/配置.示例.json" "$cfg"
  if [[ -n ${XUI_PROXY:-} ]]; then
    XUI_PROXY="$XUI_PROXY" python3 - <<'PY'
import json, os
p = "/etc/xui-bridge/config.json"
d = json.load(open(p, encoding="utf-8"))
px = (os.environ.get("XUI_PROXY") or "").strip()
d["proxies"] = [px] if px else []
open(p, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
PY
  fi
}

关分流(){
  if [[ -f /opt/xui-bridge/写入分流.py ]]; then
    python3 /opt/xui-bridge/写入分流.py 关 || true
  elif [[ -f "$根/写入分流.py" ]]; then
    python3 "$根/写入分流.py" 关 || true
  else
    echo "没找到写入分流.py，面板若已写过桥规则，请稍后在管理页确认代理是关的"
  fi
}

装依赖
mkdir -p /opt/xui-bridge /etc/xui-bridge
cp -f "$根/主程序.py" "$根/解析.py" "$根/池.py" "$根/转发.py" "$根/网页.py" "$根/更新.py" "$根/面板.html" "$根/登录.html" "$根/对接.md" /opt/xui-bridge/
cp -f "$根/写入分流.py" "$根/最低消耗.json" /opt/xui-bridge/ 2>/dev/null || true
写池
cp -f "$根/xui-bridge.service" /etc/systemd/system/xui-bridge.service
systemctl daemon-reload
systemctl enable xui-bridge
systemctl restart xui-bridge
关分流
sleep 1
systemctl --no-pager --full status xui-bridge || true
echo
echo "=============== 部署完成 ==============="
echo "只在业务机跑。出口机不要跑这个脚本。"
echo "SOCKS  127.0.0.1:41000"
echo "管理页 http://公网IP:41001/  密码见 web_pass（默认 YPN940815...）"
echo "========================================"
