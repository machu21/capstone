"""
hardware/test_gpio_pins.py
──────────────────────────
Tests each GPIO pin one by one using an LED.

Wiring:
    GPIO pin → 330Ω resistor → LED (+) → LED (-) → GND

Run:
    python hardware/test_gpio_pins.py

Then move the LED wire to each GPIO pin when prompted.
"""

import sys
import time

# ── All testable BCM GPIO pins on Raspberry Pi 5 ────────────────────────────
# Excludes reserved/special pins (I2C, UART, etc. can still be tested
# as plain output if not in use)
ALL_GPIO_PINS = [
    4, 5, 6, 12, 13, 16, 17, 18, 19, 20,
    21, 22, 23, 24, 25, 26, 27
]

# Pins used by this project — shown as a reminder
PROJECT_PINS = {
    17: "Motor IN1",
    27: "Motor IN2",
    18: "Servo MG996R",
    23: "Ultrasonic TRIG",
    24: "Ultrasonic ECHO",
    5:  "HX711 DT",
    6:  "HX711 SCK",
    2:  "PCA9685 SDA (I2C)",
    3:  "PCA9685 SCL (I2C)",
}


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


# ── GPIO setup ───────────────────────────────────────────────────────────────

def init_gpiozero():
    try:
        from gpiozero import LED
        Debug.ok("gpiozero imported.")
        return LED
    except ImportError:
        Debug.error("gpiozero not found. Run: pip install gpiozero")
        sys.exit(1)


# ── Test modes ────────────────────────────────────────────────────────────────

def test_single_pin(LED, pin: int):
    """Blink an LED on a single pin and ask user to confirm."""
    label = PROJECT_PINS.get(pin, "")
    label_str = f"  ({label})" if label else ""
    print(f"\n  {Debug.BOLD}GPIO {pin}{Debug.RESET}{label_str}")

    try:
        led = LED(pin)
    except Exception as e:
        Debug.error(f"Could not open GPIO {pin}: {e}")
        return False

    # Blink 3 times
    Debug.info("Blinking 3 times...")
    for _ in range(3):
        led.on()
        time.sleep(0.4)
        led.off()
        time.sleep(0.3)

    # Hold on for visual confirmation
    led.on()
    result = input(
        f"  {Debug.YELLOW}LED on GPIO {pin} — is it lit? [y/n]: {Debug.RESET}"
    ).strip().lower()
    led.off()
    led.close()

    if result == "y":
        Debug.ok(f"GPIO {pin} PASSED")
        return True
    else:
        Debug.warn(f"GPIO {pin} FAILED or not confirmed")
        return False


def test_all_pins(LED):
    """Walk through every GPIO pin one by one."""
    results = {}
    print()
    Debug.info(
        "Move your LED wire to each GPIO pin when prompted.\n"
        "  Wiring: GPIO pin → 330Ω → LED(+) → LED(-) → GND\n"
    )

    for pin in ALL_GPIO_PINS:
        label = PROJECT_PINS.get(pin, "")
        label_str = f" ({label})" if label else ""
        proceed = input(
            f"  Move LED to GPIO {pin}{label_str} then press Enter "
            f"(or 's' to skip): "
        ).strip().lower()

        if proceed == "s":
            Debug.warn(f"GPIO {pin} skipped.")
            results[pin] = "SKIP"
            continue

        passed = test_single_pin(LED, pin)
        results[pin] = "PASS" if passed else "FAIL"

    _print_summary(results)


def test_project_pins(LED):
    """Only test the pins used by this project."""
    results = {}
    print()
    Debug.info("Testing project pins only.\n")

    for pin, label in PROJECT_PINS.items():
        if pin in (2, 3):
            Debug.warn(f"GPIO {pin} ({label}) is I2C — skipping output test.")
            results[pin] = "SKIP"
            continue

        proceed = input(
            f"  Move LED to GPIO {pin} ({label}) then press Enter "
            f"(or 's' to skip): "
        ).strip().lower()

        if proceed == "s":
            Debug.warn(f"GPIO {pin} skipped.")
            results[pin] = "SKIP"
            continue

        passed = test_single_pin(LED, pin)
        results[pin] = "PASS" if passed else "FAIL"

    _print_summary(results)


def test_specific_pin(LED):
    """Test a single pin by number."""
    try:
        pin = int(input("  Enter GPIO BCM pin number: ").strip())
    except ValueError:
        Debug.error("Invalid number.")
        return
    test_single_pin(LED, pin)


def blink_loop(LED):
    """Continuously blink a pin — useful for checking a specific connection."""
    try:
        pin = int(input("  Enter GPIO BCM pin number: ").strip())
    except ValueError:
        Debug.error("Invalid number.")
        return

    try:
        led = LED(pin)
    except Exception as e:
        Debug.error(f"Could not open GPIO {pin}: {e}")
        return

    Debug.info(f"Blinking GPIO {pin} continuously — press Ctrl+C to stop.")
    try:
        while True:
            led.on()
            time.sleep(0.5)
            led.off()
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        led.off()
        led.close()
        print()
        Debug.info("Stopped.")


def _print_summary(results: dict):
    print()
    print("─" * 44)
    print(f"  {'GPIO':<8} {'Label':<22} {'Result'}")
    print("─" * 44)
    for pin, status in sorted(results.items()):
        label = PROJECT_PINS.get(pin, "")
        color = (
            Debug.GREEN  if status == "PASS" else
            Debug.RED    if status == "FAIL" else
            Debug.YELLOW
        )
        print(f"  GPIO {pin:<4} {label:<22} {color}{status}{Debug.RESET}")
    print("─" * 44)
    passed = sum(1 for v in results.values() if v == "PASS")
    failed = sum(1 for v in results.values() if v == "FAIL")
    skipped = sum(1 for v in results.values() if v == "SKIP")
    print(f"  {passed} passed  {failed} failed  {skipped} skipped")
    print("─" * 44)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 44)
    print("  GPIO PIN TESTER")
    print("  Wiring: GPIO → 330Ω → LED(+) → LED(-) → GND")
    print("=" * 44)
    print()
    print("  Project pin assignments:")
    for pin, label in sorted(PROJECT_PINS.items()):
        print(f"    GPIO {pin:<4} → {label}")

    LED = init_gpiozero()

    try:
        mode = input(
            "\nChoose mode:\n"
            "  [1] Test all GPIO pins (walk through one by one)\n"
            "  [2] Test project pins only\n"
            "  [3] Test a specific pin\n"
            "  [4] Blink a pin continuously\n"
            "  > "
        ).strip()

        if mode == "1":
            test_all_pins(LED)
        elif mode == "2":
            test_project_pins(LED)
        elif mode == "3":
            test_specific_pin(LED)
        elif mode == "4":
            blink_loop(LED)
        else:
            Debug.warn("Invalid choice.")

    except KeyboardInterrupt:
        print()
        Debug.warn("Interrupted.")
    finally:
        Debug.info("Done.")


if __name__ == "__main__":
    main()