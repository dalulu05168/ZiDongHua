import test from 'node:test'
import assert from 'node:assert/strict'
import { createChatStore,validChatJid,textOf } from './chatstore.mjs'

const record=(id, remoteJid='123@g.us', text='Hello', fromMe=false)=>({
  key:{id,remoteJid,fromMe,participant:'111@s.whatsapp.net'},
  message:{conversation:text},messageTimestamp:100
});
test('read-only incoming text is grouped by chat and duplicate IDs suppressed',()=>{
  const store=createChatStore();
  assert.equal(store.seeMessage(record('m1')),true);
  assert.equal(store.seeMessage(record('m1')),false);
  assert.equal(store.list().length,1);
  assert.equal(store.messages('123@g.us')[0].text,'Hello');
  assert.equal(store.messages('123@g.us')[0].fromMe,false);
});
test('text formats and chat JID validation',()=>{
  assert.equal(textOf({extendedTextMessage:{text:'formatted'}}),'formatted');
  assert.equal(textOf({ephemeralMessage:{message:{conversation:'ephemeral'}}}),'ephemeral');
  assert.equal(textOf({imageMessage:{caption:'caption'}}),'caption');
  assert.equal(textOf({imageMessage:{}}),null);
  assert.equal(validChatJid('123@g.us'),true);
  assert.equal(validChatJid('123@s.whatsapp.net'),true);
  assert.equal(validChatJid('../../etc/passwd'),false);
});
test('message list and chat count have hard caps',()=>{
  const store=createChatStore({maxChats:2,maxMessages:2});
  ['1','2','3'].forEach(id=>store.seeMessage(record(id)));
  assert.deepEqual(store.messages('123@g.us').map(m=>m.id),['2','3']);
  store.seeMessage(record('4','234@g.us','Second'));
  store.seeMessage(record('5','345@g.us','Third'));
  assert.equal(store.list().length,2);
});
test('metadata title can be known before any inbound messages',()=>{
  const store=createChatStore();
  store.setTitle('567@g.us','授权群组');
  assert.equal(store.list()[0].title,'授权群组');
  assert.equal(store.messages('567@g.us').length,0);
});

test('history sync fills chats, orders messages chronologically, and deduplicates live events',()=>{
  const store=createChatStore({maxChats:5,maxMessages:3});
  const msg=(id,time)=>({...record(id,'321@g.us',id),messageTimestamp:time});
  store.seeMessage(msg('live',400));
  const batch={chats:[{id:'321@g.us',name:'My real test group'}],
    messages:[msg('third',300),msg('first',100),msg('second',200),msg('live',400)]};
  assert.equal(store.ingestHistory(batch).added,3);
  assert.deepEqual(store.messages('321@g.us').map(m=>m.id),['second','third','live']);
  assert.equal(store.list()[0].title,'My real test group');
  assert.equal(store.list()[0].preview,'live');
  assert.equal(store.ingestHistory(batch).added,1); // old first was evicted
});
test('history batches are bounded and ignore invalid chat ids',()=>{
  const store=createChatStore({maxChats:2,maxMessages:3});
  const history={chats:[{id:'111@g.us',subject:'Group 1'},
                        {id:'222@g.us',subject:'Group 2'},
                        {id:'333@g.us',subject:'Group 3'}],
    messages:[record('a','111@g.us','A'),record('b','111@g.us','B'),
              record('c','111@g.us','C'),record('d','111@g.us','D')]};
  const result=store.ingestHistory(history,{maxBatchMessages:2});
  assert.equal(result.limited,true);
  assert.equal(result.added,2);
  assert.equal(store.list().length,2);
  assert.deepEqual(store.messages('111@g.us').map(m=>m.id),['a','b']);
});
