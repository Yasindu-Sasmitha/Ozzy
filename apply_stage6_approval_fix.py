"""Install a reliable Electron-native confirmation dialog for Ozzy Stage 6.

Run from the Ozzy project root. The patch backs up the three touched files and
uses the Electron main process dialog API instead of relying on window.confirm.
"""
from __future__ import annotations

import datetime as _dt
import shutil
from pathlib import Path

MARKER = "OZZY_STAGE6_NATIVE_APPROVAL_DIALOG"
REQUIRED = ("index.html", "desktop/preload.js", "desktop/main.js", "server.py")

NEW_RENDERER_CASE = r'''        case 'workflow_template_approval': {
          const action = String(message.action || 'save');
          const name = String(message.name || 'Unnamed workflow').slice(0, 64);
          const count = Math.max(0, Math.min(Number(message.step_count || 0), 8));
          const stepsPreview = Array.isArray(message.steps_preview)
            ? message.steps_preview.slice(0, 8).map((step, index) => ({
                label: String(step.label || step.action || `Step ${index + 1}`).slice(0, 100),
                action: String(step.action || 'unknown action').slice(0, 80),
              }))
            : [];
          const payload = {
            action: action === 'delete' ? 'delete' : 'save',
            name,
            description: String(message.description || '').slice(0, 240),
            step_count: count,
            steps_preview: stepsPreview,
          };
          const fallbackSteps = stepsPreview.map((step, index) => `${index + 1}. ${step.label} [${step.action}]`).join('\n');
          const fallbackPrompt = payload.action === 'delete'
            ? `Delete the saved workflow "${name}"?\n\nIts local execution history will also be deleted. No external files, websites, or applications will be changed.`
            : `Save the workflow "${name}" with ${count} step(s) to this device?\n\n${payload.description}\n\nSteps:\n${fallbackSteps}\n\nThe recipe is stored locally and still requires PC Control to run.`;

          setStatus(`Approval required: ${payload.action} workflow "${name}". Review the confirmation dialog.`, 'live');
          showComputerAction(`Approval required: ${payload.action} workflow "${name}".`, true);
          let approved = false;
          try {
            if (window.ozzyDesktop && typeof window.ozzyDesktop.confirmWorkflowApproval === 'function') {
              approved = await window.ozzyDesktop.confirmWorkflowApproval(payload);
            } else {
              // Browser-mode fallback. The packaged Electron desktop uses the native IPC dialog.
              approved = window.confirm(fallbackPrompt);
            }
          } catch (error) {
            console.error('Could not display the Stage 6 workflow approval dialog:', error);
            setStatus('The workflow approval dialog could not be displayed. No change was made.', 'error');
            approved = false;
          }
          const sent = sendJson({
            type: 'workflow_template_decision',
            requestId: String(message.requestId || ''),
            approved: Boolean(approved),
          });
          if (sent) {
            setStatus(approved
              ? (payload.action === 'delete' ? 'Workflow deletion approved.' : 'Workflow recipe save approved.')
              : 'Workflow library action cancelled. No changes were made.', 'live');
          } else {
            setStatus('Could not send the workflow approval decision. Reconnect Ozzy; no approval was recorded.', 'error');
          }
          break;
        }
'''

PRELOAD_METHOD = "  confirmWorkflowApproval: (payload) => ipcRenderer.invoke('ozzy:workflow-library:confirm', payload),\n"
MAIN_HANDLER = r'''// OZZY_STAGE6_NATIVE_APPROVAL_DIALOG
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

'''


def replace_region(source: str, start_marker: str, end_marker: str, replacement: str, label: str) -> str:
    if source.count(start_marker) != 1:
        raise RuntimeError(f"Expected exactly one {label} start marker, found {source.count(start_marker)}.")
    start = source.index(start_marker)
    end = source.find(end_marker, start + len(start_marker))
    if end < 0:
        raise RuntimeError(f"Could not find the end of {label} block.")
    return source[:start] + replacement + source[end:]


def main() -> int:
    root = Path.cwd().resolve()
    missing = [name for name in REQUIRED if not (root / name).is_file()]
    if missing:
        print("Run this installer from the Ozzy project root. Missing: " + ", ".join(missing))
        return 1

    paths = {name: root / name for name in REQUIRED}
    sources = {name: path.read_text(encoding='utf-8') for name, path in paths.items()}
    if MARKER in sources['desktop/main.js']:
        print("Stage 6 native approval fix is already installed; no files were changed.")
        return 0

    server = sources['server.py']
    index = sources['index.html']
    preload = sources['desktop/preload.js']
    main_js = sources['desktop/main.js']

    # Confirm this is a Stage 6 installation and the expected event is wired.
    if 'workflow_template_approval' not in server or 'workflow_template_decision' not in server:
        print("Stage 6 workflow approval backend was not found in server.py; no files were changed.")
        return 1
    if "case 'workflow_template_approval': {" not in index or "case 'memory_approval':" not in index:
        print("Could not find the Stage 6 renderer approval handler; no files were changed.")
        return 1
    if "const { contextBridge } = require('electron');" not in preload:
        print("Unexpected desktop/preload.js import; no files were changed.")
        return 1
    if "electronVersion: process.versions.electron," not in preload:
        print("Could not find the desktop preload API insertion point; no files were changed.")
        return 1
    if "const pendingCapturePickers = new Map();" not in main_js:
        print("Could not find the Electron main-process IPC insertion point; no files were changed.")
        return 1
    if "const { app, BrowserWindow, dialog, session, desktopCapturer, ipcMain } = require('electron');" not in main_js:
        print("Electron dialog/ipcMain APIs are not imported in desktop/main.js; no files were changed.")
        return 1

    try:
        index = replace_region(
            index,
            "        case 'workflow_template_approval': {",
            "        case 'memory_approval':",
            NEW_RENDERER_CASE,
            "workflow approval renderer",
        )
        preload = preload.replace(
            "const { contextBridge } = require('electron');",
            "const { contextBridge, ipcRenderer } = require('electron');",
            1,
        )
        preload = preload.replace(
            "  electronVersion: process.versions.electron,\n",
            "  electronVersion: process.versions.electron,\n" + PRELOAD_METHOD,
            1,
        )
        main_js = main_js.replace(
            "const pendingCapturePickers = new Map();\n",
            "const pendingCapturePickers = new Map();\n\n" + MAIN_HANDLER,
            1,
        )
    except Exception as exc:
        print(f"{exc} No files were changed.")
        return 1

    stamp = _dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_dir = root / 'backups' / f'stage6-approval-fix-{stamp}'
    backup_dir.mkdir(parents=True, exist_ok=False)
    for name, path in paths.items():
        shutil.copy2(path, backup_dir / Path(name).name)

    updated = {
        'index.html': index,
        'desktop/preload.js': preload,
        'desktop/main.js': main_js,
    }
    try:
        for name, content in updated.items():
            paths[name].write_text(content, encoding='utf-8', newline='\n')
    except Exception:
        for name, path in paths.items():
            backup = backup_dir / Path(name).name
            if backup.exists():
                shutil.copy2(backup, path)
        print(f"Installation failed; original files restored from {backup_dir}")
        return 1

    print('Stage 6 native approval dialog fix installed successfully.')
    print(f'Backups: {backup_dir}')
    print('Restart Ozzy with npm start. The confirmation will appear as an Electron-native dialog.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
