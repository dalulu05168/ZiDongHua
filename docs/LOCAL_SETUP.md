# 小霸王 V0.2 本机调试

需 Python 3.11+；WhatsApp 连接桥额外需要 Node.js 20+。不需要 Docker。

## 启动管理后台
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
# 在本机设置三个不同强密钥，不要提交到 GitHub
$env:XBW_API_KEY="替换为随机长密钥"
$env:XBW_TG_KEY="替换为另一个随机长密钥"
$env:XBW_BRIDGE_KEY="替换为第三个随机长密钥"
$env:DRY_RUN="true"
uvicorn backend.app:app --host 127.0.0.1 --port 3100
```

浏览器打开 http://127.0.0.1:3100，输入本地管理密钥。规则默认关闭，当前所有消息处理仅模拟。

## WhatsApp 连接桥
```powershell
cd integrations/whatsapp
npm install
$env:XBW_BRIDGE_KEY="与后台一致的桥接密钥"
npm start
```
在后台录入 WA 账号别名，连接并查看二维码，使用该账号 WhatsApp 的“已关联设备”扫码。二维码、auth 目录不可分享或提交。Baileys 是非官方 WhatsApp Web 接入，有账号安全与政策限制；请只在授权账号和群组使用。

## Telegram
在 https://my.telegram.org 获取自己的 API ID 与 API Hash，仅保存在本机环境变量。
```powershell
cd integrations/telegram
pip install -r requirements.txt
$env:TELEGRAM_API_ID="你自己的API_ID"
$env:TELEGRAM_API_HASH="你自己的API_HASH"
$env:XBW_TG_KEY="与后台一致的TG服务密钥"
python worker.py login tg_01
python worker.py groups tg_01
python worker.py listen tg_01
```
监听程序只接收后台已启用的 TG 群组 ID。当前只处理文本；断线重连、持久重试尚未实现。

## 限制
- 本版本的网页是开发管理端，不是 Windows EXE。
- 没有真实群发 API，真实发送不可用。
- Telegram 多个别名需要分别启动监听进程。
- 未接通 Chatwoot；未测试实际扫码或 70/7 规模目标。
- 后台默认只绑定本机 127.0.0.1，不要未经额外鉴权直接公开至互联网。
