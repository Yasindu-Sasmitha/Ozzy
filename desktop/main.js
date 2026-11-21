const { app, BrowserWindow, dialog, session, desktopCapturer, ipcMain, Notification } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const { randomUUID } = require('node:crypto');

app.setName('Ozzy');
// Windows needs an AppUserModelID for native toast notifications to show the app's name.
if (process.platform === 'win32') app.setAppUserModelId('com.yasindu.ozzy');
// Reminders may need Ozzy to speak first without a click, so let the local UI play audio unprompted.
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');
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

// OZZY_STAGE9_NOTIFICATIONS
ipcMain.handle('ozzy:notify', (event, payload = {}) => {
  if (!mainWindow || mainWindow.isDestroyed() || event.sender !== mainWindow.webContents) return false;
  if (!Notification.isSupported()) return false;
  const clip = (value, limit) => (typeof value === 'string' ? value.replace(/[\u0000-\u001f\u007f]/g, ' ').trim().slice(0, limit) : '');
  const title = clip(payload && payload.title, 120) || 'Ozzy';
  const body = clip(payload && payload.body, 300);
  const notification = new Notification({ title, body });
  notification.on('click', () => {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });
  notification.show();
  return true;
});

// OZZY_STAGE6_NATIVE_APPROVAL_DIALOG
ipcMain.handle('ozzy:workflow-library:confirm', async (event, payload = {}) => {
  if (!mainWindow || mainWindow.isDestroyed() || event.sender !== mainWindow.webContents) return false;

  const action = payload && payload.action === 'delete' ? 'delete' : 'save';
  const rawName = payload && typeof payload.name === 'string' ? payload.name : '';
  const name = rawName.trim().slice(0, 64) || 'Unnamed workflow';
  const description = payload && typeof payload.description === 'string'
    ? payload.description.trim().slice(0, 240)
    : '';
  const suppliedSteps = payload && Array.isArray(payload.steps_preview) ? payload.steps_preview : [];
  const steps = suppliedSteps.slice(0, 8).map((step, index) => {
    const label = step && typeof step.label === 'string' ? step.label.slice(0, 100) : `Step ${index + 1}`;
    const tool = step && typeof step.action === 'string' ? step.action.slice(0, 80) : 'unknown action';
    return `${index + 1}. ${label} [${tool}]`;
  });
  const detail = action === 'delete'
    ? 'Its local execution history will also be deleted. This will not affect external files, websites, or applications.'
    : [description, steps.length ? `Steps:\n${steps.join('\n')}` : 'No step preview was provided.', 'The recipe is stored locally and still requires PC Control to run.'].filter(Boolean).join('\n\n');

  const result = await dialog.showMessageBox(mainWindow, {
    type: 'question',
    title: action === 'delete' ? 'Confirm workflow deletion' : 'Confirm workflow save',
    message: action === 'delete'
      ? `Delete the saved workflow "${name}"?`
      : `Save the workflow "${name}" to this device?`,
    detail,
    buttons: [action === 'delete' ? 'Delete workflow' : 'Save workflow', 'Cancel'],
    defaultId: 1,
    cancelId: 1,
    noLink: true,
  });
  return result.response === 0;
});


// OZZY_STAGE7_OFFICE_SAVE_APPROVAL
ipcMain.handle('ozzy:office:confirm-save', async (event, payload = {}) => {
  if (!mainWindow || mainWindow.isDestroyed() || event.sender !== mainWindow.webContents) return false;
  const labels = { word: 'Microsoft Word', excel: 'Microsoft Excel', powerpoint: 'Microsoft PowerPoint' };
  const application = labels[payload && payload.application] || 'Microsoft Office';
  const filePath = payload && typeof payload.file_path === 'string' ? payload.file_path.trim().slice(0, 500) : '';
  const sourceName = payload && typeof payload.source_name === 'string'
    ? payload.source_name.trim().slice(0, 180)
    : 'Active Office document';
  if (!filePath || !path.isAbsolute(filePath)) return false;
  const result = await dialog.showMessageBox(mainWindow, {
    type: 'question',
    title: 'Confirm new Office file',
    message: `Create a new ${application} file?`,
    detail: `Source: ${sourceName}\nDestination:\n${filePath}\n\nNo existing file will be overwritten. Word's active document will switch to this new path; Excel and PowerPoint create a copy.`,
    buttons: ['Save new file', 'Cancel'],
    defaultId: 1,
    cancelId: 1,
    noLink: true,
  });
  return result.response === 0;
});

// OZZY_STAGE8_OFFICE_OPEN_APPROVAL
ipcMain.handle('ozzy:office:confirm-open', async (event, payload = {}) => {
  if (!mainWindow || mainWindow.isDestroyed() || event.sender !== mainWindow.webContents) return false;
  const labels = { word: 'Microsoft Word', excel: 'Microsoft Excel', powerpoint: 'Microsoft PowerPoint' };
  const application = labels[payload && payload.application] || 'Microsoft Office';
  const filePath = payload && typeof payload.file_path === 'string' ? payload.file_path.trim().slice(0, 500) : '';
  if (!filePath || !path.isAbsolute(filePath)) return false;
  const sizeBytes = Number(payload && payload.size_bytes);
  const sizeText = Number.isFinite(sizeBytes) && sizeBytes >= 0
    ? (sizeBytes >= 1048576 ? `${(sizeBytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(sizeBytes / 1024))} KB`)
    : 'unknown size';
  const notes = [
    'Macros are disabled while Ozzy opens the file. Ozzy will not save over it.',
    payload && payload.will_start_app ? `${application} is not running, so Ozzy will start it.` : '',
    payload && payload.internet_download ? 'This file was downloaded from the internet, so it opens read-only.' : '',
    payload && payload.read_only && !payload.internet_download ? 'It will open read-only.' : '',
  ].filter(Boolean).join('\n');
  const result = await dialog.showMessageBox(mainWindow, {
    type: 'question',
    title: 'Confirm opening an Office file',
    message: `Open this file in ${application}?`,
    detail: `${filePath}\n(${sizeText})\n\n${notes}`,
    buttons: ['Open file', 'Cancel'],
    defaultId: 1,
    cancelId: 1,
    noLink: true,
  });
  return result.response === 0;
});

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
      // Keep reminder timers and the speak-first poller running when the window is minimised.
      backgroundThrottling: false,
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
