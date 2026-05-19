"""
hardware/test_coin_dispenser.py
───────────────────────────────
Manual test for PCA9685 + SG90 coin dispensers.

Channels:
    Ch 0 → ₱1
    Ch 1 → ₱5
    Ch 2 → ₱10
    Ch 3 → ₱20

Wiring:
    PCA9685 VCC → 5V       (Pin 2 or 4)
    PCA9685 GND → GND      (Pin 6)
    PCA9685 SDA → GPIO 2   (Pin 3)
    PCA9685 SCL → GPIO 3   (Pin 5)
    SG90 power  → PCA9685 V+ (external 5V recommended)

Run:
    python hardware/test_coin_dispenser.py
"""

import sys
import traceback
import time

# ── Channel / denomination map ───────────────────────────────────────────────
COIN_CHANNELS = {
    0: 1,
    1: 5,
    2: 10,
    3: 20,
}

PCA9685_ADDRESS = 0x40

# SG90 angles
ANGLE_DISPENSE = 180   # rotate to release coin
ANGLE_NEUTRAL  =   0   # return to rest

# Timing (seconds)
DISPENSE_HOLD  = 0.6   # how long to hold dispense angle
RETURN_HOLD    = 0.4   # how long to hold neutral before next coin


# ── Debug logger ─────────────────────────────────────────────────────────────

class Debug:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"

    @staticmethod
    def info(msg):    print(f"{Debug.CYAN}[INFO]{Debug.RESET}  {msg}")

    @staticmethod
    def ok(msg):      print(f"{Debug.GREEN}[OK]{Debug.RESET}    {msg}")

    @staticmethod
    def warn(msg):    print(f"{Debug.YELLOW}[WARN]{Debug.RESET}  {msg}")

    @staticmethod
    def error(msg):   print(f"{Debug.RED}[ERROR]{Debug.RESET} {msg}")

    @staticmethod
    def step(n, msg): print(f"\n{Debug.BOLD}── Step {n}: {msg}{Debug.RESET}")


# ── PCA9685 setup ─────────────────────────────────────────────────────────────

def init_pca9685():
    Debug.step(1, "Importing adafruit libraries")
    try:
        import board                                        # type: ignore
        import busio                                        # type: ignore
        from adafruit_pca9685 import PCA9685               # type: ignore
        from adafruit_motor import servo as adafruit_servo  # type: ignore
        Debug.ok("Libraries imported.")
    except ImportError as e:
        Debug.error(
            f"Missing library: {e}\n"
            "Run: pip install adafruit-circuitpython-pca9685 "
            "adafruit-circuitpython-motor adafruit-blinka"
        )
        sys.exit(1)

    Debug.step(2, f"Connecting to PCA9685 at I2C address 0x{PCA9685_ADDRESS:02X}")
    try:
        i2c = busio.I2C(board.SCL, board.SDA)              # type: ignore
        pca = PCA9685(i2c, address=PCA9685_ADDRESS)        # type: ignore
        pca.frequency = 50
        Debug.ok("PCA9685 connected. Frequency set to 50 Hz.")
    except Exception:
        Debug.error(
            "Failed to connect to PCA9685.\n"
            "Check:\n"
            "  1. SDA → GPIO 2  (Pin 3)\n"
            "  2. SCL → GPIO 3  (Pin 5)\n"
            "  3. VCC → 5V\n"
            "  4. I2C enabled: sudo raspi-config → Interface Options → I2C\n"
            "  5. Run: i2cdetect -y 1  (should show 0x40)"
        )
        traceback.print_exc()
        sys.exit(1)

    Debug.step(3, "Initializing SG90 servos on channels 0–3")
    try:
        servos = {}
        for ch, denom in COIN_CHANNELS.items():
            servos[denom] = adafruit_servo.Servo(          # type: ignore
                pca.channels[ch],
                min_pulse=500,
                max_pulse=2400,
            )
            Debug.ok(f"  Ch {ch} → ₱{denom} servo ready.")
        return pca, servos
    except Exception:
        Debug.error("Failed to initialize servos.")
        traceback.print_exc()
        sys.exit(1)


# ── Servo actions ─────────────────────────────────────────────────────────────

def dispense_one(servos: dict, denom: int):
    """Rotate servo to dispense angle, hold, return to neutral."""
    if denom not in servos:
        Debug.error(f"No servo for ₱{denom}.")
        return
    Debug.info(f"Dispensing ₱{denom} — rotating to {ANGLE_DISPENSE}°...")
    servos[denom].angle = ANGLE_DISPENSE
    time.sleep(DISPENSE_HOLD)
    Debug.info(f"Returning ₱{denom} to neutral ({ANGLE_NEUTRAL}°)...")
    servos[denom].angle = ANGLE_NEUTRAL
    time.sleep(RETURN_HOLD)
    Debug.ok(f"₱{denom} dispense complete.")


def neutral_all(servos: dict):
    """Return all servos to neutral position."""
    Debug.info("Setting all servos to neutral...")
    for denom, servo in servos.items():
        servo.angle = ANGLE_NEUTRAL
        Debug.ok(f"  ₱{denom} → {ANGLE_NEUTRAL}°")
    time.sleep(0.5)


def cleanup(pca):
    try:
        pca.deinit()
        Debug.info("PCA9685 deinitialized.")
    except Exception:
        pass


# ── Coin breakdown helper ─────────────────────────────────────────────────────

def break_into_coins(amount: float) -> dict:
    """Greedy breakdown of PHP amount into coin counts."""
    coins = {}
    remaining = int(round(amount))
    for denom in sorted(COIN_CHANNELS.values(), reverse=True):
        count = remaining // denom
        if count:
            coins[denom] = count
        remaining %= denom
    return coins


# ── Test sequence ─────────────────────────────────────────────────────────────

def run_tests(pca, servos: dict):
    tests = [
        ("Neutral all servos",           lambda: _t_neutral(servos)),
        ("Dispense ₱1  (Ch 0)",          lambda: _t_single(servos, 1)),
        ("Dispense ₱5  (Ch 1)",          lambda: _t_single(servos, 5)),
        ("Dispense ₱10 (Ch 2)",          lambda: _t_single(servos, 10)),
        ("Dispense ₱20 (Ch 3)",          lambda: _t_single(servos, 20)),
        ("Dispense all in sequence",     lambda: _t_all_sequence(servos)),
        ("Payout ₱37 (20+10+5+1+1)",     lambda: _t_payout(servos, 37)),
    ]

    passed = failed = 0
    for idx, (name, fn) in enumerate(tests, start=1):
        Debug.step(idx + 3, name)
        try:
            fn()
            Debug.ok(f"PASSED: {name}")
            passed += 1
        except Exception:
            Debug.error(f"FAILED: {name}")
            traceback.print_exc()
            failed += 1
        time.sleep(0.5)

    print()
    print("─" * 40)
    print(f"Results:  {passed} passed  {failed} failed")
    print("─" * 40)


def _t_neutral(servos):
    neutral_all(servos)


def _t_single(servos, denom):
    dispense_one(servos, denom)


def _t_all_sequence(servos):
    for denom in sorted(COIN_CHANNELS.values()):
        Debug.info(f"Testing ₱{denom}...")
        dispense_one(servos, denom)
        time.sleep(0.3)


def _t_payout(servos, amount: float):
    coins = break_into_coins(amount)
    total_coins = sum(coins.values())
    Debug.info(f"Payout ₱{amount}: {coins}  ({total_coins} coins total)")
    for denom in sorted(coins.keys(), reverse=True):
        count = coins[denom]
        for i in range(count):
            Debug.info(f"  ₱{denom} coin {i+1}/{count}")
            dispense_one(servos, denom)


# ── Interactive mode ──────────────────────────────────────────────────────────

def interactive(pca, servos: dict):
    print()
    Debug.info(
        "Commands:\n"
        "  1 / 5 / 10 / 20     → dispense one coin of that denomination\n"
        "  all                  → dispense one of each\n"
        "  payout <amount>      → dispense coins for PHP amount (e.g. payout 37)\n"
        "  angle <denom> <deg>  → set servo to custom angle (e.g. angle 10 90)\n"
        "  neutral              → return all to neutral\n"
        "  quit\n"
    )
    while True:
        try:
            raw = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        parts = raw.split()
        cmd   = parts[0] if parts else ""

        if cmd in ("quit", "exit", "q"):
            break
        elif cmd in ("1", "5", "10", "20"):
            dispense_one(servos, int(cmd))
        elif cmd == "all":
            _t_all_sequence(servos)
        elif cmd == "neutral":
            neutral_all(servos)
        elif cmd == "payout" and len(parts) == 2:
            try:
                amount = float(parts[1])
                _t_payout(servos, amount)
            except ValueError:
                Debug.warn("Usage: payout <amount>  e.g. payout 37")
        elif cmd == "angle" and len(parts) == 3:
            try:
                denom = int(parts[1])
                deg   = float(parts[2])
                if denom not in servos:
                    Debug.warn(f"Unknown denomination ₱{denom}. Use 1, 5, 10, or 20.")
                elif not (0 <= deg <= 180):
                    Debug.warn("Angle must be 0–180.")
                else:
                    servos[denom].angle = deg
                    Debug.ok(f"₱{denom} servo → {deg}°")
            except ValueError:
                Debug.warn("Usage: angle <denom> <degrees>  e.g. angle 10 90")
        else:
            Debug.warn(
                f"Unknown command '{raw}'. "
                "Try: 1 / 5 / 10 / 20 / all / payout <amt> / angle <denom> <deg> / neutral / quit"
            )


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 46)
    print("  PCA9685 + SG90 COIN DISPENSER TEST")
    print(f"  I2C addr=0x{PCA9685_ADDRESS:02X}  SDA=GPIO2  SCL=GPIO3")
    print(f"  Ch0=₱1  Ch1=₱5  Ch2=₱10  Ch3=₱20")
    print(f"  Dispense={ANGLE_DISPENSE}°  Neutral={ANGLE_NEUTRAL}°")
    print("=" * 46)

    pca, servos = init_pca9685()

    Debug.step(4, "Setting all servos to neutral")
    neutral_all(servos)

    try:
        mode = input(
            "\nMode:\n"
            "  [1] Automated test sequence\n"
            "  [2] Interactive (manual control)\n"
            "  > "
        ).strip()

        if mode == "1":
            run_tests(pca, servos)
        elif mode == "2":
            interactive(pca, servos)
        else:
            Debug.warn("Invalid — running automated test.")
            run_tests(pca, servos)

    except KeyboardInterrupt:
        print()
        Debug.warn("Interrupted.")
    finally:
        neutral_all(servos)
        cleanup(pca)
        Debug.info("Done.")


if __name__ == "__main__":
    main()