"""
sync_sheets.py
──────────────
Background Google Sheets sync for RTL Junkshop.

- Runs in a daemon thread — never blocks the UI
- Syncs unsynced transactions whenever WiFi is available
- Retries failed syncs automatically
- Called after every log_transaction()

Usage:
    import sync_sheets
    sync_sheets.start()          # call once at app startup
    sync_sheets.sync_now()       # call after each transaction
"""

import sqlite3
import threading
import urllib.request
import urllib.error
import json
import time
import logging

# ── Config ────────────────────────────────────────────────────────────────────
DB_NAME     = "users.db"
SHEETS_URL  = (
    "https://script.google.com/macros/s/"
    "AKfycbyY7RbV7xLkMVSLRE7glOu9A5cjmtKnoCyQwTMK2kx2bku8WB_gEZmYNjUxvV8Yg513Zw"
    "/exec"
)
RETRY_INTERVAL_S  = 30    # retry every 30s if WiFi unavailable
WIFI_CHECK_HOST   = "8.8.8.8"
WIFI_CHECK_PORT   = 53
WIFI_TIMEOUT_S    = 3
REQUEST_TIMEOUT_S = 10

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SYNC] %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sync_sheets")

# ── Internal state ────────────────────────────────────────────────────────────
_sync_event  = threading.Event()   # signal background thread to sync now
_started     = False
_lock        = threading.Lock()


# ── Database helpers ──────────────────────────────────────────────────────────

def _ensure_synced_column():
    """Add 'synced' column to transactions if it doesn't exist."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE transactions ADD COLUMN synced INTEGER DEFAULT 0")
        conn.commit()
        log.info("Added 'synced' column to transactions table.")
    except sqlite3.OperationalError:
        pass   # column already exists
    conn.close()


def _get_unsynced() -> list[dict]:
    """Return all transactions that haven't been synced yet."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, timestamp, material, weight_kg, total_payout
        FROM transactions
        WHERE synced = 0
        ORDER BY id ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [
        {
            "id":       row[0],
            "date":     row[1],
            "material": row[2],
            "weight":   row[3],
            "payout":   row[4],
            "status":   "active",
        }
        for row in rows
    ]


def _mark_synced(ids: list[int]):
    """Mark a list of transaction IDs as synced."""
    if not ids:
        return
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.executemany(
        "UPDATE transactions SET synced = 1 WHERE id = ?",
        [(i,) for i in ids]
    )
    conn.commit()
    conn.close()


# ── Network helpers ───────────────────────────────────────────────────────────

def _has_wifi() -> bool:
    """Quick check — can we reach Google's DNS?"""
    import socket
    try:
        socket.setdefaulttimeout(WIFI_TIMEOUT_S)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
            (WIFI_CHECK_HOST, WIFI_CHECK_PORT)
        )
        return True
    except OSError:
        return False


def _post_to_sheets(records: list[dict]) -> bool:
    """
    POST records to Google Sheets web app.
    Returns True on success.
    """
    payload = json.dumps(records).encode("utf-8")
    req = urllib.request.Request(
        SHEETS_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            body = resp.read().decode("utf-8").strip()
            if "Success" in body:
                return True
            else:
                log.warning(f"Sheets returned unexpected response: {body}")
                return False
    except urllib.error.HTTPError as e:
        log.error(f"HTTP {e.code}: {e.reason}")
        return False
    except urllib.error.URLError as e:
        log.error(f"URL error: {e.reason}")
        return False
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        return False


# ── Core sync logic ───────────────────────────────────────────────────────────

def _do_sync():
    """Attempt to sync all unsynced records. Returns number synced."""
    records = _get_unsynced()
    if not records:
        log.info("Nothing to sync.")
        return 0

    if not _has_wifi():
        log.warning(f"{len(records)} record(s) pending — no WiFi. Will retry.")
        return 0

    log.info(f"WiFi available. Syncing {len(records)} record(s)...")

    # Send in batches of 50 to avoid request size limits
    batch_size = 50
    total_synced = 0

    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        if _post_to_sheets(batch):
            ids = [r["id"] for r in batch]
            _mark_synced(ids)
            total_synced += len(batch)
            log.info(f"Synced batch of {len(batch)} — IDs {ids[0]}–{ids[-1]}")
        else:
            log.error(f"Batch failed (IDs {batch[0]['id']}–{batch[-1]['id']}). Will retry.")
            break   # stop on first failed batch; retry next cycle

    return total_synced


# ── Background thread ─────────────────────────────────────────────────────────

def _background_worker():
    """
    Daemon thread — waits for sync_now() signal or periodic retry interval.
    """
    log.info("Sync worker started.")
    while True:
        # Wait for signal or timeout
        triggered = _sync_event.wait(timeout=RETRY_INTERVAL_S)
        _sync_event.clear()

        if triggered:
            log.info("Sync triggered by new transaction.")
        else:
            log.info("Periodic retry check.")

        try:
            _do_sync()
        except Exception as e:
            log.error(f"Sync error: {e}")


# ── Public API ────────────────────────────────────────────────────────────────

def start():
    """
    Start the background sync worker.
    Call once at app startup (in main.py after setup_database()).
    """
    global _started
    with _lock:
        if _started:
            return
        _ensure_synced_column()
        t = threading.Thread(target=_background_worker, daemon=True, name="SheetsSync")
        t.start()
        _started = True
        log.info("Sync service started.")


def sync_now():
    """
    Signal the background worker to sync immediately.
    Call after every log_transaction().
    """
    _sync_event.set()


def sync_status() -> dict:
    """
    Returns current sync status — useful for displaying in UI.
    {pending: int, has_wifi: bool}
    """
    records = _get_unsynced()
    return {
        "pending":  len(records),
        "has_wifi": _has_wifi(),
    }