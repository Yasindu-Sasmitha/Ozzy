import 'package:flutter/material.dart';
import '../services/api_key_store.dart';

class ApiKeySettingsScreen extends StatefulWidget {
  const ApiKeySettingsScreen({super.key, this.initialKey});
  final String? initialKey;

  @override
  State<ApiKeySettingsScreen> createState() => _ApiKeySettingsScreenState();
}

class _ApiKeySettingsScreenState extends State<ApiKeySettingsScreen> {
  late final TextEditingController _keyController;
  bool _obscure = true;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _keyController = TextEditingController(text: widget.initialKey ?? '');
  }

  @override
  void dispose() {
    _keyController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final value = _keyController.text.trim();
    if (value.length < 20) {
      setState(() => _error = 'That key looks too short. Check the value copied from AI Studio.');
      return;
    }
    setState(() { _saving = true; _error = null; });
    try {
      await ApiKeyStore.instance.save(value);
      if (mounted) Navigator.pop(context, value);
    } catch (error) {
      if (mounted) setState(() => _error = 'Could not save the key securely: $error');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _delete() async {
    final sure = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF111A24),
        title: const Text('Remove API key?'),
        content: const Text('Ozzy will no longer be able to connect until you enter a key again.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Remove key')),
        ],
      ),
    );
    if (sure != true) return;
    await ApiKeyStore.instance.delete();
    if (mounted) Navigator.pop(context, '');
  }

  @override
  Widget build(BuildContext context) {
    final hasKey = widget.initialKey != null && widget.initialKey!.isNotEmpty;
    return Scaffold(
      backgroundColor: const Color(0xFF070B11),
      appBar: AppBar(
        backgroundColor: const Color(0xFF070B11),
        title: const Text('Ozzy settings'),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
        children: [
          const Icon(Icons.key_rounded, color: Color(0xFF25CFEF), size: 42),
          const SizedBox(height: 12),
          const Text('Gemini API key', style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800), textAlign: TextAlign.center),
          const SizedBox(height: 8),
          Text(hasKey ? 'A key is saved on this device.' : 'Enter your personal Gemini API key to connect Ozzy.', style: const TextStyle(color: Color(0xFF91A4B8)), textAlign: TextAlign.center),
          const SizedBox(height: 24),
          TextField(
            controller: _keyController,
            obscureText: _obscure,
            autocorrect: false,
            enableSuggestions: false,
            textInputAction: TextInputAction.done,
            onSubmitted: (_) => _save(),
            decoration: InputDecoration(
              labelText: 'Gemini API key',
              hintText: 'Paste key from Google AI Studio',
              errorText: _error,
              prefixIcon: const Icon(Icons.password_rounded),
              suffixIcon: IconButton(
                tooltip: _obscure ? 'Show key' : 'Hide key',
                onPressed: () => setState(() => _obscure = !_obscure),
                icon: Icon(_obscure ? Icons.visibility_rounded : Icons.visibility_off_rounded),
              ),
              filled: true,
              fillColor: const Color(0xFF101822),
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(16)),
            ),
          ),
          const SizedBox(height: 14),
          SizedBox(
            height: 52,
            child: FilledButton.icon(
              onPressed: _saving ? null : _save,
              icon: _saving ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.lock_rounded),
              label: Text(_saving ? 'Saving securely…' : 'Save API key securely'),
            ),
          ),
          if (hasKey) ...[
            const SizedBox(height: 10),
            OutlinedButton.icon(
              onPressed: _saving ? null : _delete,
              icon: const Icon(Icons.delete_outline_rounded),
              label: const Text('Remove saved key'),
            ),
          ],
          const SizedBox(height: 24),
          _infoCard(
            icon: Icons.verified_user_outlined,
            title: 'Where is it stored?',
            body: 'Ozzy saves the key using Android Keystore-backed secure storage or Apple Keychain. It is not written into this project or a plain settings file.',
          ),
          const SizedBox(height: 12),
          _infoCard(
            icon: Icons.warning_amber_rounded,
            title: 'Personal-use security note',
            body: 'A key used directly by a mobile app can still be extracted from a compromised device or reverse-engineered app. Use a key restricted to the Gemini API, monitor usage, and do not publish this personal-key build as a public app. A public release should use a backend to mint short-lived ephemeral tokens.',
            warning: true,
          ),
          const SizedBox(height: 18),
          const Text('Get a key at: aistudio.google.com/apikey', style: TextStyle(color: Color(0xFF81DDEF), fontWeight: FontWeight.w700), textAlign: TextAlign.center),
        ],
      ),
    );
  }

  Widget _infoCard({required IconData icon, required String title, required String body, bool warning = false}) {
    final accent = warning ? const Color(0xFFFFC36B) : const Color(0xFF25CFEF);
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: const Color(0xFF101822), borderRadius: BorderRadius.circular(16), border: Border.all(color: accent.withValues(alpha: .25))),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(icon, color: accent),
        const SizedBox(width: 12),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title, style: const TextStyle(fontWeight: FontWeight.w800)), const SizedBox(height: 6), Text(body, style: const TextStyle(color: Color(0xFFA5B4C5), height: 1.45, fontSize: 13))]),),
      ]),
    );
  }
}
