# MPPC High Voltage Module Controller

## Description

This application provides a web-based interface to control and monitor multiple Hamamatsu C11204-01 MPPC High Voltage Power Supply modules connected via serial ports (UART) to a Raspberry Pi or similar Linux system. It allows users to set voltages, turn outputs on/off, monitor voltage/current/temperature, and log both monitoring data and user actions.

## Directory Structure 📁

```
raspi-mppchv/
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
```

## Setup & Installation ⚙️

1.  **Clone the Repository:**
    ```bash
    git clone <your-repository-url>
    cd raspi-mppchv
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
    (You can omit `--config config/config.yaml` if the file is in the default location). The server will log the host and port it's running on (e.g., `0.0.0.0:8000`).

2.  **Access the Web UI:**

    * **From the Same Local Network:**
        Open a web browser on a device connected to the **same local network** as the server and navigate to:
        `http://<server-ip-address>:<port>`
        (e.g., `http://192.168.20.5:8000`, using the host and port defined in `config.yaml` or logged by the server).

    * **From an External Network (using SSH Tunnel):**
        If your access device (e.g., your laptop) is *not* on the same network as the server, but you can SSH into the server:
        1.  Keep the server running on the server machine.
        2.  Open a **new terminal on your local machine** (e.g., your laptop) and establish an SSH tunnel with the following command:
            ```bash
            ssh -L <local_port>:localhost:<server_port> <username>@<server_ip_address>
            ```
            * Replace `<local_port>` with an unused port on your local machine (e.g., `8080`).
            * Replace `<server_port>` with the port the server is running on (usually `8000`).
            * Replace `<username>@<server_ip_address>` with your SSH login details for the server (e.g., `pi@192.168.20.5`).
            * **Example:** `ssh -L 8080:localhost:8000 pi@192.168.20.5`
        3.  Keep this SSH terminal window open.
        4.  Open a web browser on your **local machine** and navigate to:
            `http://localhost:<local_port>`
            (e.g., `http://localhost:8080`)

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
