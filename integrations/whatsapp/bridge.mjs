// 小霸王 Baileys adapter. V0.2 is login/group-enumeration ONLY.
// Real sends are intentionally NOT exposed by this bridge.
import express from 'express'
import makeWASocket, { useMultiFileAuthState, DisconnectReason } from '@whiskeysockets/baileys'
import pino from 'pino'
import path from 'node:path'
import { decision, safeAlias, activeCapacity } from './lifecycle.mjs'

const app = express()
app.use(express.json({ limit: '32kb' }))
const authKey = process.env.XBW_BRIDGE_KEY || ''
const maxActive = Math.max(1, Math.min(7, Number(process.env.MAX_ACTIVE_SESSIONS || 7)))
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
  const authDir = path.resolve(process.env.WA_AUTH_DIR || './auth')
  const { state, saveCreds } = await useMultiFileAuthState(path.join(authDir, name))
  const current = { status: 'connecting', qr: null, user: null, sock: null, retries: restartCounts.get(name) || 0, stopped: false }
  sessions.set(name, current)
  try {
    const sock = makeWASocket({
      auth: state, logger: pino({ level: 'silent' }), markOnlineOnConnect: false
    })
    current.sock = sock
    sock.ev.on('creds.update', saveCreds)
    sock.ev.on('connection.update', stateUpdate => {
      if (sessions.get(name) !== current) return
      if (stateUpdate.qr) { current.qr = stateUpdate.qr; current.status = 'qr_ready' }
      if (stateUpdate.connection === 'open') {
        current.status = 'connected'
        current.user = sock.user?.id || null
        restartCounts.delete(name)
        current.qr = null
      }
      if (stateUpdate.connection === 'close') {
        current.status = 'disconnected'
        current.qr = null
        const reason = stateUpdate.lastDisconnect?.error?.output?.statusCode
        const action = decision({ reason, restartRequired: DisconnectReason.restartRequired,
          wasStopped: current.stopped, retries: current.retries })
        sessions.delete(name)
        if (action === 'restart') {
          current.retries += 1
          restartCounts.set(name, current.retries)
          // Reuse saved credentials; never copy QR/auth data into source control.
          setImmediate(() => connect(name).catch(err => console.error('Restart failed', name, err.message)))
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
  [...sessions].map(([name, s]) => ({ name, status: s.status, user: s.user }))
))
app.post('/v1/sessions/:name/connect', async (req, res) => {
  try {
    const s = await connect(req.params.name)
    res.json({ name: req.params.name, status: s.status })
  } catch (error) { res.status(400).json({ error: error.message }) }
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
const host = process.env.XBW_BRIDGE_HOST || '127.0.0.1'
const port = Number(process.env.XBW_BRIDGE_PORT || 3101)
app.listen(port, host, () => console.log('WhatsApp bridge on', host, port))
