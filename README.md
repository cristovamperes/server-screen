# ![Icon](https://raw.githubusercontent.com/mathoudebine/turing-smart-screen-python/main/res/icons/monitor-icon-17865/24.png) Custom Smart Screen Display

### DISCLAIMER - PLEASE READ

This project is a fork of the original [turing-smart-screen-python](https://github.com/mathoudebine/turing-smart-screen-python) project. It is **not affiliated, associated, authorized, endorsed by, or in any way officially connected with Turing / XuanFang / Kipye brands**, or any of their subsidiaries, affiliates, manufacturers, or sellers of their products. All product and company names are the registered trademarks of their original owners.

This fork focuses on a custom implementation for displaying homelab metrics using a Python script (`screen_update.py`) on a small IPS USB-C (UART) display.

---

![Linux](https://img.shields.io/badge/Linux-FCC624?style=for-the-badge&logo=linux&logoColor=black) ![Windows](https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white) ![macOS](https://img.shields.io/badge/mac%20os-000000?style=for-the-badge&logo=apple&logoColor=white) ![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-A22846?style=for-the-badge&logo=Raspberry%20Pi&logoColor=white) ![Python](https://img.shields.io/badge/Python-3.8/3.12-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54) [![Licence](https://img.shields.io/github/license/mathoudebine/turing-smart-screen-python?style=for-the-badge)](./LICENSE)

## Overview

This repo runs `screen_update.py`, which:

- Reads metrics from InfluxDB (UPS + servers + NVME temps).
- Gets WAN ISP/location via `ip-api.com` with a cached fallback to avoid flashing back to `Unknown`.
- Renders a fixed layout with sections: **INTERNET**, **UPS**, **SERVERS** (SMALL/BIG), **NVME**.

## Key Behavior (current)

- The background is drawn once at startup (`black_bg.png`), not every loop.
- Section headers/labels are drawn once at startup (separator line + INTERNET/UPS/SERVERS/NVME + table labels).
- The loop only redraws *dynamic values* every **15 seconds** (`time.sleep(15)`).
- Dynamic rows/cells use fixed `width`/`height` in `DisplayText(...)` so values that shrink don't leave artifacts.

## Configuration

Create a `.env` file (same folder as `screen_update.py`) with at least:

```
INFLUXDB_URL=...
INFLUXDB_TOKEN=...
INFLUXDB_ORG=...
INFLUXDB_BUCKET=homelab
```

Server selection uses a tag (defaults to `server_alias`). You can override:

```
INFLUXDB_SERVER_TAG=server_alias
SMALLSERVER_ALIAS=smallserver
BIGSERVER_ALIAS=bigserver
```

## Running

Use the existing virtual environment for this repo (local) or the pre-created `/root/server-screen/venv` (host). Avoid installing packages on the host.

Run:

```bash
python screen_update.py
```

## Making Layout Changes

All drawing happens in `screen_update.py` inside `main()`.

Guidelines:

- Prefer drawing static labels/headers once before the `while True:` loop.
- For values that change, use fixed-size redraw regions: `DisplayText(width=..., height=...)`.
- If you add new sections, follow the same spacing constants already defined in `screen_update.py`.

## Deployment Workflow (local -> GitHub -> host)

This setup is deployed by **git only** (no direct file copying to the host).

1) Make changes locally (usually `screen_update.py`).

2) Commit + push to GitHub:

```bash
git status
git add -A
git commit -m "Your message"
git push origin main
```

3) Pull on the host and restart the service:

```bash
ssh -i "D:\Dropbox\Documentos Pessoais\SSHs\homelab" root@192.168.0.60
cd /root/server-screen
git pull --ff-only origin main
./venv/bin/python -m py_compile screen_update.py
systemctl restart server-screen.service
systemctl status server-screen.service --no-pager -l
```

## Acknowledgments

This project is based on the [turing-smart-screen-python](https://github.com/mathoudebine/turing-smart-screen-python) project. Special thanks to the original authors for their work on the smart screen abstraction library.
