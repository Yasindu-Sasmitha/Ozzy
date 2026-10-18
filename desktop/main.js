const { app, BrowserWindow, dialog, session, desktopCapturer, ipcMain } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const { randomUUID } = require('node:crypto');

app.setName('Ozzy');
const userDataDir = path.join(app.getPath('appData'), 'Ozzy');
app.setPath('userData', userDataDir);

const APP_URL = 'http://127.0.0.1:8000';
const HEALTH_URL = `${APP_URL}/api/health`;
const PROJECT_DIR = app.getAppPath();
let mainWindow = null;
let backendProcess = null;
let logStream = null;
let quitting = false;
const pendingCapturePickers = new Map();

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function localOrigin(value) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'http:' && parsed.hostname === '127.0.0.1' && parsed.port === '8000';
  } catch {
    return false;
  }
}

function ensureUserDataFiles() {
  fs.mkdirSync(userDataDir, { recursive: true });
  const envPath = path.join(userDataDir, '.env');
  if (!fs.existsSync(envPath)) {
    fs.writeFileSync(
      envPath,
      '# Add your Gemini API key below, then restart Ozzy. Keep this file private.\nGEMINI_API_KEY=replace_with_your_gemini_api_key\n',
      { encoding: 'utf8', flag: 'wx' },
    );
  }
}

function appendBackendLogs() {
  const logPath = path.join(userDataDir, 'ozzy-backend.log');
  logStream = fs.createWriteStream(logPath, { flags: 'a' });
  logStream.write(`\n\n===== Ozzy backend launch ${new Date().toISOString()} =====\n`);
  return logPath;
}

function launchBackend() {
  const logPath = appendBackendLogs();
  const env = {
    ...process.env,
    OZZY_DATA_DIR: userDataDir,
    PYTHONUNBUFFERED: '1',
  };

  if (app.isPackaged) {
    const executable = path.join(process.resourcesPath, 'backend', process.platform === 'win32' ? 'ozzy-backend.exe' : 'ozzy-backend');
    if (!fs.existsSync(executable)) {
      throw new Error(`Packaged Python backend is missing: ${executable}\nBuild it using the instructions in README.md.`);
    }
    backendProcess = spawn(executable, [], { cwd: userDataDir, env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  } else {
    const scriptPath = path.join(PROJECT_DIR, 'server.py');
    if (!fs.existsSync(scriptPath)) throw new Error(`Cannot find server.py in ${PROJECT_DIR}`);

    const candidates = process.platform === 'win32'
      ? [path.join(PROJECT_DIR, '.venv', 'Scripts', 'python.exe')]
      : [path.join(PROJECT_DIR, '.venv', 'bin', 'python')];
    const virtualEnvPython = candidates.find((candidate) => fs.existsSync(candidate));
    const pythonCommand = process.env.OZZY_PYTHON || virtualEnvPython || (process.platform === 'win32' ? 'python' : 'python3');
    backendProcess = spawn(pythonCommand, [scriptPath], {
      cwd: PROJECT_DIR,
      env,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  }

  backendProcess.stdout.on('data', (chunk) => logStream?.write(chunk));
  backendProcess.stderr.on('data', (chunk) => logStream?.write(chunk));
  backendProcess.on('error', (error) => logStream?.write(`\n[spawn error] ${error.stack || error}\n`));
  backendProcess.on('exit', (code, signal) => {
    logStream?.write(`\n[backend exited] code=${code}, signal=${signal}\n`);
    if (!quitting && mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('ozzy-backend-exited', { code, signal });
    }
  });

  return logPath;
}

async function waitForBackend(timeoutMs = 45000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = 'Not started yet';
  while (Date.now() < deadline) {
    if (backendProcess && backendProcess.exitCode !== null) {
      throw new Error(`Ozzy backend exited early (code ${backendProcess.exitCode}).`);
    }
    try {
      const response = await fetch(HEALTH_URL, { signal: AbortSignal.timeout(1200), cache: 'no-store' });
      if (response.ok) return await response.json();
      lastError = `Health check returned ${response.status}`;
    } catch (error) {
      lastError = error.message || String(error);
    }
    await wait(300);
  }
  throw new Error(`Ozzy backend did not start in time. Last check: ${lastError}`);
}

function settleCapturePicker(requestId, sourceOrNull) {
  const pending = pendingCapturePickers.get(requestId);
  if (!pending) return false;
  pendingCapturePickers.delete(requestId);
  try { pending.resolve(sourceOrNull || null); } catch { /* Promise already settled. */ }
  if (pending.picker && !pending.picker.isDestroyed()) pending.picker.close();
  return true;
}

async function chooseDesktopSource(sources) {
  if (!sources.length) return null;
  return new Promise((resolve) => {
    const requestId = randomUUID();
    const picker = new BrowserWindow({
      width: 760,
      height: 620,
      minWidth: 560,
      minHeight: 440,
      parent: mainWindow || undefined,
      modal: Boolean(mainWindow),
      title: 'Ozzy — Choose what to share',
      show: false,
      resizable: true,
      autoHideMenuBar: true,
      webPreferences: {
        preload: path.join(PROJECT_DIR, 'desktop', 'picker-preload.js'),
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: true,
        webSecurity: true,
      },
    });
    pendingCapturePickers.set(requestId, { sources, resolve, picker });
    picker.once('ready-to-show', () => picker.show());
    picker.on('closed', () => {
      // Closing the picker window without choosing a source counts as Cancel.
      if (pendingCapturePickers.has(requestId)) settleCapturePicker(requestId, null);
    });
    picker.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    picker.loadFile(path.join(PROJECT_DIR, 'desktop', 'screen-picker.html'), { query: { requestId } });
  });
}

ipcMain.handle('ozzy:picker:list-sources', (event, requestId) => {
  const pending = pendingCapturePickers.get(String(requestId));
  if (!pending || event.sender !== pending.picker.webContents) return [];
  return pending.sources.map((source) => ({
    id: source.id,
    name: source.name,
    thumbnail: source.thumbnail ? source.thumbnail.toDataURL() : '',
  }));
});

ipcMain.handle('ozzy:picker:choose-source', (event, requestId, sourceId) => {
  const pending = pendingCapturePickers.get(String(requestId));
  if (!pending || event.sender !== pending.picker.webContents) return false;
  const selected = pending.sources.find((source) => source.id === String(sourceId));
  if (!selected) return false;
  return settleCapturePicker(String(requestId), selected);
});

ipcMain.handle('ozzy:picker:cancel', (event, requestId) => {
  const pending = pendingCapturePickers.get(String(requestId));
  if (!pending || event.sender !== pending.picker.webContents) return false;
  return settleCapturePicker(String(requestId), null);
});

function installPermissionHandlers() {
  const ses = session.defaultSession;
  ses.setPermissionRequestHandler((webContents, permission, callback, details) => {
    const url = details?.requestingUrl || webContents.getURL();
    if (!localOrigin(url)) return callback(false);

    // These permissions are only requested after the user presses Ozzy's mic/camera/share controls.
    if (permission === 'media' || permission === 'display-capture' || permission === 'notifications') {
      return callback(true);
    }
    return callback(false);
  });

  ses.setPermissionCheckHandler((_webContents, permission, requestingOrigin) => {
    if (!localOrigin(requestingOrigin)) return false;
    return permission === 'media' || permission === 'display-capture' || permission === 'notifications';
  });

  // Electron needs an explicit source-selection handler for getDisplayMedia. Unlike
  // auto-selecting the first screen, this always presents a picker and supports Cancel.
  ses.setDisplayMediaRequestHandler(async (request, callback) => {
    if (!localOrigin(request.securityOrigin) || !request.userGesture || !request.videoRequested) {
      callback({});
      return;
    }
    try {
      const sources = await desktopCapturer.getSources({
        types: ['screen', 'window'],
        thumbnailSize: { width: 320, height: 180 },
        fetchWindowIcons: true,
      });
      const selected = await chooseDesktopSource(sources);
      callback(selected ? { video: selected } : {});
    } catch (error) {
      logStream?.write(`[screen capture picker error] ${error.stack || error}\n`);
      callback({});
    }
  }, { useSystemPicker: process.platform === 'darwin' });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1120,
    height: 900,
    minWidth: 780,
    minHeight: 680,
    show: false,
    title: 'Ozzy',
    autoHideMenuBar: true,
    backgroundColor: '#000000',
    webPreferences: {
      preload: path.join(PROJECT_DIR, 'desktop', 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!localOrigin(url)) event.preventDefault();
  });
  mainWindow.once('ready-to-show', () => mainWindow?.show());
  mainWindow.on('closed', () => { mainWindow = null; });
  mainWindow.loadURL(APP_URL);
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    ensureUserDataFiles();
    installPermissionHandlers();
    let logPath = path.join(userDataDir, 'ozzy-backend.log');
    try {
      logPath = launchBackend();
      const health = await waitForBackend();
      createWindow();
      if (!health.apiKeyConfigured) {
        await dialog.showMessageBox({
          type: 'warning',
          title: 'Configure Ozzy',
          message: 'Ozzy started, but the Gemini API key is not configured.',
          detail: `Add GEMINI_API_KEY=your_key to this file and restart Ozzy:\n${path.join(userDataDir, '.env')}\n\nBackend log: ${logPath}`,
          buttons: ['OK'],
        });
      }
    } catch (error) {
      await dialog.showMessageBox({
        type: 'error',
        title: 'Ozzy could not start',
        message: error.message || String(error),
        detail: `Check your Python dependencies and API configuration. Backend log: ${logPath}`,
        buttons: ['Quit'],
      });
      app.quit();
    }
  });

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0 && backendProcess && backendProcess.exitCode === null) createWindow();
  });
}

app.on('before-quit', () => {
  quitting = true;
  if (backendProcess && backendProcess.exitCode === null) {
    backendProcess.kill();
  }
  if (logStream) logStream.end();
});

app.on('window-all-closed', () => {
  // Desktop Ozzy quits when the main window closes for this first release.
  if (process.platform !== 'darwin') app.quit();
});
