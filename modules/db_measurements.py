"""
Handles database connection, table definition (Measurement),
and data saving logic for monitoring data.
Maps status information from different device types to a unified schema.
"""
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
import os

from modules.logger import log

# --- Database Setup ---
DATABASE_URL = "sqlite:///data/measurements.db" # Default, can be overridden by main.py
engine = None
SessionLocal = None
Base = declarative_base()

# --- Database Model (Unified Schema) ---
class Measurement(Base):
    """SQLAlchemy model for the 'measurements' table."""
    __tablename__ = 'measurements'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, index=True, default=datetime.now)
    port_id = Column(Integer, index=True)

    # --- Common Fields ---
    voltage = Column(Float, nullable=True)
    current = Column(Float, nullable=True)
    is_hv_on = Column(Boolean, nullable=True) # Common status flag
    raw_response = Column(String, nullable=True) # Raw string for debugging

    # --- Unified Status Fields (Used by both Serial and Kikusui) ---
    # Serial uses status_raw directly. Kikusui status is mapped onto these flags.
    status_raw = Column(Integer, nullable=True) # Original raw status integer (Mainly for Serial)
    temperature = Column(Float, nullable=True) # Primarily from Serial
    
    # Unified Flag: Overcurrent Protection Status
    # - Serial: maps to flags.get("is_overcurrent_protection_active")
    # - Kikusui: maps to status_info.get("has_ocp_tripped")
    is_overcurrent_protection_active = Column(Boolean, nullable=True)
    
    # Unified Flag: Current Limit / Constant Current Status
    # - Serial: maps to flags.get("is_current_out_of_spec")
    # - Kikusui: maps to status_info.get("is_cc_mode")
    is_current_out_of_spec = Column(Boolean, nullable=True) # Unified name

    # --- Serial (Hamamatsu) Specific Temperature Flags ---
    # These remain as they are specific to the temperature sensor module
    is_temp_sensor_connected = Column(Boolean, nullable=True)
    is_temp_in_range = Column(Boolean, nullable=True)
    is_temp_correction_enabled = Column(Boolean, nullable=True)


def init_database_connection(db_dir: str = "data", suffix: str = ""):
    """Initializes the database engine and session."""
    global engine, SessionLocal, DATABASE_URL
    
    os.makedirs(db_dir, exist_ok=True)
    db_name = f"measurements{'_' if suffix else ''}{suffix}.db"
    db_path = os.path.join(db_dir, db_name)
    DATABASE_URL = f"sqlite:///{db_path}"
    
    try:
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        log("INFO", f"Database connection initialized: {DATABASE_URL}")
    except Exception as e:
        log("ERROR", f"Failed to initialize database connection: {e}")
        raise

def init_db():
    """Creates the database tables if they don't exist."""
    if not engine:
        log("ERROR", "init_db called before database connection was initialized.")
        return
    try:
        Base.metadata.create_all(bind=engine)
        log("INFO", f"Database tables checked/created for {DATABASE_URL}")
    except Exception as e:
        log("ERROR", f"Failed to create database tables: {e}")
        raise

def save_monitor_data(port_id: int, data: dict):
    """
    Saves parsed monitoring data (from either Serial or Kikusui, or combined)
    to the database using a unified schema. Handles different input structures.
    """
    if not SessionLocal:
        log("ERROR", "save_monitor_data called before DB connection initialized.")
        return
    
    if "error" in data:
        log("WARN", f"Skipping DB save for port {port_id} due to monitor error: {data.get('error')}")
        return
        
    db = SessionLocal()
    try:
        # --- Extract Common Data ---
        voltage = data.get("voltage")
        current = data.get("current")
        raw_response = data.get("raw_response")
        temperature = data.get("temperature") # From Serial or combined

        # --- Determine HV On Status (Unified) ---
        is_hv_on = data.get("is_on") # Check Kikusui key first
        if is_hv_on is None:
             flags = data.get("status_flags", {})
             is_hv_on = flags.get("is_hv_on") # Fallback to Serial key

        # --- Extract and Map Status Flags (Unified Logic) ---
        flags = data.get("status_flags", {})       # Primarily from Serial
        status_info = data.get("status_info", {}) # Primarily from Kikusui
        status_raw = data.get("status_raw")       # Only from Serial

        # Map Overcurrent Status
        is_overcurrent = flags.get("is_overcurrent_protection_active") # Serial value
        if is_overcurrent is None:
            is_overcurrent = status_info.get("has_ocp_tripped") # Fallback to Kikusui value

        # Map Current Limit / CC Mode Status
        is_current_limit = flags.get("is_current_out_of_spec") # Serial value
        if is_current_limit is None:
            is_current_limit = status_info.get("is_cc_mode") # Fallback to Kikusui value

        # --- Extract Serial-Specific Temp Flags ---
        is_temp_sensor_connected = flags.get("is_temp_sensor_connected")
        is_temp_in_range = flags.get("is_temp_in_range")
        is_temp_correction_enabled = flags.get("is_temp_correction_enabled")

        # --- Create DB Model Instance (Using Unified Columns) ---
        db_measurement = Measurement(
            timestamp=datetime.now(),
            port_id=port_id,
            
            voltage=voltage,
            current=current,
            is_hv_on=is_hv_on,
            raw_response=raw_response,
            temperature=temperature,
            status_raw=status_raw, # Primarily Serial's raw value
            
            # Use unified columns
            is_overcurrent_protection_active=is_overcurrent,
            is_current_out_of_spec=is_current_limit,
            
            # Serial specific temp flags
            is_temp_sensor_connected=is_temp_sensor_connected,
            is_temp_in_range=is_temp_in_range,
            is_temp_correction_enabled=is_temp_correction_enabled,
        )
        
        db.add(db_measurement)
        db.commit()
        
    except SQLAlchemyError as e:
        log("ERROR", f"Database error saving measurement for port {port_id}: {e}")
        db.rollback()
    except Exception as e:
        log("ERROR", f"Unexpected error saving measurement for port {port_id}: {e}")
        db.rollback()
    finally:
        db.close()


def get_data_from_db_since(start_time: datetime) -> list[dict]:
    """Fetches monitoring data from the database since the specified start_time."""
    if not SessionLocal:
        log("ERROR", "get_data_from_db_since called before DB connection initialized.")
        return []

    db = SessionLocal()
    try:
        measurements = db.query(Measurement)\
            .filter(Measurement.timestamp >= start_time)\
            .order_by(Measurement.timestamp.asc())\
            .all()

        # Convert SQLAlchemy objects to dictionaries for JSON serialization
        data = []
        for m in measurements:
            data.append({
                "id": m.id,
                "timestamp": m.timestamp.isoformat(),
                "port_id": m.port_id,
                "voltage": m.voltage,
                "current": m.current,
                "temperature": m.temperature,
                "is_hv_on": m.is_hv_on,
                "is_overcurrent": m.is_overcurrent_protection_active,
                "is_current_limit": m.is_current_out_of_spec,
                "is_temp_sensor_connected": m.is_temp_sensor_connected,
                "is_temp_in_range": m.is_temp_in_range,      
                "is_temp_correction_enabled": m.is_temp_correction_enabled,      
            })
        return data

    except SQLAlchemyError as e:
        log("ERROR", f"Database error fetching measurements: {e}")
        return []
    finally:
        db.close()

