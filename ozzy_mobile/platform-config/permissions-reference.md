The setup script edits the generated native files for you.

Android `android/app/src/main/AndroidManifest.xml`, before `<application>`:

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-permission android:name="android.permission.CAMERA" />
```

Android minimum SDK: 24 for the selected camera package. iOS `ios/Runner/Info.plist` should include `NSCameraUsageDescription`, `NSMicrophoneUsageDescription`, and `NSPhotoLibraryUsageDescription`.
