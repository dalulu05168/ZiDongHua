# 小霸王 ↔ Chatwoot V0.3 接口说明

此阶段是 **只读 Application API + 经过签名认证的 Webhook 记录接入**，不是完整的 Chatwoot 双向客服系统。

## 配置
在本地环境设置：
- `CHATWOOT_URL`：Chatwoot 的 HTTPS 网址，本机可以使用 http://127.0.0.1:3000
- `CHATWOOT_ACCOUNT_ID`：Chatwoot account ID
- `CHATWOOT_API_TOKEN`：用户的 Application API access token
- `CHATWOOT_WEBHOOK_SECRET`：Settings → Integrations → Webhooks 所创建的独立 webhook secret

不要提交这些值到公开 GitHub。应用通过 `api_access_token` 请求头读取 `/api/v1/accounts/{account_id}/inboxes`、`/conversations`、`/contacts`，然后在小霸王管理页显示摘要。

Chatwoot Settings → Integrations → Webhooks 添加小霸王地址 `https://your-protected-host/api/chatwoot/webhook`，选 `message_created`、`conversation_created`、`conversation_updated`。必须在受保护的 HTTPS 域名/反向代理上接收 Webhook，**默认本机地址不能被远程 Chatwoot 调用**。

小霸王使用 Chatwoot 提供的 `X-Chatwoot-Signature`、`X-Chatwoot-Timestamp` 原始请求体验证 HMAC SHA256 并限制时间偏差，优先用 `X-Chatwoot-Delivery` 去重。只保存事件类型、会话/消息 ID、时间戳及唯一投递键，不存聊天正文。

此模块没有向 Chatwoot 或 WhatsApp 写入消息的 API，客服分配、自动回复与双向同步尚需接入和实测。

文档：https://app.chatwoot.com/hc/user-guide/articles/1677693021-how-to-use-webhooks
