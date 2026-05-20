import serial
import time

# /dev/serial0 is the hardware TX/RX pins on the Pi
PORT = '/dev/serial0' 
BAUD = 9600

try:
    print(f"Connecting to Arduino on {PORT}...")
    # timeout=1 is important so it doesn't hang forever
    arduino = serial.Serial(PORT, BAUD, timeout=1)
    time.sleep(2)  
    print("Connected.")
except Exception as e:
    print(f"Error connecting: {e}")
    exit()

def dispense(coin_value):
    print(f"Dispensing ₱{coin_value}...")
    
    if coin_value == 1:
        arduino.write(b'1')
    elif coin_value == 5:
        arduino.write(b'5')
    elif coin_value == 10:
        arduino.write(b'A')
    elif coin_value == 20:
        arduino.write(b'B')
    
    time.sleep(1.2) 

# Test
if __name__ == "__main__":
    dispense(1)