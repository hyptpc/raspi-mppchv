"""
Handles database operations for monitoring data (measurements.db).
"""
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
import os

# --- Database Connection Setup ---
# Point to the data directory
DATA_DIR = "data"
DATABASE_URL = f"sqlite:///./{DATA_DIR}/measurements.db"

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Table Schema ---
class Measurement(Base):
    __tablename__ = "measurements"
    id=Column(Integer, primary_key=True, index=True); timestamp=Column(DateTime); port_id=Column(Integer)
    status_raw=Column(Integer, nullable=True); voltage=Column(Float, nullable=True); current=Column(Float, nullable=True)
    temperature=Column(Float, nullable=True); is_hv_on=Column(Boolean, nullable=True)
    is_overcurrent_protection_active=Column(Boolean, nullable=True); is_current_out_of_spec=Column(Boolean, nullable=True)
    is_temp_sensor_connected=Column(Boolean, nullable=True); is_temp_in_range=Column(Boolean, nullable=True)
    is_temp_correction_enabled=Column(Boolean, nullable=True); raw_response=Column(String, nullable=True)

# --- Database Interaction Functions ---
def init_db():
    Base.metadata.create_all(bind=engine)

def save_monitor_data(port_id: int, data: dict):
    db = SessionLocal()
    try:
        flags = data.get("status_flags", {}); db_m = Measurement(timestamp=datetime.now(), port_id=port_id, status_raw=data.get("status_raw"), voltage=data.get("voltage"), current=data.get("current"), temperature=data.get("temperature"), is_hv_on=flags.get("is_hv_on"), is_overcurrent_protection_active=flags.get("is_overcurrent_protection_active"), is_current_out_of_spec=flags.get("is_current_out_of_spec"), is_temp_sensor_connected=flags.get("is_temp_sensor_connected"), is_temp_in_range=flags.get("is_temp_in_range"), is_temp_correction_enabled=flags.get("is_temp_correction_enabled"), raw_response=data.get("raw_response")); db.add(db_m); db.commit()
    finally: db.close()

def get_data_from_db(skip: int = 0, limit: int = 100):
    db = SessionLocal()
    try: results = db.query(Measurement).order_by(Measurement.timestamp.desc()).offset(skip).limit(limit).all(); return results
    finally: db.close()

if __name__ == '__main__':
    from logger import log # Use the logger for consistency
    log("INFO", f"Initializing measurements database at {DATABASE_URL}...")
    init_db()
    log("INFO", "Measurements database and table created successfully.")