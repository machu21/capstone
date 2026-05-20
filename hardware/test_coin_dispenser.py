"""
hardware/test_coin_dispenser.py
───────────────────────────────
Manual test for SG90 coin dispensers via PCA9685 channels 0-3.

Channel assignments:
    Ch 0 → ₱1
    Ch 1 → ₱5
    Ch 2 → ₱10
    Ch 3 → ₱20

Wiring:
    PCA9685 SDA  → GPIO 2 (Pin 3) via level shifter
    PCA9685 SCL  → GPIO 3 (Pin 5) via level shifter
    PCA9685 VCC  → Pi 5V
    PCA9685 V+   → External 6V (servo power)
    PCA9685 GND  → Pi GND + External GND

Run:
    python hardware/test_coin_dispenser.py
"""

import sys
import traceback
import time
import os

os.environ["BLINKA_FORCEBOARD"] = "RASPBERRY_PI_5"

# ── PCA9685 config ────────────────────────────────────────────────────────────
PCA9685_ADDRESS = 0x40
FREQ_HZ         = 50

COIN_CHANNELS = {
    1:  0,
    5:  1,
    10: 2,
    20: 3,
}

# SG90 pulse widths (us)
PW_NEUTRAL  =  500   # 0°   rest
PW_DISPENSE = 2500   # 180° dispense

# Timing (seconds)
DISPENSE_HOLD = 0.6
RETURN_HOLD   = 0.4


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

def _us_to_duty(us: int) -> int:
    period_us  = 1_000_000 / FREQ_HZ
    duty_12bit = int((us / period_us) * 4096)
    return duty_12bit << 4   # 12-bit → 16-bit


def init_pca9685():
    Debug.step(1, "Importing adafruit libraries")
    try:
        import board                          # type: ignore
        import busio                          # type: ignore
        from adafruit_pca9685 import PCA9685  # type: ignore
        Debug.ok("Libraries imported.")
    except ImportError as e:
        Debug.error(
            f"Missing: {e}\n"
            "Run: pip install adafruit-circuitpython-pca9685 adafruit-blinka"
        )
        sys.exit(1)

    Debug.step(2, f"Connecting PCA9685 at 0x{PCA9685_ADDRESS:02X}")
    try:
        import board, busio                   # type: ignore
        from adafruit_pca9685 import PCA9685  # type: ignore
        i2c = busio.I2C(board.SCL, board.SDA)
        pca = PCA9685(i2c, address=PCA9685_ADDRESS)
        pca.frequency = FREQ_HZ
        Debug.ok(f"PCA9685 ready. Frequency={FREQ_HZ}Hz.")
        return pca
    except Exception:
        Debug.error(
            "Failed to connect PCA9685.\n"
            "Check: i2cdetect -y 1  (should show 0x40)"
        )
        traceback.print_exc()
        sys.exit(1)


def set_pulse(pca, channel: int, us: int):
    pca.channels[channel].duty_cycle = _us_to_duty(us)


def stop_channel(pca, channel: int):
    pca.channels[channel].duty_cycle = 0


def cleanup(pca):
    for ch in COIN_CHANNELS.values():
        stop_channel(pca, ch)
    pca.deinit()
    Debug.info("PCA9685 deinitialized.")


# ── Servo actions ─────────────────────────────────────────────────────────────

def neutral_all(pca):
    Debug.info("Setting all coin servos to neutral...")
    for denom, ch in COIN_CHANNELS.items():
        set_pulse(pca, ch, PW_NEUTRAL)
        Debug.ok(f"  ₱{denom} (Ch {ch}) → neutral ({PW_NEUTRAL}us)")
    time.sleep(0.5)


def dispense_one(pca, denom: int):
    ch = COIN_CHANNELS.get(denom)
    if ch is None:
        Debug.error(f"No channel for ₱{denom}.")
        return
    Debug.info(f"Dispensing ₱{denom} (Ch {ch}) → {PW_DISPENSE}us...")
    set_pulse(pca, ch, PW_DISPENSE)
    time.sleep(DISPENSE_HOLD)
    Debug.info(f"Returning ₱{denom} → neutral...")
    set_pulse(pca, ch, PW_NEUTRAL)
    time.sleep(RETURN_HOLD)
    Debug.ok(f"₱{denom} done.")


def stop_all(pca):
    for ch in COIN_CHANNELS.values():
        stop_channel(pca, ch)
    Debug.ok("All PWM signals cut.")


# ── Coin breakdown ────────────────────────────────────────────────────────────

def break_into_coins(amount: float) -> dict:
    coins = {}
    remaining = int(round(amount))
    for denom in sorted(COIN_CHANNELS.keys(), reverse=True):
        count = remaining // denom
        if count:
            coins[denom] = count
        remaining %= denom
    return coins


# ── Test sequence ─────────────────────────────────────────────────────────────

def run_tests(pca):
    tests = [
        ("Neutral all",          lambda: neutral_all(pca)),
        ("Dispense ₱1  (Ch 0)",  lambda: dispense_one(pca, 1)),
        ("Dispense ₱5  (Ch 1)",  lambda: dispense_one(pca, 5)),
        ("Dispense ₱10 (Ch 2)",  lambda: dispense_one(pca, 10)),
        ("Dispense ₱20 (Ch 3)",  lambda: dispense_one(pca, 20)),
        ("All in sequence",      lambda: _t_all(pca)),
        ("Payout ₱37",           lambda: _t_payout(pca, 37)),
    ]

    passed = failed = 0
    for idx, (name, fn) in enumerate(tests, start=1):
        Debug.step(idx + 2, name)
        try:
            fn()
            Debug.ok(f"PASSED: {name}")
            passed += 1
        except Exception:
            Debug.error(f"FAILED: {name}")
            traceback.print_exc()
            failed += 1
        time.sleep(0.3)

    print()
    print("─" * 40)
    print(f"Results:  {passed} passed  {failed} failed")
    print("─" * 40)


def _t_all(pca):
    for denom in sorted(COIN_CHANNELS.keys()):
        dispense_one(pca, denom)
        time.sleep(0.2)


def _t_payout(pca, amount: float):
    coins = break_into_coins(amount)
    total = sum(coins.values())
    Debug.info(f"Payout ₱{amount}: {coins}  ({total} coins)")
    for denom in sorted(coins.keys(), reverse=True):
        for i in range(coins[denom]):
            Debug.info(f"  ₱{denom} coin {i+1}/{coins[denom]}")
            dispense_one(pca, denom)


# ── Interactive mode ──────────────────────────────────────────────────────────

def interactive(pca):
    print()
    Debug.info(
        "Commands:\n"
        "  1 / 5 / 10 / 20     → dispense one coin\n"
        "  all                  → one of each\n"
        "  payout <amount>      → e.g. payout 37\n"
        "  neutral              → all to neutral\n"
        "  stop                 → cut all PWM\n"
        "  pulse <denom> <us>   → custom pulse e.g. pulse 10 1500\n"
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
            dispense_one(pca, int(cmd))
        elif cmd == "all":
            _t_all(pca)
        elif cmd == "neutral":
            neutral_all(pca)
        elif cmd == "stop":
            stop_all(pca)
        elif cmd == "payout" and len(parts) == 2:
            try:
                _t_payout(pca, float(parts[1]))
            except ValueError:
                Debug.warn("Usage: payout <amount>  e.g. payout 37")
        elif cmd == "pulse" and len(parts) == 3:
            try:
                denom = int(parts[1])
                us    = int(parts[2])
                ch    = COIN_CHANNELS.get(denom)
                if ch is None:
                    Debug.warn(f"Unknown denomination ₱{denom}.")
                elif not (400 <= us <= 2600):
                    Debug.warn("Pulse must be 400–2600us.")
                else:
                    set_pulse(pca, ch, us)
                    Debug.ok(f"₱{denom} Ch {ch} → {us}us")
            except ValueError:
                Debug.warn("Usage: pulse <denom> <us>  e.g. pulse 10 2500")
        else:
            Debug.warn(f"Unknown: '{raw}'")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 50)
    print("  SG90 COIN DISPENSER TEST  (PCA9685 Ch 0-3)")
    print(f"  Addr=0x{PCA9685_ADDRESS:02X}  Ch0=₱1  Ch1=₱5  Ch2=₱10  Ch3=₱20")
    print(f"  Neutral={PW_NEUTRAL}us  Dispense={PW_DISPENSE}us")
    print("=" * 50)

    pca = init_pca9685()

    Debug.step(3, "Setting all coin servos to neutral")
    neutral_all(pca)

    try:
        mode = input(
            "\nMode:\n"
            "  [1] Automated test\n"
            "  [2] Interactive\n"
            "  > "
        ).strip()

        if mode == "1":
            run_tests(pca)
        elif mode == "2":
            interactive(pca)
        else:
            Debug.warn("Invalid — running automated test.")
            run_tests(pca)

    except KeyboardInterrupt:
        print()
        Debug.warn("Interrupted.")
    finally:
        neutral_all(pca)
        time.sleep(0.3)
        cleanup(pca)
        Debug.info("Done.")


if __name__ == "__main__":
    main()