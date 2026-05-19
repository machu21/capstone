import sqlite3

DB_NAME = "users.db"


def setup_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role     TEXT NOT NULL DEFAULT 'user'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            material     TEXT PRIMARY KEY,
            price_per_kg REAL NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp    DATETIME DEFAULT CURRENT_TIMESTAMP,
            material     TEXT NOT NULL,
            weight_kg    REAL NOT NULL,
            total_payout REAL NOT NULL,
            synced       INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Default admin account
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            ("admin", "admin123", "admin"),
        )
        cursor.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            ("user", "user123", "user"),
        )

    # Default prices
    cursor.execute("SELECT COUNT(*) FROM prices")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO prices (material, price_per_kg) VALUES (?, ?)", ("PET", 15.00)
        )
        cursor.execute(
            "INSERT INTO prices (material, price_per_kg) VALUES (?, ?)", ("Metal", 20.00)
        )

    conn.commit()
    conn.close()


def verify_login(username, password):
    """Returns the user's role string on success, or None on failure."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role FROM users WHERE username = ? AND password = ?",
        (username, password),
    )
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


def get_price(material):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT price_per_kg FROM prices WHERE material=?", (material,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0.0


def update_prices(pet_price, metal_price):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE prices SET price_per_kg=? WHERE material='PET'", (pet_price,))
    cursor.execute("UPDATE prices SET price_per_kg=? WHERE material='Metal'", (metal_price,))
    conn.commit()
    conn.close()


def log_transaction(material, weight, total_payout):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO transactions (timestamp, material, weight_kg, total_payout, synced)
        VALUES (datetime('now', 'localtime'), ?, ?, ?, 0)
        """,
        (material, weight, total_payout),
    )
    conn.commit()
    conn.close()

    # Trigger background sync immediately after logging
    try:
        import sync_sheets
        sync_sheets.sync_now()
    except Exception:
        pass   # sync is best-effort, never block the transaction


def get_all_transactions():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, timestamp, material, weight_kg, total_payout "
        "FROM transactions ORDER BY id DESC"
    )
    records = cursor.fetchall()
    conn.close()
    return records


def get_sync_pending_count() -> int:
    """Returns number of transactions not yet synced to Google Sheets."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM transactions WHERE synced = 0")
    count = cursor.fetchone()[0]
    conn.close()
    return count