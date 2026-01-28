import json
import os
import time

from dotenv import load_dotenv
from influxdb_client import InfluxDBClient
from PIL import Image
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from library.lcd.lcd_comm import Orientation
from library.lcd.lcd_comm_rev_a import LcdCommRevA

# Load environment variables at the start of your script
load_dotenv()

# Colors
WHITE = (255, 255, 255)
LIGHT_BLUE = (135, 206, 235)    # Sky blue
LIGHT_GREEN = (144, 238, 144)   # Light green
LIGHT_RED = (255, 160, 160)     # Light red for CPU temp
LIGHT_YELLOW = (255, 255, 153)   # Light yellow for CPU temp

# WAN/IP details (same approach as `origin/main`)
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

# Influx / host config
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "homelab")
# Name of the Influx tag that identifies which server a metric belongs to.
# You mentioned you created a `server_alias` tag, so that's the default.
INFLUXDB_SERVER_TAG = os.getenv("INFLUXDB_SERVER_TAG", os.getenv("INFLUXDB_HOST_TAG", "server_alias"))

SMALLSERVER_ALIAS = os.getenv("SMALLSERVER_ALIAS", os.getenv("SMALLSERVER_HOST", "smallserver"))
BIGSERVER_ALIAS = os.getenv("BIGSERVER_ALIAS", os.getenv("BIGSERVER_HOST", "bigserver"))

SERVER_TEMP_MEASUREMENT = os.getenv("SERVER_TEMP_MEASUREMENT", "sensors")
SERVER_TEMP_FIELD = os.getenv("SERVER_TEMP_FIELD", "temp_input")
SERVER_TEMP_CHIP = os.getenv("SERVER_TEMP_CHIP", "coretemp-isa-0000")
SERVER_TEMP_FEATURE = os.getenv("SERVER_TEMP_FEATURE", "package_id_0")

SERVER_RAM_MEASUREMENT = os.getenv("SERVER_RAM_MEASUREMENT", "mem")
SERVER_RAM_FIELD = os.getenv("SERVER_RAM_FIELD", "used_percent")

# NVME temps (defaults assume the drives exist on BIGSERVER)
NVME_SERVER_ALIAS = os.getenv("NVME_SERVER_ALIAS", BIGSERVER_ALIAS)
NVME_TEMP_FEATURE = os.getenv("NVME_TEMP_FEATURE", "composite")
NVME_0100_CHIP = os.getenv("NVME_0100_CHIP", "nvme-pci-0100")
NVME_8100_CHIP = os.getenv("NVME_8100_CHIP", "nvme-pci-8100")

# Layout constants (320x480 portrait)
# Keep consistent spacing:
# - 40px between last line of a section and next section header
# - 30px between section header and first row
# - 20px between consecutive rows
INTERNET_Y = 60
LABEL_COL_X = 5
LABEL_COL_W = 120
DIVIDER_X = 240
SMALL_RIGHT_X = DIVIDER_X - 10
BIG_RIGHT_X = 315
ROW_H = 28
TABLE_FONT_SIZE = 20
SECTION_FONT_SIZE = 24

SECTION_TO_SECTION_GAP = 40
HEADER_TO_FIRST_ROW_GAP = 30
ROW_GAP = 20

FONT_TABLE = "roboto/Roboto-Regular.ttf"
FONT_TABLE_BOLD = "roboto/Roboto-Bold.ttf"


def get_public_ip():
    try:
        with urlopen(IPIFY_URL, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("ip", "Unknown")
    except (URLError, HTTPError, TimeoutError, json.JSONDecodeError):
        return "Unknown"


def get_ip_details():
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
    internet_query = f'''
    from(bucket: "{INFLUXDB_BUCKET}")
    |> range(start: -1h)
    |> filter(fn: (r) => r["_field"] == "download" or r["_field"] == "upload" or r["_field"] == "location" or r["_field"] == "latency" or r["_field"] == "isp")
    |> last()
    '''

    # UPS metrics query
    ups_query = f'''
    from(bucket: "{INFLUXDB_BUCKET}")
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

    def _query_last_value(query: str):
        tables = client.query_api().query(query)
        for table in tables:
            for record in table.records:
                return record.get_value()
        return None

    def _server_eq(server_alias: str) -> str:
        return f'r["{INFLUXDB_SERVER_TAG}"] == {json.dumps(server_alias)}'

    def _server_cpu_temp_query(host_value: str) -> str:
        return f'''
        from(bucket: "{INFLUXDB_BUCKET}")
        |> range(start: -5m)
        |> filter(fn: (r) => r["_measurement"] == "{SERVER_TEMP_MEASUREMENT}")
        |> filter(fn: (r) => r["_field"] == "{SERVER_TEMP_FIELD}")
        |> filter(fn: (r) => {_server_eq(host_value)})
        |> filter(fn: (r) => r["chip"] == "{SERVER_TEMP_CHIP}")
        |> filter(fn: (r) => r["feature"] == "{SERVER_TEMP_FEATURE}")
        |> last()
        '''

    def _server_ram_used_query(host_value: str) -> str:
        return f'''
        from(bucket: "{INFLUXDB_BUCKET}")
        |> range(start: -5m)
        |> filter(fn: (r) => r["_measurement"] == "{SERVER_RAM_MEASUREMENT}")
        |> filter(fn: (r) => r["_field"] == "{SERVER_RAM_FIELD}")
        |> filter(fn: (r) => {_server_eq(host_value)})
        |> last()
        '''

    def _server_nvme_temp_query(server_alias: str, chip_value: str) -> str:
        return f'''
        from(bucket: "{INFLUXDB_BUCKET}")
        |> range(start: -5m)
        |> filter(fn: (r) => r["_measurement"] == "{SERVER_TEMP_MEASUREMENT}")
        |> filter(fn: (r) => r["_field"] == "{SERVER_TEMP_FIELD}")
        |> filter(fn: (r) => {_server_eq(server_alias)})
        |> filter(fn: (r) => r["chip"] == "{chip_value}")
        |> filter(fn: (r) => r["feature"] == "{NVME_TEMP_FEATURE}")
        |> last()
        '''

    # Initialize values
    data = {
        'download': 0,
        'upload': 0,
        'location': "Unknown",
        'isp': "Unknown",
        'latency': 0,
        'ups_status': "Unknown",
        'load_percent': 0,
        'battery_charge_percent': 0,
        'battery_charger_status': "Unknown",
        'battery_voltage': 0,
        'input_voltage': 0,
        'output_voltage': 0,
        'internal_temp': 0,
        'smallserver_cpu_temp': None,
        'bigserver_cpu_temp': None,
        'smallserver_ram_used_percent': None,
        'bigserver_ram_used_percent': None,
        'nvme_0100_temp': None,
        'nvme_8100_temp': None,
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

        # Server metrics (two columns)
        data['smallserver_cpu_temp'] = _query_last_value(_server_cpu_temp_query(SMALLSERVER_ALIAS))
        data['bigserver_cpu_temp'] = _query_last_value(_server_cpu_temp_query(BIGSERVER_ALIAS))
        data['smallserver_ram_used_percent'] = _query_last_value(_server_ram_used_query(SMALLSERVER_ALIAS))
        data['bigserver_ram_used_percent'] = _query_last_value(_server_ram_used_query(BIGSERVER_ALIAS))

        # NVME temps (typically on BIGSERVER, configurable)
        data['nvme_0100_temp'] = _query_last_value(_server_nvme_temp_query(NVME_SERVER_ALIAS, NVME_0100_CHIP))
        data['nvme_8100_temp'] = _query_last_value(_server_nvme_temp_query(NVME_SERVER_ALIAS, NVME_8100_CHIP))

        return data
    finally:
        client.close()

def temp_to_color(temp_value):
    if temp_value is None:
        return WHITE
    try:
        temp_value = float(temp_value)
    except (TypeError, ValueError):
        return WHITE

    if temp_value < 60:
        return LIGHT_GREEN
    if temp_value < 80:
        return LIGHT_YELLOW
    return LIGHT_RED


def _format_temp(value):
    try:
        return f"{float(value):.1f}C"
    except (TypeError, ValueError):
        return "--.-C"


def _format_percent(value):
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "--.-%"


def _capitalize_only_first(value):
    if value is None:
        return "Unknown"
    value = str(value).strip()
    if not value or value.lower() == "unknown":
        return "Unknown"
    return value[:1].upper() + value[1:].lower()

def main():
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

    # Draw black background once (avoid full-screen wipe on every refresh)
    if not os.path.exists("black_bg.png"):
        Image.new("RGB", (320, 480), color=(0, 0, 0)).save("black_bg.png")
    lcd_comm.DisplayBitmap("black_bg.png")

    # Fixed regions for dynamic values (prevents leftover characters without full clears)
    FULL_LINE_W = 315
    FULL_LINE_H = ROW_H
    CELL_W = 70
    SMALL_CELL_X = SMALL_RIGHT_X - CELL_W
    BIG_CELL_X = BIG_RIGHT_X - CELL_W

    while True:
        # Get latest data
        data = get_system_data()

        # Prefer WAN/IP-derived ISP/location (fallback to last successful values)
        ip_details = get_ip_details()
        if ip_details.get("location_city") and ip_details["location_city"] != "Unknown":
            data["location"] = ip_details["location_city"]
        if ip_details.get("isp") and ip_details["isp"] != "Unknown":
            data["isp"] = ip_details["isp"]

        # Display time and date
        current_time = time.strftime("%H:%M:%S")
        current_date = time.strftime("%d/%m/%Y")
        lcd_comm.DisplayText(
            text=current_time,
            x=5,
            y=5,
            width=155,
            height=34,
            font="roboto/Roboto-Bold.ttf",
            font_size=24,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="left",
            anchor="lt",
        )
        lcd_comm.DisplayText(
            text=current_date,
            x=190,
            y=5,
            width=125,
            height=34,
            font="roboto/Roboto-Bold.ttf",
            font_size=24,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="right",
            anchor="rt",
        )

        # Draw a line below time and date
        lcd_comm.DisplayText(
            text="____________________________________",
            x=5,
            y=25,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0),
        )

        # Internet Status Section
        internet_y = INTERNET_Y
        lcd_comm.DisplayText(
            text="INTERNET",
            x=5,
            y=internet_y,
            font="roboto/Roboto-Bold.ttf",
            font_size=24,
            font_color=LIGHT_BLUE,
            background_color=(0, 0, 0),
        )

        lcd_comm.DisplayText(
            text=f"Location: {data['location']}",
            x=5,
            y=internet_y + HEADER_TO_FIRST_ROW_GAP,
            width=FULL_LINE_W,
            height=FULL_LINE_H,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="left",
            anchor="lt",
        )

        lcd_comm.DisplayText(
            text=f"ISP: {_capitalize_only_first(data['isp'])}",
            x=5,
            y=internet_y + HEADER_TO_FIRST_ROW_GAP + ROW_GAP,
            width=FULL_LINE_W,
            height=FULL_LINE_H,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="left",
            anchor="lt",
        )

        lcd_comm.DisplayText(
            text=f"Latency: {data['latency']:.0f}ms",
            x=5,
            y=internet_y + HEADER_TO_FIRST_ROW_GAP + 2 * ROW_GAP,
            width=FULL_LINE_W,
            height=FULL_LINE_H,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="left",
            anchor="lt",
        )

        internet_metrics = f"Up: {data['upload']:.1f}  |  Down:{data['download']:.1f}"
        internet_last_line_y = internet_y + HEADER_TO_FIRST_ROW_GAP + 3 * ROW_GAP
        lcd_comm.DisplayText(
            text=internet_metrics,
            x=5,
            y=internet_last_line_y,
            width=FULL_LINE_W,
            height=FULL_LINE_H,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="left",
            anchor="lt",
        )

        ups_y = internet_last_line_y + SECTION_TO_SECTION_GAP
        lcd_comm.DisplayText(
            text="UPS",
            x=5,
            y=ups_y,
            font="roboto/Roboto-Bold.ttf",
            font_size=24,
            font_color=LIGHT_GREEN,
            background_color=(0, 0, 0),
        )
        y_pos = ups_y + HEADER_TO_FIRST_ROW_GAP
        ups_info = [
            f"Status: {data['ups_status']}  |  Charger: {data['battery_charger_status']}",
            f"Battery: {data['battery_charge_percent']:.1f}%  |  {data['battery_voltage']:.1f}V",
            f"Load: {data['load_percent']:.1f}%  |  Temp: {data['internal_temp']:.1f}°C",
            f"Input: {data['input_voltage']:.1f}V  |  Output: {data['output_voltage']:.1f}V",
        ]
        for info in ups_info:
            lcd_comm.DisplayText(
                text=info,
                x=5,
                y=y_pos,
                width=FULL_LINE_W,
                height=FULL_LINE_H,
                font="roboto/Roboto-Regular.ttf",
                font_size=20,
                font_color=WHITE,
                background_color=(0, 0, 0),
                align="left",
                anchor="lt",
            )
            y_pos += ROW_GAP

        servers_y = (ups_y + HEADER_TO_FIRST_ROW_GAP + (len(ups_info) - 1) * ROW_GAP) + SECTION_TO_SECTION_GAP
        lcd_comm.DisplayText(
            text="SERVERS",
            x=LABEL_COL_X,
            y=servers_y,
            font="roboto/Roboto-Bold.ttf",
            font_size=SECTION_FONT_SIZE,
            font_color=LIGHT_BLUE,
            background_color=(0, 0, 0),
            align="left",
            anchor="lt",
        )
        lcd_comm.DisplayText(
            text="SMALL",
            x=SMALL_RIGHT_X,
            y=servers_y,
            font="roboto/Roboto-Bold.ttf",
            font_size=SECTION_FONT_SIZE,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="right",
            anchor="rt",
        )
        lcd_comm.DisplayText(
            text="|",
            x=DIVIDER_X,
            y=servers_y,
            font="roboto/Roboto-Bold.ttf",
            font_size=SECTION_FONT_SIZE,
            font_color=WHITE,
            background_color=(0, 0, 0),
        )
        lcd_comm.DisplayText(
            text="BIG",
            x=BIG_RIGHT_X,
            y=servers_y,
            font="roboto/Roboto-Bold.ttf",
            font_size=SECTION_FONT_SIZE,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="right",
            anchor="rt",
        )

        row1_y = servers_y + HEADER_TO_FIRST_ROW_GAP
        row2_y = row1_y + ROW_GAP

        lcd_comm.DisplayText(
            text="CPU Temp",
            x=LABEL_COL_X,
            y=row1_y,
            font=FONT_TABLE,
            font_size=TABLE_FONT_SIZE,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="left",
            anchor="lt",
        )
        lcd_comm.DisplayText(
            text=_format_temp(data.get("smallserver_cpu_temp")),
            x=SMALL_CELL_X,
            y=row1_y,
            width=CELL_W,
            height=ROW_H,
            font=FONT_TABLE,
            font_size=TABLE_FONT_SIZE,
            font_color=temp_to_color(data.get("smallserver_cpu_temp")),
            background_color=(0, 0, 0),
            align="right",
            anchor="rt",
        )
        lcd_comm.DisplayText(
            text="|",
            x=DIVIDER_X,
            y=row1_y,
            font=FONT_TABLE,
            font_size=TABLE_FONT_SIZE,
            font_color=WHITE,
            background_color=(0, 0, 0),
        )
        lcd_comm.DisplayText(
            text=_format_temp(data.get("bigserver_cpu_temp")),
            x=BIG_CELL_X,
            y=row1_y,
            width=CELL_W,
            height=ROW_H,
            font=FONT_TABLE,
            font_size=TABLE_FONT_SIZE,
            font_color=temp_to_color(data.get("bigserver_cpu_temp")),
            background_color=(0, 0, 0),
            align="right",
            anchor="rt",
        )

        lcd_comm.DisplayText(
            text="RAM Usage",
            x=LABEL_COL_X,
            y=row2_y,
            font=FONT_TABLE,
            font_size=TABLE_FONT_SIZE,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="left",
            anchor="lt",
        )
        lcd_comm.DisplayText(
            text=_format_percent(data.get("smallserver_ram_used_percent")),
            x=SMALL_CELL_X,
            y=row2_y,
            width=CELL_W,
            height=ROW_H,
            font=FONT_TABLE,
            font_size=TABLE_FONT_SIZE,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="right",
            anchor="rt",
        )
        lcd_comm.DisplayText(
            text="|",
            x=DIVIDER_X,
            y=row2_y,
            font=FONT_TABLE,
            font_size=TABLE_FONT_SIZE,
            font_color=WHITE,
            background_color=(0, 0, 0),
        )
        lcd_comm.DisplayText(
            text=_format_percent(data.get("bigserver_ram_used_percent")),
            x=BIG_CELL_X,
            y=row2_y,
            width=CELL_W,
            height=ROW_H,
            font=FONT_TABLE,
            font_size=TABLE_FONT_SIZE,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="right",
            anchor="rt",
        )

        nvme_y = row2_y + SECTION_TO_SECTION_GAP
        nvme_line_y = nvme_y + HEADER_TO_FIRST_ROW_GAP
        lcd_comm.DisplayText(
            text="NVME",
            x=5,
            y=nvme_y,
            font="roboto/Roboto-Bold.ttf",
            font_size=SECTION_FONT_SIZE,
            font_color=LIGHT_YELLOW,
            background_color=(0, 0, 0),
        )
        lcd_comm.DisplayText(
            text=f"UMIS: {_format_temp(data.get('nvme_0100_temp'))}  |  990 Evo: {_format_temp(data.get('nvme_8100_temp'))}",
            x=5,
            y=nvme_line_y,
            width=FULL_LINE_W,
            height=FULL_LINE_H,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="left",
            anchor="lt",
        )

        time.sleep(30)
if __name__ == "__main__":
    main()
