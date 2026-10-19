// Pure session lifecycle helpers - can be tested without live WhatsApp.
export function decision({ reason, restartRequired, wasStopped = false, retries = 0, maxRetries = 2 }) {
  if (wasStopped) return 'stop'
  if (reason === restartRequired && retries < maxRetries) return 'restart'
  return 'stop'
}
export function safeAlias(value) {
  return typeof value === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(value)
}
export function activeCapacity(current, maxActive) {
  return Number.isInteger(maxActive) && maxActive >= 1 && maxActive <= 7 && current < maxActive
}
