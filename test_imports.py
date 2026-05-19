import PyQt6.QtWidgets
import gpiozero
import picamera2
import hx711_multi
import adafruit_pca9685
import board

print("✅ All libraries imported successfully!")

# Check if I2C is seeing the PCA9685
try:
    i2c = board.I2C()
    print("✅ I2C Bus initialized.")
except Exception as e:
    print(f"❌ I2C Error: {e} (Did you enable I2C in raspi-config?)")
    