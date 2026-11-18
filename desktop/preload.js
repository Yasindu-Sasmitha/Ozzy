const { contextBridge, ipcRenderer } = require('electron');

// Deliberately expose metadata only. The renderer does not receive Node.js or filesystem access.
contextBridge.exposeInMainWorld('ozzyDesktop', Object.freeze({
  isDesktop: true,
  platform: process.platform,
  electronVersion: process.versions.electron,
  confirmWorkflowApproval: (payload) => ipcRenderer.invoke('ozzy:workflow-library:confirm', payload),
  confirmOfficeSave: (payload) => ipcRenderer.invoke('ozzy:office:confirm-save', payload),
  confirmOfficeOpen: (payload) => ipcRenderer.invoke('ozzy:office:confirm-open', payload),
}));
