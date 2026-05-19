"""
hardware/test_conveyor.py
─────────────────────────
Manual test for the L298N-controlled DC motor (conveyor belt).
Wiring:
    IN1 → GPIO 17  (forward)
    IN2 → GPIO 27  (brake / reverse)

Run:
    python hardware/test_conveyor.py
"""

import sys
import traceback
import time

# ── Pin assignments ──────────────────────────────────────────────────────────
PIN_IN1 = 17
PIN_IN2 = 27

# ── Debug logger ─────────────────────────────────────────────────────────────

class Debug:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"

    @staticmethod
    def info(msg: str):
        print(f"{Debug.CYAN}[INFO]{Debug.RESET}  {msg}")

    @staticmethod
    def ok(msg: str):
        print(f"{Debug.GREEN}[OK]{Debug.RESET}    {msg}")

    @staticmethod
    def warn(msg: str):
        print(f"{Debug.YELLOW}[WARN]{Debug.RESET}  {msg}")

    @staticmethod
    def error(msg: str):
        print(f"{Debug.RED}[ERROR]{Debug.RESET} {msg}")

    @staticmethod
    def step(n: int, msg: str):
        print(f"\n{Debug.BOLD}── Step {n}: {msg}{Debug.RESET}")


# ── GPIO setup ───────────────────────────────────────────────────────────────

def init_gpio():
    Debug.step(1, "Importing gpiozero")
    try:
        from gpiozero import OutputDevice
        Debug.ok("gpiozero imported successfully.")
    except ImportError:
        Debug.error("gpiozero not found. Run: pip install gpiozero")
        sys.exit(1)

    Debug.step(2, f"Setting up GPIO pins  IN1={PIN_IN1}  IN2={PIN_IN2}")
    try:
        in1 = OutputDevice(PIN_IN1, active_high=True, initial_value=False)
        in2 = OutputDevice(PIN_IN2, active_high=True, initial_value=False)
        Debug.ok(f"GPIO {PIN_IN1} (IN1) ready.")
        Debug.ok(f"GPIO {PIN_IN2} (IN2) ready.")
        return in1, in2
    except Exception:
        Debug.error("Failed to initialize GPIO pins.")
        traceback.print_exc()
        sys.exit(1)


# ── Motor actions ─────────────────────────────────────────────────────────────

def conveyor_on(in1, in2):
    in1.on()
    in2.off()
    Debug.ok("Conveyor ON  (IN1=HIGH, IN2=LOW)")

def conveyor_off(in1, in2):
    in1.off()
    in2.off()
    Debug.ok("Conveyor OFF (IN1=LOW,  IN2=LOW)")

def conveyor_brake(in1, in2):
    in1.on()
    in2.on()
    Debug.warn("Conveyor BRAKE (IN1=HIGH, IN2=HIGH)")

def cleanup(in1, in2):
    conveyor_off(in1, in2)
    in1.close()
    in2.close()
    Debug.info("GPIO pins released.")


# ── Test sequence ────────────────────────────────────────────────────────────

def run_tests(in1, in2):
    tests = [
        ("Run conveyor for 3 seconds",  lambda: _test_run(in1, in2, duration=3)),
        ("Stop for 2 seconds",          lambda: _test_stop(in1, in2, duration=2)),
        ("Run conveyor for 2 seconds",  lambda: _test_run(in1, in2, duration=2)),
        ("Brake stop",                  lambda: _test_brake(in1, in2)),
        ("Run-stop cycle x3",           lambda: _test_cycle(in1, in2, cycles=3)),
    ]

    passed = 0
    failed = 0

    for idx, (name, fn) in enumerate(tests, start=1):
        Debug.step(idx + 2, name)   # steps 1-2 used in init
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


def _test_run(in1, in2, duration: float):
    conveyor_on(in1, in2)
    Debug.info(f"Running for {duration}s...")
    time.sleep(duration)
    conveyor_off(in1, in2)


def _test_stop(in1, in2, duration: float):
    conveyor_off(in1, in2)
    Debug.info(f"Stopped for {duration}s...")
    time.sleep(duration)


def _test_brake(in1, in2):
    conveyor_on(in1, in2)
    Debug.info("Running 1s then braking...")
    time.sleep(1)
    conveyor_brake(in1, in2)
    time.sleep(0.5)
    conveyor_off(in1, in2)


def _test_cycle(in1, in2, cycles: int):
    for i in range(cycles):
        Debug.info(f"Cycle {i+1}/{cycles}: ON")
        conveyor_on(in1, in2)
        time.sleep(1.5)
        Debug.info(f"Cycle {i+1}/{cycles}: OFF")
        conveyor_off(in1, in2)
        time.sleep(1.0)


# ── Interactive mode ─────────────────────────────────────────────────────────

def interactive(in1, in2):
    print()
    Debug.info("Entering interactive mode. Commands: on / off / brake / quit")
    commands = {
        "on":    lambda: conveyor_on(in1, in2),
        "off":   lambda: conveyor_off(in1, in2),
        "brake": lambda: conveyor_brake(in1, in2),
    }
    while True:
        try:
            cmd = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if cmd in ("quit", "q", "exit"):
            break
        elif cmd in commands:
            commands[cmd]()
        else:
            Debug.warn(f"Unknown command '{cmd}'. Try: on / off / brake / quit")


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 40)
    print("  CONVEYOR MOTOR TEST  (L298N + DC Motor)")
    print(f"  IN1 = GPIO {PIN_IN1}   IN2 = GPIO {PIN_IN2}")
    print("=" * 40)

    in1, in2 = init_gpio()

    try:
        mode = input(
            "\nChoose mode:\n"
            "  [1] Automated test sequence\n"
            "  [2] Interactive (manual on/off)\n"
            "  > "
        ).strip()

        if mode == "1":
            run_tests(in1, in2)
        elif mode == "2":
            interactive(in1, in2)
        else:
            Debug.warn("Invalid choice. Running automated test by default.")
            run_tests(in1, in2)

    except KeyboardInterrupt:
        print()
        Debug.warn("Interrupted by user.")
    finally:
        cleanup(in1, in2)
        Debug.info("Done.")


if __name__ == "__main__":
    main()