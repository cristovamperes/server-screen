# ![Icon](https://raw.githubusercontent.com/mathoudebine/turing-smart-screen-python/main/res/icons/monitor-icon-17865/24.png) Custom Smart Screen Display

### ⚠️ DISCLAIMER - PLEASE READ ⚠️

This project is a fork of the original [turing-smart-screen-python](https://github.com/mathoudebine/turing-smart-screen-python) project. It is **not affiliated, associated, authorized, endorsed by, or in any way officially connected with Turing / XuanFang / Kipye brands**, or any of their subsidiaries, affiliates, manufacturers, or sellers of their products. All product and company names are the registered trademarks of their original owners.

This fork focuses on a custom implementation for displaying system metrics using a Python script (`screen_update.py`) on small IPS USB-C (UART) displays.

---

![Linux](https://img.shields.io/badge/Linux-FCC624?style=for-the-badge&logo=linux&logoColor=black) ![Windows](https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white) ![macOS](https://img.shields.io/badge/mac%20os-000000?style=for-the-badge&logo=apple&logoColor=white) ![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-A22846?style=for-the-badge&logo=Raspberry%20Pi&logoColor=white) ![Python](https://img.shields.io/badge/Python-3.8/3.12-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54) [![Licence](https://img.shields.io/github/license/mathoudebine/turing-smart-screen-python?style=for-the-badge)](./LICENSE)

## Overview

This fork provides a Python script (`screen_update.py`) that connects to an InfluxDB database to retrieve system metrics and displays them on a small IPS USB-C display. The script is designed to run on various operating systems, including macOS, Windows, and Linux (including Raspberry Pi).

### Features

- **System Metrics Display**: Retrieves and displays internet metrics, UPS status, and CPU temperature.
- **Customizable Display**: Uses a text-based temperature gauge with color coding for easy readability.
- **Cross-Platform**: Compatible with multiple operating systems that support Python 3.8+.
- **Easy Setup**: Utilizes environment variables for configuration, making it easy to adapt to different setups.

### How to Use

1. **Clone the Repository**:    ```bash
   git clone <your-fork-url>
   cd <your-fork-directory>   ```

2. **Install Dependencies**:
   Ensure you have Python 3.8+ and the required packages installed. You can use `pip` to install the dependencies:   ```bash
   pip install -r requirements.txt   ```

3. **Configure Environment Variables**:
   Create a `.env` file in the root directory with the following variables:   ```plaintext
   INFLUXDB_URL=<your-influxdb-url>
   INFLUXDB_TOKEN=<your-influxdb-token>
   INFLUXDB_ORG=<your-influxdb-organization>   ```

4. **Run the Script**:
   Execute the script to start displaying system metrics:   ```bash
   python server-screen/screen_update.py   ```

### Customization

- **Display Settings**: Modify the `screen_update.py` script to change display settings such as font, colors, and layout.
- **Data Sources**: Adjust the InfluxDB queries to fetch different metrics or from different buckets.

### Troubleshooting

If you encounter issues, ensure that your environment variables are correctly set and that your InfluxDB instance is accessible. For further assistance, refer to the [original project's issues page](https://github.com/mathoudebine/turing-smart-screen-python/issues).

## Acknowledgments

This project is based on the [turing-smart-screen-python](https://github.com/mathoudebine/turing-smart-screen-python) project. Special thanks to the original authors for their work on the smart screen abstraction library.
