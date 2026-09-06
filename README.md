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

### 最简：全部用随机值

```bash
bash <(curl -Ls https://raw.githubusercontent.com/你的用户名/你的仓库/main/install.sh) auto
```

### 指定账号密码端口路径

```bash
XUI_USER=798 XUI_PASS=798 XUI_PORT=798 XUI_PATH=798 \
bash <(curl -Ls https://raw.githubusercontent.com/你的用户名/你的仓库/main/install.sh) auto
```

### 连出站代理和分流规则一起配好

```bash
XUI_USER=798 XUI_PASS=798 XUI_PORT=798 XUI_PATH=798 \
XUI_PROXY='socks5://用户名:密码@1.2.3.4:1080' \
bash <(curl -Ls .../install.sh) auto
```

装完直接就是「Dola 走代理、CDN 直连」的状态，不用再手动粘 JSON。

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
| `XUI_PROXY_DOMAIN` | 走代理的域名，逗号分隔，默认 `domain:dola.com` |
| `XUI_DIRECT_DOMAIN` | 强制直连的域名，逗号分隔，默认是图床/CDN/打点那几个 |
| `XUI_TPL` | 直接给一份完整 Xray 配置，本地路径或 URL。给了就忽略上面三个 |

两个都不给就不动默认配置。

**视频 CDN 已内置排除**：`v16-dola.dola.com`、`v19-dola.dola.com` 这类子域用正则强制直连。不加这条的话，`domain:dola.com` 会把几十 MB 的视频下载也塞进代理。

### 仓库地址

fork 之后改脚本开头这两行就行：

```bash
RAW_BASE=${RAW_BASE:-https://raw.githubusercontent.com/你的用户名/你的仓库/main}
REL_BASE=${REL_BASE:-https://github.com/你的用户名/你的仓库/releases/download/xui_yg}
```

`RAW_BASE` 放 `install.sh`、`version`、`xuiwpph_*`；`REL_BASE` 放面板 tar.gz。

也可以临时用环境变量覆盖，不用改文件：

```bash
RAW_BASE=https://raw.githubusercontent.com/xxx/yyy/main bash install.sh auto
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
