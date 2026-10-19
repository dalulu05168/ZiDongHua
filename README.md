# 小霸王 XiaoBaWang

## 产品定位
**目标是 Windows 本地安装的 WhatsApp / Telegram 多账号聊天工作台**，不是浏览器配置工具。参考跨平台聊天应用的多账户聚合体验，但不复制其商标或代码。当前翻译模块暂停。

## Windows 本地安装包（V0.5.1 预览）
[查看 Windows 安装包的 GitHub Actions 构建](https://github.com/dalulu05168/ZiDongHua/actions/workflows/windows-installer.yml)

构建通过后，在最近一次成功运行页的 **Artifacts** 中下载 `XiaoBaWang-Windows-Installer-Preview`，解压后运行 `XiaoBaWang-Setup-0.5.1-x64.exe`。这是尚未签名的开发预览安装包，Windows 可能提示未知发布者。**只有构建实际通过并出现 Artifact 才代表安装包已经生成。**

安装包目标：
- 双击桌面快捷方式启动，无需用户手动安装 Python、Node.js、Docker 或运行 PowerShell。
- 同一桌面窗口内显示 WhatsApp 风格账号与聊天列表、消息详情及群组映射。
- 应用自动启动本地 FastAPI 与 Baileys；本地密钥和 WhatsApp 授权记录保存在 Windows 用户数据目录，不上传到 GitHub。
- 真正的 WhatsApp 扫码仍要用户自己完成，系统不会代替账号持有人授权。
- 用户运行环境不提供真实发送功能，避免误将预览版当成可群发的成品。


### 为什么看到旧的 V0.2 管理页面？
原来的开发后台固定在 http://127.0.0.1:3100，旧浏览器标签页或旧 PowerShell 服务可能仍在运行。那不是 V0.5.1 的聊天桌面窗口。
V0.5.1 桌面客户端为自身服务选择独立空闲本地端口，不再依赖 3100/3101；启动时应直接出现账号列表、消息区及右侧群组映射的紧凑聊天界面。旧的 `/settings` 大表单页不再提供给用户。
**安装后只从 Windows 开始菜单或桌面上的「小霸王」快捷方式运行，不需要在浏览器输入 127.0.0.1:3100，也不要双击以前解压的 ZIP 或旧 V0.5.0 安装包。**

### 尚未完成，不能当作已有功能
- WhatsApp 真实账号的长期稳定登录与完整历史消息同步；目前只读取连接后的内存消息。
- Telegram 在桌面内的账号登录 UI 与实际授权群组监听（已有 Telethon 脚本，但尚未打包进 GUI）。
- Chatwoot 的完整客服分配、自动回复与收发同步。
- 真实消息发送、文件与语音收发、70 个账号保存/7 个活跃账号的实际压力测试、Windows 代码签名。
- 与 PanTGPT/HappyWord/HelloWorld 等产品的完整功能一致性。

## 代码模块
- `desktop/`：Electron 窗口、自动服务管理、Windows 安装打包。
- `backend/`：FastAPI 本地接口、只读聊天工作台 HTML、SQLite 规则与审核。
- `integrations/whatsapp/`：Baileys 多会话扫码、消息观察、群组读取。
- `integrations/telegram/`：Telethon 开发接入脚本（未整合到安装程序）。
- `integrations/chatwoot/`：Chatwoot 只读接口与 webhook 审计。
- `router/`：安全路由与离线测试。

## 安全
仓库是**公开的**。不要提交 `.env`、`secrets.json`、`.secrets.local.json`、任何 `auth/` 或 `*.session`、二维码或个人聊天内容。
真实发送默认关闭，`DRY_RUN=true`。

更多调试信息：[docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md)。
