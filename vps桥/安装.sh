#!/bin/bash
# 业务机一键：装桥 + 最低消耗分流指向 127.0.0.1:41000。不要在出口机上跑。
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
d.setdefault("web", "127.0.0.1")
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

写xray(){
  local db="" t
  for t in /etc/x-ui-yg/x-ui-yg.db /etc/x-ui/x-ui.db; do
    [[ -f $t ]] && db=$t && break
  done
  if [[ -z $db ]]; then
    echo "没找到面板数据库，跳过写 Xray。装完面板后把 $根/最低消耗.json 贴进「Xray 配置」。"
    return 0
  fi
  if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "没有 sqlite3，请手动在面板粘贴 $根/最低消耗.json"
    return 0
  fi
  local tbl=""
  for t in settings setting; do
    sqlite3 "$db" "SELECT name FROM sqlite_master WHERE type='table' AND name='$t';" 2>/dev/null | grep -q "$t" && tbl=$t && break
  done
  if [[ -z $tbl ]]; then
    echo "数据库里没有设置表，跳过写 Xray"
    return 0
  fi
  if command -v systemctl >/dev/null 2>&1; then
    systemctl stop x-ui >/dev/null 2>&1 || true
  else
    rc-service x-ui stop >/dev/null 2>&1 || true
  fi
  sleep 1
  if sqlite3 "$db" "SELECT 1 FROM $tbl WHERE key='xrayTemplateConfig' LIMIT 1;" | grep -q 1; then
    sqlite3 "$db" "UPDATE $tbl SET value=readfile('$根/最低消耗.json') WHERE key='xrayTemplateConfig';"
  else
    sqlite3 "$db" "INSERT INTO $tbl (key,value) VALUES ('xrayTemplateConfig', readfile('$根/最低消耗.json'));"
  fi
  if command -v systemctl >/dev/null 2>&1; then
    systemctl start x-ui >/dev/null 2>&1 || true
  else
    rc-service x-ui start >/dev/null 2>&1 || true
  fi
  echo "已写入最低消耗 Xray（3 个主机 → 127.0.0.1:41000）"
}

装依赖
mkdir -p /opt/xui-bridge /etc/xui-bridge
cp -f "$根/主程序.py" "$根/解析.py" "$根/池.py" "$根/转发.py" "$根/网页.py" /opt/xui-bridge/
写池
cp -f "$根/xui-bridge.service" /etc/systemd/system/xui-bridge.service
systemctl daemon-reload
systemctl enable xui-bridge
systemctl restart xui-bridge
写xray
sleep 1
systemctl --no-pager --full status xui-bridge || true
echo
echo "=============== 部署完成 ==============="
echo "只在业务机跑。出口机不要跑这个脚本。"
echo "SOCKS  127.0.0.1:41000"
echo "管理页 http://127.0.0.1:41001/"
echo "密码   /etc/xui-bridge/config.json 的 web_pass（默认 YPN940815...）"
echo "本机看页：ssh -L 41001:127.0.0.1:41001 root@这台IP"
echo "========================================"
