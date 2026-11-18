<?php
declare(strict_types=1);

function db(): PDO
{
    $file = getenv('TRESEN_DB');
    if (!$file) {
        $dir = basename(__DIR__);
        $parent = basename(dirname(__DIR__));
        $legacyHosting = $dir === 'kasse' && $parent === 'site-data';
        $siteHosting = $dir === 'data' && is_dir(dirname(__DIR__) . '/public');
        if (!$legacyHosting && !$siteHosting) {
            throw new RuntimeException('TRESEN_DB muss außerhalb des Webverzeichnisses konfiguriert sein.');
        }
        $file = __DIR__ . '/app.sqlite';
    }
    $db = new PDO('sqlite:' . $file, null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
    $db->exec('PRAGMA busy_timeout = 5000; PRAGMA foreign_keys = ON');
    return $db;
}

function query(PDO $db, string $sql, array $params = []): PDOStatement
{
    $stmt = $db->prepare($sql);
    $stmt->execute($params);
    return $stmt;
}

function transaction(PDO $db, callable $action): array
{
    $db->exec('BEGIN IMMEDIATE');
    try {
        $result = $action();
        $db->exec('COMMIT');
        return $result;
    } catch (Throwable $error) {
        $db->exec('ROLLBACK');
        throw $error;
    }
}

function businessDay(): string
{
    return (new DateTimeImmutable('now', new DateTimeZone('Europe/Berlin')))->format('Y-m-d');
}

function displayUsername(string $name): string
{
    $name = trim($name);
    $initial = mb_substr($name, 0, 1, 'UTF-8');
    return mb_convert_case($initial, MB_CASE_TITLE, 'UTF-8') . mb_substr($name, 1, null, 'UTF-8');
}

function account(PDO $db, string $username, string $password, bool $guest): ?array
{
    $scope = $guest ? "role = 'guest'" : "role != 'guest'";
    $row = query($db,
        "SELECT * FROM accounts WHERE username = ? COLLATE NOCASE AND enabled = 1 AND $scope",
        [displayUsername($username)]
    )->fetch(PDO::FETCH_ASSOC);
    if (!$row || !password_verify($password, $row['password_hash'])) {
        return null;
    }
    return $row;
}

function throttle(PDO $db, string $area): void
{
    $window = intdiv(time(), 300);
    $key = $area . ':' . ($_SERVER['REMOTE_ADDR'] ?? 'unknown');
    $attempts = transaction($db, function () use ($db, $key, $window): array {
        query($db, 'DELETE FROM attempts WHERE window < ?', [$window]);
        query($db, 'INSERT INTO attempts VALUES (?, ?, 1)
            ON CONFLICT(client, window) DO UPDATE SET count = count + 1', [$key, $window]);
        return ['count' => query($db, 'SELECT count FROM attempts WHERE client = ? AND window = ?',
            [$key, $window])->fetchColumn()];
    });
    if ((int)$attempts['count'] > 15) {
        throw new DomainException('Zu viele Anmeldeversuche. Bitte warte einige Minuten.', 429);
    }
}

function newAccount(PDO $db, string $name, string $password, string $role, ?int $tab = null): void
{
    $name = displayUsername($name);
    if (strlen($name) < 2 || strlen($name) > 64) {
        throw new DomainException('Benutzername: 2–64 Bytes.');
    }
    $scope = $role === 'guest' ? "role = 'guest'" : "role != 'guest'";
    if (query($db, "SELECT 1 FROM accounts WHERE username = ? COLLATE NOCASE AND $scope", [$name])->fetchColumn()) {
        throw new DomainException('Dieser Benutzername ist in diesem Kontobereich bereits vergeben.');
    }
    query($db, 'INSERT INTO accounts(username, password_hash, role, tab_id) VALUES (?, ?, ?, ?)',
        [$name, accountPasswordHash($password), $role, $tab]);
}

function accountPasswordHash(string $password): string
{
    if (strlen($password) < 8 || strlen($password) > 72 || str_contains($password, "\0")) {
        throw new DomainException('Passwort: 8–72 Bytes.');
    }
    return password_hash($password, PASSWORD_DEFAULT);
}

function rows(PDO $db, string $sql, array $params = []): array
{
    return query($db, $sql, $params)->fetchAll(PDO::FETCH_ASSOC);
}

function tlsRequired(): void
{
    if (empty($_SERVER['HTTPS']) || $_SERVER['HTTPS'] === 'off') {
        if (getenv('TRESEN_LOCAL') !== '1' ||
            !in_array($_SERVER['REMOTE_ADDR'] ?? '', ['127.0.0.1', '::1'], true)) {
            throw new DomainException('HTTPS erforderlich.', 403);
        }
    }
}
