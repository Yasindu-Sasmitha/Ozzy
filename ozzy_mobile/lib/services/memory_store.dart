import 'package:path/path.dart' as path;
import 'package:sqflite/sqflite.dart';

class OzzyMemory {
  const OzzyMemory({
    required this.id,
    required this.content,
    required this.category,
    required this.createdAt,
  });

  final int id;
  final String content;
  final String category;
  final String createdAt;

  factory OzzyMemory.fromMap(Map<String, Object?> row) => OzzyMemory(
        id: row['id'] as int,
        content: row['content'] as String,
        category: row['category'] as String,
        createdAt: row['created_at'] as String,
      );

  Map<String, Object?> toMap() => {
        'id': id,
        'content': content,
        'category': category,
        'created_at': createdAt,
      };
}

/// On-device memory store. Writes/deletes are only invoked after the UI asks
/// the user to approve the specific operation.
class MemoryStore {
  MemoryStore._();
  static final MemoryStore instance = MemoryStore._();
  Database? _database;

  Future<void> initialize() async {
    if (_database != null) return;
    final dbPath = path.join(await getDatabasesPath(), 'ozzy_mobile_memory.sqlite3');
    _database = await openDatabase(
      dbPath,
      version: 1,
      onCreate: (db, version) async {
        await db.execute('''
          CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL COLLATE NOCASE UNIQUE,
            category TEXT NOT NULL DEFAULT 'fact',
            created_at TEXT NOT NULL
          )
        ''');
        await db.execute('CREATE INDEX memories_created_idx ON memories(created_at DESC)');
      },
    );
  }

  Future<Database> get _db async {
    if (_database == null) await initialize();
    return _database!;
  }

  static String? validateContent(String content) {
    final value = content.trim();
    if (value.length < 3) return 'That memory is too short.';
    if (value.length > 600) return 'Memories must be 600 characters or fewer.';
    final secretPatterns = <RegExp>[
      RegExp(r'(api[_ -]?key|password|passcode|private key|access token)\s*[:=]\s*\S+', caseSensitive: false),
      RegExp(r'\b\d{13,19}\b'),
      RegExp(r'\b\d{3,4}\s*(?:cvv|cvc)\b', caseSensitive: false),
    ];
    if (secretPatterns.any((pattern) => pattern.hasMatch(value))) {
      return 'This looks like a secret or financial credential. Ozzy will not store it.';
    }
    return null;
  }

  Future<Map<String, Object?>> save(String content, {String category = 'fact'}) async {
    final validation = validateContent(content);
    if (validation != null) return {'ok': false, 'message': validation};
    final safeCategory = const {'fact', 'preference', 'project', 'goal', 'reminder'}.contains(category)
        ? category
        : 'fact';
    final db = await _db;
    final existing = await db.query('memories', where: 'content = ?', whereArgs: [content.trim()], limit: 1);
    if (existing.isNotEmpty) {
      return {'ok': true, 'duplicate': true, 'memory': OzzyMemory.fromMap(existing.first).toMap(), 'message': 'That memory already exists.'};
    }
    final now = DateTime.now().toUtc().toIso8601String();
    final id = await db.insert('memories', {
      'content': content.trim(),
      'category': safeCategory,
      'created_at': now,
    }, conflictAlgorithm: ConflictAlgorithm.ignore);
    final rows = await db.query('memories', where: 'id = ?', whereArgs: [id], limit: 1);
    return {'ok': rows.isNotEmpty, 'memory': rows.isEmpty ? null : OzzyMemory.fromMap(rows.first).toMap(), 'message': rows.isEmpty ? 'Memory was not added.' : 'Memory saved on this device.'};
  }

  Future<List<OzzyMemory>> list({int limit = 50}) async {
    final rows = await (await _db).query('memories', orderBy: 'created_at DESC', limit: limit.clamp(1, 100).toInt());
    return rows.map(OzzyMemory.fromMap).toList(growable: false);
  }

  Future<List<OzzyMemory>> search(String query, {int limit = 10}) async {
    final cleaned = query.trim();
    if (cleaned.isEmpty) return list(limit: limit);
    final tokens = cleaned.split(RegExp(r'\s+')).where((token) => token.isNotEmpty).take(6).toList();
    final clauses = tokens.map((_) => '(content LIKE ? OR category LIKE ?)').join(' AND ');
    final args = <Object>[];
    for (final token in tokens) {
      args.add('%$token%');
      args.add('%$token%');
    }
    final rows = await (await _db).query(
      'memories',
      where: clauses,
      whereArgs: args,
      orderBy: 'created_at DESC',
      limit: limit.clamp(1, 100).toInt(),
    );
    return rows.map(OzzyMemory.fromMap).toList(growable: false);
  }

  Future<int> deleteIds(Iterable<int> ids) async {
    final uniqueIds = ids.toSet().toList();
    if (uniqueIds.isEmpty) return 0;
    final placeholders = List.filled(uniqueIds.length, '?').join(',');
    return (await _db).delete('memories', where: 'id IN ($placeholders)', whereArgs: uniqueIds);
  }
}
