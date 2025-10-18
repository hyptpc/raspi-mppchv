# MPPC High Voltage Module Controller

## Description

This application provides a web-based interface to control and monitor multiple Hamamatsu C11204-01 MPPC High Voltage Power Supply modules connected via serial ports (UART) to a Raspberry Pi or similar Linux system. It allows users to set voltages, turn outputs on/off, monitor voltage/current/temperature, and log both monitoring data and user actions.

## Directory Structure 📁

mppc_controller/
├── main.py                     # Main application entry point (FastAPI server)
├── config/
│   └── config.yaml             # Configuration file
├── data/                       # Stores database files (created automatically)
├── static/
│   ├── index.html              # Main Web UI file
│   ├── style.css               # CSS styles
│   └── script.js               # JavaScript for UI logic and charts
├── modules/
│   ├── __init__.py             # Makes 'modules' a Python package
│   ├── serial_com.py           # Handles serial communication logic
│   ├── db_measurements.py      # Database logic for monitoring data
│   ├── db_logs.py              # Database logic for action logs
│   └── logger.py               # Logging setup
└── requirements.txt            # Python dependencies

## Setup & Installation ⚙️

1.  **Clone the Repository:**
    ```bash
    git clone <your-repository-url>
    cd mppc_controller
    ```

2.  **Create & Activate Virtual Environment (Recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure:**
    * Edit `config/config.yaml` to match your setup:
        * Set `serial_ports` device names (e.g., `/dev/ttyAMA0`, `/dev/ttyUSB0`).
        * Adjust `monitoring_interval` if needed.
        * Set `test_mode.enabled` to `false` for use with real hardware.
        * Change `server.host` and `server.port` if necessary.
    * **Permissions (Linux):** Ensure the user running the script has permission to access the serial ports. Add the user to the `dialout` group:
        ```bash
        sudo usermod -a -G dialout $USER 
        # Log out and log back in, or reboot for the change to take effect.
        ```

5.  **Initialize Databases:**
    Run these commands once to create the database files in the `data/` directory:
    ```bash
    python modules/db_measurements.py
    python modules/db_logs.py
    ```

## Usage ▶️

1.  **Start the Server:**
    Navigate to the `mppc_controller` directory in your terminal and run:
    ```bash
    python main.py --config config/config.yaml
    ```
    (You can omit `--config config/config.yaml` if the file is in the default location).

2.  **Access the Web UI:**
    Open a web browser on a device connected to the **same local network** as the server and navigate to:
    `http://<server-ip-address>:<port>`
    (e.g., `http://192.168.20.5:8000`, using the host and port defined in `config.yaml`).

3.  **Use the Interface:**
    * Use the "Structured Commands" panel for common actions.
    * Use the "Raw Command" panel to send specific device commands from the manual.
    * Monitor status in the top-right panels.
    * View live data trends in the charts below.
    * Use the "Graph Display" toggles to show/hide specific data series.
    * Access historical monitoring data via the "View Raw Data Log" link.
    * Access command history via the "View Action Log" link.

## Dependencies 📦

* FastAPI: Web framework
* Uvicorn: ASGI server
* SQLAlchemy: Database interaction (ORM)
* PySerial: Serial port communication
* PyYAML: Reading YAML configuration files
* Chart.js & chartjs-adapter-date-fns: Front-end charting libraries (loaded via CDN or locally)

## License 📜

This project is licensed under the **MIT License**. See the `LICENSE` file for details.

*(Note: Please confirm you are using the MIT License and add the corresponding `LICENSE` file to the repository root)*
