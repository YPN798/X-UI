# x-ui-yg 自动安装分支

基于 [yonggekkk/x-ui-yg](https://github.com/yonggekkk/x-ui-yg) 修改，**加了一个全自动安装模式**：一行命令装完，全程不用回答任何问题。

原版所有功能、菜单都保留，不带 `auto` 参数运行时行为和上游完全一致。

---

## 为什么要改

原版安装要手动回答 7 次：

| 步骤 | 问题 |
|---|---|
| 1 | 主菜单选 `1` |
| 2 | 是否开放端口、关闭防火墙 |
| 3 | 登录用户名 |
| 4 | 登录密码 |
| 5 | 登录端口 |
| 6 | 登录根路径 |
| 7 | 是否 https 登录 → 进 ACME 又要答 4 次 |

批量装机时只能用 SSH 模拟按键去喂答案，容易因为提示语变化、网络延迟而卡住。

这个分支把整条流程做成非交互的，不再依赖等待关键字。

---

## 用法

和甬哥一样：VPS 上 `curl` 本仓库的 `install.sh`。面板二进制仍从甬哥 Releases 下；桥和自动安装从 [YPN798/X-UI](https://github.com/YPN798/X-UI) 拉。

**先把本仓库（含 `vps桥/`）推到 GitHub**，否则网上还是旧脚本。

### 新机：面板 + 最低消耗 + 桥

```bash
XUI_USER=798 XUI_PASS=798 XUI_PORT=798 XUI_PATH=798 \
XUI_PROXY='socks5://用户:密码@1.2.3.4:1080' \
bash <(curl -Ls https://raw.githubusercontent.com/YPN798/X-UI/main/install.sh) auto
```

`XUI_USER` 等可省略（会随机）。`XUI_PROXY` 可省略（桥先空着，管理页再加）。

### 已有面板：只补桥和分流

```bash
bash <(curl -Ls https://raw.githubusercontent.com/YPN798/X-UI/main/install.sh) bridge
```

装完默认最低消耗：3 个主机走本机桥 `127.0.0.1:41000`。换池不用再改面板。

---

## 环境变量

### 面板

| 变量 | 说明 | 默认 |
|---|---|---|
| `XUI_USER` | 面板用户名 | 随机 6 位 |
| `XUI_PASS` | 面板密码 | 随机 10 位 |
| `XUI_PORT` | 面板端口 | 随机 10000-65535，被占用会自动换 |
| `XUI_PATH` | 面板根路径 | 随机 6 位 |
| `XUI_FIREWALL` | `1` 关防火墙开全端口，`0` 不动 | `1` |

含 `admin` 的用户名/密码会被自动换成随机值，和原版规则一致。

### 证书

| 变量 | 说明 | 默认 |
|---|---|---|
| `XUI_HTTPS` | `1` 申请 IP 证书开 https，`0` 只用 http | `1` |
| `XUI_EMAIL` | 证书注册邮箱 | 随机虚拟 gmail |
| `XUI_CERT_IP` | 申请证书用的 IP | 本机公网 IP |

等价于原流程的：`certinstall 输入 1` → `ACME 菜单 1` → `模式 1（独立 80 端口 IP 证书）` → `邮箱回车` → `IP 回车`。

申请失败会自动退回 http，不会中断安装。检测到 WARP IP 会直接跳过。

### Xray 配置

| 变量 | 说明 |
|---|---|
| `XUI_PROXY` | 出站代理，格式 `socks5://user:pass@host:port`，也支持无账密 |
| `XUI_PROXY_DOMAIN` | 走代理的域名，逗号分隔。默认 `full:www.dola.com,full:dola.com,full:wss-normal-i18n.dola.com`（生成接口所在主机；HTTPS 不能按 `/chat/completion` 路径再拆） |
| `XUI_DIRECT_DOMAIN` | 强制直连的域名，逗号分隔，默认是图床/CDN/打点那几个 |
| `XUI_TPL` | 直接给一份完整 Xray 配置，本地路径或 URL。给了就忽略上面三个 |

两个都不给就不动默认配置。

若改回 `XUI_PROXY_DOMAIN=domain:dola.com`（整棵 `*.dola.com`），脚本会自动把 `v16-dola.dola.com` 这类视频 CDN 排除直连，避免把几十 MB 视频塞进代理。

### 仓库地址

脚本开头三行：

```bash
RAW_BASE=.../yonggekkk/x-ui-yg/main          # 面板 version / xuiwpph
REL_BASE=.../yonggekkk/x-ui-yg/releases/...  # 面板 tar.gz
SELF_RAW=.../YPN798/X-UI/main                # 本仓库 install.sh + vps桥
```

换自己的 fork 只改 `SELF_RAW`。也可以临时覆盖：

```bash
SELF_RAW=https://raw.githubusercontent.com/xxx/yyy/main bash install.sh auto
```

---

## 装完做了什么

1. 关防火墙、放开所有端口
2. 下载安装面板，写 systemd 服务，设开机自启
3. 设好用户名、密码、端口、根路径
4. 申请 IP 证书，开 https 登录，加每天 0 点自动续期
5. 生成自签证书（给 Hysteria2 用）
6. 把自定义 Xray 配置写进面板数据库
7. 装守护 cron，刷新 IP 信息
8. 打印面板地址、账号、密码

最后输出长这样：

```
=============== 安装完成 ===============
面板地址：https://1.2.3.4:798/798
用户名  ：798
密码    ：798
管理命令：x-ui
x-ui状态: 已运行
========================================
```

---

## 相对上游的改动

| 位置 | 改了什么 |
|---|---|
| 脚本开头 | 加 `auto` 参数解析、`RAW_BASE` / `REL_BASE` 变量 |
| 全文 URL | 写死的 yonggekkk 地址换成变量 |
| `show_menu` 前 | 新增 `xui_db`、`d2j`、`freeport`、`gen_tpl`、`apply_tpl`、`auto_cert`、`auto_install` |
| 脚本结尾 | `show_menu` 改成入口分发 |

原有函数一行没动。不带 `auto` 参数时，走的还是原版的 `show_menu`。

---

## 注意

**写默认 Xray 配置需要 `sqlite3`**，脚本会自动装。配置存在 `/etc/x-ui-yg/x-ui-yg.db` 的设置表，键名 `xrayTemplateConfig`。写入前会停面板、写完再启。

不同版本的表名可能是 `settings` 或 `setting`，脚本会自动探测。**如果这一步失败，安装照常完成**，只是需要你手动进面板粘一次 Xray 配置。

**面板二进制不开源**。上游 README 写明了这点，这个分支只改安装脚本，面板本身还是从 Releases 下的那个 tar.gz。要么沿用上游地址，要么自己镜像一份到你的 Releases。

**重复安装会被拒绝**。检测到 `/usr/local/x-ui/x-ui` 已存在就直接退出，要重装先跑 `x-ui` 选 `2` 卸载。

---

## 装之前先验语法

```bash
bash -n install.sh && echo OK
```

在任意 Linux 上跑，只解析不执行。
