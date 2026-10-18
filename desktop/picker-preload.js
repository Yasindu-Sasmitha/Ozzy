const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('ozzyPicker', Object.freeze({
  listSources: (requestId) => ipcRenderer.invoke('ozzy:picker:list-sources', String(requestId || '')),
  chooseSource: (requestId, sourceId) => ipcRenderer.invoke('ozzy:picker:choose-source', String(requestId || ''), String(sourceId || '')),
  cancel: (requestId) => ipcRenderer.invoke('ozzy:picker:cancel', String(requestId || '')),
}));
