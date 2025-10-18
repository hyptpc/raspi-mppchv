"""
Handles database operations for action logs (action_log.db).
"""
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
import os

# --- Database Connection Setup ---
DATA_DIR = "data"
DATABASE_URL = f"sqlite:///./{DATA_DIR}/action_log.db" # Point to data dir

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Table Schema ---
class ActionLog(Base):
    __tablename__ = "action_logs"
    id=Column(Integer, primary_key=True, index=True); timestamp=Column(DateTime); port_id=Column(Integer)
    action_command=Column(String); raw_response=Column(String, nullable=True)

# --- Database Interaction Functions ---
def init_db():
    Base.metadata.create_all(bind=engine)

def save_action_log(port_id: int, command: str, response: bytes):
    db = SessionLocal()
    try: db_log = ActionLog(timestamp=datetime.now(), port_id=port_id, action_command=command, raw_response=response.decode(errors='ignore').strip()); db.add(db_log); db.commit()
    finally: db.close()

def get_action_logs(limit: int = 200):
    db = SessionLocal()
    try: results = db.query(ActionLog).order_by(ActionLog.timestamp.desc()).limit(limit).all(); return results
    finally: db.close()

if __name__ == '__main__':
    from logger import log
    log("INFO", f"Initializing action log database at {DATABASE_URL}...")
    init_db()
    log("INFO", "Action log database and table created successfully.")