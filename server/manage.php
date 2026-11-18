<?php
declare(strict_types=1);
require __DIR__ . '/bootstrap.php';

if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

function migrateAccounts(PDO $db): bool
{
    $db->exec('PRAGMA foreign_keys = OFF');
    try {
        $result = transaction($db, function () use ($db): array {
            $columns = array_column(rows($db, 'PRAGMA table_info(accounts)'), 'name');
            if (!$columns || in_array('deleted_at', $columns, true)) {
                return ['changed' => false];
            }
            $db->exec("CREATE TABLE accounts_migrated (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'staff', 'guest')),
                enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
                tab_id INTEGER UNIQUE REFERENCES tabs(id),
                deleted_at TEXT,
                CHECK((role = 'guest') = (tab_id IS NOT NULL)),
                CHECK(deleted_at IS NULL OR (role != 'guest' AND enabled = 0))
            );
            INSERT INTO accounts_migrated(id, username, password_hash, role, enabled, tab_id)
                SELECT id, username, password_hash, role, enabled, tab_id FROM accounts;
            DROP TABLE accounts;
            ALTER TABLE accounts_migrated RENAME TO accounts;
            CREATE UNIQUE INDEX accounts_staff_username ON accounts(username) WHERE role != 'guest';
            CREATE UNIQUE INDEX accounts_guest_username ON accounts(username) WHERE role = 'guest';");
            if ($db->query('PRAGMA foreign_key_check')->fetch()) {
                throw new RuntimeException('Kontenmigration abgebrochen: Fremdschlüsselprüfung fehlgeschlagen.');
            }
            return ['changed' => true];
        });
        return $result['changed'];
    } finally {
        $db->exec('PRAGMA foreign_keys = ON');
    }
}

function capitalizeUsernames(PDO $db): void
{
    if (!in_array('original_username', array_column(rows($db, 'PRAGMA table_info(accounts)'), 'name'), true)) {
        $db->exec('ALTER TABLE accounts ADD COLUMN original_username TEXT');
    }
    foreach (rows($db, 'SELECT id, username FROM accounts') as $row) {
        $name = displayUsername($row['username']);
        if ($name !== $row['username']) {
            query($db, 'UPDATE accounts SET username = ?, original_username = COALESCE(original_username, ?) WHERE id = ?',
                [$name, $row['username'], $row['id']]);
        }
    }
    foreach (rows($db, 'SELECT tab_id, username FROM guest_invites') as $row) {
        $name = displayUsername($row['username']);
        if ($name !== $row['username']) {
            query($db, 'UPDATE guest_invites SET username = ? WHERE tab_id = ?', [$name, $row['tab_id']]);
        }
    }
    if (query($db, "SELECT 1 FROM guest_invites i JOIN accounts a ON i.username = a.username
        WHERE a.role = 'guest' AND a.tab_id != i.tab_id AND i.expires_at > ?", [time()])->fetchColumn()) {
        throw new RuntimeException('Die Umstellung würde einen Kundennamen zwei Deckeln zuordnen.');
    }
}

try {
    $db = db();
    $command = $argv[1] ?? '';
    if ($command === 'init') {
        $db->exec('PRAGMA journal_mode = WAL');
        migrateAccounts($db);
        transaction($db, function () use ($db, $argv): array {
            $columns = array_column(rows($db, 'PRAGMA table_info(entries)'), 'name');
            if ($columns === ['id', 'message', 'created_at']) {
                if (query($db, "SELECT 1 FROM sqlite_master WHERE name = 'casaos_entries_archive'")->fetchColumn()) {
                    throw new DomainException('Das CasaOS-Archiv existiert bereits. Bitte die Datenbank prüfen.');
                }
                if (query($db, "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'items'")->fetchColumn()) {
                    if (query($db, 'SELECT 1 FROM items LIMIT 1')->fetchColumn()) {
                        throw new DomainException('Die vorhandene Artikeltabelle enthält Daten. Bitte die Datenbank prüfen.');
                    }
                    $db->exec('DROP TABLE items');
                }
                $db->exec('ALTER TABLE entries RENAME TO casaos_entries_archive');
            } elseif ($columns && !in_array('tab_id', $columns, true)) {
                throw new DomainException('Die vorhandene Tabelle entries hat ein unbekanntes Format.');
            }
            $db->exec(file_get_contents(__DIR__ . '/schema.sql'));
            capitalizeUsernames($db);
            if (!query($db, "SELECT 1 FROM accounts WHERE role = 'admin'")->fetchColumn()) {
                newAccount($db, $argv[2] ?? 'Admin', getenv('TRESEN_ADMIN_PASSWORD') ?: '', 'admin');
            }
            return [];
        });
        echo "Datenbank initialisiert.\n";
    } elseif ($command === 'migrate') {
        migrateAccounts($db);
        transaction($db, function () use ($db): array {
            capitalizeUsernames($db);
            return [];
        });
        echo "Kontendatenbank geprüft und aktualisiert.\n";
    } elseif ($command === 'backup' && isset($argv[2])) {
        $path = $argv[2];
        if (file_exists($path)) {
            throw new DomainException('Die Backup-Datei existiert bereits.');
        }
        query($db, 'VACUUM INTO ?', [$path]);
        echo "Backup erstellt.\n";
    } else {
        throw new DomainException('Verwendung: php manage.php init [adminname], migrate oder backup DATEI');
    }
} catch (Throwable $error) {
    fwrite(STDERR, $error->getMessage() . PHP_EOL);
    exit(1);
}
