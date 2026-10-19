package com.yasindu.ozzy_mobile

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Build
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    companion object {
        private const val SCREEN_SHARE_METHOD_CHANNEL = "ozzy_mobile/screen_share"
        private const val SCREEN_SHARE_EVENT_CHANNEL = "ozzy_mobile/screen_frames"
        private const val REQUEST_SCREEN_CAPTURE = 7314

        @Volatile
        var screenFrameSink: EventChannel.EventSink? = null
    }

    private var pendingScreenShareResult: MethodChannel.Result? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, SCREEN_SHARE_METHOD_CHANNEL)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "startScreenShare" -> {
                        if (pendingScreenShareResult != null) {
                            result.error("SCREEN_SHARE_PENDING", "A screen-share permission request is already pending.", null)
                            return@setMethodCallHandler
                        }
                        pendingScreenShareResult = result
                        val projectionManager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
                        try {
                            startActivityForResult(projectionManager.createScreenCaptureIntent(), REQUEST_SCREEN_CAPTURE)
                        } catch (error: Exception) {
                            pendingScreenShareResult = null
                            result.error("SCREEN_SHARE_REQUEST_FAILED", error.message, null)
                        }
                    }
                    "stopScreenShare" -> {
                        stopService(Intent(this, ScreenCaptureService::class.java))
                        result.success(true)
                    }
                    else -> result.notImplemented()
                }
            }

        EventChannel(flutterEngine.dartExecutor.binaryMessenger, SCREEN_SHARE_EVENT_CHANNEL)
            .setStreamHandler(object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
                    screenFrameSink = events
                }

                override fun onCancel(arguments: Any?) {
                    screenFrameSink = null
                }
            })
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQUEST_SCREEN_CAPTURE) return

        val result = pendingScreenShareResult
        pendingScreenShareResult = null
        if (resultCode != Activity.RESULT_OK || data == null) {
            result?.success(false)
            return
        }

        val serviceIntent = Intent(this, ScreenCaptureService::class.java).apply {
            action = ScreenCaptureService.ACTION_START
            putExtra(ScreenCaptureService.EXTRA_RESULT_CODE, resultCode)
            putExtra(ScreenCaptureService.EXTRA_RESULT_DATA, data)
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(serviceIntent)
            } else {
                startService(serviceIntent)
            }
            result?.success(true)
        } catch (error: Exception) {
            result?.error("SCREEN_SHARE_START_FAILED", error.message, null)
        }
    }
}
