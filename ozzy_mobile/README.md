# Ozzy Mobile — Flutter (Android first, iOS-ready)

This is the Flutter mobile companion for the current Ozzy desktop project. It keeps Ozzy's minimal cyan-eyes identity and adds a native mobile interface around Gemini Live.

## Included in this starter

- Eyes-only black home screen with animated gaze, blinking, and basic mood expressions.
- Gemini Live voice chat using model `gemini-3.8-live`.
- Text chat and streamed input/output transcriptions.
- Live camera preview with front/back camera switching; compressed camera snapshots are sent to Gemini approximately every 1.1 seconds while enabled.
- Android screen sharing through the system MediaProjection permission prompt and a visible foreground-service notification. Frames are sent to Gemini at a conservative rate; iOS screen sharing is not included in this patch.
- Pick an image from the gallery and ask Ozzy about it.
- Local SQLite memory with `remember_fact`, `search_memories`, `list_memories`, and `forget_memories` tool calls. Saving and deletion require an explicit in-app confirmation.
- API-key settings screen. The user can enter, reveal/hide, save, or remove a key.
- API key storage through `flutter_secure_storage` (Android Keystore-backed secure storage / Apple Keychain).

### Mobile limitation

Mobile supports camera snapshots, selected gallery images, and Android screen sharing when the user approves the operating-system prompt. Screen sharing has a persistent Android foreground-service notification and stops when the user selects Stop share in Ozzy or Android ends the projection. iOS screen sharing requires a ReplayKit broadcast extension and is not included.

## Requirements

- Flutter with Dart 3.12 or newer (the current `gemini_live`, `camera`, `record`, and `flutter_soloud` dependencies target the current Flutter toolchain).
- Android device/emulator for the first run. Building/signing the iOS app requires macOS with Xcode.
- A Gemini API key with Live API access to `gemini-3.8-live`.

## Create the native Flutter scaffolding

This ZIP includes `lib/` and `pubspec.yaml`; the setup script uses your installed Flutter SDK to generate the native Android/iOS runner folders, adds camera/microphone permissions, then restores Ozzy's source files.

On Windows PowerShell, extract the folder, enter `ozzy_mobile`, and run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup_mobile.ps1
```

If you prefer to manage platform folders yourself, run `flutter create --platforms=android,ios --org com.yasindu --project-name ozzy_mobile --empty .`, then keep this project's `lib/` and `pubspec.yaml`; add the native permissions described in the script.

## Run on Android

```powershell
flutter doctor -v
flutter devices
flutter run
```

For a release APK for personal testing:

```powershell
flutter build apk --release
```

The APK will be created under `build/app/outputs/flutter-apk/` after the Android toolchain is configured.

## Add your API key

Launch Ozzy, tap the settings icon, paste the key from `https://aistudio.google.com/apikey`, and tap **Save API key securely**. Then return to Ozzy and tap the microphone/connect button. The key is not hardcoded in the project and is not committed in a config file.

### Important security note

This direct-key mode is intended for your own personal build/testing. Even when a key is stored using Android Keystore/Apple Keychain, a key used directly by a mobile application can still be extracted from a compromised device or reverse-engineered app. Restrict the key to the Gemini API, monitor usage, and never publish a public app containing your personal key workflow as the only authentication method. Before distributing Ozzy, use a backend to mint short-lived Gemini Live ephemeral tokens and never ship a permanent server key in the app.

## Local memory

Memories are saved in the app's private SQLite database on the phone. They are not synchronized with the desktop version in this first mobile build. When Ozzy calls `remember_fact`, the app shows an approval dialog before saving. `forget_memories` shows candidate matches and requires selecting and approving exact records for deletion.

## Troubleshooting

- **API key missing:** open Settings from the home screen and add one.
- **No microphone prompt:** check app permissions in Android Settings; microphone permission is required for Live voice mode.
- **No camera preview:** grant camera access. Camera is off unless you explicitly enable it.
- **Unsupported model or Live API setup error:** verify that the key and account have access to `gemini-3.8-live`. The model ID is in `lib/main.dart` near `_modelId`.
- **Audio package build errors:** use current stable Flutter/Dart compatible with the versions in `pubspec.yaml`, then rerun `flutter pub get`.
- **iOS build:** run the iOS build from macOS/Xcode after generating the iOS folder; the setup script adds the required usage descriptions.

## Architecture

- `lib/main.dart` — Ozzy home/advanced UI, Gemini Live controller, live audio, camera frames and memory tool confirmations.
- `lib/widgets/ozzy_face.dart` — mobile eyes-only face and randomized gaze.
- `lib/screens/settings_screen.dart` — API-key entry/removal UI.
- `lib/services/api_key_store.dart` — secure local key storage.
- `lib/services/memory_store.dart` — SQLite memory store and basic secret screening.
