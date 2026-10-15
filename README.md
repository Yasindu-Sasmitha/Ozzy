# Denise — Gemini Live Voice & Vision

This project adds **live camera input** and **screen sharing** to the existing Denise voice chatbot. It keeps the Gemini Live audio stream, output audio playback, transcription bubbles, and typed-message fallback.

## Features

- Continuous microphone audio streamed to Gemini Live as PCM16 audio.
- Live-generated speech playback and optional input/output transcripts.
- **Start camera**: preview your camera locally and send compressed JPEG frames to Gemini.
- **Share screen**: choose a screen, window, or browser tab in the browser permission dialog and send its frames to Gemini.
- **Stop visuals**: stops the camera/screen capture immediately while keeping the voice-chat session connected.
- The browser sends at most one image about every 1.1 seconds. Gemini Live accepts video as individual image frames, not a full-rate video stream.
- The app does not write camera or screen frames to local files.

## Requirements

- Python 3.10 or newer.
- A Gemini API key with access to the configured Live model (`gemini-3.8-live`).
- A modern browser that supports microphone capture and, for screen sharing, `navigator.mediaDevices.getDisplayMedia`.

## Setup on Windows PowerShell

1. Extract the project folder and open a terminal in it.
2. Create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks activation, use Command Prompt and run `.venv\Scripts\activate.bat`.

3. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env` and place your actual key in `.env`:

   ```env
   GEMINI_API_KEY=your_actual_gemini_api_key
   ```

   Keep `.env` private. Do not put your key in `index.html` or commit it to a public repository.

5. Run the server:

   ```powershell
   python server.py
   ```

6. Open **http://127.0.0.1:8000**. Keep the terminal open while chatting.

## Using visual awareness

1. Click **Connect & Talk** and allow microphone access.
2. Click **Start camera** or **Share screen**. The browser will request permission; the share-screen picker lets you select what to share.
3. Ask Denise about what is visible, for example, “What is on my screen?” or “Help me understand this error.”
4. Click **Stop visuals** to stop sharing without disconnecting voice chat.

Camera and screen sharing are off until you explicitly start one. Only one visual source is active at a time; starting a new source switches from the previous source. Disconnecting the conversation also stops visual capture.

Frames are streamed to the Gemini API while visual sharing is active. Do not share sensitive pages, passwords, private chats, or confidential information. The local browser preview is visible so you can confirm what is being shared.

## Troubleshooting

- **Camera buttons are disabled:** Connect to the Live session first.
- **Browser does not ask for camera permission:** Check the browser's site permissions for `127.0.0.1`.
- **Screen-share picker was cancelled:** Click **Share screen** again and select a source.
- **Denise says the text is hard to read:** Zoom in on the screen/window before sharing; Gemini receives compressed frames no more frequently than once about every 1.1 seconds.
- **Gemini reports an unsupported model or video input:** Verify the configured model supports Live API video input for your account, then check the Python terminal for the exact API error.
- **Port already in use:** Close the other local server using port 8000 or 8765 before restarting this app.
