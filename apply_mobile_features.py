from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT
DART = PROJECT / 'ozzy_mobile' / 'lib' / 'main.dart'
MANIFEST = PROJECT / 'ozzy_mobile' / 'android' / 'app' / 'src' / 'main' / 'AndroidManifest.xml'
README = PROJECT / 'ozzy_mobile' / 'README.md'


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: expected one matching code anchor, found {count}. No changes were written to this file.')
    return source.replace(old, new, 1)


def main():
    if not DART.exists():
        raise SystemExit('Could not find ozzy_mobile/lib/main.dart. Extract this patch at the root of the Ozzy repository.')

    source = DART.read_text(encoding='utf-8')
    source = replace_once(
        source,
        "import 'package:flutter/material.dart';\n",
        "import 'package:flutter/material.dart';\nimport 'package:flutter/services.dart';\n",
        'Flutter services import',
    )
    source = replace_once(
        source,
        "const _modelId = 'gemini-3.8-live';\n",
        "const _modelId = 'gemini-3.8-live';\n"
        "const MethodChannel _screenShareMethodChannel = MethodChannel('ozzy_mobile/screen_share');\n"
        "const EventChannel _screenShareEventChannel = EventChannel('ozzy_mobile/screen_frames');\n",
        'screen share channels',
    )
    source = replace_once(
        source,
        'Mobile limitations: you can receive camera frames and selected gallery images.\n'
        "You cannot see the phone's entire screen or share arbitrary mobile apps.\n",
        'Mobile vision: you can receive camera frames, selected gallery images, and—on Android only—screen frames after the user approves the system screen-sharing prompt. Never imply the screen is visible when screen sharing is off.\n',
        'system prompt mobile vision note',
    )
    source = replace_once(
        source,
        '  DateTime? _lastModelAudioChunkAt;\n  static const Duration _echoGuardTail = Duration(milliseconds: 1200);\n  CameraController? _camera;\n',
        '  DateTime? _lastModelAudioChunkAt;\n'
        '  DateTime? _speakerPlaybackUntil;\n'
        '  // A longer tail plus an estimate of queued speaker audio prevents the mic\n'
        '  // from reopening while the phone is still physically playing Ozzy\'s voice.\n'
        '  static const Duration _echoGuardTail = Duration(milliseconds: 1800);\n'
        '  CameraController? _camera;\n'
        '  bool _usingFrontCamera = false;\n'
        '  bool _screenShareActive = false;\n'
        '  StreamSubscription<dynamic>? _screenFrameSubscription;\n'
        '  DateTime? _lastScreenShareFrameSentAt;\n',
        'audio/camera/screen share fields',
    )
    source = replace_once(
        source,
        '      _incomingAudioSubscription = controller.incomingAudioStream.listen((pcm) {\n'
        '        // Remember every incoming model-audio chunk, not just the final chunk.\n'
        '        // The microphone gate below uses this timestamp to cover speaker-buffer\n'
        '        // latency after Gemini stops producing audio.\n'
        '        _lastModelAudioChunkAt = DateTime.now();\n'
        '        final source = _speakerSource;\n',
        '      _incomingAudioSubscription = controller.incomingAudioStream.listen((pcm) {\n'
        '        // Track the expected end of the queued 24 kHz, mono, 16-bit speaker audio.\n'
        '        // This covers output still buffered for playback after the API stream pauses.\n'
        '        final now = DateTime.now();\n'
        '        _lastModelAudioChunkAt = now;\n'
        '        final previousEnd = _speakerPlaybackUntil;\n'
        '        final playbackBase = previousEnd != null && previousEnd.isAfter(now) ? previousEnd : now;\n'
        '        final chunkMicros = (pcm.length * 1000000) ~/ 48000;\n'
        '        _speakerPlaybackUntil = playbackBase.add(Duration(microseconds: chunkMicros));\n'
        '        final source = _speakerSource;\n',
        'speaker playback queue tracking',
    )
    source = replace_once(
        source,
        '        final lastOutputAt = _lastModelAudioChunkAt;\n'
        '        final modelAudioRecentlyArrived = lastOutputAt != null &&\n'
        '            DateTime.now().difference(lastOutputAt) < _echoGuardTail;\n'
        '\n'
        '        // IMPORTANT: Do not send microphone audio while Ozzy is speaking.\n'
        '        // Otherwise the phone can record Ozzy\'s speaker output and Gemini may\n'
        '        // treat Ozzy\'s own words as a new user turn, creating a reply loop.\n'
        '        // Keep the recorder running so it resumes naturally after the guard.\n'
        '        if (live.isModelSpeaking || modelAudioRecentlyArrived) return;\n',
        '        final now = DateTime.now();\n'
        '        final lastOutputAt = _lastModelAudioChunkAt;\n'
        '        final modelAudioRecentlyArrived = lastOutputAt != null &&\n'
        '            now.difference(lastOutputAt) < _echoGuardTail;\n'
        '        final playbackUntil = _speakerPlaybackUntil;\n'
        '        final queuedSpeakerAudioMayStillPlay = playbackUntil != null &&\n'
        '            now.isBefore(playbackUntil.add(const Duration(milliseconds: 850)));\n'
        '\n'
        '        // Do not feed the model its own speaker audio. The state flag covers active\n'
        '        // generation, the queue estimate covers buffered playback, and the tail\n'
        '        // covers room acoustics after the last chunk.\n'
        '        if (live.isModelSpeaking || modelAudioRecentlyArrived || queuedSpeakerAudioMayStillPlay) return;\n',
        'microphone echo guard',
    )

    # Reset the playback estimate anywhere the existing audio timestamp is reset.
    source = source.replace('    _lastModelAudioChunkAt = null;\n', '    _lastModelAudioChunkAt = null;\n    _speakerPlaybackUntil = null;\n')

    camera_start = source.find('  Future<void> _startCamera() async {')
    camera_end = source.find('  Future<void> _sendGalleryImage() async {', camera_start)
    if camera_start < 0 or camera_end < 0:
        raise RuntimeError('Camera methods anchor not found; no Dart changes were written.')
    camera_block = r'''  Future<void> _startCamera() async {
    _markInteraction();
    if (_live?.isConnected != true) {
      setState(() => _status = 'Connect Ozzy before starting the camera.');
      return;
    }
    if (_cameraActive) {
      await _stopCamera();
      return;
    }
    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) throw Exception('No camera was found on this device.');
      final preferredDirection = _usingFrontCamera ? CameraLensDirection.front : CameraLensDirection.back;
      final matching = cameras.where((camera) => camera.lensDirection == preferredDirection).toList();
      final selected = matching.isNotEmpty ? matching.first : cameras.first;
      final camera = CameraController(selected, ResolutionPreset.medium, enableAudio: false, imageFormatGroup: ImageFormatGroup.jpeg);
      await camera.initialize();
      if (!mounted) { await camera.dispose(); return; }
      setState(() { _camera = camera; _usingFrontCamera = selected.lensDirection == CameraLensDirection.front; _faceState = 'visual'; _status = 'Camera active. I can see snapshots about once per second.'; });
      _cameraTimer?.cancel();
      _cameraTimer = Timer.periodic(const Duration(milliseconds: 1100), (_) => unawaited(_captureAndSendFrame()));
      await _captureAndSendFrame();
    } catch (error) {
      if (mounted) setState(() { _status = 'Could not start camera: $error'; _faceState = 'error'; });
    }
  }

  Future<void> _switchCamera() async {
    _markInteraction();
    final current = _camera;
    if (current == null || !current.value.isInitialized) {
      setState(() => _status = 'Start the camera before switching lenses.');
      return;
    }

    final targetDirection = current.description.lensDirection == CameraLensDirection.front
        ? CameraLensDirection.back
        : CameraLensDirection.front;
    CameraController? nextCamera;
    try {
      final cameras = await availableCameras();
      final candidates = cameras.where((camera) => camera.lensDirection == targetDirection).toList();
      if (candidates.isEmpty) {
        if (mounted) setState(() => _status = targetDirection == CameraLensDirection.front
            ? 'This device does not report a front camera.'
            : 'This device does not report a rear camera.');
        return;
      }

      _cameraTimer?.cancel();
      _cameraTimer = null;
      _camera = null;
      try { await current.dispose(); } catch (_) { /* release is best-effort */ }

      nextCamera = CameraController(candidates.first, ResolutionPreset.medium, enableAudio: false, imageFormatGroup: ImageFormatGroup.jpeg);
      await nextCamera.initialize();
      if (!mounted) { await nextCamera.dispose(); return; }
      setState(() {
        _camera = nextCamera;
        _usingFrontCamera = targetDirection == CameraLensDirection.front;
        _faceState = 'visual';
        _status = _usingFrontCamera ? 'Front camera active.' : 'Back camera active.';
      });
      _cameraTimer = Timer.periodic(const Duration(milliseconds: 1100), (_) => unawaited(_captureAndSendFrame()));
      await _captureAndSendFrame();
    } catch (error) {
      if (nextCamera != null && _camera != nextCamera) {
        try { await nextCamera.dispose(); } catch (_) {}
      }
      if (mounted) setState(() { _camera = null; _status = 'Could not switch camera: $error'; _faceState = 'error'; });
    }
  }

  Future<void> _captureAndSendFrame() async {
    final camera = _camera;
    final live = _live;
    if (_frameCaptureInProgress || camera == null || !camera.value.isInitialized || camera.value.isTakingPicture || live?.isConnected != true) return;
    _frameCaptureInProgress = true;
    try {
      final file = await camera.takePicture();
      final bytes = await file.readAsBytes();
      if (bytes.isNotEmpty && _live?.isConnected == true && _camera == camera) {
        live!.sendRealtimeImage(Uint8List.fromList(bytes), mimeType: 'image/jpeg');
      }
      try { await File(file.path).delete(); } catch (_) { /* cache cleanup is best effort */ }
    } catch (error) {
      if (mounted && _camera == camera) setState(() => _status = 'Camera frame was skipped: $error');
    } finally {
      _frameCaptureInProgress = false;
    }
  }

  Future<void> _stopCamera({bool updateStatus = true}) async {
    _cameraTimer?.cancel();
    _cameraTimer = null;
    final camera = _camera;
    _camera = null;
    if (camera != null) {
      try { await camera.dispose(); } catch (_) { /* already disposed by lifecycle */ }
    }
    if (mounted && updateStatus) {
      setState(() { _faceState = _connected ? 'listening' : 'idle'; _status = _connected ? 'Camera off. I’m listening.' : 'Camera off.'; });
    }
  }

  Future<void> _toggleScreenShare() async {
    _markInteraction();
    if (_screenShareActive) {
      await _stopScreenShare();
      return;
    }
    if (!Platform.isAndroid) {
      setState(() => _status = 'Screen sharing is supported on Android in this build.');
      return;
    }
    if (_live?.isConnected != true) {
      setState(() => _status = 'Connect Ozzy before sharing your screen.');
      return;
    }

    _screenFrameSubscription ??= _screenShareEventChannel.receiveBroadcastStream().listen((event) {
      if (event is Uint8List) {
        final now = DateTime.now();
        final lastSent = _lastScreenShareFrameSentAt;
        // Gemini Live video input is best sent at about one frame per second.
        if (lastSent != null && now.difference(lastSent) < const Duration(milliseconds: 1250)) return;
        _lastScreenShareFrameSentAt = now;
        final live = _live;
        if (_screenShareActive && live?.isConnected == true) {
          live!.sendRealtimeImage(event, mimeType: 'image/jpeg');
        }
      } else if (event is Map && event['type'] == 'stopped') {
        _screenShareActive = false;
        _lastScreenShareFrameSentAt = null;
        if (mounted) setState(() => _status = 'Screen sharing stopped.');
        unawaited(_screenFrameSubscription?.cancel() ?? Future<void>.value());
        _screenFrameSubscription = null;
      } else if (event is Map && event['type'] == 'error') {
        _screenShareActive = false;
        if (mounted) setState(() { _status = 'Screen share error: ${event['message'] ?? 'unknown error'}'; _faceState = 'error'; });
      }
    }, onError: (Object error) {
      _screenShareActive = false;
      if (mounted) setState(() { _status = 'Screen share stream error: $error'; _faceState = 'error'; });
    });

    setState(() { _screenShareActive = true; _lastScreenShareFrameSentAt = null; _status = 'Waiting for Android screen-share permission…'; });
    try {
      final started = await _screenShareMethodChannel.invokeMethod<bool>('startScreenShare');
      if (started != true) {
        _screenShareActive = false;
        await _screenFrameSubscription?.cancel();
        _screenFrameSubscription = null;
        if (mounted) setState(() => _status = 'Screen sharing was not started.');
        return;
      }
      if (mounted) setState(() => _status = 'Screen sharing is active. Anything visible on your shared screen may be sent to Ozzy.');
    } catch (error) {
      _screenShareActive = false;
      await _screenFrameSubscription?.cancel();
      _screenFrameSubscription = null;
      if (mounted) setState(() { _status = 'Could not start screen sharing: $error'; _faceState = 'error'; });
    }
  }

  Future<void> _stopScreenShare({bool updateStatus = true}) async {
    final wasActive = _screenShareActive;
    _screenShareActive = false;
    if (Platform.isAndroid && wasActive) {
      try { await _screenShareMethodChannel.invokeMethod<void>('stopScreenShare'); } catch (_) { /* service may already have stopped */ }
    }
    await _screenFrameSubscription?.cancel();
    _screenFrameSubscription = null;
    _lastScreenShareFrameSentAt = null;
    if (mounted && updateStatus && wasActive) setState(() => _status = 'Screen sharing stopped.');
  }

'''
    source = source[:camera_start] + camera_block + source[camera_end:]

    source = replace_once(
        source,
        '  Future<void> _disconnect() async {\n'
        '    if (!_connected && !_isConnecting && _live == null) return;\n'
        '    if (mounted) setState(() { _connected = false; _isConnecting = false; _faceState = \'idle\'; _status = \'Disconnected. Tap connect when you want to talk.\'; });\n'
        '    _cameraTimer?.cancel();\n',
        '  Future<void> _disconnect() async {\n'
        '    if (!_connected && !_isConnecting && _live == null && !_screenShareActive) return;\n'
        '    if (mounted) setState(() { _connected = false; _isConnecting = false; _faceState = \'idle\'; _status = \'Disconnected. Tap connect when you want to talk.\'; });\n'
        '    await _stopScreenShare(updateStatus: false);\n'
        '    _cameraTimer?.cancel();\n',
        'disconnect screen share cleanup',
    )
    source = replace_once(
        source,
        "                Positioned(right: 8, top: 4, child: IconButton.filledTonal(onPressed: _stopCamera, icon: const Icon(Icons.close_rounded, size: 18))),\n",
        "                Positioned(right: 50, top: 4, child: IconButton.filledTonal(onPressed: _switchCamera, tooltip: 'Switch front/back camera', icon: const Icon(Icons.cameraswitch_rounded, size: 18))),\n"
        "                Positioned(right: 8, top: 4, child: IconButton.filledTonal(onPressed: _stopCamera, tooltip: 'Stop camera', icon: const Icon(Icons.close_rounded, size: 18))),\n",
        'camera preview switch button',
    )
    source = replace_once(
        source,
        "          _actionChip(_cameraActive ? Icons.videocam_off_outlined : Icons.videocam_outlined, _cameraActive ? 'Stop camera' : 'Live camera', _startCamera, active: _cameraActive),\n"
        "          const SizedBox(width: 7),\n"
        "          _actionChip(Icons.image_outlined, 'Choose image', _sendGalleryImage),\n",
        "          _actionChip(_cameraActive ? Icons.videocam_off_outlined : Icons.videocam_outlined, _cameraActive ? 'Stop camera' : 'Live camera', _startCamera, active: _cameraActive),\n"
        "          if (_cameraActive) ...[const SizedBox(width: 7), _actionChip(Icons.cameraswitch_rounded, _usingFrontCamera ? 'Use back cam' : 'Use front cam', _switchCamera)],\n"
        "          const SizedBox(width: 7),\n"
        "          _actionChip(Icons.image_outlined, 'Choose image', _sendGalleryImage),\n"
        "          if (Platform.isAndroid) ...[const SizedBox(width: 7), _actionChip(_screenShareActive ? Icons.stop_screen_share_rounded : Icons.screen_share_rounded, _screenShareActive ? 'Stop share' : 'Share screen', _toggleScreenShare, active: _screenShareActive)],\n",
        'advanced camera and screen share actions',
    )
    source = replace_once(
        source,
        'Connect and talk, or type a message. Camera snapshots and selected images can be discussed too.',
        'Connect and talk, or type a message. Share camera frames, a selected image, or your Android screen after granting permission.',
        'advanced empty-state help',
    )
    DART.write_text(source, encoding='utf-8')

    if not MANIFEST.exists():
        raise SystemExit('Dart was patched, but AndroidManifest.xml was not found. Check that this ZIP was extracted at the Ozzy repository root.')
    manifest = MANIFEST.read_text(encoding='utf-8')
    manifest = replace_once(
        manifest,
        '    <uses-permission android:name="android.permission.CAMERA" />\n',
        '    <uses-permission android:name="android.permission.CAMERA" />\n'
        '    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />\n'
        '    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION" />\n',
        'screen capture permissions',
    )
    manifest = replace_once(
        manifest,
        '    </application>\n',
        '        <service\n'
        '            android:name=".ScreenCaptureService"\n'
        '            android:exported="false"\n'
        '            android:foregroundServiceType="mediaProjection" />\n'
        '    </application>\n',
        'screen capture foreground service declaration',
    )
    MANIFEST.write_text(manifest, encoding='utf-8')

    if README.exists():
        readme = README.read_text(encoding='utf-8')
        old_bullet = '- Live camera preview; compressed camera snapshots are sent to Gemini approximately every 1.1 seconds while you explicitly enable the camera.\n'
        new_bullet = '- Live camera preview with front/back camera switching; compressed camera snapshots are sent to Gemini approximately every 1.1 seconds while enabled.\n- Android screen sharing through the system MediaProjection permission prompt and a visible foreground-service notification. Frames are sent to Gemini at a conservative rate; iOS screen sharing is not included in this patch.\n'
        if old_bullet in readme:
            readme = readme.replace(old_bullet, new_bullet, 1)
        old_limit = 'Mobile supports camera snapshots and images you select. This initial version does **not** capture the entire device screen or share arbitrary other apps; operating systems restrict that capability and it needs a separate native screen-capture workflow. The desktop app retains the desktop screen-share feature.\n'
        new_limit = 'Mobile supports camera snapshots, selected gallery images, and Android screen sharing when the user approves the operating-system prompt. Screen sharing has a persistent Android foreground-service notification and stops when the user selects Stop share in Ozzy or Android ends the projection. iOS screen sharing requires a ReplayKit broadcast extension and is not included.\n'
        if old_limit in readme:
            readme = readme.replace(old_limit, new_limit, 1)
        README.write_text(readme, encoding='utf-8')

    print('Applied Ozzy mobile echo guard, camera switch, and Android screen-share UI changes.')
    print('Next: flutter pub get && flutter analyze && flutter run')


if __name__ == '__main__':
    main()
