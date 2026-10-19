# XiaoBaWang 路由核心（离线原型）

运行：

```bash
cd router
python -m unittest -v test_engine.py
```

功能：按已启用规则匹配 Telegram 账号/群组与 WhatsApp 账号/目标群组；在进程内去重；默认需要人工审核；三个独立发送安全闸门。

**不提供 Telegram 或 WhatsApp 实际连接，也不能在当前版本发送消息。**去重状态仅驻留内存，服务重启失效；接入前必须改为持久化数据库，并增加访问控制、签名校验、群成员权限检查、日志和限流。
