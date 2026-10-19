package com.yasindu.ozzy_mobile

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Looper
import java.io.ByteArrayOutputStream
import kotlin.math.max

class ScreenCaptureService : Service() {
    companion object {
        const val ACTION_START = "com.yasindu.ozzy_mobile.action.START_SCREEN_SHARE"
        const val EXTRA_RESULT_CODE = "screen_share_result_code"
        const val EXTRA_RESULT_DATA = "screen_share_result_data"
        private const val NOTIFICATION_CHANNEL_ID = "ozzy_screen_share"
        private const val NOTIFICATION_ID = 7315
        private val mainHandler = Handler(Looper.getMainLooper())

        private fun sendEvent(event: Any) {
            mainHandler.post { MainActivity.screenFrameSink?.success(event) }
        }

        private fun sendError(message: String) {
            sendEvent(mapOf("type" to "error", "message" to message))
        }
    }

    private var mediaProjection: MediaProjection? = null
    private var projectionCallback: MediaProjection.Callback? = null
    private var imageReader: ImageReader? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var captureThread: HandlerThread? = null
    private var captureHandler: Handler? = null
    private var lastFrameAtMs = 0L
    private var releasing = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action != ACTION_START) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (mediaProjection != null) return START_NOT_STICKY

        try {
            // Android 14+ requires the service to enter the declared mediaProjection
            // foreground state before getMediaProjection() is called.
            startProjectionForeground()
            val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, -1)
            val resultData: Intent? = if (Build.VERSION.SDK_INT >= 33) {
                intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
            } else {
                @Suppress("DEPRECATION")
                intent.getParcelableExtra(EXTRA_RESULT_DATA)
            }
            if (resultCode == -1 || resultData == null) {
                throw IllegalArgumentException("Screen-share permission data was missing.")
            }

            val manager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            mediaProjection = manager.getMediaProjection(resultCode, resultData)
                ?: throw IllegalStateException("Android did not create a screen projection.")
            startFrameCapture()
        } catch (error: Exception) {
            sendError(error.message ?: "Android could not start screen sharing.")
            stopSelf()
        }
        return START_NOT_STICKY
    }

    private fun startProjectionForeground() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(
                NotificationChannel(NOTIFICATION_CHANNEL_ID, "Ozzy screen sharing", NotificationManager.IMPORTANCE_LOW)
            )
        }
        val notificationBuilder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, NOTIFICATION_CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        val notification = notificationBuilder
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentTitle("Ozzy screen sharing")
            .setContentText("Screen frames may be sent to Ozzy until you stop sharing.")
            .setOngoing(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .build()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun startFrameCapture() {
        val projection = mediaProjection ?: throw IllegalStateException("Screen projection is not available.")
        val metrics = resources.displayMetrics
        val sourceWidth = max(1, metrics.widthPixels)
        val sourceHeight = max(1, metrics.heightPixels)
        val captureWidth = minOf(sourceWidth, 1280)
        val captureHeight = max(1, sourceHeight * captureWidth / sourceWidth)

        captureThread = HandlerThread("OzzyScreenCapture").also { it.start() }
        captureHandler = Handler(captureThread!!.looper)
        imageReader = ImageReader.newInstance(captureWidth, captureHeight, PixelFormat.RGBA_8888, 2)
        projectionCallback = object : MediaProjection.Callback() {
            override fun onStop() {
                if (!releasing) stopSelf()
            }
        }
        projection.registerCallback(projectionCallback!!, captureHandler!!)

        imageReader!!.setOnImageAvailableListener({ reader ->
            val image = try { reader.acquireLatestImage() } catch (_: Exception) { null } ?: return@setOnImageAvailableListener
            try {
                val now = System.currentTimeMillis()
                // Keep the native capture rate low. Dart also applies a 1.25 s throttle
                // before forwarding frames to Gemini Live.
                if (now - lastFrameAtMs < 850L) return@setOnImageAvailableListener
                lastFrameAtMs = now

                val plane = image.planes.firstOrNull() ?: return@setOnImageAvailableListener
                val buffer = plane.buffer
                val pixelStride = plane.pixelStride
                val rowPadding = plane.rowStride - pixelStride * image.width
                val paddedWidth = image.width + rowPadding / pixelStride
                val paddedBitmap = Bitmap.createBitmap(paddedWidth, image.height, Bitmap.Config.ARGB_8888)
                buffer.rewind()
                paddedBitmap.copyPixelsFromBuffer(buffer)
                val cropped = if (paddedWidth == image.width) paddedBitmap else Bitmap.createBitmap(paddedBitmap, 0, 0, image.width, image.height)
                if (cropped !== paddedBitmap) paddedBitmap.recycle()
                val scaled = if (cropped.width > 960) {
                    val scaledHeight = max(1, cropped.height * 960 / cropped.width)
                    Bitmap.createScaledBitmap(cropped, 960, scaledHeight, true).also { if (it !== cropped) cropped.recycle() }
                } else cropped

                val output = ByteArrayOutputStream()
                scaled.compress(Bitmap.CompressFormat.JPEG, 58, output)
                if (scaled !== cropped) scaled.recycle() else cropped.recycle()
                val jpeg = output.toByteArray()
                if (jpeg.isNotEmpty()) sendEvent(jpeg)
            } catch (error: Exception) {
                // A single bad frame should not terminate the user's screen-share session.
                android.util.Log.w("OzzyScreenShare", "Skipping an unreadable screen frame", error)
            } finally {
                image.close()
            }
        }, captureHandler)

        virtualDisplay = projection.createVirtualDisplay(
            "OzzyScreenShare",
            captureWidth,
            captureHeight,
            metrics.densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            imageReader!!.surface,
            null,
            captureHandler
        ) ?: throw IllegalStateException("Android could not create a screen capture display.")
    }

    private fun releaseCapture() {
        releasing = true
        try { imageReader?.setOnImageAvailableListener(null, null) } catch (_: Exception) {}
        try { virtualDisplay?.release() } catch (_: Exception) {}
        virtualDisplay = null
        try { imageReader?.close() } catch (_: Exception) {}
        imageReader = null
        val projection = mediaProjection
        val callback = projectionCallback
        if (projection != null && callback != null) {
            try { projection.unregisterCallback(callback) } catch (_: Exception) {}
        }
        try { projection?.stop() } catch (_: Exception) {}
        mediaProjection = null
        projectionCallback = null
        captureThread?.quitSafely()
        captureThread = null
        captureHandler = null
    }

    override fun onDestroy() {
        releaseCapture()
        sendEvent(mapOf("type" to "stopped"))
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } else {
            @Suppress("DEPRECATION")
            stopForeground(true)
        }
        super.onDestroy()
    }
}
