// Pure session lifecycle helpers - can be tested without live WhatsApp.
export function decision({ reason, restartRequired, wasStopped = false, retries = 0, maxRetries = 5 }) {
  if (wasStopped || !Number.isInteger(retries) || retries < 0 || retries >= maxRetries) return 'stop'
  // These Baileys disconnect statuses can be transient; never auto-retry a logout (401).
  if ([restartRequired, 408, 428, 503].includes(reason)) return 'restart'
  return 'stop'
}
export function safeAlias(value) {
  return typeof value === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(value)
}
export function activeCapacity(current, maxActive) {
  return Number.isInteger(maxActive) && maxActive >= 1 && maxActive <= 7 && current < maxActive
}
