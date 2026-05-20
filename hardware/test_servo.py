"""
hardware/test_servo.py
──────────────────────
Manual test for the MG996R sorter servo via PCA9685 channel 4.

Positions:
    Neutral   → 1500us (pointing forward)
    Reject    →  900us (left,  -60°)
    Qualified → 2100us (right, +60°)

Wiring:
    PCA9685 Ch 4 → MG996R Signal
    PCA9685 V+   → External 6V
    PCA9685 GND  → External GND + Pi GND
    PCA9685 SDA  → GPIO 2 (Pin 3)
    PCA9685 SCL  → GPIO 3 (Pin 5)

Run:
    python hardware/test_servo.py
"""

import sys
import traceback
import time
import os

os.environ["BLINKA_FORCEBOARD"] = "RASPBERRY_PI_5"

# ── PCA9685 config ────────────────────────────────────────────────────────────
PCA9685_ADDRESS = 0x40
SERVO_CHANNEL   = 4
FREQ_HZ         = 50

# Pulse widths in microseconds
PW_NEUTRAL   = 1500
PW_REJECT    =  900
PW_QUALIFIED = 2100

MOVE_DELAY = 0.5


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
    """Convert pulse width in microseconds to PCA9685 16-bit duty cycle."""
    period_us    = 1_000_000 / FREQ_HZ
    duty_12bit   = int((us / period_us) * 4096)
    return duty_12bit << 4   # 12-bit → 16-bit


def init_servo():
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

    Debug.step(2, f"Connecting PCA9685 at 0x{PCA9685_ADDRESS:02X}  Ch={SERVO_CHANNEL}")
    try:
        import board, busio                          # type: ignore
        from adafruit_pca9685 import PCA9685         # type: ignore
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


def set_pulse(pca, us: int):
    pca.channels[SERVO_CHANNEL].duty_cycle = _us_to_duty(us)


def stop_pulse(pca):
    pca.channels[SERVO_CHANNEL].duty_cycle = 0


def cleanup(pca):
    set_pulse(pca, PW_NEUTRAL)
    time.sleep(0.3)
    stop_pulse(pca)
    pca.deinit()
    Debug.info("PCA9685 deinitialized.")


# ── Servo actions ─────────────────────────────────────────────────────────────

def go_neutral(pca):
    set_pulse(pca, PW_NEUTRAL)
    Debug.ok(f"NEUTRAL   → {PW_NEUTRAL}us  (forward)")
    time.sleep(MOVE_DELAY)
    

def go_reject(pca):
    set_pulse(pca, PW_REJECT)
    Debug.ok(f"REJECT    → {PW_REJECT}us  (left)")
    time.sleep(MOVE_DELAY)
    

def go_qualified(pca):
    set_pulse(pca, PW_QUALIFIED)
    Debug.ok(f"QUALIFIED → {PW_QUALIFIED}us  (right)")
    time.sleep(MOVE_DELAY)
    

def go_stop(pca):
    stop_pulse(pca)
    Debug.ok("STOP — PWM signal cut.")

def go_pulse(pca, us: int):
    set_pulse(pca, us)
    Debug.ok(f"CUSTOM    → {us}us")
    time.sleep(MOVE_DELAY)


# ── Test sequence ─────────────────────────────────────────────────────────────

def run_tests(pca):
    tests = [
        ("Move to NEUTRAL",                          lambda: _t_neutral(pca)),
        ("Move to REJECT  (left)",                   lambda: _t_reject(pca)),
        ("Return to NEUTRAL",                        lambda: _t_neutral(pca)),
        ("Move to QUALIFIED (right)",                lambda: _t_qualified(pca)),
        ("Return to NEUTRAL",                        lambda: _t_neutral(pca)),
        ("Full sweep: reject → neutral → qualified", lambda: _t_sweep(pca)),
        ("Rapid toggle x3",                          lambda: _t_rapid(pca, cycles=3)),
        ("Stop PWM at neutral",                      lambda: _t_stop(pca)),
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
        time.sleep(0.2)

    print()
    print("─" * 40)
    print(f"Results:  {passed} passed  {failed} failed")
    print("─" * 40)


def _t_neutral(pca):
    go_neutral(pca)
    time.sleep(1.0)

def _t_reject(pca):
    go_reject(pca)
    time.sleep(1.5)

def _t_qualified(pca):
    go_qualified(pca)
    time.sleep(1.5)

def _t_sweep(pca):
    go_reject(pca);    time.sleep(1.5)
    go_neutral(pca);   time.sleep(1.0)
    go_qualified(pca); time.sleep(1.5)
    go_neutral(pca);   time.sleep(1.0)

def _t_rapid(pca, cycles: int):
    for i in range(cycles):
        Debug.info(f"Cycle {i+1}/{cycles}")
        go_reject(pca);    time.sleep(0.8)
        go_qualified(pca); time.sleep(0.8)
    go_neutral(pca)

def _t_stop(pca):
    go_neutral(pca)
    time.sleep(0.5)
    go_stop(pca)


# ── Interactive mode ──────────────────────────────────────────────────────────

def interactive(pca):
    print()
    Debug.info(
        "Commands:\n"
        "  neutral / n      → forward\n"
        "  reject  / r      → left\n"
        "  qualify / q      → right\n"
        "  stop    / s      → cut PWM\n"
        "  sweep            → full sweep\n"
        "  pulse <us>       → custom e.g. pulse 1200\n"
        "  scan             → step 800–2200us to find exact positions\n"
        "  quit\n"
    )
    while True:
        try:
            raw = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        parts = raw.split()
        cmd   = parts[0] if parts else ""

        if cmd in ("quit", "exit") or (cmd == "q" and len(parts) == 1):
            break
        elif cmd in ("neutral", "n"):
            go_neutral(pca)
        elif cmd in ("reject", "r"):
            go_reject(pca)
        elif cmd in ("qualify", "qualified"):
            go_qualified(pca)
        elif cmd in ("stop", "s"):
            go_stop(pca)
        elif cmd == "sweep":
            _t_sweep(pca)
        elif cmd == "pulse" and len(parts) == 2:
            try:
                us = int(parts[1])
                if 400 <= us <= 2600:
                    go_pulse(pca, us)
                else:
                    Debug.warn("Pulse must be 400–2600us.")
            except ValueError:
                Debug.warn("Usage: pulse <us>  e.g. pulse 1500")
        elif cmd == "scan":
            _scan(pca)
        else:
            Debug.warn(f"Unknown: '{raw}'")


def _scan(pca):
    Debug.info("Scanning 800→2200us in 100us steps. Press Enter each step.")
    for us in range(800, 2300, 100):
        Debug.info(f"  {us}us — press Enter...")
        set_pulse(pca, us)
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            break
    go_neutral(pca)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 50)
    print("  MG996R SORTER SERVO TEST  (PCA9685 Ch 4)")
    print(f"  Addr=0x{PCA9685_ADDRESS:02X}  Ch={SERVO_CHANNEL}  {FREQ_HZ}Hz")
    print(f"  Neutral={PW_NEUTRAL}us  Reject={PW_REJECT}us  Qualified={PW_QUALIFIED}us")
    print("=" * 50)

    pca = init_servo()

    Debug.step(3, "Moving to neutral")
    go_neutral(pca)

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
        cleanup(pca)
        Debug.info("Done.")


if __name__ == "__main__":
    main()