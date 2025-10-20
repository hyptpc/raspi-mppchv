"""
Handles database operations for monitoring data (measurements.db).
Connection is initialized by main.py.
"""
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
import os

# --- 1. Database Connection (Global but uninitialized) ---
engine = None
SessionLocal = None
Base = declarative_base()


# --- 2. Initialization Function (called by main.py) ---
def init_database_connection(db_directory: str, suffix: str = ""):
    """
    Initializes the database connection using the directory path and suffix from config.
    """
    global engine, SessionLocal
    
    filename_suffix = f"_{suffix}" if suffix else ""
    DB_FILENAME = f"measurements{filename_suffix}.db"
    
    if db_directory and not os.path.exists(db_directory):
        try:
            os.makedirs(db_directory, exist_ok=True)
        except OSError as e:
            print(f"ERROR: Could not create database directory {db_directory}: {e}")
            raise
            
    db_path = os.path.join(db_directory, DB_FILENAME)
    DATABASE_URL = f"sqlite:///{db_path}"
    
    engine = create_engine(
        DATABASE_URL, 
        connect_args={"check_same_thread": False}
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
# --- 3. Table Schema (no changes) ---
class Measurement(Base):
    __tablename__ = "measurements"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime)
    port_id = Column(Integer)
    status_raw = Column(Integer, nullable=True)
    voltage = Column(Float, nullable=True)
    current = Column(Float, nullable=True)
    temperature = Column(Float, nullable=True)
    is_hv_on = Column(Boolean, nullable=True)
    is_overcurrent_protection_active = Column(Boolean, nullable=True)
    is_current_out_of_spec = Column(Boolean, nullable=True)
    is_temp_sensor_connected = Column(Boolean, nullable=True)
    is_temp_in_range = Column(Boolean, nullable=True)
    is_temp_correction_enabled = Column(Boolean, nullable=True)
    raw_response = Column(String, nullable=True)

# --- 4. Database Interaction Functions ---
def init_db():
    """
    Creates all database tables based on the schema.
    This function *requires* init_database_connection to have been called first.
    """
    if not engine:
        raise Exception("Database connection not initialized. Call init_database_connection() first.")
    Base.metadata.create_all(bind=engine)

def save_monitor_data(port_id: int, data: dict):
    """Saves parsed monitoring data to the database."""
    if not SessionLocal:
        print("ERROR: save_monitor_data called before database connection was initialized.")
        return
        
    db = SessionLocal()
    try:
        flags = data.get("status_flags", {})
        db_measurement = Measurement(
            timestamp=datetime.now(),
            port_id=port_id,
            status_raw=data.get("status_raw"),
            voltage=data.get("voltage"),
            current=data.get("current"),
            temperature=data.get("temperature"),
            is_hv_on=flags.get("is_hv_on"),
            is_overcurrent_protection_active=flags.get("is_overcurrent_protection_active"),
            is_current_out_of_spec=flags.get("is_current_out_of_spec"),
            is_temp_sensor_connected=flags.get("is_temp_sensor_connected"),
            is_temp_in_range=flags.get("is_temp_in_range"),
            is_temp_correction_enabled=flags.get("is_temp_correction_enabled"),
            raw_response=data.get("raw_response")
        )
        db.add(db_measurement)
        db.commit()
    finally:
        db.close()

def get_data_from_db(skip: int = 0, limit: int = 100):
    """Retrieves the latest measurement records from the database."""
    if not SessionLocal:
        print("ERROR: get_data_from_db called before database connection was initialized.")
        return [] # Return empty list on error
        
    db = SessionLocal()
    try:
        results = db.query(Measurement).order_by(Measurement.timestamp.desc()).offset(skip).limit(limit).all()
        return results
    finally:
        db.close()

def get_data_from_db_since(start_time: datetime):
    """
    Fetches all Measurement records from the database where the timestamp
    is on or after the specified start_time.
    """
    if not SessionLocal:
        print("ERROR: get_data_from_db_since called before database connection was initialized.")
        return []
        
    db = SessionLocal()
    try:
        # Filter by time and sort ASC (oldest first)
        # This is critical for data.findLast() in JavaScript to work correctly.
        results = db.query(Measurement)\
                    .filter(Measurement.timestamp >= start_time)\
                    .order_by(Measurement.timestamp.asc())\
                    .all()
        return results
    finally:
        db.close()

if __name__ == '__main__':
    # This script is not meant to be run directly. Run main.py instead.
    print("Initializing measurements database manually...")
    try:
        init_database_connection("data") # Use default "data" dir for manual init
        init_db()
        print("Manual DB init complete for 'data/measurements.db'")
    except Exception as e:
        print(f"Manual init failed: {e}")