CREATE TABLE IF NOT EXISTS tabs (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS archived_tabs (
    tab_id INTEGER PRIMARY KEY REFERENCES tabs(id),
    actor INTEGER NOT NULL REFERENCES accounts(id),
    archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'staff', 'guest')),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    tab_id INTEGER UNIQUE REFERENCES tabs(id),
    deleted_at TEXT,
    original_username TEXT,
    CHECK((role = 'guest') = (tab_id IS NOT NULL)),
    CHECK(deleted_at IS NULL OR (role != 'guest' AND enabled = 0))
);

CREATE UNIQUE INDEX IF NOT EXISTS accounts_staff_username ON accounts(username) WHERE role != 'guest';
CREATE UNIQUE INDEX IF NOT EXISTS accounts_guest_username ON accounts(username) WHERE role = 'guest';

CREATE TABLE IF NOT EXISTS pending_staff_onboarding (
    account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE TRIGGER IF NOT EXISTS mark_new_staff_onboarding
AFTER INSERT ON accounts WHEN NEW.role IN ('admin', 'staff')
BEGIN
    INSERT INTO pending_staff_onboarding(account_id) VALUES (NEW.id);
END;

CREATE TABLE IF NOT EXISTS guest_invites (
    tab_id INTEGER PRIMARY KEY REFERENCES tabs(id) ON DELETE CASCADE,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    code_hash TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS register_session (
    slot INTEGER PRIMARY KEY CHECK(slot = 1),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    token_hash TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    cents INTEGER NOT NULL CHECK(cents BETWEEN 1 AND 1000000),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1))
);

CREATE TABLE IF NOT EXISTS product_layouts (
    account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    product_ids TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS personal_product_categories (
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    PRIMARY KEY (account_id, product_id)
);

CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK(kind IN ('sale', 'charge', 'payment', 'reversal')),
    cents INTEGER NOT NULL CHECK(cents > 0),
    received INTEGER,
    tab_id INTEGER REFERENCES tabs(id),
    actor INTEGER NOT NULL REFERENCES accounts(id),
    reversed_id INTEGER UNIQUE REFERENCES entries(id),
    reason TEXT,
    day TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS items (
    entry_id INTEGER NOT NULL REFERENCES entries(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    name TEXT NOT NULL,
    unit_cents INTEGER NOT NULL,
    quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 999),
    PRIMARY KEY(entry_id, product_id)
);

CREATE INDEX IF NOT EXISTS entries_tab ON entries(tab_id, id);
CREATE INDEX IF NOT EXISTS entries_day ON entries(day, id);

CREATE TABLE IF NOT EXISTS attempts (
    client TEXT NOT NULL,
    window INTEGER NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY(client, window)
);

CREATE TABLE IF NOT EXISTS booking_deletions (
    id INTEGER PRIMARY KEY,
    actor INTEGER NOT NULL REFERENCES accounts(id),
    from_day TEXT NOT NULL,
    to_day TEXT NOT NULL,
    entry_count INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS deleted_booking_requests (
    request_hash TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS booking_sequence (
    slot INTEGER PRIMARY KEY CHECK(slot = 1),
    last_id INTEGER NOT NULL
);

INSERT OR IGNORE INTO booking_sequence(slot, last_id) SELECT 1, COALESCE(MAX(id), 0) FROM entries;

CREATE VIEW IF NOT EXISTS tab_balances AS
    SELECT t.*, COALESCE(SUM(CASE
        WHEN e.kind = 'charge' OR original.kind = 'payment' THEN e.cents
        WHEN e.kind = 'payment' OR original.kind = 'charge' THEN -e.cents
        ELSE 0 END), 0) balance
    FROM tabs t LEFT JOIN entries e ON e.tab_id = t.id
    LEFT JOIN entries original ON original.id = e.reversed_id
    GROUP BY t.id;
