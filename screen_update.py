import json
import os
import time

from dotenv import load_dotenv
from influxdb_client import InfluxDBClient
from PIL import Image

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
SERVERS_Y = 300
LABEL_COL_X = 5
LABEL_COL_W = 95
SMALL_COL_X = 105
SMALL_COL_W = 100
DIVIDER_X = 210
BIG_COL_X = 220
BIG_COL_W = 95
ROW_H = 28
TABLE_FONT_SIZE = 20
SECTION_FONT_SIZE = 24

NVME_Y = 385
NVME_LINE_Y = 415

FONT_TABLE = "roboto/Roboto-Regular.ttf"
FONT_TABLE_BOLD = "roboto/Roboto-Bold.ttf"

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
    |> filter(fn: (r) => r["_field"] == "download" or r["_field"] == "upload" or r["_field"] == "location" or r["_field"] == "latency")
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

        # Display location on the next line
        lcd_comm.DisplayText(
            text=f"Location: {data['location']}",
            x=5,
            y=90,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0)
        )

        lcd_comm.DisplayText(
            text=f"Latency: {data['latency']:.0f}ms",
            x=5,
            y=110,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0)
        )

        # Display internet metrics in a single line with symbols
        internet_metrics = f"Up: {data['upload']:.1f}  |  Down:{data['download']:.1f}"
        lcd_comm.DisplayText(
            text=internet_metrics,
            x=5,
            y=130,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0)
        )

        # UPS Status Section
        lcd_comm.DisplayText(
            text="UPS",
            x=5,
            y=170,
            font="roboto/Roboto-Bold.ttf",
            font_size=24,
            font_color=LIGHT_GREEN,
            background_color=(0, 0, 0)
        )
        y_pos = 200
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

        # Servers Section (two columns)
        lcd_comm.DisplayText(
            text="SERVERS",
            x=5,
            y=SERVERS_Y,
            font="roboto/Roboto-Bold.ttf",
            font_size=SECTION_FONT_SIZE,
            font_color=LIGHT_BLUE,
            background_color=(0, 0, 0),
        )
        lcd_comm.DisplayText(
            text="SMALL",
            x=SMALL_COL_X,
            y=SERVERS_Y,
            width=SMALL_COL_W,
            height=ROW_H,
            font=FONT_TABLE_BOLD,
            font_size=SECTION_FONT_SIZE,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="right",
            anchor="rt",
        )
        lcd_comm.DisplayText(
            text="|",
            x=DIVIDER_X,
            y=SERVERS_Y,
            font=FONT_TABLE_BOLD,
            font_size=SECTION_FONT_SIZE,
            font_color=WHITE,
            background_color=(0, 0, 0),
        )
        lcd_comm.DisplayText(
            text="BIG",
            x=BIG_COL_X,
            y=SERVERS_Y,
            width=BIG_COL_W,
            height=ROW_H,
            font=FONT_TABLE_BOLD,
            font_size=SECTION_FONT_SIZE,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="right",
            anchor="rt",
        )

        row1_y = SERVERS_Y + 34
        row2_y = row1_y + 26

        lcd_comm.DisplayText(
            text="CPU Temp",
            x=LABEL_COL_X,
            y=row1_y,
            width=LABEL_COL_W,
            height=ROW_H,
            font=FONT_TABLE,
            font_size=TABLE_FONT_SIZE,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="left",
            anchor="lt",
        )
        lcd_comm.DisplayText(
            text=_format_temp(data.get("smallserver_cpu_temp")),
            x=SMALL_COL_X,
            y=row1_y,
            width=SMALL_COL_W,
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
            x=BIG_COL_X,
            y=row1_y,
            width=BIG_COL_W,
            height=ROW_H,
            font=FONT_TABLE,
            font_size=TABLE_FONT_SIZE,
            font_color=temp_to_color(data.get("bigserver_cpu_temp")),
            background_color=(0, 0, 0),
            align="right",
            anchor="rt",
        )

        lcd_comm.DisplayText(
            text="RAM Usage:",
            x=LABEL_COL_X,
            y=row2_y,
            width=LABEL_COL_W,
            height=ROW_H,
            font=FONT_TABLE,
            font_size=TABLE_FONT_SIZE,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="left",
            anchor="lt",
        )
        lcd_comm.DisplayText(
            text=_format_percent(data.get("smallserver_ram_used_percent")),
            x=SMALL_COL_X,
            y=row2_y,
            width=SMALL_COL_W,
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
            x=BIG_COL_X,
            y=row2_y,
            width=BIG_COL_W,
            height=ROW_H,
            font=FONT_TABLE,
            font_size=TABLE_FONT_SIZE,
            font_color=WHITE,
            background_color=(0, 0, 0),
            align="right",
            anchor="rt",
        )

        # NVME Temperature Section
        lcd_comm.DisplayText(
            text="NVME",
            x=5,
            y=NVME_Y,
            font="roboto/Roboto-Bold.ttf",
            font_size=SECTION_FONT_SIZE,
            font_color=LIGHT_YELLOW,
            background_color=(0, 0, 0),
        )
        lcd_comm.DisplayText(
            text=f"SK Hynix: {_format_temp(data.get('nvme_0100_temp'))}  |  990 Evo: {_format_temp(data.get('nvme_8100_temp'))}",
            x=5,
            y=NVME_LINE_Y,
            font="roboto/Roboto-Regular.ttf",
            font_size=20,
            font_color=WHITE,
            background_color=(0, 0, 0),
        )

        time.sleep(30)

if __name__ == "__main__":
    main()
