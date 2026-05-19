"""
hardware/test_ultrasonic.py
───────────────────────────
Manual test for the HC-SR04 ultrasonic distance sensor.

Wiring:
    TRIG → GPIO 23
    ECHO → GPIO 24
    VCC  → 5V
    GND  → GND

    NOTE: ECHO pin outputs 5V — use a voltage divider to protect the Pi:
          ECHO → 1kΩ → GPIO 24 → 2kΩ → GND

Run:
    python hardware/test_ultrasonic.py
"""

import sys
import traceback
import time

# ── Pin assignments ──────────────────────────────────────────────────────────
PIN_TRIG = 23
PIN_ECHO = 24

# Detection threshold — object is "present" if closer than this (meters)
DETECT_THRESHOLD_M = 0.20   # 17 cm


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

    @staticmethod
    def distance(m: float, detected: bool):
        cm      = m * 100
        bar_len = min(40, int(cm / 5))        # 1 block per 5 cm
        bar     = "█" * bar_len + "░" * (40 - bar_len)
        status  = (
            f"{Debug.RED}● DETECTED{Debug.RESET}"
            if detected else
            f"{Debug.GREEN}○ clear{Debug.RESET}"
        )
        print(
            f"  {Debug.BOLD}{cm:>7.1f} cm{Debug.RESET}  "
            f"[{bar}]  {status}"
        )


# ── Sensor setup ─────────────────────────────────────────────────────────────

def init_sensor():
    Debug.step(1, "Importing gpiozero")
    try:
        from gpiozero import DistanceSensor
        Debug.ok("gpiozero imported.")
    except ImportError:
        Debug.error("gpiozero not found. Run: pip install gpiozero")
        sys.exit(1)

    Debug.step(2, f"Setting up HC-SR04  TRIG=GPIO{PIN_TRIG}  ECHO=GPIO{PIN_ECHO}")
    try:
        sensor = DistanceSensor(
            echo=PIN_ECHO,
            trigger=PIN_TRIG,
            max_distance=2.0,
            threshold_distance=DETECT_THRESHOLD_M,
        )
        Debug.ok("HC-SR04 ready.")
        return sensor
    except Exception:
        Debug.error("Failed to initialize HC-SR04.")
        traceback.print_exc()
        sys.exit(1)


def read_distance(sensor) -> tuple[float, bool]:
    """Returns (distance_m, object_detected). Clamps negative/invalid readings."""
    d        = max(0.0, sensor.distance)   # clamp negatives from missed echoes
    detected = 0 < d < DETECT_THRESHOLD_M
    return d, detected


def cleanup(sensor):
    sensor.close()
    Debug.info("Sensor closed.")


# ── Test sequence ─────────────────────────────────────────────────────────────

def run_tests(sensor):
    tests = [
        ("10 baseline readings — keep area clear",  lambda: _t_baseline(sensor)),
        ("Detection test — place object within 10 cm", lambda: _t_detect(sensor)),
        ("Removal test — remove object",            lambda: _t_removal(sensor)),
        ("Range test — move object gradually",      lambda: _t_range(sensor)),
        ("Stability — 30 rapid readings",           lambda: _t_stability(sensor)),
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
        time.sleep(0.5)

    print()
    print("─" * 40)
    print(f"Results: {passed} passed, {failed} failed")
    print("─" * 40)


def _t_baseline(sensor):
    Debug.info("Reading 10 times with nothing in front — expect > 10 cm")
    all_clear = True
    for _ in range(10):
        d, detected = read_distance(sensor)
        Debug.distance(d, detected)
        if detected:
            all_clear = False
        time.sleep(0.3)
    if not all_clear:
        Debug.warn("Object detected during baseline — make sure sensor path is clear.")


def _t_detect(sensor):
    input(
        f"\n  {Debug.YELLOW}Place an object within {DETECT_THRESHOLD_M*100:.0f} cm "
        f"of the sensor, then press Enter...{Debug.RESET}"
    )
    Debug.info("Reading 10 times — expect DETECTED")
    detected_count = 0
    for _ in range(10):
        d, detected = read_distance(sensor)
        Debug.distance(d, detected)
        if detected:
            detected_count += 1
        time.sleep(0.3)
    if detected_count >= 8:
        Debug.ok(f"Detection confirmed ({detected_count}/10 readings detected).")
    else:
        Debug.warn(
            f"Only {detected_count}/10 readings detected. "
            "Move object closer or check wiring."
        )


def _t_removal(sensor):
    input(
        f"\n  {Debug.YELLOW}Remove the object from sensor range, then press Enter...{Debug.RESET}"
    )
    Debug.info("Reading 10 times — expect clear")
    clear_count = 0
    for _ in range(10):
        d, detected = read_distance(sensor)
        Debug.distance(d, detected)
        if not detected:
            clear_count += 1
        time.sleep(0.3)
    if clear_count >= 8:
        Debug.ok(f"Clear confirmed ({clear_count}/10 readings clear).")
    else:
        Debug.warn(f"Only {clear_count}/10 readings were clear.")


def _t_range(sensor):
    Debug.info(
        "Move an object slowly from far to close.\n"
        "  Watch the bar shrink and the DETECTED flag appear."
    )
    Debug.info("Reading for 10 seconds...")
    end = time.time() + 10
    while time.time() < end:
        d, detected = read_distance(sensor)
        Debug.distance(d, detected)
        time.sleep(0.2)


def _t_stability(sensor, n: int = 30):
    Debug.info(f"Taking {n} rapid readings to check noise...")
    readings = []
    for _ in range(n):
        d, detected = read_distance(sensor)
        Debug.distance(d, detected)
        readings.append(d)
        time.sleep(0.1)

    avg  = sum(readings) / len(readings)
    mn   = min(readings)
    mx   = max(readings)
    span = mx - mn
    print(
        f"\n  Min={mn*100:.1f} cm  Max={mx*100:.1f} cm  "
        f"Avg={avg*100:.1f} cm  Span={span*100:.1f} cm"
    )
    if span < 0.02:
        Debug.ok("Stable — span < 2 cm")
    elif span < 0.05:
        Debug.warn("Moderate noise — span < 5 cm (acceptable)")
    else:
        Debug.warn(
            f"High noise — {span*100:.1f} cm span. "
            "Check for reflective surfaces or wiring issues."
        )


# ── Interactive / live mode ───────────────────────────────────────────────────

def interactive(sensor):
    print()
    Debug.info(
        "Live mode. Commands:\n"
        "  read / r      → single distance reading\n"
        "  live / l      → continuous readings (Ctrl+C to stop)\n"
        "  watch / w     → watch for object detection events only\n"
        "  threshold / t → show current detection threshold\n"
        "  quit          → exit\n"
    )
    while True:
        try:
            cmd = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if cmd in ("quit", "exit", "q"):
            break
        elif cmd in ("read", "r"):
            d, detected = read_distance(sensor)
            Debug.distance(d, detected)
        elif cmd in ("live", "l"):
            Debug.info("Live mode — press Ctrl+C to stop.")
            try:
                while True:
                    d, detected = read_distance(sensor)
                    Debug.distance(d, detected)
                    time.sleep(0.2)
            except KeyboardInterrupt:
                print()
                Debug.info("Live mode stopped.")
        elif cmd in ("watch", "w"):
            debounce_n = 3   # consecutive reads needed to confirm state change
            Debug.info(
                f"Watching for objects within {DETECT_THRESHOLD_M*100:.0f} cm "
                f"(debounce={debounce_n}) — press Ctrl+C to stop."
            )
            last_state    = False
            confirm_count = 0
            pending_state = False
            try:
                while True:
                    d, detected = read_distance(sensor)
                    if detected == pending_state:
                        confirm_count += 1
                    else:
                        pending_state = detected
                        confirm_count = 1

                    if confirm_count >= debounce_n and pending_state != last_state:
                        last_state    = pending_state
                        confirm_count = 0
                        if last_state:
                            Debug.warn(f"⚡ OBJECT DETECTED at {d*100:.1f} cm")
                        else:
                            Debug.ok("✓ Path clear")
                    time.sleep(0.1)
            except KeyboardInterrupt:
                print()
                Debug.info("Watch mode stopped.")
        elif cmd in ("threshold", "t"):
            Debug.info(
                f"Detection threshold: {DETECT_THRESHOLD_M*100:.0f} cm  "
                f"({DETECT_THRESHOLD_M} m)\n"
                f"  Edit DETECT_THRESHOLD_M at the top of this file to change it."
            )
        else:
            Debug.warn(f"Unknown command '{cmd}'.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 46)
    print("  HC-SR04 ULTRASONIC SENSOR TEST")
    print(f"  TRIG = GPIO {PIN_TRIG}   ECHO = GPIO {PIN_ECHO}")
    print(f"  Detection threshold: {DETECT_THRESHOLD_M*100:.0f} cm")
    print("=" * 46)

    sensor = init_sensor()

    try:
        mode = input(
            "\nChoose mode:\n"
            "  [1] Automated test sequence\n"
            "  [2] Interactive / live readings\n"
            "  > "
        ).strip()

        if mode == "1":
            run_tests(sensor)
        elif mode == "2":
            interactive(sensor)
        else:
            Debug.warn("Invalid choice. Running automated test by default.")
            run_tests(sensor)

    except KeyboardInterrupt:
        print()
        Debug.warn("Interrupted by user.")
    finally:
        cleanup(sensor)
        Debug.info("Done.")


if __name__ == "__main__":
    main()