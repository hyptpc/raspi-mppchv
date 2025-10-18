"""
Centralized logging setup for the application.
"""

class Colors:
    """ANSI color codes for terminal output."""
    RESET = "\033[0m"; BOLD = "\033[1m"; RED = "\033[91m"; GREEN = "\033[92m"
    YELLOW = "\033[93m"; BLUE = "\033[94m"; MAGENTA = "\033[95m"; CYAN = "\033[96m"

LOG_LEVELS = {
    "WORKER": Colors.GREEN, "MONITOR": Colors.CYAN, "SEND": Colors.BLUE,
    "RECV": Colors.MAGENTA, "RAMP": Colors.YELLOW, "MOCK": Colors.YELLOW,
    "ACTION": Colors.GREEN, "ERROR": Colors.RED, "INFO": "" , "WARN": Colors.YELLOW
}

def log(level: str, message: str):
    """Prints a formatted and colored log message."""
    color = LOG_LEVELS.get(level.upper(), "")
    # Pad the level string to 8 characters for alignment
    padded_level = f"[{level.upper():<8}]"
    print(f"{color}{padded_level}{Colors.RESET} {message}")