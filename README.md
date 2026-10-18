## Eyes-only companion home

- Ozzy starts on a full-window black screen showing only two glowing cyan rectangular eyes.
- The eyes blink subtly while idle, brighten when listening, tilt with a small spark while thinking, pulse while speaking, scan when visual input is active, and briefly squint for a positive reaction.
- The **Advanced options** button stays hidden until the pointer is over the home window (or keyboard focus reaches it).
- Advanced options opens the existing voice chat, camera, screen-sharing, and SQLite memory controls. **Back to Ozzy** returns home without disconnecting an active conversation.
- View switching explicitly sets the display state to avoid the previous blank/white-screen transition. Electron's initial window background is also black to avoid a white flash while loading.

# Ozzy Desktop — Gemini Live Voice, Vision & Persistent Memory

This is the first Electron desktop version of Ozzy, based on the existing working voice-and-vision frontend and Python Gemini Live bridge. It adds:

- A dedicated Electron desktop window instead of requiring you to open a browser tab.
- Automatic launch/shutdown of the Python backend.
- Voice conversation, camera and screen-share support retained from the existing app.
- SQLite-backed long-term memories stored in the operating-system user-data directory.
- Gemini Live function tools for explicit memory save, memory listing, searching relevant memories, and finding candidates to forget.
- A confirmation dialog before a memory is saved or deleted, plus a Memory panel to review and manually remove saved items.
- An Electron-native screen/window picker rather than silently selecting a display.
- Local-only HTTP health/memory endpoints; the static server serves only `index.html`, not `.env` or Python source files.
- Sensitive-looking credentials and payment-card details are rejected by the memory service.


## Companion home screen

The default landing view is an original, Cozmo-inspired expressive robot face built with HTML and CSS (not copied Cozmo artwork). It blinks, glances around in idle mode, changes eye appearance when listening/thinking/visual input is active, and animates its mouth while generated audio plays. Positive-sounding output transcripts may trigger a brief happy expression. Use **Advanced options** to open the existing voice chat, camera, screen-share, and memory workspace; **Back to Ozzy** returns to the face without disconnecting the session.

The face is a visual representation of app state, not a claim that Ozzy has human feelings. Listening/thinking uses a basic local microphone level heuristic; speaking follows queued output audio.

## 1. Requirements

- Windows 10/11 for the current Windows desktop setup.
- Node.js LTS and npm.
- Python 3.10+.
- A Gemini API key with access to the configured Live model (`gemini-3.8-live`).

## 2. Set up the development version

Open PowerShell in this project folder and run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Open `.env` and replace the placeholder with your key:

```env
GEMINI_API_KEY=your_actual_gemini_api_key
```

Install Electron packages and launch Ozzy:

```powershell
npm install
npm start
```

Electron opens a desktop window and starts `server.py` automatically. You do not need to manually open the local webpage or run the server separately. Keep `.env` private and never commit it to GitHub.

If you already have a project `.env`, preserve it and only ensure `GEMINI_API_KEY` is configured. The local database does not replace or alter the API key.

## 3. How memory works

### Voice commands to try

- “Remember that my current robotics project is called Ozzy.”
- “Remember that I prefer concise answers.”
- “What do you remember about my projects?”
- “Find the memory about my robotics project.”
- “Forget the memory about my speaking preference.”

Gemini uses the Live API's function-calling flow. `save_memory` and `forget_memories` are only proposals: the app displays the exact content or candidate records and waits for you to approve. Cancelling sends a rejection back to Gemini. Read-only memory search/list calls do not need approval.

The tool behavior depends on the configured Live model supporting function calling for your account. If the model reports a tool-configuration error, check the terminal log and the current Live API tool-calling documentation before changing model IDs.

### Manage memories manually

Click **Memories** in the app. It shows saved items and categories. You can refresh the list or click **Forget** next to an entry; deletion requires a confirmation dialog.

### Storage location

The database file is named `ozzy_memory.sqlite3` inside Ozzy's application user-data folder. On Windows this is normally:

```text
%APPDATA%\Ozzy\ozzy_memory.sqlite3
```

The installed app also reads its API-key file from:

```text
%APPDATA%\Ozzy\.env
```

The dev server checks this per-user `.env` first and then the project-root `.env` file. For a fresh packaged installation, create `%APPDATA%\Ozzy\.env` and add `GEMINI_API_KEY=your_actual_gemini_api_key`, then restart Ozzy. The installer does not include your API key.

Back up the SQLite database if you want to preserve memories when reinstalling Windows. To erase all saved memories, close Ozzy and remove the database file. The `-wal` and `-shm` companion files may also be present while the app is running; close Ozzy before managing these files.

## 4. Build a Windows installer

First verify development mode with `npm start`. Then run:

```powershell
npm run dist:win
```

The script uses PyInstaller to bundle the Python backend into `backend-dist\ozzy-backend.exe`, then Electron Builder packages the desktop app. The installer is output to `release\`.

Build the Windows installer on Windows. PyInstaller/Electron Builder builds are platform-specific. If PyInstaller fails to collect a Google SDK dependency, see the exact error in the terminal and adjust the build script; the development version can still run directly against your local Python environment.

## 5. Tests and checks

Run the SQLite unit tests (no Gemini API key is required):

```powershell
python -m unittest discover -s tests -v
```

Syntax checks:

```powershell
python -m py_compile server.py memory_service.py
node --check desktop/main.js
node --check desktop/preload.js
```

The automated tests cover SQLite save, duplicate prevention, keyword lookup, secret rejection, and deletion. They do not simulate Gemini Live, real microphone input, camera permissions, or the Electron installer; those need a local end-to-end run.

## Privacy and security notes

- SQLite is local to the current device in this first version; this version does not sync memories to a future mobile app.
- Memory content is sent to Gemini only when needed by an active memory tool call (for example, listing or searching saved memories), or when the user approves a new memory.
- Microphone audio and enabled visual frames are streamed to the Gemini API as in the existing app. Stop visuals before showing anything private.
- Saving and deleting memories require explicit approval. The app also exposes a manual memory list so you can review and remove them.
- The Electron renderer uses `contextIsolation`, `sandbox`, and `nodeIntegration: false`. Do not load arbitrary remote websites inside the Ozzy window.
- For production distribution, code-sign the installer, review permission behavior on each target OS, and keep Electron updated.
