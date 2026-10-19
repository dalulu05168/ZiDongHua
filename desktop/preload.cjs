'use strict';
// Intentionally tiny and narrowly scoped: expose only local auth to this app window.
const {contextBridge, ipcRenderer} = require('electron');
contextBridge.exposeInMainWorld('xbwDesktop', Object.freeze({
  authorize: () => ipcRenderer.invoke('xbw:get-local-token')
}));
