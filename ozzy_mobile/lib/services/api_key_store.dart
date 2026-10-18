import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Stores a user's personal Gemini key in Android Keystore / Apple Keychain.
/// A key stored on a mobile client is still recoverable by a sufficiently
/// determined attacker; use backend-issued ephemeral tokens for public releases.
class ApiKeyStore {
  ApiKeyStore._();
  static final ApiKeyStore instance = ApiKeyStore._();

  static const _storage = FlutterSecureStorage();
  static const _storageKey = 'ozzy.gemini_api_key';

  Future<String?> read() async {
    final key = await _storage.read(key: _storageKey);
    if (key == null || key.trim().isEmpty) return null;
    return key.trim();
  }

  Future<void> save(String apiKey) async {
    final value = apiKey.trim();
    if (value.isEmpty) throw ArgumentError('API key cannot be empty.');
    await _storage.write(key: _storageKey, value: value);
  }

  Future<void> delete() => _storage.delete(key: _storageKey);
}
