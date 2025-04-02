# System Monitor Server

A real-time hardware monitoring server that provides system metrics via REST API and WebSocket connections.
This is a server for TempDash app, but can be used and modified for any other app.

## Overview

This application collects and exposes system statistics including:
- CPU usage, frequency, temperature
- GPU information, including temperature (when available)
- Memory usage
- Currently playing media information

## Requirements

- Windows OS
- .NET Framework 4.5 or higher (for OpenHardwareMonitor integration)

## Installation

### Option 1: Use the Executable Release

1. Download the latest release from the [Releases](https://github.com/mechres/temp_dash_server/releases) page.
2. Extract the zip file to a location of your choice.
3. Run `SystemMonitor.exe` to start the server.

### Option 2: Run from Source

1. Clone this repository
2. Install requirements with: `pip install -r requirements.txt`
3. Get the "OpenHardwareMonitorLib.dll" from a safe source, and put it in the same folder
4. Run the server: `python app.py`

## Usage

Once started, the server will:

1. Listen on `http://localhost:5000` for REST API requests.
2. Provide WebSocket connections for real-time data at the same address.
3. Display hardware monitoring information in the mobile app.

### REST API

GET system statistics: `http://localhost:5000/api/system/stats`

### WebSocket Events

Connect to the WebSocket and listen for the `system_stats` event to receive real-time updates.

### Keyboard Controls

- Press `q` to quit the server.

## Logging

Logs are stored in the `logs` directory with timestamps:
- Regular logs: `system_monitor_YYYYMMDD_HHMMSS.log`
- Crash logs: `CRASH_YYYYMMDD_HHMMSS.log`

## Troubleshooting

### Missing Temperature Data

If temperature readings show as "Not available":
1. Make sure OpenHardwareMonitorLib.dll is present in the same directory as the application
2. Run the application as administrator for complete hardware access

### Connection Issues

- Make sure no other application is using port 5000
- Check if your firewall is blocking the application

## License

[MIT License](LICENSE)