<?php
declare(strict_types=1);
$hostingBackend = __DIR__ . '/../data/bootstrap.php';
require is_file($hostingBackend) ? $hostingBackend : dirname(__DIR__) . '/bootstrap.php';

function h(string|int $text): string
{
    return htmlspecialchars((string)$text, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function euros(int $cents): string
{
    return number_format($cents / 100, 2, ',', '.') . ' €';
}

header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
header('Referrer-Policy: no-referrer');
header("Content-Security-Policy: default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'");
$error = '';
$tab = null;
$entries = [];
$activate = isset($_GET['aktivieren']);

try {
    tlsRequired();
    session_name('tresen_guest');
    session_start([
        'use_strict_mode' => 1,
        'cookie_httponly' => true,
        'cookie_secure' => !empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off',
        'cookie_samesite' => 'Lax',
    ]);
    $_SESSION['csrf'] ??= bin2hex(random_bytes(32));
    $db = db();
    if ($_SERVER['REQUEST_METHOD'] === 'POST') {
        if (!hash_equals($_SESSION['csrf'], (string)($_POST['csrf'] ?? ''))) {
            throw new DomainException('Seite abgelaufen. Bitte erneut laden.', 403);
        }
        if (isset($_POST['logout'])) {
            $_SESSION = [];
            session_regenerate_id(true);
            $_SESSION['csrf'] = bin2hex(random_bytes(32));
        } elseif ($activate) {
            throttle($db, 'guest-activation');
            $username = displayUsername((string)($_POST['username'] ?? ''));
            $code = strtoupper(trim((string)($_POST['code'] ?? '')));
            $password = (string)($_POST['password'] ?? '');
            if ($password !== (string)($_POST['confirmation'] ?? '')) {
                throw new DomainException('Die Passwörter stimmen nicht überein.');
            }
            $guest = transaction($db, function () use ($db, $username, $code, $password): array {
                $invite = query($db, 'SELECT * FROM guest_invites WHERE username = ? AND expires_at > ?',
                    [$username, time()])->fetch(PDO::FETCH_ASSOC);
                if (!$invite) {
                    return ['error' => 'Benutzername oder Freigabecode ist ungültig oder abgelaufen.'];
                }
                if ((int)$invite['failed_attempts'] >= 5) {
                    return ['error' => 'Zu viele falsche Codes. Bitte lass dir einen neuen Code geben.'];
                }
                if (!hash_equals($invite['code_hash'], hash('sha256', $code))) {
                    query($db, 'UPDATE guest_invites SET failed_attempts = failed_attempts + 1 WHERE tab_id = ?',
                        [$invite['tab_id']]);
                    return ['error' => 'Benutzername oder Freigabecode ist ungültig oder abgelaufen.'];
                }
                $tab = (int)$invite['tab_id'];
                query($db, 'DELETE FROM accounts WHERE tab_id = ?', [$tab]);
                newAccount($db, $invite['username'], $password, 'guest', $tab);
                $id = (int)$db->lastInsertId();
                $hash = query($db, 'SELECT password_hash FROM accounts WHERE id = ?', [$id])->fetchColumn();
                query($db, 'DELETE FROM guest_invites WHERE tab_id = ?', [$tab]);
                return ['id' => $id, 'password_hash' => $hash];
            });
            if (isset($guest['error'])) {
                throw new DomainException($guest['error'], 401);
            }
            session_regenerate_id(true);
            $_SESSION['guest'] = (int)$guest['id'];
            $_SESSION['proof'] = hash('sha256', $guest['password_hash']);
            $_SESSION['expires'] = time() + 1800;
        } else {
            throttle($db, 'guest');
            $guest = account($db, (string)($_POST['username'] ?? ''), (string)($_POST['password'] ?? ''), true);
            if (!$guest) {
                throw new DomainException('Anmeldung fehlgeschlagen.', 401);
            }
            session_regenerate_id(true);
            $_SESSION['guest'] = (int)$guest['id'];
            $_SESSION['proof'] = hash('sha256', $guest['password_hash']);
            $_SESSION['expires'] = time() + 1800;
        }
        header('Location: ./', true, 303);
        exit;
    }
    if (!$activate && isset($_SESSION['guest']) && ($_SESSION['expires'] ?? 0) > time()) {
        $tab = query($db, "SELECT b.*, a.password_hash FROM accounts a JOIN tab_balances b ON a.tab_id = b.id
            WHERE a.id = ? AND a.enabled = 1 AND a.role = 'guest'", [$_SESSION['guest']])->fetch(PDO::FETCH_ASSOC);
        if ($tab && hash_equals($_SESSION['proof'], hash('sha256', $tab['password_hash']))) {
            $entries = rows($db, 'SELECT e.id, e.kind, e.cents, e.created_at, e.reversed_id,
                (SELECT GROUP_CONCAT(i.quantity || ? || i.name, ?) FROM items i WHERE i.entry_id = e.id) items
                FROM entries e WHERE e.tab_id = ? ORDER BY e.id DESC', [' × ', ', ', $tab['id']]);
        } else {
            $tab = null;
        }
    }
} catch (DomainException $e) {
    http_response_code($e->getCode() ?: 400);
    $error = $e->getMessage();
} catch (Throwable $e) {
    error_log((string)$e);
    http_response_code(500);
    $error = 'Die Deckelansicht ist vorübergehend nicht erreichbar.';
}
$labels = ['charge' => 'Auf Deckel', 'payment' => 'Barzahlung', 'reversal' => 'Storno'];
?>
<!doctype html>
<html lang="de">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mein Deckel · CashApp</title>
<link rel="stylesheet" href="guest.css">
<main>
<p class="brand">CashApp</p>
<h1>Mein Deckel</h1>
<?php if ($error): ?><p class="error" role="alert"><?= h($error) ?></p><?php endif; ?>
<?php if ($tab): ?>
<section class="balance">
<h2><?= h($tab['name']) ?></h2>
<p>Offener Betrag <strong><?= h(euros((int)$tab['balance'])) ?></strong></p>
</section>
<h2>Buchungen</h2>
<ul>
<?php foreach ($entries as $entry): ?>
<li>
<div><strong><?= h($labels[$entry['kind']] ?? $entry['kind']) ?></strong>
<small><?= h((new DateTimeImmutable($entry['created_at'], new DateTimeZone('UTC')))
    ->setTimezone(new DateTimeZone('Europe/Berlin'))->format('d.m.Y · H:i')) ?> · #<?= h($entry['id']) ?></small>
<?php if ($entry['items']): ?><div><?= h($entry['items']) ?></div><?php endif; ?>
<?php if ($entry['reversed_id']): ?><div>Gegenbuchung zu #<?= h($entry['reversed_id']) ?></div><?php endif; ?>
</div>
<strong><?= h(euros((int)$entry['cents'])) ?></strong>
</li>
<?php endforeach; ?>
</ul>
<form method="post">
<input type="hidden" name="csrf" value="<?= h($_SESSION['csrf']) ?>">
<button name="logout" value="1">Abmelden</button>
</form>
<?php elseif (isset($_SESSION['csrf']) && $activate): ?>
<h2>Konto aktivieren</h2>
<form method="post" action="?aktivieren">
<input type="hidden" name="csrf" value="<?= h($_SESSION['csrf']) ?>">
<label>Benutzername <input name="username" autocomplete="username" maxlength="64" required></label>
<label>Einmalcode <input name="code" autocomplete="one-time-code" maxlength="16" required></label>
<label>Neues Passwort <input name="password" type="password" autocomplete="new-password" minlength="8" maxlength="72" required></label>
<label>Passwort wiederholen <input name="confirmation" type="password" autocomplete="new-password" minlength="8" maxlength="72" required></label>
<button>Konto aktivieren</button>
</form>
<p><a href="./">Zur Anmeldung</a></p>
<?php elseif (isset($_SESSION['csrf'])): ?>
<form method="post">
<input type="hidden" name="csrf" value="<?= h($_SESSION['csrf']) ?>">
<label>Benutzername <input name="username" autocomplete="username" maxlength="64" required></label>
<label>Passwort <input name="password" type="password" autocomplete="current-password" maxlength="72" required></label>
<button>Anmelden</button>
</form>
<p><a href="?aktivieren">Konto zum ersten Mal aktivieren</a></p>
<?php endif; ?>
</main>
</html>
