import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createAccountRegistry } from './account-registry.mjs';

function tempRegistry(run, opts = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'xbw-accounts-'));
  try { return run(directory, createAccountRegistry({ authDir: directory, ...opts })); }
  finally { fs.rmSync(directory, { recursive: true, force: true }); }
}

test('70 saved accounts persist and only seven selected sessions restore', () => {
  tempRegistry((dir, registry) => {
    for (let i = 1; i <= 70; i++) registry.register('wa_' + i);
    for (let i = 1; i <= 7; i++) registry.activate('wa_' + i);
    assert.equal(registry.saved().length, 70);
    assert.equal(registry.active().length, 7);
    assert.throws(() => registry.register('wa_71'), /Saved account cap/);
    assert.throws(() => registry.activate('wa_8'), /Active session cap/);
    const restored = createAccountRegistry({ authDir: dir });
    assert.deepEqual(restored.active(), ['wa_1','wa_2','wa_3','wa_4','wa_5','wa_6','wa_7']);
    restored.pause('wa_1');
    restored.activate('wa_8');
    const reread = createAccountRegistry({ authDir: dir });
    assert.equal(reread.saved().length, 70);
    assert.deepEqual(reread.active(), ['wa_2','wa_3','wa_4','wa_5','wa_6','wa_7','wa_8']);
  });
});

test('invalid aliases cannot escape auth directory', () => {
  tempRegistry((_dir, registry) => {
    for (const alias of ['../bad','a/b','a'.repeat(65),'']) {
      assert.throws(() => registry.activate(alias), /Invalid alias/);
    }
    assert.deepEqual(registry.saved(), []);
  });
});

test('corrupt registry fails closed rather than deleting account selections', () => {
  tempRegistry((dir, registry) => {
    registry.activate('wa_1');
    const file = path.join(dir, 'account-registry.json');
    const corrupt = JSON.stringify({version:1,saved:['wa_1'],active:['wa_2']});
    fs.writeFileSync(file, corrupt);
    assert.throws(() => createAccountRegistry({authDir:dir}), /Invalid account registry/);
    assert.equal(fs.readFileSync(file,'utf8'),corrupt);
  });
});

test('pausing an unknown alias does not create it', () => {
  tempRegistry((_dir, registry) => {
    registry.pause('unknown');
    assert.deepEqual(registry.list(),[]);
  });
});
