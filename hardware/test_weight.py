"""
hardware/test_weight.py
───────────────────────
Manual test for the HX711 load-cell amplifier + weight sensor.
Uses the 'hx711' library (pip install hx711).

Wiring:
    HX711 VCC → 5V     (Pin 2 or 4)
    HX711 GND → GND    (Pin 6)
    HX711 DT  → GPIO 5 (Pin 29)
    HX711 SCK → GPIO 6 (Pin 31)

Load cell:
    Red   → E+
    Black → E-
    White → A-
    Green → A+

Run:
    python hardware/test_weight.py
"""

import sys
import traceback
import time
import json
import os
import statistics  # Add this to the top of your file with the other imports

# ── Pin assignments ──────────────────────────────────────────────────────────
PIN_DT  = 5
PIN_SCK = 6

CALIB_FILE = os.path.join(os.path.dirname(__file__), "weight_calibration.json")
SAMPLE_TIMES = 10   # readings per sample


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
    def reading(kg: float, raw: float = None):
        bar_len = min(40, int(abs(kg) * 20))
        bar     = "█" * bar_len + "░" * (40 - bar_len)
        raw_str = f"  raw={raw:.0f}" if raw is not None else ""
        print(f"  {Debug.BOLD}{kg:>8.3f} kg{Debug.RESET}  [{bar}]{raw_str}")


# ── HX711 setup ──────────────────────────────────────────────────────────────

def init_hx711():
    Debug.step(1, "Setting GPIO mode to BCM")
    try:
        import RPi.GPIO as GPIO  # type: ignore
        GPIO.setmode(GPIO.BCM)
        Debug.ok("GPIO BCM mode set.")
    except Exception:
        Debug.error("RPi.GPIO failed.")
        traceback.print_exc()
        sys.exit(1)

    Debug.step(2, "Importing hx711")
    try:
        from hx711 import HX711  # type: ignore
        Debug.ok("hx711 imported.")
    except ImportError:
        Debug.error("hx711 not found. Run: pip install hx711")
        sys.exit(1)

    Debug.step(3, f"Initializing HX711  DT=GPIO{PIN_DT}  SCK=GPIO{PIN_SCK}")
    try:
        hx = HX711(dout_pin=PIN_DT, pd_sck_pin=PIN_SCK)  # type: ignore
        hx.reset()
        Debug.ok("HX711 initialized and reset.")
        return hx
    except Exception:
        Debug.error("Failed to initialize HX711.")
        traceback.print_exc()
        sys.exit(1)


# ── Raw reading ───────────────────────────────────────────────────────────────

def read_raw_mean(hx, times: int = SAMPLE_TIMES) -> float | None:
    """Get median of raw ADC readings to filter out OS timing spikes."""
    try:
        data = hx.get_raw_data(times=times)
        if data and len(data) >= 3:
            # Median completely ignores extreme high/low spikes 
            # caused by Raspberry Pi GPIO bit-banging misses.
            return statistics.median(data)
        elif data and len(data) > 0:
            return sum(data) / len(data)
    except Exception:
        pass
    return None


# ── Tare (manual zero offset) ─────────────────────────────────────────────────

def tare(hx, times: int = 20) -> float | None:
    """
    Record zero offset by averaging readings with empty scale.
    Returns the zero offset value, or None on failure.
    """
    Debug.info("Taring — make sure platform is empty...")
    samples = []
    for _ in range(times):
        val = read_raw_mean(hx, times=5)
        if val is not None:
            samples.append(val)
        time.sleep(0.05)

    if not samples:
        Debug.error("Tare failed — no readings.")
        return None

    offset = sum(samples) / len(samples)
    Debug.ok(f"Tare offset: {offset:.0f}  ({len(samples)}/{times} valid reads)")
    return offset


# ── Calibration ───────────────────────────────────────────────────────────────

def load_calibration() -> dict | None:
    """Load saved calibration: {offset, units_per_kg}."""
    if os.path.exists(CALIB_FILE):
        try:
            with open(CALIB_FILE) as f:
                data = json.load(f)
            if data.get("units_per_kg") and data.get("offset") is not None:
                Debug.ok(
                    f"Loaded calibration — "
                    f"offset={data['offset']:.0f}  "
                    f"units/kg={data['units_per_kg']:.2f}"
                )
                return data
        except Exception:
            pass
    return None


def save_calibration(offset: float, units_per_kg: float):
    with open(CALIB_FILE, "w") as f:
        json.dump({"offset": offset, "units_per_kg": units_per_kg}, f, indent=2)
    Debug.ok(f"Calibration saved → {CALIB_FILE}")


def calibrate(hx) -> dict:
    """
    Interactive calibration.
    Returns {offset, units_per_kg}.
    """
    print()
    Debug.info("── CALIBRATION ──────────────────────────────────")
    Debug.info("You need a known weight (e.g. 0.5 kg or 1.0 kg).")

    # Step A — tare
    input(f"\n  {Debug.YELLOW}Remove everything from scale, press Enter...{Debug.RESET}")
    offset = tare(hx, times=20)
    if offset is None:
        Debug.error("Cannot calibrate — tare failed.")
        sys.exit(1)

    # Step B — known weight
    known_str = input(
        f"\n  {Debug.YELLOW}Enter known weight in kg (e.g. 0.5): {Debug.RESET}"
    ).strip()
    try:
        known_kg = float(known_str)
        if known_kg <= 0:
            raise ValueError
    except ValueError:
        Debug.warn("Invalid — using 1.0 kg.")
        known_kg = 1.0

    input(
        f"\n  {Debug.YELLOW}Place {known_kg} kg on scale, press Enter...{Debug.RESET}"
    )
    time.sleep(0.5)

    Debug.info("Recording loaded readings (20 samples)...")
    loaded_samples = []
    for _ in range(20):
        val = read_raw_mean(hx, times=5)
        if val is not None:
            loaded_samples.append(val)
        time.sleep(0.05)

    if not loaded_samples:
        Debug.error("No readings with weight on scale.")
        sys.exit(1)

    raw_loaded = sum(loaded_samples) / len(loaded_samples)
    Debug.ok(f"Loaded raw mean: {raw_loaded:.0f}  ({len(loaded_samples)}/20 valid)")

    # Step C — derive factor
    raw_diff = raw_loaded - offset
    Debug.info(f"Raw difference: {raw_diff:.0f}")

    if abs(raw_diff) < 100:
        Debug.error(
            "Difference too small — load cell may not be responding.\n"
            "Check mounting and wiring."
        )
        sys.exit(1)

    units_per_kg = raw_diff / known_kg
    Debug.ok(f"Calibration factor: {units_per_kg:.2f} raw units/kg")

    save_calibration(offset, units_per_kg)
    return {"offset": offset, "units_per_kg": units_per_kg}


# ── Weight reading ────────────────────────────────────────────────────────────

def read_kg(hx, calib: dict, times: int = SAMPLE_TIMES) -> tuple[float, float]:
    """
    Returns (weight_kg, raw_value).
    Applies offset and calibration factor.
    """
    raw = read_raw_mean(hx, times=times)
    if raw is None:
        return 0.0, 0.0
    corrected = raw - calib["offset"]
    kg = corrected / calib["units_per_kg"]
    return kg, raw


def cleanup(hx):
    try:
        hx.power_down()
        Debug.info("HX711 powered down.")
    except Exception:
        pass


# ── Test sequence ─────────────────────────────────────────────────────────────

def run_tests(hx, calib: dict):
    tests = [
        ("10 readings at zero — expect ~0.000 kg", lambda: _t_zero_readings(hx, calib)),
        ("Verify known weight",                    lambda: _t_known_weight(hx, calib)),
        ("Stability — 20 readings",                lambda: _t_stability(hx, calib)),
        ("Re-tare check",                          lambda: _t_retare(hx, calib)),
    ]

    passed = failed = 0
    for idx, (name, fn) in enumerate(tests, start=1):
        Debug.step(idx + 5, name)
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


def _t_zero_readings(hx, calib):
    Debug.info("10 readings — expect ~0.000 kg")
    for _ in range(10):
        kg, raw = read_kg(hx, calib)
        Debug.reading(kg, raw)
        time.sleep(0.3)


def _t_known_weight(hx, calib):
    input(f"\n  {Debug.YELLOW}Place known weight on scale, press Enter...{Debug.RESET}")
    Debug.info("10 samples...")
    readings = []
    for _ in range(10):
        kg, raw = read_kg(hx, calib, times=15)
        Debug.reading(kg, raw)
        readings.append(kg)
        time.sleep(0.3)
    avg = sum(readings) / len(readings)
    print(f"\n  Average: {avg:.4f} kg  ({avg*1000:.1f} g)")
    Debug.info("Compare to your known weight.")


def _t_stability(hx, calib, n: int = 20):
    Debug.info(f"{n} rapid readings...")
    readings = []
    for _ in range(n):
        kg, raw = read_kg(hx, calib, times=5)
        Debug.reading(kg, raw)
        readings.append(kg)
        time.sleep(0.15)

    span = max(readings) - min(readings)
    avg  = sum(readings) / len(readings)
    print(
        f"\n  Min={min(readings):.4f}  Max={max(readings):.4f}  "
        f"Avg={avg:.4f}  Span={span*1000:.1f} g"
    )
    if span < 0.005:
        Debug.ok("Stable — noise < 5 g")
    elif span < 0.020:
        Debug.warn("Moderate noise — < 20 g (acceptable)")
    else:
        Debug.warn(f"High noise — {span*1000:.1f} g. Check wiring/mounting.")


def _t_retare(hx, calib):
    input(f"\n  {Debug.YELLOW}Remove weight, press Enter to re-tare...{Debug.RESET}")
    new_offset = tare(hx, times=20)
    if new_offset:
        calib["offset"] = new_offset
        Debug.info("5 readings after re-tare — expect ~0.000 kg")
        for _ in range(5):
            kg, raw = read_kg(hx, calib)
            Debug.reading(kg, raw)
            time.sleep(0.3)


# ── Interactive mode ──────────────────────────────────────────────────────────

def interactive(hx, calib: dict):
    print()
    Debug.info(
        "Commands:\n"
        "  tare / t        → re-zero the scale\n"
        "  read / r        → single reading in kg\n"
        "  live / l        → continuous readings (Ctrl+C to stop)\n"
        "  raw             → show raw ADC value\n"
        "  stability / s   → 20-reading noise check\n"
        "  calibrate / c   → redo full calibration\n"
        "  quit\n"
    )
    while True:
        try:
            cmd = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if cmd in ("quit", "exit", "q"):
            break
        elif cmd in ("tare", "t"):
            new_offset = tare(hx, times=20)
            if new_offset is not None:
                calib["offset"] = new_offset
        elif cmd in ("read", "r"):
            kg, raw = read_kg(hx, calib)
            Debug.reading(kg, raw)
        elif cmd == "raw":
            val = read_raw_mean(hx, times=5)
            Debug.info(f"Raw ADC mean: {val:.0f}" if val else "No reading.")
        elif cmd in ("live", "l"):
            Debug.info("Live — Ctrl+C to stop.")
            try:
                while True:
                    kg, raw = read_kg(hx, calib, times=5)
                    Debug.reading(kg, raw)
                    time.sleep(0.25)
            except KeyboardInterrupt:
                print()
                Debug.info("Stopped.")
        elif cmd in ("stability", "s"):
            _t_stability(hx, calib)
        elif cmd in ("calibrate", "c"):
            calib = calibrate(hx)
        else:
            Debug.warn(f"Unknown: '{cmd}'")

    return calib


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 44)
    print("  HX711 WEIGHT SENSOR TEST")
    print(f"  DT=GPIO{PIN_DT}  SCK=GPIO{PIN_SCK}  VCC=5V")
    print("=" * 44)

    hx = init_hx711()

    # ── Confirm ADC is alive ──────────────────────────────────────────────
    Debug.step(4, "Raw ADC diagnostic")
    data = hx.get_raw_data(times=5)
    if not data or all(v == 0 for v in data):
        Debug.error("ADC returned no data. Check wiring.")
        sys.exit(1)
    Debug.ok(f"ADC alive — sample: {data}")

    # ── Calibration ───────────────────────────────────────────────────────
    Debug.step(5, "Calibration check")
    calib = load_calibration()
    if calib is None:
        Debug.warn("No calibration found — running now.")
        calib = calibrate(hx)
    else:
        redo = input(
            f"\n  offset={calib['offset']:.0f}  units/kg={calib['units_per_kg']:.2f}\n"
            f"  Recalibrate? [y/N]: "
        ).strip().lower()
        if redo == "y":
            calib = calibrate(hx)

    # ── Initial tare ──────────────────────────────────────────────────────
    Debug.step(6, "Initial tare")
    new_offset = tare(hx, times=20)
    if new_offset:
        calib["offset"] = new_offset

    try:
        mode = input(
            "\nMode:\n"
            "  [1] Automated test\n"
            "  [2] Interactive\n"
            "  > "
        ).strip()

        if mode == "1":
            run_tests(hx, calib)
        elif mode == "2":
            interactive(hx, calib)
        else:
            Debug.warn("Invalid — running automated test.")
            run_tests(hx, calib)

    except KeyboardInterrupt:
        print()
        Debug.warn("Interrupted.")
    finally:
        cleanup(hx)
        Debug.info("Done.")


if __name__ == "__main__":
    main()