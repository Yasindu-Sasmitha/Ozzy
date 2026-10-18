import 'package:flutter_test/flutter_test.dart';
import 'package:ozzy_mobile/services/memory_store.dart';

void main() {
  group('MemoryStore.validateContent', () {
    test('allows an ordinary project memory', () {
      expect(MemoryStore.validateContent('I am building the Ozzy robot companion.'), isNull);
    });

    test('rejects obvious API key assignments', () {
      expect(MemoryStore.validateContent('api_key: abcdefghijklmnopqrstuvwxyz123456'), isNotNull);
    });

    test('rejects long digit-only payment-like strings', () {
      expect(MemoryStore.validateContent('Card number 4242424242424242'), isNotNull);
    });

    test('rejects empty and too-long memories', () {
      expect(MemoryStore.validateContent('  '), isNotNull);
      expect(MemoryStore.validateContent('x' * 601), isNotNull);
    });
  });
}
