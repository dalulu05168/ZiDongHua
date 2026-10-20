// Bounded, in-memory, read-only view of WhatsApp events observed after connection.
// No sendMessage usage, no persistence of private chat contents in GitHub or logs.
const jidPattern = /^[A-Za-z0-9_.-]{1,90}@(g\.us|s\.whatsapp\.net|lid)$/;
export const validChatJid = value => typeof value === 'string' && jidPattern.test(value);

function unwrapped(input) {
  let node = input || {};
  for (let n = 0; n < 3; n += 1) {
    if (node.ephemeralMessage?.message) node = node.ephemeralMessage.message;
    else if (node.viewOnceMessage?.message) node = node.viewOnceMessage.message;
    else if (node.viewOnceMessageV2?.message) node = node.viewOnceMessageV2.message;
    else break;
  }
  return node;
}
export function textOf(raw) {
  const message = unwrapped(raw);
  const value = message.conversation ?? message.extendedTextMessage?.text ??
    message.imageMessage?.caption ?? message.videoMessage?.caption ?? null;
  return typeof value === 'string' ? value.slice(0,8000) : null;
}

function stamp(raw) {
  if (typeof raw === 'number') return raw;
  if (typeof raw === 'string') return Number(raw) || 0;
  if (raw && typeof raw.toNumber === 'function') return raw.toNumber();
  return 0;
}
export function createChatStore({maxChats=500, maxMessages=150}={}) {
  const chats = new Map();
  function seeMessage(item, participantName='') {
    const jid = item?.key?.remoteJid;
    const id = item?.key?.id;
    if (!validChatJid(jid) || typeof id !== 'string' || !id) return false;
    const body = textOf(item.message);
    if (!body) return false;
    if (!chats.has(jid) && chats.size >= maxChats) {
      const oldest = [...chats.entries()].sort((a,b)=>a[1].lastTime-b[1].lastTime)[0];
      if (oldest) chats.delete(oldest[0]);
    }
    const chat = chats.get(jid) || {jid, title:jid.split('@')[0], messages:[], ids:new Set(), lastTime:0};
    if (chat.ids.has(id)) return false;
    const record = {
      id, jid, text:body, fromMe: Boolean(item.key.fromMe),
      sender: String(item.key.participant || participantName || '').slice(0,120),
      timestamp: stamp(item.messageTimestamp),
    };
    // History sync can arrive newest-first. Keep conversations chronological,
    // otherwise the chat list preview can incorrectly show an old message.
    const index=chat.messages.findIndex(m=>m.timestamp>record.timestamp);
    if(index<0)chat.messages.push(record);
    else chat.messages.splice(index,0,record);
    chat.ids.add(id);
    while(chat.messages.length>maxMessages){
      const removed=chat.messages.shift();
      chat.ids.delete(removed.id);
    }
    chat.lastTime=Math.max(chat.lastTime, record.timestamp);
    chats.set(jid,chat);
    return true;
  }
  function setTitle(jid,title) {
    if (!validChatJid(jid) || typeof title!=='string') return;
    const chat=chats.get(jid) || {jid,title:jid.split('@')[0],messages:[],ids:new Set(),lastTime:0};
    chat.title=title.slice(0,120)||chat.title;
    chats.set(jid,chat);
  }
  function ingestHistory(batch,{maxBatchMessages=3000}={}){
    // Only a bounded, local, in-memory projection; never persist message bodies.
    const historicalChats=Array.isArray(batch?.chats)?batch.chats:[];
    const historicalMessages=Array.isArray(batch?.messages)?batch.messages:[];
    let added=0;
    for(const chat of historicalChats.slice(0,maxChats)){
      if(chat&&typeof chat.id==='string')setTitle(chat.id,chat.name||chat.subject||chat.id.split('@')[0]);
    }
    // The WhatsApp history event usually supplies recent messages first.
    // Limit processing to prevent one large initial sync from blocking the bridge.
    for(const message of historicalMessages.slice(0,maxBatchMessages)){
      if(seeMessage(message))added++;
    }
    return {added,limited:historicalMessages.length>maxBatchMessages};
  }
  function list() {
    return [...chats.values()].map(c=>({
      jid:c.jid,title:c.title,lastTime:c.lastTime,kind:c.jid.endsWith('@g.us')?'group':'direct',
      preview:c.messages.length?c.messages[c.messages.length-1].text.slice(0,120):'暂无新消息',
      observedMessages:c.messages.length,
    })).sort((a,b)=>b.lastTime-a.lastTime).slice(0,maxChats);
  }
  function messages(jid) {
    if (!validChatJid(jid)) return null;
    return chats.get(jid)?.messages.map(m=>({...m})) || [];
  }
  return {seeMessage,setTitle,ingestHistory,list,messages};
}
