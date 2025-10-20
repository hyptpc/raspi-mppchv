"""
Handles database operations for action logs (action_log.db).
Connection is initialized by main.py.
"""
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime
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
    DB_FILENAME = f"action_log{filename_suffix}.db"
    
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
class ActionLog(Base):
    __tablename__ = "action_logs"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime)
    port_id = Column(Integer)
    action_command = Column(String)
    raw_response = Column(String, nullable=True)


# --- 4. Database Interaction Functions ---
def init_db():
    """
    Creates the action_logs table if it doesn't exist.
    Requires init_database_connection to have been called first.
    """
    if not engine:
        raise Exception("Database connection not initialized. Call init_database_connection() first.")
    Base.metadata.create_all(bind=engine)

def save_action_log(port_id: int, command: str, response: bytes):
    """Saves a user-initiated action command to the action_log database."""
    if not SessionLocal:
        print("ERROR: save_action_log called before database connection was initialized.")
        return
        
    db = SessionLocal()
    try:
        db_log = ActionLog(
            timestamp=datetime.now(),
            port_id=port_id,
            action_command=command,
            raw_response=response.decode(errors='ignore').strip()
        )
        db.add(db_log)
        db.commit()
    finally:
        db.close()

def get_action_logs(limit: int = 200):
    """Retrieves the latest action log records from the database."""
    if not SessionLocal:
        print("ERROR: get_action_logs called before database connection was initialized.")
        return []
        
    db = SessionLocal()
    try:
        results = db.query(ActionLog).order_by(ActionLog.timestamp.desc()).limit(limit).all()
        return results
    finally:
        db.close()

if __name__ == '__main__':
    # This script is not meant to be run directly. Run main.py instead.
    print("Initializing action log database manually...")
    try:
        init_database_connection("data") # Use default "data" dir for manual init
        init_db()
        print("Manual DB init complete for 'data/action_log.db'")
    except Exception as e:
        print(f"Manual init failed: {e}")