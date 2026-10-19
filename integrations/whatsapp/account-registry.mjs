// Durable account selection only. Credentials remain in Baileys auth folders.
// Never store QR codes, chats, passwords, session keys, or message bodies here.
import fs from 'node:fs';
import path from 'node:path';
import { safeAlias } from './lifecycle.mjs';

export function createAccountRegistry({ authDir, maxSaved = 70, maxActive = 7 }) {
  if (!authDir || !Number.isInteger(maxSaved) || maxSaved < 1 ||
      !Number.isInteger(maxActive) || maxActive < 1 || maxActive > 7) {
    throw new Error('Invalid account-registry configuration');
  }
  fs.mkdirSync(authDir, { recursive: true, mode: 0o700 });
  const filename = path.join(authDir, 'account-registry.json');
  let state = { version: 1, saved: [], active: [] };
  function validate(value) {
    if (!value || value.version !== 1 || !Array.isArray(value.saved) ||
        !Array.isArray(value.active) ||
        value.saved.some(x => !safeAlias(x)) || value.active.some(x => !safeAlias(x)) ||
        new Set(value.saved).size !== value.saved.length ||
        new Set(value.active).size !== value.active.length ||
        value.saved.length > maxSaved || value.active.length > maxActive ||
        value.active.some(x => !value.saved.includes(x))) {
      throw new Error('Invalid account registry; saved data was not overwritten');
    }
    return { version: 1, saved: [...value.saved], active: [...value.active] };
  }
  if (fs.existsSync(filename)) {
    state = validate(JSON.parse(fs.readFileSync(filename, 'utf8')));
  }
  function persist(next) {
    next = validate(next);
    const temp = filename + '.tmp-' + process.pid;
    try {
      fs.writeFileSync(temp, JSON.stringify(next, null, 2) + '\n', { mode: 0o600, flag: 'w' });
      fs.renameSync(temp, filename);
    } finally {
      if (fs.existsSync(temp)) fs.unlinkSync(temp);
    }
    state = next;
  }
  function register(alias) {
    if (!safeAlias(alias)) throw new Error('Invalid alias');
    if (state.saved.includes(alias)) return;
    if (state.saved.length >= maxSaved) throw new Error('Saved account cap reached (70)');
    persist({ ...state, saved: [...state.saved, alias] });
  }
  function activate(alias) {
    register(alias);
    if (state.active.includes(alias)) return;
    if (state.active.length >= maxActive) throw new Error('Active session cap reached (7)');
    persist({ ...state, active: [...state.active, alias] });
  }
  function pause(alias) {
    if (!safeAlias(alias)) throw new Error('Invalid alias');
    if (state.active.includes(alias)) {
      persist({ ...state, active: state.active.filter(x => x !== alias) });
    }
  }
  return {
    register, activate, pause,
    saved: () => [...state.saved],
    active: () => [...state.active],
    isActive: alias => state.active.includes(alias),
    list: () => state.saved.map(name => ({ name, selected: state.active.includes(name) }))
  };
}
