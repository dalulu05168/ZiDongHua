'use strict';
const {app, BrowserWindow, ipcMain, dialog, session} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');

let API_PORT = null;
let BRIDGE_PORT = null;
let window = null;
let backend = null;
let bridge = null;
let quitting = false;
let adminKey = null;
let logsDir = null;

function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
function localRoot() { return app.getPath('userData'); }
function errorMessage(err) { return err && err.message ? err.message : String(err); }
function log(label, text) {
  if (!logsDir) return;
  try { fs.appendFileSync(path.join(logsDir, label + '.log'), String(text).slice(-50000), {encoding:'utf8',mode:0o600}); }
  catch { /* diagnostics must not crash desktop app */ }
}
function credentials() {
  const root = localRoot();
  fs.mkdirSync(root, {recursive:true});
  const p = path.join(root, 'secrets.json');
  let obj = null;
  if (fs.existsSync(p)) {
    obj = JSON.parse(fs.readFileSync(p,'utf8'));
  } else {
    obj = {
      XBW_API_KEY:crypto.randomBytes(32).toString('hex'),
      XBW_TG_KEY:crypto.randomBytes(32).toString('hex'),
      XBW_BRIDGE_KEY:crypto.randomBytes(32).toString('hex')
    };
    fs.writeFileSync(p, JSON.stringify(obj), {flag:'wx', mode:0o600});
  }
  for (const key of ['XBW_API_KEY','XBW_TG_KEY','XBW_BRIDGE_KEY']) {
    if (typeof obj[key]!=='string' || !/^[a-f0-9]{64}$/.test(obj[key])) {
      throw new Error('本地凭据格式错误，请检查用户数据目录（不会自动删除你的凭据）。');
    }
  }
  return obj;
}
async function freeLocalPort() {
  return new Promise((resolve,reject) => {
    const socket=net.createServer();
    socket.once('error',reject);
    socket.listen(0,'127.0.0.1',()=>{
      const port=socket.address().port;
      socket.close(error=>error?reject(error):resolve(port));
    });
  });
}
async function check(url, key, maxTime=1200) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), maxTime);
  try {
    const resp = await fetch(url, {headers: key?{'X-Bridge-Key':key}:{},signal:controller.signal});
    return resp.ok;
  } catch { return false; }
  finally {clearTimeout(timer);}
}
function startProcess(label, binary, args, options={}) {
  const child=spawn(binary,args,{windowsHide:true,stdio:['ignore','pipe','pipe'],...options});
  child.stdout?.on('data',chunk=>log(label+'-stdout',chunk));
  child.stderr?.on('data',chunk=>log(label+'-stderr',chunk));
  child.on('error',error=>log(label+'-error',errorMessage(error)));
  child.on('exit',(code,signal)=>{
    log(label+'-exit', 'exit '+code+', signal '+signal+'\n');
    if (!quitting && window) window.webContents.send('xbw:service-exited',label);
  });
  return child;
}
function environment(creds) {
  const root=localRoot();
  const waDir=path.join(root,'wa-auth');
  fs.mkdirSync(waDir,{recursive:true});
  fs.mkdirSync(path.join(root,'data'),{recursive:true});
  return {
    ...process.env,
    ...creds,
    XBW_DB_PATH:path.join(root,'data','xiaobawang.sqlite3'),
    WA_AUTH_DIR:waDir,
    DRY_RUN:'true',
    XBW_SEND_ENABLED:'false',
    BAILEYS_SEND_ENABLED:'false',
    XBW_API_PORT:String(API_PORT),
    XBW_BRIDGE_PORT:String(BRIDGE_PORT),
    XBW_BRIDGE_HOST:'127.0.0.1',
    XBW_BRIDGE_URL:'http://127.0.0.1:'+BRIDGE_PORT,
    ELECTRON_RUN_AS_NODE:'1'
  };
}
async function startServices() {
  // Use desktop-private ephemeral ports: old dev servers on 3100/3101 do not
  // interfere with the installed app. No need to kill other programs.
  API_PORT=await freeLocalPort();
  BRIDGE_PORT=await freeLocalPort();
  while(BRIDGE_PORT===API_PORT) BRIDGE_PORT=await freeLocalPort();
  const creds=credentials();
  adminKey=creds.XBW_API_KEY;
  const env=environment(creds);
  const root=app.isPackaged ? process.resourcesPath : path.resolve(__dirname,'..');
  const bridgeDir=app.isPackaged ? path.join(root,'bridge') : path.join(root,'integrations','whatsapp');
  const bridgeFile=path.join(bridgeDir,'bridge.mjs');
  if (!fs.existsSync(bridgeFile)) throw new Error('安装包中未找到 WhatsApp 通信引擎：'+bridgeFile);

  // Electron's Node runtime is bundled in the installed desktop app;
  // this does not require separately installed Node.js.
  bridge=startProcess('whatsapp',process.execPath,[bridgeFile],{
    cwd:bridgeDir,env:{...env,ELECTRON_RUN_AS_NODE:'1'}
  });
  let bridgeReady=false;
  for(let i=0;i<45;i++){
    if(bridge.exitCode!==null) break;
    if(await check('http://127.0.0.1:'+BRIDGE_PORT+'/v1/sessions',creds.XBW_BRIDGE_KEY)){bridgeReady=true;break}
    await sleep(400);
  }
  if(!bridgeReady) throw new Error('WhatsApp 引擎未成功启动。请查看本机小霸王日志 whatsapp-stderr.log。');

  let pyBinary,pyArgs;
  if(app.isPackaged){
    pyBinary=path.join(root,'bin','xiaobawang-backend.exe');
    pyArgs=[];
  }else{
    const venv=path.join(root,'.venv','Scripts','python.exe');
    pyBinary=fs.existsSync(venv)?venv:(process.env.XBW_PYTHON||'python');
    pyArgs=['-m','backend.desktop_entry'];
  }
  if(app.isPackaged&&!fs.existsSync(pyBinary)) throw new Error('安装包缺少 Python 后台组件。');
  const backendEnv={...env};
  delete backendEnv.ELECTRON_RUN_AS_NODE;
  backend=startProcess('backend',pyBinary,pyArgs,{cwd:root,env:backendEnv});
  let backendReady=false;
  for(let i=0;i<75;i++){
    if(backend.exitCode!==null) break;
    if(await check('http://127.0.0.1:'+API_PORT+'/health')){backendReady=true;break}
    await sleep(400);
  }
  if(!backendReady) throw new Error('聊天后台启动失败。请查看本机小霸王日志 backend-stderr.log。');
  // No authentication tokens are ever written to the runtime-info file.
  fs.writeFileSync(path.join(logsDir,'runtime.json'),
    JSON.stringify({api_port:API_PORT,bridge_port:BRIDGE_PORT,mode:'read_only',version:'0.5.1'}),
    {encoding:'utf8',mode:0o600});
}
function stopServices() {
  quitting=true;
  if(logsDir){try{fs.unlinkSync(path.join(logsDir,'runtime.json'));}catch{}}
  for (const child of [backend,bridge]) {
    if(child && child.exitCode===null && !child.killed){ try {child.kill();} catch {} }
  }
}
function showStartupError(error) {
  const root=localRoot();
  dialog.showErrorBox('小霸王启动失败',errorMessage(error)+'\n\n日志目录：'+root+'\\logs');
}
function createWindow() {
  window=new BrowserWindow({
    width:1360,height:840,minWidth:870,minHeight:640,
    title:'小霸王 · 多账号聊天工作台',
    show:false,autoHideMenuBar:true,
    webPreferences:{
      preload:path.join(__dirname,'preload.cjs'),
      nodeIntegration:false,contextIsolation:true,sandbox:true,
      webviewTag:false
    }
  });
  window.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  window.webContents.on('will-navigate',(event,url)=>{
    if(!url.startsWith('http://127.0.0.1:'+API_PORT+'/')) event.preventDefault();
  });
  window.webContents.on('did-finish-load',async()=>{
    try {
      const title=await window.webContents.executeJavaScript('document.title');
      const layout=await window.webContents.executeJavaScript(
        'Boolean(document.getElementById("threadList") && document.getElementById("messages"))'
      );
      log('desktop-ui', 'Rendered page: '+title+', chat layout: '+layout+'\n');
      if(!layout) throw new Error('桌面窗口未载入新版聊天界面');
      fs.writeFileSync(path.join(logsDir,'ui-ready.json'),
        JSON.stringify({title,chat_layout:true,port:API_PORT}),
        {encoding:'utf8',mode:0o600});
    }catch(err){log('desktop-ui-error',errorMessage(err));}
  });
  window.once('ready-to-show',()=>window.show());
  window.loadURL('http://127.0.0.1:'+API_PORT+'/');
}
ipcMain.handle('xbw:get-local-token',(event)=>{
  if (!window || event.sender!==window.webContents) throw new Error('Unauthorized window');
  const url=event.sender.getURL();
  if(!url.startsWith('http://127.0.0.1:'+API_PORT+'/')) throw new Error('Unauthorized origin');
  return adminKey;
});
app.on('before-quit',stopServices);
app.on('window-all-closed',()=>app.quit());
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance',()=>{if(window){if(window.isMinimized())window.restore();window.focus();}});
  app.whenReady().then(async()=>{
    session.defaultSession.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));
    const userRoot=localRoot();
    logsDir=path.join(userRoot,'logs');
    fs.mkdirSync(logsDir,{recursive:true});
    try {
      await startServices();
      createWindow();
    } catch(err) {
      showStartupError(err);
      stopServices();
      app.quit();
    }
  }).catch(err=>{showStartupError(err);app.quit()});
}
