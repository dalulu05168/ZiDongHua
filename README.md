# 小霸王 XiaoBaWang

**状态：V0.4 聊天工作台开发原型（不是完整交付的软件）**。目标是支持 Telegram 授权群组监听与 WhatsApp 多账号、群组消息路由，并逐步集成 Chatwoot 客服工作台。翻译功能暂不开发。

## 产品首页：WhatsApp 风格多账号聊天工作台
- `/`：左侧账号/会话列表、中间只读聊天气泡、右侧 TG ↔ WA 群组映射和审核入口。
- `/settings`：旧版系统配置与排障页面，保留兼容。
- WhatsApp 列表和聊天消息来自 Baileys 已连接会话的内存观察缓存，**不提供完整历史聊天记录**；重启后消息缓存清空。
- Telegram 聊天记录只包含已匹配启用规则而记录的消息，并非 Telegram 完整历史。
- 聊天发送框明确停用，真实发送尚未实现。

## 当前提交的功能
- `backend/app.py` + `backend/chat.html` + `backend/index.html`：聊天工作台与本地管理网页，规则新建/启停、消息待审核列表、模拟通过/拒绝。
- SQLite：持久化路由规则、已监听的消息及审核记录；按来源账号、群 ID、消息 ID 去重。
- `integrations/telegram/worker.py`：Telethon 授权登录、群组枚举、只监听明确启用的群组文本消息。
- `integrations/whatsapp/bridge.mjs`：Baileys 连接、二维码字符串查询、活跃账号列表和群组枚举；最多 7 个活跃连接的本地保护。
- `router/`：独立离线消息路由示例和单元测试。
- GitHub Actions：安全默认值、路由测试、后台 API 测试及 Python/Node 语法检查。

## 严格限制
**真实发送未实现，任何后台审核操作均为模拟操作，不会向 WhatsApp 发消息。**
未完成真实 Telegram / WhatsApp 账号登录联调、Chatwoot 集成、断线自动重连、持续重试、访问控制加固、70 账号规模测试、Windows 安装程序。

使用指南见 [docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md)。项目当前在公开仓库中：严禁上传账号密码、密钥、会话文件、二维码或客户真实消息数据。

## 开源基础
- [Chatwoot](https://github.com/chatwoot/chatwoot)（规划接入，尚未完成）
- [Telethon](https://codeberg.org/Lonami/Telethon)
- [Baileys](https://github.com/WhiskeySockets/Baileys)
