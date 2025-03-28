import os
import time
from dotenv import load_dotenv
from library.lcd.lcd_comm import Orientation
from library.lcd.lcd_comm_rev_a import LcdCommRevA
from PIL import Image
from influxdb_client import InfluxDBClient
from dotenv import load_dotenv

# Load environment variables at the start of your script
load_dotenv()

# Colors
WHITE = (255, 255, 255)
LIGHT_BLUE = (135, 206, 235)    # Sky blue
LIGHT_GREEN = (144, 238, 144)   # Light green
LIGHT_RED = (255, 160, 160)     # Light red for CPU temp
LIGHT_YELLOW = (255, 255, 153)   # Light yellow for CPU temp

def get_system_data():
    # Configure InfluxDB connection
    client = InfluxDBClient(
        url=os.getenv('INFLUXDB_URL'),
        token=os.getenv('INFLUXDB_TOKEN'),
        org=os.getenv('INFLUXDB_ORG')
    )

    # Internet metrics query
    internet_query = '''
    from(bucket: "homelab")
    |> range(start: -1h)
    |> filter(fn: (r) => r["_field"] == "download" or r["_field"] == "upload" or r["_field"] == "location" or r["_field"] == "latency")
    |> last()
    '''

    # UPS metrics query
    ups_query = '''
    from(bucket: "homelab")
    |> range(start: -1m)
    |> filter(fn: (r) => r["_measurement"] == "upsd")
    |> filter(fn: (r) => r["_field"] == "ups_status" or 
                         r["_field"] == "load_percent" or 
                         r["_field"] == "battery_charge_percent" or 
                         r["_field"] == "battery_charger_status" or 
                         r["_field"] == "battery_voltage" or 
                         r["_field"] == "input_voltage" or 
                         r["_field"] == "output_voltage" or 
                         r["_field"] == "internal_temp")
    |> last()
    '''

    # CPU temperature query
    cpu_temp_query = '''
    from(bucket: "homelab")
    |> range(start: -1m)
    |> filter(fn: (r) => r["_measurement"] == "sensors")
    |> filter(fn: (r) => r["_field"] == "temp_input")
    |> filter(fn: (r) => r["chip"] == "k10temp-pci-00c3")
    |> filter(fn: (r) => r["feature"] == "tctl")
    |> last()
    '''

    # Initialize values
    data = {
        'download': 0,
        'upload': 0,
        'location': "Unknown",
        'latency': 0,
        'ups_status': "Unknown",
        'load_percent': 0,
        'battery_charge_percent': 0,
        'battery_charger_status': "Unknown",
        'battery_voltage': 0,
        'input_voltage': 0,
        'output_voltage': 0,
        'internal_temp': 0,
        'cpu_temp': 0
    }
    
    try:
        # Get internet metrics
        tables = client.query_api().query(internet_query)
        for table in tables:
            for record in table.records:
                field = record.get_field()
                if field in data:
                    data[field] = record.get_value()

        # Get UPS metrics
        tables = client.query_api().query(ups_query)
        for table in tables:
            for record in table.records:
                field = record.get_field()
                if field in data:
                    data[field] = record.get_value()

        # Get CPU temperature
        tables = client.query_api().query(cpu_temp_query)
        for table in tables:
            for record in table.records:
                if record.get_field() == "temp_input":
                    data['cpu_temp'] = record.get_value()

        return data
    finally:
        client.close()

def create_temp_gauge(temp, min_temp=30, max_temp=90, width=20):
    """
    Creates a text-based temperature gauge
    Example: [####----] 65°C
    Using simple characters that are widely supported
    """
    # Normalize temperature to our scale
    temp = max(min_temp, min(temp, max_temp))  # Clamp between min and max
    filled = int(((temp - min_temp) / (max_temp - min_temp)) * width)
    
    # Create gauge characters using simple ASCII
    gauge = '['
    gauge += '#' * filled
    gauge += '-' * (width - filled)
    gauge += ']'
    
    # Add color based on temperature
    if temp < 60:
        return gauge, LIGHT_GREEN  # Cool
    elif temp < 80:
        return gauge, LIGHT_YELLOW # Light yellow/Warning
    else:
        return gauge, LIGHT_RED  # Hot

def main():
    # Get absolute path to the font
    current_dir = os.path.dirname(os.path.abspath(__file__))
    font_path = os.path.join(current_dir, "res", "fonts", "jetbrains-mono", "JetBrainsMono-Regular.ttf")
    
    # Initialize display communication
    lcd_comm = LcdCommRevA(
        com_port="/dev/ttyACM0",
        display_width=320,
        display_height=480
    )

    # Initialize the display
    lcd_comm.Reset()
    lcd_comm.InitializeComm()
    
    # Configure display settings
    lcd_comm.SetBrightness(level=10)
    lcd_comm.SetOrientation(orientation=Orientation.PORTRAIT)


    while True:
        # Get latest data
        data = get_system_data()
        
        # Create and display black background
        black_bg = Image.new('RGB', (320, 480), color=(0, 0, 0))
        black_bg.save('black_bg.png')
        lcd_comm.DisplayBitmap('black_bg.png')
        
        # Display time and date
        current_time = time.strftime("%H:%M:%S")
        current_date = time.strftime("%d/%m/%Y")
        lcd_comm.DisplayText(
            text=current_time,
            x=5,
            y=5,
            font="roboto/Roboto-Bold.ttf",
            font_size=24,
            font_color=WHITE,
            background_color=(0, 0, 0)
        )
        lcd_comm.DisplayText(
            text=current_date,
            x=5,
            y=35,
            font="roboto/Roboto-Bold.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0)
        )

        # Internet Status Section
        lcd_comm.DisplayText(
            text="Internet",
            x=5,
            y=65,
            font="roboto/Roboto-Bold.ttf",
            font_size=24,
            font_color=LIGHT_BLUE,
            background_color=(0, 0, 0)
        )
        y_pos = 90
        internet_info = [
            f"Location: {data['location']}",
            f"Download: {data['download']:.1f} Mbps",
            f"Upload: {data['upload']:.1f} Mbps",
            f"Latency: {data['latency']:.0f} ms"
        ]
        for info in internet_info:
            lcd_comm.DisplayText(
                text=info,
                x=5,
                y=y_pos,
                font="roboto/Roboto-Regular.ttf",
                font_size=20,
                font_color=WHITE,
                background_color=(0, 0, 0)
            )
            y_pos += 20

        # UPS Status Section
        lcd_comm.DisplayText(
            text="UPS",
            x=5,
            y=180,
            font="roboto/Roboto-Bold.ttf",
            font_size=24,
            font_color=LIGHT_GREEN,
            background_color=(0, 0, 0)
        )
        y_pos = 205
        ups_info = [
            f"Status: {data['ups_status']}",
            f"Load: {data['load_percent']:.1f}%",
            f"Battery: {data['battery_charge_percent']:.1f}%",
            f"Charger: {data['battery_charger_status']}",
            f"Batt V: {data['battery_voltage']:.1f}V",
            f"Input: {data['input_voltage']:.1f}V",
            f"Output: {data['output_voltage']:.1f}V",
            f"Temp: {data['internal_temp']:.1f}°C"
        ]
        for info in ups_info:
            lcd_comm.DisplayText(
                text=info,
                x=5,
                y=y_pos,
                font="roboto/Roboto-Regular.ttf",
                font_size=20,
                font_color=WHITE,
                background_color=(0, 0, 0)
            )
            y_pos += 20

        # CPU Temperature Section
        lcd_comm.DisplayText(
            text="CPU Temperature",
            x=5,
            y=375,
            font="roboto/Roboto-Bold.ttf",
            font_size=24,
            font_color=LIGHT_RED,
            background_color=(0, 0, 0)
        )
        
        # Create temperature gauge
        gauge, gauge_color = create_temp_gauge(data['cpu_temp'])
        
        # Display temperature value
        lcd_comm.DisplayText(
            text=f"{data['cpu_temp']:.1f}°C",
            x=5,
            y=400,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0)
        )
        
        # Display gauge
        lcd_comm.DisplayText(
            text=gauge,
            x=80,  # Adjusted x position to align with temperature
            y=400,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=gauge_color,
            background_color=(0, 0, 0)
        )

        time.sleep(30)

if __name__ == "__main__":
    main()
