const { contextBridge } = require('electron');

// Deliberately expose metadata only. The renderer does not receive Node.js or filesystem access.
contextBridge.exposeInMainWorld('ozzyDesktop', Object.freeze({
  isDesktop: true,
  platform: process.platform,
  electronVersion: process.versions.electron,
}));
