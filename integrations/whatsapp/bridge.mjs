// 小霸王 Baileys adapter. V0.2 is login/group-enumeration ONLY.
// Real sends are intentionally NOT exposed by this bridge.
import express from 'express'
import makeWASocket, { useMultiFileAuthState, DisconnectReason } from '@whiskeysockets/baileys'
import pino from 'pino'
import path from 'node:path'
import { decision, safeAlias, activeCapacity } from './lifecycle.mjs'
import { createChatStore, validChatJid } from './chatstore.mjs'
import { createAccountRegistry } from './account-registry.mjs'

const app = express()
app.use(express.json({ limit: '32kb' }))
const authKey = process.env.XBW_BRIDGE_KEY || ''
const maxActive = Math.max(1, Math.min(7, Number(process.env.MAX_ACTIVE_SESSIONS || 7)))
const authDir = path.resolve(process.env.WA_AUTH_DIR || './auth')
const accountRegistry = createAccountRegistry({authDir, maxActive})
const sessions = new Map()
const restartCounts = new Map()
const valid = safeAlias

app.use((req, res, next) => {
  if (!authKey || req.get('X-Bridge-Key') !== authKey) return res.status(401).json({ error: 'Unauthorized' })
  next()
})

async function connect(name) {
  if (!valid(name)) throw new Error('Invalid alias')
  if (sessions.has(name)) return sessions.get(name)
  if (!activeCapacity(sessions.size, maxActive)) throw new Error('Active session cap reached')
  accountRegistry.activate(name)
  // Reserve a slot synchronously: concurrent connect requests must not exceed seven.
  const current = { status: 'connecting', qr: null, user: null, sock: null, chats: createChatStore(), retries: restartCounts.get(name) || 0, stopped: false }
  sessions.set(name, current)
  try {
    const { state, saveCreds } = await useMultiFileAuthState(path.join(authDir, name))
    if (sessions.get(name) !== current || current.stopped) return current
    const sock = makeWASocket({
      auth: state, logger: pino({ level: 'silent' }), markOnlineOnConnect: false
    })
    current.sock = sock
    sock.ev.on('creds.update', saveCreds)
    sock.ev.on('messages.upsert', ({ messages = [] }) => {
      for (const message of messages) current.chats.seeMessage(message)
    })
    // Initial phone history is asynchronous and may arrive after QR login.
    // Store only a bounded in-memory view for the local chat workspace.
    sock.ev.on('messaging-history.set', payload => {
      if (sessions.get(name) !== current) return
      current.chats.ingestHistory(payload)
    })
    sock.ev.on('chats.upsert', chatList => {
      for (const chat of chatList || []) current.chats.setTitle(chat.id, chat.name || chat.subject || '')
    })
    sock.ev.on('chats.update', chatList => {
      for (const chat of chatList || []) if (chat.name || chat.subject) current.chats.setTitle(chat.id, chat.name || chat.subject)
    })
    sock.ev.on('connection.update', stateUpdate => {
      if (sessions.get(name) !== current) return
      if (stateUpdate.qr) { current.qr = stateUpdate.qr; current.status = 'qr_ready' }
      if (stateUpdate.connection === 'open') {
        current.status = 'connected'
        current.user = sock.user?.id || null
        restartCounts.delete(name)
        current.qr = null
        // Populate joined group names in the chat list, even before new messages arrive.
        void sock.groupFetchAllParticipating().then(groups => {
          if (sessions.get(name) !== current) return
          for (const group of Object.values(groups).slice(0, 500)) {
            current.chats.setTitle(group.id, group.subject || '')
          }
        }).catch(() => { /* Group refresh can be retried later via groups endpoint. */ })
      }
      if (stateUpdate.connection === 'close') {
        current.status = 'disconnected'
        current.qr = null
        const reason = stateUpdate.lastDisconnect?.error?.output?.statusCode
        const action = decision({ reason, restartRequired: DisconnectReason.restartRequired,
          wasStopped: current.stopped, retries: current.retries })
        sessions.delete(name)
        if (reason === DisconnectReason.loggedOut) accountRegistry.pause(name)
        if (action === 'restart' && accountRegistry.isActive(name)) {
          current.retries += 1
          restartCounts.set(name, current.retries)
          // Reuse saved credentials; never copy QR/auth data into source control.
          // Back off between retries instead of immediately hammering WhatsApp.
          const delayMs = Math.min(30000, 1000 * (2 ** (current.retries - 1)))
          setTimeout(() => {
            if (!accountRegistry.isActive(name) || sessions.has(name)) return
            connect(name).catch(err => console.error('Restart failed', name, err.message))
          }, delayMs).unref()
        } else {
          restartCounts.delete(name)
          console.log('Closed session', name,
          reason === DisconnectReason.loggedOut ? 'logged-out' : 'manual-reconnect-required')
        }
      }
    })
    return current
  } catch (error) {
    sessions.delete(name)
    throw error
  }
}

app.get('/v1/sessions', (_req, res) => res.json(
  accountRegistry.list().map(({ name, selected }) => ({
    name, selected, status: sessions.get(name)?.status || (selected ? 'reconnecting' : 'paused'),
    user: sessions.get(name)?.user || null
  }))
))
app.post('/v1/sessions/:name/connect', async (req, res) => {
  try {
    const s = await connect(req.params.name)
    res.json({ name: req.params.name, status: s.status })
  } catch (error) { res.status(400).json({ error: error.message }) }
})
// Pausing retains Baileys authorization on disk and frees an online slot.
app.post('/v1/sessions/:name/pause', (req, res) => {
  const name = req.params.name
  if (!valid(name)) return res.status(400).json({ error: 'Invalid alias' })
  try {
    accountRegistry.pause(name)
    const current = sessions.get(name)
    if (current) {
      current.stopped = true
      sessions.delete(name)
      try { current.sock?.end(new Error('Paused in XiaoBaWang')) } catch { /* already closed */ }
    }
    restartCounts.delete(name)
    res.json({ name, status: 'paused', credentials_preserved: true })
  } catch (error) { res.status(500).json({ error: 'Account pause failed' }) }
})
app.get('/v1/sessions/:name', (req, res) => {
  const s = sessions.get(req.params.name)
  if (!s) return res.status(404).json({ error: 'Not active' })
  // QR is a credential! Keep this service bound to loopback and only return it to authorized users.
  res.json({ name: req.params.name, status: s.status, user: s.user, qr: s.qr })
})
app.get('/v1/sessions/:name/groups', async (req, res) => {
  const s = sessions.get(req.params.name)
  if (!s || s.status !== 'connected')
    return res.status(409).json({ error: 'Not connected' })
  try {
    const groups = await s.sock.groupFetchAllParticipating()
    res.json(Object.values(groups).map(g => ({ id: g.id, subject: g.subject })))
  } catch (error) { res.status(502).json({ error: error.message }) }
})
// Read-only, current-process chat projection. Historical sync and outbound messaging are disabled.
app.get('/v1/sessions/:name/chats', (req, res) => {
  const s = sessions.get(req.params.name)
  if (!s || s.status !== 'connected') return res.status(409).json({ error: 'Not connected' })
  res.json({ chats: s.chats.list(), scope: 'available_history_sync_and_live', sending_enabled: false })
})
app.get('/v1/sessions/:name/chats/:jid/messages', (req, res) => {
  const s = sessions.get(req.params.name)
  if (!s || s.status !== 'connected') return res.status(409).json({ error: 'Not connected' })
  if (!validChatJid(req.params.jid)) return res.status(400).json({ error: 'Invalid chat id' })
  res.json({ jid: req.params.jid, messages: s.chats.messages(req.params.jid), scope: 'observed_since_connection', sending_enabled: false })
})

const host = process.env.XBW_BRIDGE_HOST || '127.0.0.1'
const port = Number(process.env.XBW_BRIDGE_PORT || 3101)
app.listen(port, host, () => console.log('WhatsApp bridge on', host, port))
// Only previously selected accounts resume; saved/paused accounts stay offline.
setImmediate(async () => {
  for (const name of accountRegistry.active()) {
    try { await connect(name) }
    catch (error) { console.error('Account restore failed', name, error.message) }
  }
})
