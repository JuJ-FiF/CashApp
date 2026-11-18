<?php
declare(strict_types=1);
$hostingBackend = __DIR__ . '/../data/bootstrap.php';
require is_file($hostingBackend) ? $hostingBackend : dirname(__DIR__) . '/bootstrap.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

const REGISTER_LEASE_SECONDS = 60;

class BookingRejected extends DomainException {}

function requireInt(array $data, string $key, int $min, int $max = 100000000): int
{
    $value = $data[$key] ?? null;
    if (!is_int($value) || $value < $min || $value > $max) {
        throw new DomainException('Ungültiger Wert: ' . $key);
    }
    return $value;
}

function requireText(array $data, string $key): string
{
    $value = $data[$key] ?? null;
    $value = is_string($value) ? trim($value) : '';
    if ($value === '' || strlen($value) > 160) {
        throw new DomainException('Ungültiger Text: ' . $key);
    }
    return $value;
}

function bookingDay(array $input): string
{
    $today = businessDay();
    if (isset($input['booking_time'])) {
        $timestamp = requireInt($input, 'booking_time', 1, PHP_INT_MAX);
        if ($timestamp > time() + 300) {
            throw new DomainException('Die Uhrzeit des Kassengeräts liegt in der Zukunft.');
        }
        return (new DateTimeImmutable('@' . min($timestamp, time())))
            ->setTimezone(new DateTimeZone('Europe/Berlin'))->format('Y-m-d');
    }
    if (!isset($input['booking_day'])) {
        return $today;
    }
    $day = $input['booking_day'];
    $parsed = is_string($day) ? DateTimeImmutable::createFromFormat('!Y-m-d', $day) : false;
    if (!$parsed || $parsed->format('Y-m-d') !== $day || $day > $today) {
        throw new DomainException('Ungültiges Buchungsdatum.');
    }
    return $day;
}

function dailyTotals(PDO $db, string $today): array
{
    return rows($db, "WITH days AS (SELECT ? day UNION SELECT day FROM entries)
        SELECT days.day,
            COALESCE(SUM(CASE WHEN e.kind IN ('sale', 'payment') THEN e.cents
                WHEN original.kind IN ('sale', 'payment') THEN -e.cents ELSE 0 END), 0) cash,
            COALESCE(SUM(CASE WHEN e.kind IN ('sale', 'charge') THEN e.cents
                WHEN original.kind IN ('sale', 'charge') THEN -e.cents ELSE 0 END), 0) sales
        FROM days LEFT JOIN entries e ON e.day = days.day
        LEFT JOIN entries original ON original.id = e.reversed_id
        GROUP BY days.day ORDER BY CAST(days.day AS TEXT) DESC", [$today]);
}

function balance(PDO $db, int $id): int
{
    $value = query($db, 'SELECT balance FROM tab_balances WHERE id = ?
        AND NOT EXISTS (SELECT 1 FROM archived_tabs WHERE tab_id = ?)', [$id, $id])->fetchColumn();
    if ($value === false) {
        throw new DomainException('Deckel nicht gefunden.', 404);
    }
    return (int)$value;
}

function normalizedTabName(string $name): string
{
    return trim(preg_replace('/\s+/u', ' ', $name) ?? '');
}

function availableTabName(PDO $db, string $name, ?int $except = null): string
{
    $name = normalizedTabName($name);
    if ($name === '') {
        throw new DomainException('Gib einen Deckelnamen ein.');
    }
    $pattern = '/\A' . preg_quote($name, '/') . '\z/iu';
    foreach (rows($db, 'SELECT id, name FROM tabs WHERE NOT EXISTS
        (SELECT 1 FROM archived_tabs WHERE tab_id = tabs.id)') as $tab) {
        if ((int)$tab['id'] !== $except && preg_match($pattern, normalizedTabName($tab['name']))) {
            throw new DomainException('Dieser Deckelname ist bereits vergeben. Wähle den vorhandenen Deckel oder einen anderen Namen.', 409);
        }
    }
    return $name;
}

function nextBookingId(PDO $db): int
{
    return (int)$db->query('UPDATE booking_sequence SET last_id = MAX(last_id,
        COALESCE((SELECT MAX(id) FROM entries), 0)) + 1 WHERE slot = 1 RETURNING last_id')->fetchColumn();
}

function deletionRange(PDO $db, array $input): array
{
    $from = requireText($input, 'from_day');
    $to = requireText($input, 'to_day');
    foreach ([$from, $to] as $day) {
        $parsed = preg_match('/^\d{4}-\d{2}-\d{2}$/D', $day)
            ? DateTimeImmutable::createFromFormat('!Y-m-d', $day) : false;
        if (!$parsed || $parsed->format('Y-m-d') !== $day) {
            throw new DomainException('Gib beide Daten im Format JJJJ-MM-TT ein.');
        }
    }
    if ($from > $to || $to > businessDay()) {
        throw new DomainException('Der Zeitraum ist ungültig oder liegt in der Zukunft.');
    }
    if (query($db, 'SELECT 1 FROM entries r JOIN entries e ON e.id = r.reversed_id
        WHERE (r.day BETWEEN ? AND ?) <> (e.day BETWEEN ? AND ?) LIMIT 1', [$from, $to, $from, $to])->fetchColumn()) {
        throw new DomainException('Im Zeitraum liegt eine Buchung mit einem Storno außerhalb des Zeitraums oder umgekehrt. Wähle beide Tage.', 409);
    }
    return [$from, $to];
}

function deleteBookings(PDO $db, array $input, array $staff, bool $delete): array
{
    $single = isset($input['entry_id']);
    if ($single) {
        $id = requireInt($input, 'entry_id', 1, PHP_INT_MAX);
        $entries = rows($db, 'SELECT id, request_id, tab_id, kind, cents, day FROM entries
            WHERE id = ? OR reversed_id = ? OR id = (SELECT reversed_id FROM entries WHERE id = ?) ORDER BY id',
            [$id, $id, $id]);
        if (!$entries) {
            throw new DomainException('Diese Buchung wurde nicht gefunden.', 404);
        }
        $days = array_column($entries, 'day');
        $from = min($days);
        $to = max($days);
        $params = array_column($entries, 'id');
        $where = 'id IN (' . implode(',', array_fill(0, count($params), '?')) . ')';
    } else {
        [$from, $to] = deletionRange($db, $input);
        $where = 'day BETWEEN ? AND ?';
        $params = [$from, $to];
        $entries = rows($db, 'SELECT id, request_id, tab_id, kind FROM entries WHERE ' . $where . ' ORDER BY id', $params);
    }
    $token = hash('sha256', json_encode([$single ? $id : [$from, $to], array_column($entries, 'request_id')], JSON_THROW_ON_ERROR));
    $count = count($entries);
    if (!$delete) {
        return [
            'count' => $count, 'kinds' => array_count_values(array_column($entries, 'kind')), 'token' => $token,
            'bookings' => $single ? array_map(fn(array $entry): array =>
                array_intersect_key($entry, array_flip(['id', 'kind', 'cents', 'day'])), $entries) : [],
        ];
    }
    if (($input['confirmation'] ?? '') !== 'LÖSCHEN' || !$count ||
        !hash_equals($token, requireText($input, 'token'))) {
        throw new DomainException('Bestätigung fehlt oder die Auswahl hat sich geändert. Lade eine neue Vorschau.', 409);
    }

    $db->exec('PRAGMA secure_delete = ON');
    $db->exec('UPDATE booking_sequence SET last_id = MAX(last_id, COALESCE((SELECT MAX(id) FROM entries), 0)) WHERE slot = 1');
    $tombstone = $db->prepare('INSERT INTO deleted_booking_requests(request_hash) VALUES (?)');
    foreach ($entries as $entry) {
        $tombstone->execute([hash('sha256', $entry['request_id'])]);
    }
    query($db, 'DELETE FROM items WHERE entry_id IN (SELECT id FROM entries WHERE ' . $where . ')', $params);
    query($db, 'DELETE FROM entries WHERE ' . $where, $params);
    $tabIds = array_unique(array_filter(array_column($entries, 'tab_id'), fn($id) => $id !== null));
    foreach ($tabIds as $tabId) {
        $tab = query($db, 'SELECT balance, EXISTS(SELECT 1 FROM archived_tabs WHERE tab_id = ?) AS archived
            FROM tab_balances WHERE id = ?', [$tabId, $tabId])->fetch(PDO::FETCH_ASSOC);
        if (!$tab || $tab['balance'] < 0 || ($tab['archived'] && $tab['balance'] != 0)) {
            throw new DomainException('Die Auswahl hinterlässt einen ungültigen Deckelsaldo. Erfasse die zugehörigen Buchungen gemeinsam über die Zeitraum-Auswahl.', 409);
        }
    }
    query($db, 'INSERT INTO booking_deletions(actor, from_day, to_day, entry_count) VALUES (?, ?, ?, ?)',
        [$staff['account_id'], $from, $to, $count]);
    return ['count' => $count];
}

function book(PDO $db, array $input, array $staff, string $kind): array
{
    $request = requireText($input, 'request_id');
    if (query($db, 'SELECT 1 FROM deleted_booking_requests WHERE request_hash = ?', [hash('sha256', $request)])->fetchColumn()) {
        throw new DomainException('Diese Buchung wurde bereits gelöscht und wird nicht erneut gebucht.', 409);
    }
    $existing = query($db, 'SELECT id, kind, cents, received, actor FROM entries WHERE request_id = ?', [$request])
        ->fetch(PDO::FETCH_ASSOC);
    if ($existing) {
        if ((int)$existing['actor'] !== (int)$staff['account_id'] || $existing['kind'] !== $kind) {
            throw new DomainException('Die Buchungskennung wird bereits verwendet.', 409);
        }
        unset($existing['actor']);
        return $existing;
    }

    $day = bookingDay($input);
    $items = [];
    $tab = null;
    $received = null;
    $reversed = null;
    $reason = null;
    if ($kind === 'sale' || $kind === 'charge') {
        $cart = $input['items'] ?? null;
        if (!is_array($cart) || !array_is_list($cart) || !$cart || count($cart) > 200) {
            throw new DomainException('Der Warenkorb ist leer oder zu groß.');
        }
        $cents = 0;
        foreach ($cart as $line) {
            if (!is_array($line)) {
                throw new DomainException('Ungültige Warenkorbposition.');
            }
            $id = requireInt($line, 'id', 1);
            $quantity = requireInt($line, 'quantity', 1, 999);
            $expected = requireInt($line, 'cents', 1, 1000000);
            $p = query($db, 'SELECT * FROM products WHERE id = ? AND enabled = 1', [$id])->fetch(PDO::FETCH_ASSOC);
            if (!$p || (int)$p['cents'] !== $expected || isset($items[$id])) {
                throw new DomainException('Artikel oder Preis geändert. Bitte Warenkorb und Artikel neu laden.', 409);
            }
            $cents += $expected * $quantity;
            $items[$id] = [$p['name'], $expected, $quantity];
        }
        if ($cents > 100000000) {
            throw new DomainException('Der Warenkorb überschreitet den Höchstbetrag.');
        }
        if ($kind === 'sale') {
            $received = requireInt($input, 'received', $cents);
        } else {
            if (isset($input['tab_id'])) {
                $tab = requireInt($input, 'tab_id', 1);
                balance($db, $tab);
            } else {
                query($db, 'INSERT INTO tabs(name) VALUES (?)', [availableTabName($db, requireText($input, 'tab_name'))]);
                $tab = (int)$db->lastInsertId();
            }
        }
    } elseif ($kind === 'payment') {
        $tab = requireInt($input, 'tab_id', 1);
        $cents = requireInt($input, 'cents', 1);
        if ($cents > balance($db, $tab)) {
            throw new DomainException('Die Zahlung übersteigt den offenen Betrag.');
        }
        $received = requireInt($input, 'received', $cents);
    } else {
        if ($staff['role'] !== 'admin') {
            throw new DomainException('Stornos erfordern Adminrechte.', 403);
        }
        $reversed = requireInt($input, 'entry_id', 1);
        $reason = requireText($input, 'reason');
        $original = query($db, "SELECT * FROM entries e WHERE id = ? AND kind != 'reversal'
            AND NOT EXISTS (SELECT 1 FROM entries r WHERE r.reversed_id = e.id)", [$reversed])
            ->fetch(PDO::FETCH_ASSOC);
        if (!$original) {
            throw new DomainException('Buchung nicht gefunden oder bereits storniert.');
        }
        $tab = $original['tab_id'] === null ? null : (int)$original['tab_id'];
        $cents = (int)$original['cents'];
        $tabBalance = $tab === null ? null : balance($db, $tab);
        if ($original['kind'] === 'charge' && $cents > $tabBalance) {
            throw new DomainException('Storno würde den Deckel ins Minus bringen. Prüfe zuerst die Teilzahlungen.');
        }
    }

    $id = nextBookingId($db);
    query($db, 'INSERT INTO entries(id, request_id, kind, cents, received, tab_id, actor, reversed_id, reason, day)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [$id, $request, $kind, $cents, $received, $tab, $staff['account_id'], $reversed, $reason, $day]);
    foreach ($items as $product => [$name, $unit, $quantity]) {
        query($db, 'INSERT INTO items VALUES (?, ?, ?, ?, ?)', [$id, $product, $name, $unit, $quantity]);
    }
    return ['id' => $id, 'cents' => $cents, 'kind' => $kind, 'received' => $received];
}

try {
    tlsRequired();
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        throw new DomainException('POST erforderlich.', 405);
    }
    $input = json_decode(file_get_contents('php://input', false, null, 0, 65537), true, 32);
    if (!is_array($input)) {
        throw new DomainException('Ungültige Anfrage.');
    }
    $db = db();
    $action = $input['action'] ?? '';
    if ($action === 'login') {
        throttle($db, 'staff');
        $result = transaction($db, function () use ($db, $input): array {
            $staff = account($db, (string)($input['username'] ?? ''), (string)($input['password'] ?? ''), false);
            if (!$staff) {
                throw new DomainException('Anmeldung fehlgeschlagen.', 401);
            }
            $now = time();
            $expiry = query($db, 'SELECT expires_at FROM register_session WHERE expires_at > ?', [$now])->fetchColumn();
            if ($expiry !== false) {
                $seconds = (int)$expiry - $now;
                throw new DomainException(
                    "Eine andere Kassensitzung ist aktiv. Melde sie ab oder versuche es in {$seconds} s erneut.", 409
                );
            }
            $token = bin2hex(random_bytes(32));
            query($db, 'REPLACE INTO register_session VALUES (1, ?, ?, ?)',
                [$staff['id'], hash('sha256', $token), $now + REGISTER_LEASE_SECONDS]);
            return [
                'token' => $token,
                'role' => $staff['role'],
                // Keep the existing key for local booking queues and layouts.
                'username' => $staff['original_username'] ?? $staff['username'],
                'display_username' => $staff['username'],
            ];
        });
    } else {
        $result = transaction($db, function () use ($db, $input, $action): array {
            $token = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
            $staff = query($db, 'SELECT s.account_id, a.role FROM register_session s
                JOIN accounts a ON a.id = s.account_id
                WHERE s.token_hash = ? AND s.expires_at > ? AND a.enabled = 1',
                [hash('sha256', substr($token, 7)), time()])->fetch(PDO::FETCH_ASSOC);
            if (!str_starts_with($token, 'Bearer ') || !$staff) {
                throw new DomainException('Kassensitzung abgelaufen. Bitte erneut anmelden.', 401);
            }
            query($db, 'UPDATE register_session SET expires_at = ? WHERE slot = 1', [time() + REGISTER_LEASE_SECONDS]);

            if ($action === 'ping') {
                return ['day' => businessDay()];
            }
            if ($action === 'logout') {
                $db->exec('DELETE FROM register_session');
                return [];
            }
            if ($action === 'complete_onboarding') {
                query($db, 'DELETE FROM pending_staff_onboarding WHERE account_id = ?', [$staff['account_id']]);
                return [];
            }
            if ($action === 'state') {
                $day = businessDay();
                $days = dailyTotals($db, $day);
                $today = array_column($days, null, "day")[$day];
                unset($today['day']);
                $today["outstanding"] = (int)query($db, "SELECT COALESCE(SUM(balance), 0) FROM tab_balances")->fetchColumn();
                return [
                    'onboarding_pending' => (bool)query($db, 'SELECT 1 FROM pending_staff_onboarding WHERE account_id = ?',
                        [$staff['account_id']])->fetchColumn(),
                    'products' => rows($db, 'SELECT p.*, c.category AS personal_category FROM products p
                        LEFT JOIN personal_product_categories c ON c.product_id = p.id AND c.account_id = ?
                        ORDER BY p.category, p.name', [$staff['account_id']]),
                    'product_order' => json_decode(query($db,
                        'SELECT product_ids FROM product_layouts WHERE account_id = ?', [$staff['account_id']]
                    )->fetchColumn() ?: '[]', true, 8, JSON_THROW_ON_ERROR),
                    'tabs' => rows($db, 'SELECT * FROM tab_balances WHERE NOT EXISTS
                        (SELECT 1 FROM archived_tabs WHERE tab_id = tab_balances.id)
                        ORDER BY balance > 0 DESC, name, id'),
                    'day' => $day,
                    'day_open' => true,
                    'totals' => $today,
                    'daily_totals' => $days,
                    'closings' => [],
                    'entries' => rows($db, 'SELECT e.*, a.username, t.name tab_name FROM entries e
                        JOIN accounts a ON a.id = e.actor LEFT JOIN tabs t ON t.id = e.tab_id
                        ORDER BY e.id DESC LIMIT 100'),
                    'booking_deletions' => $staff['role'] === 'admin' ? rows($db, 'SELECT d.from_day, d.to_day,
                        d.entry_count, d.created_at, a.username FROM booking_deletions d
                        JOIN accounts a ON a.id = d.actor ORDER BY d.id DESC LIMIT 10') : [],
                    'staff' => $staff['role'] === 'admin' ? rows($db,
                        "SELECT id, username, role, enabled FROM accounts
                         WHERE role != 'guest' AND deleted_at IS NULL ORDER BY username") : [],
                ];
            }
            if ($action === 'tab_detail') {
                $id = requireInt($input, 'tab_id', 1);
                return ['balance' => balance($db, $id),
                    'guest_username' => $staff['role'] === 'admin' ? (query($db,
                        'SELECT username FROM guest_invites WHERE tab_id = ? UNION ALL
                         SELECT username FROM accounts WHERE tab_id = ? LIMIT 1', [$id, $id])->fetchColumn() ?: null) : null,
                    'entries' => rows($db,
                    'SELECT e.id, e.kind, e.cents, e.created_at, e.reversed_id,
                    (SELECT GROUP_CONCAT(i.quantity || ? || i.name, ?) FROM items i WHERE i.entry_id = e.id) items
                    FROM entries e WHERE e.tab_id = ? ORDER BY e.id DESC', [' × ', ', ', $id])];
            }
            if (in_array($action, ['sale', 'charge', 'payment', 'reversal'], true)) {
                try {
                    return book($db, $input, $staff, $action);
                } catch (DomainException $error) {
                    throw new BookingRejected($error->getMessage(), $error->getCode(), $error);
                }
            }
            if ($action === 'rename_tab') {
                $id = requireInt($input, 'tab_id', 1);
                balance($db, $id);
                $name = availableTabName($db, requireText($input, 'tab_name'), $id);
                query($db, 'UPDATE tabs SET name = ? WHERE id = ?', [$name, $id]);
                return [];
            }
            if ($action === 'save_personal_category') {
                $id = requireInt($input, 'product_id', 1);
                if (!query($db, 'SELECT 1 FROM products WHERE id = ?', [$id])->fetchColumn()) {
                    throw new DomainException('Artikel nicht gefunden.', 404);
                }
                if (!array_key_exists('category', $input)) {
                    throw new DomainException('Kategorie fehlt.');
                }
                if ($input['category'] === null) {
                    query($db, 'DELETE FROM personal_product_categories WHERE account_id = ? AND product_id = ?',
                        [$staff['account_id'], $id]);
                } else {
                    query($db, 'INSERT INTO personal_product_categories(account_id, product_id, category)
                        VALUES (?, ?, ?) ON CONFLICT(account_id, product_id) DO UPDATE SET category = excluded.category',
                        [$staff['account_id'], $id, requireText($input, 'category')]);
                }
                return [];
            }
            if ($action === 'save_product_order') {
                $order = $input['product_ids'] ?? null;
                if (!is_array($order) || !array_is_list($order) || count($order) > 5000) {
                    throw new DomainException('Ungültige Artikelreihenfolge.');
                }
                $available = array_fill_keys($db->query('SELECT id FROM products')->fetchAll(PDO::FETCH_COLUMN), true);
                foreach ($order as $id) {
                    if (!is_int($id) || !isset($available[$id])) {
                        throw new DomainException('Die Artikelreihenfolge enthält doppelte oder unbekannte Artikel.');
                    }
                    unset($available[$id]);
                }
                query($db, 'INSERT INTO product_layouts(account_id, product_ids) VALUES (?, ?)
                    ON CONFLICT(account_id) DO UPDATE SET product_ids = excluded.product_ids',
                    [$staff['account_id'], json_encode($order, JSON_THROW_ON_ERROR)]);
                return [];
            }
            if ($staff['role'] !== 'admin') {
                throw new DomainException('Diese Aktion erfordert Adminrechte.', 403);
            }
            if ($action === 'preview_booking_deletion' || $action === 'delete_bookings') {
                return deleteBookings($db, $input, $staff, $action === 'delete_bookings');
            }
            if ($action === 'save_product') {
                $fields = [requireText($input, 'name'), requireText($input, 'category'),
                    requireInt($input, 'cents', 1, 1000000), requireInt($input, 'enabled', 0, 1)];
                if (isset($input['id'])) {
                    $fields[] = requireInt($input, 'id', 1);
                    query($db, 'UPDATE products SET name = ?, category = ?, cents = ?, enabled = ? WHERE id = ?', $fields);
                } else {
                    query($db, 'INSERT INTO products(name, category, cents, enabled) VALUES (?, ?, ?, ?)', $fields);
                }
            } elseif ($action === 'delete_tab') {
                $id = requireInt($input, 'tab_id', 1);
                $unpaid = balance($db, $id);
                if ($unpaid !== requireInt($input, 'expected_balance', 0, PHP_INT_MAX)) {
                    throw new DomainException('Der offene Betrag hat sich geändert. Öffne den Deckel erneut.', 409);
                }
                // Payments cover the oldest charges first, so cancel the remaining charges newest first.
                if ($unpaid > 0) {
                    $day = businessDay();
                    $charges = rows($db, "SELECT id, cents FROM entries WHERE tab_id = ? AND kind = 'charge'
                        AND NOT EXISTS (SELECT 1 FROM entries AS r WHERE r.reversed_id = entries.id)
                        ORDER BY id DESC", [$id]);
                    foreach ($charges as $charge) {
                        $cents = min($unpaid, (int)$charge['cents']);
                        query($db, "INSERT INTO entries(id, request_id, kind, cents, tab_id, actor, reversed_id, reason, day)
                            VALUES (?, ?, 'reversal', ?, ?, ?, ?, ?, ?)",
                            [nextBookingId($db), 'delete-tab-' . bin2hex(random_bytes(16)), $cents, $id, $staff['account_id'],
                            $charge['id'], 'Offener Betrag beim Löschen des Deckels storniert', $day]);
                        $unpaid -= $cents;
                        if ($unpaid === 0) break;
                    }
                    if ($unpaid !== 0 || balance($db, $id) !== 0) {
                        throw new RuntimeException('Deckelsaldo konnte nicht vollständig storniert werden.');
                    }
                }
                query($db, 'INSERT INTO archived_tabs(tab_id, actor) VALUES (?, ?)', [$id, $staff['account_id']]);
                query($db, 'DELETE FROM guest_invites WHERE tab_id = ?', [$id]);
                query($db, 'DELETE FROM accounts WHERE tab_id = ?', [$id]);
            } elseif ($action === 'invite_guest') {
                $id = requireInt($input, 'tab_id', 1);
                balance($db, $id);
                $name = displayUsername(requireText($input, 'username'));
                if (strlen($name) < 2 || strlen($name) > 64) {
                    throw new DomainException('Benutzername: 2–64 Bytes.');
                }
                query($db, 'DELETE FROM guest_invites WHERE expires_at <= ?', [time()]);
                if (query($db, "SELECT 1 FROM accounts WHERE role = 'guest' AND username = ? AND tab_id != ?
                    UNION ALL SELECT 1 FROM guest_invites WHERE username = ? AND tab_id != ?",
                    [$name, $id, $name, $id])->fetchColumn()) {
                    throw new DomainException('Dieser Kundenname ist bereits einem anderen Deckel zugeordnet.');
                }
                $alphabet = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ';
                $code = '';
                for ($i = 0; $i < 4; $i++) {
                    $code .= $alphabet[random_int(0, strlen($alphabet) - 1)];
                }
                query($db, 'INSERT INTO guest_invites(tab_id, username, code_hash, expires_at) VALUES (?, ?, ?, ?)
                    ON CONFLICT(tab_id) DO UPDATE SET username = excluded.username,
                    code_hash = excluded.code_hash, expires_at = excluded.expires_at, failed_attempts = 0',
                    [$id, $name, hash('sha256', $code), time() + 604800]);
                return ['username' => $name, 'code' => $code];
            } elseif ($action === 'add_staff') {
                $role = $input['role'] ?? 'staff';
                if (!in_array($role, ['admin', 'staff'], true)) {
                    throw new DomainException('Ungültige Rolle.');
                }
                newAccount($db, requireText($input, 'username'), (string)($input['password'] ?? ''), $role);
            } elseif (in_array($action, ['toggle_staff', 'reset_staff_password', 'delete_staff'], true)) {
                $id = requireInt($input, 'id', 1);
                if ($id === (int)$staff['account_id']) {
                    throw new DomainException('Diese Aktion ist nur für andere Personalkonten verfügbar.');
                }
                if (!query($db, "SELECT 1 FROM accounts WHERE id = ? AND role != 'guest' AND deleted_at IS NULL",
                    [$id])->fetchColumn()) {
                    throw new DomainException('Personalkonto nicht gefunden.', 404);
                }
                if ($action === 'toggle_staff') {
                    query($db, 'UPDATE accounts SET enabled = ? WHERE id = ?',
                        [requireInt($input, 'enabled', 0, 1), $id]);
                } elseif ($action === 'reset_staff_password') {
                    $password = accountPasswordHash((string)($input['password'] ?? ''));
                    query($db, 'UPDATE accounts SET password_hash = ? WHERE id = ?', [$password, $id]);
                    query($db, 'DELETE FROM register_session WHERE account_id = ?', [$id]);
                } else {
                    query($db, 'UPDATE accounts SET enabled = 0, deleted_at = CURRENT_TIMESTAMP, password_hash = ? WHERE id = ?',
                        [password_hash(bin2hex(random_bytes(32)), PASSWORD_DEFAULT), $id]);
                    query($db, 'DELETE FROM register_session WHERE account_id = ?', [$id]);
                }
            } else {
                throw new DomainException('Unbekannte Aktion.', 404);
            }
            return [];
        });
    }
    echo json_encode(['ok' => true, 'data' => $result], JSON_THROW_ON_ERROR);
} catch (DomainException $e) {
    http_response_code($e->getCode() ?: 400);
    echo json_encode([
        'ok' => false, 'error' => $e->getMessage(), 'booking_rejected' => $e instanceof BookingRejected,
    ]);
} catch (Throwable $e) {
    error_log((string)$e);
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'Serverfehler. Bitte erneut versuchen.']);
}

