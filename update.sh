#!/usr/bin/env bash
# 只更新桥的代码，不碰面板、不碰 /etc/xui-bridge/config.json。
#
#   bash <(curl -Ls https://raw.githubusercontent.com/YPN798/X-UI/main/update.sh)
#
# 先全部下到临时目录、逐个用 python3 校验语法，都过了才覆盖，
# 避免网络抽风把半截文件或者 GitHub 的错误页写进 /opt/xui-bridge。
set -u

BASE=https://raw.githubusercontent.com/YPN798/X-UI/main/vps%E6%A1%A5
DEST=/opt/xui-bridge
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

red(){ echo -e "\033[31m$*\033[0m"; }
green(){ echo -e "\033[32m$*\033[0m"; }
yellow(){ echo -e "\033[33m$*\033[0m"; }

# 本地文件名|URL 里的转义名
FILES=(
"主程序.py|%E4%B8%BB%E7%A8%8B%E5%BA%8F.py"
"解析.py|%E8%A7%A3%E6%9E%90.py"
"池.py|%E6%B1%A0.py"
"转发.py|%E8%BD%AC%E5%8F%91.py"
"网页.py|%E7%BD%91%E9%A1%B5.py"
"更新.py|%E6%9B%B4%E6%96%B0.py"
"写入分流.py|%E5%86%99%E5%85%A5%E5%88%86%E6%B5%81.py"
"最低消耗.json|%E6%9C%80%E4%BD%8E%E6%B6%88%E8%80%97.json"
)

ver_now(){
python3 - <<'EOF' 2>/dev/null
import json
try:
    print(json.load(open("/etc/xui-bridge/状态.json", encoding="utf-8")).get("版本") or "未知")
except Exception:
    print("未知")
EOF
}

[[ -d $DEST ]] || { red "没有 $DEST，这台机器还没装过桥。先跑 install.sh bridge"; exit 1; }
command -v python3 >/dev/null 2>&1 || { red "没有 python3"; exit 1; }

echo "从仓库拉最新代码…"
for item in "${FILES[@]}"; do
  name=${item%%|*}; enc=${item##*|}
  # 加时间戳绕开 CDN 缓存，不然常常拉回几分钟前的旧内容
  if ! curl -fsSL --retry 3 --max-time 60 -o "$TMP/$name" "$BASE/$enc?t=$(date +%s)"; then
    red "下载失败：$name"; exit 1
  fi
  [[ -s $TMP/$name ]] || { red "下回来是空的：$name"; exit 1; }
  case "$name" in
    *.py)
      python3 -c "import ast,io,sys; ast.parse(io.open(sys.argv[1],encoding='utf-8').read())" "$TMP/$name" \
        || { red "语法过不了，多半下到了错误页：$name"; exit 1; } ;;
    *.json)
      python3 -c "import json,io,sys; json.load(io.open(sys.argv[1],encoding='utf-8'))" "$TMP/$name" \
        || { red "不是合法 JSON：$name"; exit 1; } ;;
  esac
done

OLD=$(ver_now)
NEW=$(grep -oE '^版本 *= *"[^"]+"' "$TMP/池.py" | head -n1 | sed 's/.*"\(.*\)"/\1/')
[[ -n $NEW ]] || NEW=未知

for item in "${FILES[@]}"; do
  name=${item%%|*}
  cp -f "$TMP/$name" "$DEST/$name" || { red "覆盖失败：$name"; exit 1; }
done
green "代码已更新：$OLD → $NEW"

systemctl restart xui-bridge 2>/dev/null || rc-service xui-bridge restart 2>/dev/null
sleep 3

RUN=$(ver_now)
if [[ $RUN == "$NEW" ]]; then
  green "桥已重启，正在跑 $RUN"
else
  yellow "重启了，但状态里还是 $RUN。等十几秒再看面板；还不对就查 journalctl -u xui-bridge -n 50"
fi

echo
echo "面板上会显示版本号，刷新页面记得 Ctrl+Shift+R。"
echo "分流没生效的话再跑：python3 $DEST/写入分流.py"
