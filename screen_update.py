import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import psutil
from dotenv import load_dotenv
from library.lcd.lcd_comm import Orientation
from library.lcd.lcd_comm_rev_a import LcdCommRevA
from PIL import Image
from influxdb_client import InfluxDBClient

# Load environment variables at the start of your script
load_dotenv()

# Colors
WHITE = (255, 255, 255)
LIGHT_BLUE = (135, 206, 235)    # Sky blue
LIGHT_GREEN = (144, 238, 144)   # Light green
LIGHT_RED = (255, 160, 160)     # Light red for CPU temp
LIGHT_YELLOW = (255, 255, 153)   # Light yellow for CPU temp
IPIFY_URL = os.getenv("IPIFY_URL", "https://api.ipify.org?format=json")
IP_API_URL_TEMPLATE = os.getenv(
    "IP_API_URL", "http://ip-api.com/json/{ip}?fields=status,message,city,countryCode,isp"
)
LAST_IP_DETAILS = {
    "public_ip": "Unknown",
    "location_city": "Unknown",
    "location_country_code": "",
    "isp": "Unknown",
}


def get_public_ip():
    """Fetch the current public IPv4 address, fallback to Unknown on errors."""
    try:
        with urlopen(IPIFY_URL, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("ip", "Unknown")
    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError):
        return "Unknown"


def get_ip_details():
    """
    Return WAN IP plus ISP/location details derived from ip-api.com.

    Falls back to the last known successful values when the API calls fail so the
    screen does not flash back to "Unknown" on transient network glitches.
    """
    global LAST_IP_DETAILS
    cached_details = LAST_IP_DETAILS.copy()

    ip = get_public_ip()
    if ip == "Unknown":
        return cached_details

    updated_details = cached_details.copy()
    updated_details["public_ip"] = ip

    try:
        url = IP_API_URL_TEMPLATE.format(ip=ip)
    except KeyError:
        LAST_IP_DETAILS = updated_details
        return updated_details

    try:
        with urlopen(url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError):
        LAST_IP_DETAILS = updated_details
        return updated_details

    if payload.get("status") != "success":
        LAST_IP_DETAILS = updated_details
        return updated_details

    updated_details["location_city"] = payload.get("city") or "Unknown"
    updated_details["location_country_code"] = payload.get("countryCode") or ""
    updated_details["isp"] = payload.get("isp") or "Unknown"

    LAST_IP_DETAILS = updated_details
    return updated_details

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
    |> filter(fn: (r) => r["_field"] == "download" or r["_field"] == "upload" or r["_field"] == "latency")
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
    |> filter(fn: (r) => r["chip"] == "coretemp-isa-0000")
    |> filter(fn: (r) => r["feature"] == "package_id_0")
    |> last()
    '''

    # NVME temperature query
    nvme_temp_query = '''
    from(bucket: "homelab")
    |> range(start: -1m)
    |> filter(fn: (r) => r["_measurement"] == "sensors")
    |> filter(fn: (r) => r["_field"] == "temp_input")
    |> filter(fn: (r) => r["chip"] == "nvme-pci-0100" or r["chip"] == "nvme-pci-8100")
    |> filter(fn: (r) => r["feature"] == "composite")
    |> last()
    '''

    # Initialize values
    data = {
        'download': 0,
        'upload': 0,
        'latency': 0,
        'ups_status': "Unknown",
        'load_percent': 0,
        'battery_charge_percent': 0,
        'battery_charger_status': "Unknown",
        'battery_voltage': 0,
        'input_voltage': 0,
        'output_voltage': 0,
        'internal_temp': 0,
        'cpu_temp': 0,
        'nvme_0100_temp': 0,
        'nvme_8100_temp': 0,
        'public_ip': "Unknown",
        'location_city': "Unknown",
        'location_country_code': "",
        'isp': "Unknown",
        'memory_usage': 0.0
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

        # Get NVME temperatures
        tables = client.query_api().query(nvme_temp_query)
        for table in tables:
            for record in table.records:
                if record.get_field() == "temp_input":
                    chip = record.values.get("chip")
                    if chip == "nvme-pci-0100":
                        data['nvme_0100_temp'] = record.get_value()
                    elif chip == "nvme-pci-8100":
                        data['nvme_8100_temp'] = record.get_value()

        ip_details = get_ip_details()
        data.update(ip_details)

        try:
            data['memory_usage'] = float(psutil.virtual_memory().percent)
        except Exception:
            pass

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
            x=190,  # Right-aligned position
            y=5,
            font="roboto/Roboto-Bold.ttf",
            font_size=24,
            font_color=WHITE,
            background_color=(0, 0, 0)
        )
        # Draw a line below time and date
        lcd_comm.DisplayText(
            text="____________________________________",
            x=5,
            y=25,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0)
        )

        # Internet Status Section
        lcd_comm.DisplayText(
            text="INTERNET",
            x=5,
            y=60,
            font="roboto/Roboto-Bold.ttf",
            font_size=24,
            font_color=LIGHT_BLUE,
            background_color=(0, 0, 0)
        )

        location_parts = []
        if data['location_city'] not in ("", "Unknown"):
            location_parts.append(data['location_city'])
        if data['location_country_code']:
            location_parts.append(data['location_country_code'])
        location_value = "-".join(location_parts) if location_parts else "Unknown"

        lcd_comm.DisplayText(
            text=f"WAN IP: {data['public_ip']}",
            x=5,
            y=90,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0)
        )

        lcd_comm.DisplayText(
            text=f"Location: {location_value}",
            x=5,
            y=110,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0)
        )

        lcd_comm.DisplayText(
            text=f"ISP: {str(data['isp']).capitalize()}",
            x=5,
            y=130,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0)
        )

        # Display internet metrics in a single line with symbols
        internet_metrics = f"Speed Test: {data['upload']:.0f} up / {data['download']:.0f} down"
        lcd_comm.DisplayText(
            text=internet_metrics,
            x=5,
            y=150,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0)
        )

        # UPS Status Section
        lcd_comm.DisplayText(
            text="NO-BREAK",
            x=5,
            y=190,
            font="roboto/Roboto-Bold.ttf",
            font_size=24,
            font_color=LIGHT_GREEN,
            background_color=(0, 0, 0)
        )
        y_pos = 220
        ups_info = [
            f"Status: {data['ups_status']}  |  Charger: {data['battery_charger_status']}",
            f"Battery: {data['battery_charge_percent']:.1f}%  |  {data['battery_voltage']:.1f}V",
            f"Load: {data['load_percent']:.1f}%  |  Temp: {data['internal_temp']:.1f}°C",
            f"Input: {data['input_voltage']:.1f}V  |  Output: {data['output_voltage']:.1f}V"
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
            text="SERVER",
            x=5,
            y=320,
            font="roboto/Roboto-Bold.ttf",
            font_size=24,
            font_color=LIGHT_RED,
            background_color=(0, 0, 0)
        )
        
        # Create temperature gauge
        cpu_gauge, cpu_color = create_temp_gauge(data['cpu_temp'])

        # Display temperature value
        lcd_comm.DisplayText(
            text=f"CPU Temp: {data['cpu_temp']:.1f}C",
            x=5,
            y=350,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0)
        )

        # Display CPU gauge
        lcd_comm.DisplayText(
            text=cpu_gauge,
            x=80,
            y=350,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=cpu_color,
            background_color=(0, 0, 0)
        )

        mem_gauge, mem_color = create_temp_gauge(
            data['memory_usage'],
            min_temp=0,
            max_temp=100,
            width=20
        )

        # Display memory usage value
        lcd_comm.DisplayText(
            text=f"Memory: {data['memory_usage']:.1f}%",
            x=5,
            y=370,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0)
        )

        # Display memory gauge
        lcd_comm.DisplayText(
            text=mem_gauge,
            x=80,
            y=370,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=mem_color,
            background_color=(0, 0, 0)
        )

        # NVME Temperature Section
        lcd_comm.DisplayText(
            text="NVME",
            x=5,
            y=410,
            font="roboto/Roboto-Bold.ttf",
            font_size=24,
            font_color=LIGHT_YELLOW,
            background_color=(0, 0, 0)
        )
        
        # Display NVME temperatures
        lcd_comm.DisplayText(
            text=f"SK Hynix: {data['nvme_0100_temp']:.1f}°C  |  990 Evo: {data['nvme_8100_temp']:.1f}°C",
            x=5,
            y=440,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0)
        )

        time.sleep(30)

if __name__ == "__main__":
    main()
