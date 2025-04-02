import psutil
import time
import platform
import json
from flask import Flask, jsonify
import GPUtil
import wmi
import pythoncom
import asyncio
from winsdk.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
import threading
import sys
import msvcrt
from flask_socketio import SocketIO
import logging
import os
import traceback
from datetime import datetime
import clr  # pythonnet
import shutil

# Configure logging
log_directory = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
# In executable mode, use the executable's directory
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
    log_directory = os.path.join(application_path, 'logs')

# Create logs directory if it doesn't exist
os.makedirs(log_directory, exist_ok=True)

# Setup logging with timestamp in filename
log_filename = os.path.join(log_directory, f'system_monitor_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Initialize OpenHardwareMonitorLib
try:
    # Get the directory where the script/executable is located
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        script_dir = os.path.dirname(sys.executable)
    else:
        # Running as script
        script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Create a local temp directory
    temp_dir = os.path.join(os.environ['TEMP'], 'ohm_monitor')
    os.makedirs(temp_dir, exist_ok=True)
    
    # Copy DLL to temp directory
    source_dll = os.path.join(script_dir, "OpenHardwareMonitorLib.dll")
    temp_dll = os.path.join(temp_dir, "OpenHardwareMonitorLib.dll")
    
    # Copy the DLL if it doesn't exist in temp
    if not os.path.exists(temp_dll):
        shutil.copy2(source_dll, temp_dll)
    
    # Set up .NET configuration
    import clr
    clr.AddReference("System.Security")
    from System.Security import SecurityManager
    from System.Reflection import Assembly
    
    # Set security policy to allow loading from remote sources
    SecurityManager.IsGranted(None)  # This will initialize the security manager
    
    # Load the assembly using Assembly.LoadFrom
    assembly = Assembly.LoadFile(temp_dll)
    

    from OpenHardwareMonitor.Hardware import Computer
    from OpenHardwareMonitor.Hardware import HardwareType
    from OpenHardwareMonitor.Hardware import SensorType
    OHM_AVAILABLE = True
except Exception as e:
    logger.error(f"Failed to initialize OpenHardwareMonitorLib: {str(e)}")
    OHM_AVAILABLE = False

# Global computer instance for hardware monitoring
computer = None

def initialize_hardware_monitoring():
    global computer
    if not OHM_AVAILABLE:
        return False
    
    try:
        computer = Computer()
        computer.CPUEnabled = True
        computer.GPUEnabled = True
        
        # Enable CPU temperature monitoring
        for hardware in computer.Hardware:
            if hardware.HardwareType == HardwareType.CPU:
                # Enable temperature monitoring for CPU
                hardware.Enabled = True
                for sub_hardware in hardware.SubHardware:
                    sub_hardware.Enabled = True
        
        computer.Open()
        return True
    except Exception as e:
        logger.error(f"Failed to initialize hardware monitoring: {str(e)}")
        return False

def update_hardware_monitoring():
    if computer and OHM_AVAILABLE:
        try:
            # Try to update each hardware component individually
            for hardware in computer.Hardware:
                hardware.Update()
        except Exception as e:
            logger.error(f"Failed to update hardware monitoring: {str(e)}")

# Log startup information
# logger.info(f"Application starting. Log file: {log_filename}")
# logger.info(f"Python version: {sys.version}")
# logger.info(f"Platform: {platform.platform()}")

# Global exception handler
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        # Don't log keyboard interrupt
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    
    # Write to a separate crash file for visibility
    crash_filename = os.path.join(log_directory, f'CRASH_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    with open(crash_filename, 'w') as f:
        f.write(f"CRASH REPORT - {datetime.now()}\n")
        f.write(f"Error type: {exc_type.__name__}\n")
        f.write(f"Error message: {exc_value}\n\n")
        f.write("Traceback:\n")
        f.write(''.join(traceback.format_exception(exc_type, exc_value, exc_traceback)))

# Set the exception handler
sys.excepthook = handle_exception

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

_last_media_info = {
    'title': None,
    'artist': None,
    'album_title': None,
    'thumbnail_sent': False
}



def get_cpu_info():
    try:
        cpu_percent = psutil.cpu_percent(interval=1, percpu=True)
        cpu_freq = psutil.cpu_freq()
        cpu_info = {
            "usage_per_core": cpu_percent,
            "total_usage": sum(cpu_percent) / len(cpu_percent),
            "freq_current": cpu_freq.current if cpu_freq else None,
            "freq_max": cpu_freq.max if cpu_freq else None,
            "cores_physical": psutil.cpu_count(logical=False),
            "cores_total": psutil.cpu_count(logical=True),
            "temperature": []  # Initialize as empty array
        }

        # Try different methods to get CPU temperature
        if platform.system() == 'Windows':
            # Method 1: OpenHardwareMonitorLib
            if OHM_AVAILABLE and computer:
                try:
                    update_hardware_monitoring()
                    for hardware in computer.Hardware:
                        if hardware.HardwareType == HardwareType.CPU:
                            for sensor in hardware.Sensors:
                                if sensor.SensorType == SensorType.Temperature:
                                    try:
                                        temp_value = float(sensor.Value)
                                        temp_value = round(temp_value, 1)
                                        cpu_info["temperature"].append({
                                            "name": "CPU Package",
                                            "value": temp_value
                                        })
                                        break
                                    except (ValueError, TypeError) as e:
                                        logger.error(f"Error converting temperature value: {str(e)}")
                                        continue
                except Exception as e:
                    logger.error(f"OpenHardwareMonitorLib error: {str(e)}")

            # Method 2: WMI Temperature Probe
            if not cpu_info["temperature"]:
                try:
                    pythoncom.CoInitialize()
                    w = wmi.WMI()
                    temperature_probes = w.Win32_TemperatureProbe()
                    if temperature_probes:
                        try:
                            temp_value = float(temperature_probes[0].CurrentReading)
                            temp_value = round(temp_value, 1)
                            cpu_info["temperature"].append({
                                "name": "CPU Package",
                                "value": temp_value
                            })
                        except (ValueError, TypeError) as e:
                            logger.error(f"Error converting WMI Probe temperature: {str(e)}")
                except Exception as e:
                    logger.error(f"WMI Temperature Probe error: {str(e)}")
                finally:
                    pythoncom.CoUninitialize()

            # Method 3: WMI OpenHardwareMonitor
            if not cpu_info["temperature"]:
                try:
                    pythoncom.CoInitialize()
                    w = wmi.WMI(namespace="root\OpenHardwareMonitor")
                    sensors = w.Sensor()
                    for sensor in sensors:
                        if hasattr(sensor, 'SensorType') and hasattr(sensor, 'Name') and hasattr(sensor, 'Value'):
                            if sensor.SensorType == 'Temperature' and 'CPU' in sensor.Name:
                                try:
                                    temp_value = float(sensor.Value)
                                    temp_value = round(temp_value, 1)
                                    cpu_info["temperature"].append({
                                        "name": "CPU Package",
                                        "value": temp_value
                                    })
                                    break
                                except (ValueError, TypeError) as e:
                                    logger.error(f"Error converting WMI OpenHardwareMonitor temperature: {str(e)}")
                                    continue
                except Exception as e:
                    logger.error(f"WMI OpenHardwareMonitor error: {str(e)}")
                finally:
                    pythoncom.CoUninitialize()

            # Method 4: WMI Thermal Zone
            if not cpu_info["temperature"]:
                try:
                    pythoncom.CoInitialize()
                    w = wmi.WMI(namespace="root\WMI")
                    thermal_zones = w.MSAcpi_ThermalZoneTemperature()
                    if thermal_zones:
                        try:
                            temp = (thermal_zones[0].CurrentTemperature - 2732) / 10.0
                            temp_value = round(temp, 1)
                            cpu_info["temperature"].append({
                                "name": "CPU Package",
                                "value": temp_value
                            })
                        except (ValueError, TypeError) as e:
                            logger.error(f"Error converting Thermal Zone temperature: {str(e)}")
                except Exception as e:
                    logger.error(f"WMI Thermal Zone error: {str(e)}")
                finally:
                    pythoncom.CoUninitialize()

        return cpu_info
    except Exception as e:
        logger.error(f"Error in get_cpu_info: {str(e)}")
        return {"error": str(e)}


def get_gpu_info():
    try:
        gpu_info = []
        
        # Get basic GPU info using WMI
        com_initialized = False
        try:
            pythoncom.CoInitialize()
            com_initialized = True
            
            w = wmi.WMI()
            for gpu in w.Win32_VideoController():
                gpu_data = {
                    "name": gpu.Name,
                    "driver_version": gpu.DriverVersion,
                    "video_processor": gpu.VideoProcessor,
                    "adapter_ram": gpu.AdapterRAM if gpu.AdapterRAM else "Unknown",
                    "current_resolution": f"{gpu.CurrentHorizontalResolution}x{gpu.CurrentVerticalResolution}" if gpu.CurrentHorizontalResolution else "Unknown",
                    "temperature": "Not available - OpenHardwareMonitorLib not available"
                }
                gpu_info.append(gpu_data)

            # Get GPU temperature using OpenHardwareMonitorLib
            if platform.system() == 'Windows' and OHM_AVAILABLE and computer:
                try:
                    update_hardware_monitoring()
                    temperature_found = False
                    
                    for hardware in computer.Hardware:
                        if hardware.HardwareType == HardwareType.GpuNvidia or hardware.HardwareType == HardwareType.GpuAti:
                            for sensor in hardware.Sensors:
                                if sensor.SensorType == SensorType.Temperature:
                                    for gpu in gpu_info:
                                        gpu["temperature"] = sensor.Value
                                        temperature_found = True
                    
                    if not temperature_found:
                        for gpu in gpu_info:
                            gpu["temperature"] = "No GPU temperature sensors found"
                except Exception as e:
                    logger.error(f"Error retrieving GPU temperature: {str(e)}")
                    for gpu in gpu_info:
                        gpu["temperature"] = "Error retrieving GPU temperature"
            
            return gpu_info
        finally:
            if com_initialized:
                pythoncom.CoUninitialize()
    except Exception as e:
        logger.error(f"Error in get_gpu_info: {str(e)}")
        return [{"error": str(e)}]

def get_memory_info():
    mem = psutil.virtual_memory()
    return {
        "total": mem.total,
        "available": mem.available,
        "used": mem.used,
        "percent": mem.percent
    }

async def get_media_info():
    global _last_media_info
    
    try:
        sessions = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        current_session = sessions.get_current_session()
        
        if current_session:
            info = await current_session.try_get_media_properties_async()
            
            if info:
                # Check if we have a new song
                is_new_song = (
                    info.title != _last_media_info['title'] or
                    info.artist != _last_media_info['artist'] or
                    info.album_title != _last_media_info['album_title']
                )
                
                media_info = {
                    "title": info.title,
                    "artist": info.artist,
                    "album_title": info.album_title,
                    "album_artist": info.album_artist,
                    "playback_status": str(current_session.get_playback_info().playback_status),
                    "thumbnail": None,
                    "is_new_song": is_new_song
                }
                
                # Only get thumbnail if this is a new song
                if is_new_song and info.thumbnail:
                    try:
                        from winsdk.windows.storage.streams import DataReader
                        import base64
                        
                        # Get the thumbnail stream
                        thumbnail_stream = await info.thumbnail.open_read_async()
                        reader = DataReader(thumbnail_stream)
                        
                        # Get buffer size and load data into buffer
                        buffer_size = thumbnail_stream.size
                        buffer = await reader.load_async(buffer_size)
                        
                        # Create byte array and read from buffer
                        bytes_array = bytearray(buffer_size)
                        reader.read_bytes(bytes_array)
                        
                        # Convert to base64 for transmission
                        base64_thumbnail = base64.b64encode(bytes_array).decode('utf-8')
                        media_info["thumbnail"] = f"data:image/jpeg;base64,{base64_thumbnail}"
                        _last_media_info['thumbnail_sent'] = True
                    except Exception as e:
                        media_info["thumbnail_error"] = str(e)
                
                # Update the last media info
                _last_media_info = {
                    'title': info.title,
                    'artist': info.artist,
                    'album_title': info.album_title,
                    'thumbnail_sent': _last_media_info['thumbnail_sent'] if not is_new_song else True
                }
                
                return media_info
    except Exception as e:
        return {"error": str(e)}
    
    # Reset last media info if nothing is playing
    _last_media_info = {
        'title': None,
        'artist': None,
        'album_title': None,
        'thumbnail_sent': False
    }
    
    return {"status": "No media playing"}


@app.route('/api/system/stats', methods=['GET'])
def get_system_stats():
    stats = {
        "timestamp": time.time(),
        "cpu": get_cpu_info(),
        "gpu": get_gpu_info(),
        "memory": get_memory_info(),
        "media": asyncio.run(get_media_info())  
    }
    #print(stats)
    return jsonify(stats)


def keyboard_input_thread():
    print("Press 'q' to quit the server...")
    while True:
        if msvcrt.kbhit():
            key = msvcrt.getch().decode('utf-8').lower()
            if key == 'q':
                print("Quitting server...")
                # Force exit the application
                os._exit(0)
        time.sleep(0.1)

def background_thread():
    while True:
        try:
            stats = {
                "timestamp": time.time(),
                "cpu": get_cpu_info(),
                "gpu": get_gpu_info(),
                "memory": get_memory_info(),
                "media": asyncio.run(get_media_info())
            }
            socketio.emit('system_stats', stats)
        except Exception as e:
            logger.error(f"Error in background_thread: {str(e)}")
        time.sleep(1)  # Update every second

if __name__ == '__main__':
    try:
        logger.info("Starting system monitoring server...")
        print("Starting system monitoring server...")
        
        # Initialize hardware monitoring
        if initialize_hardware_monitoring():
            print("Hardware monitoring initialized successfully")
        else:
            print("Warning: Hardware monitoring not available - temperature readings will not be available")
        
        # Start keyboard input thread
        import os
        keyboard_thread = threading.Thread(target=keyboard_input_thread, daemon=True)
        keyboard_thread.start()
        
        # Start background thread for stats
        stats_thread = threading.Thread(target=background_thread, daemon=True)
        stats_thread.start()
        
        # Run with socketio instead of app.run()
        socketio.run(app, host='0.0.0.0', port=5000, debug=False, allow_unsafe_werkzeug=True)
    except Exception as e:
        logger.critical(f"Fatal error in main thread: {str(e)}")
        print(f"FATAL ERROR: {str(e)}")
        print(f"Check logs at: {log_filename}")
        # Keep console open for 30 seconds so user can see the error
        time.sleep(30)