#!/home/mike/mtdoor/.venv/bin/python3
import sqlite3

def create_database():
    conn = sqlite3.connect("meshtastic_data.db")
    cursor = conn.cursor()

    # Create table if it doesn’t already exist
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS packets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id TEXT NOT NULL,
            long_name TEXT,
            latitude REAL,
            longitude REAL,
            snr REAL,
            rssi INTEGER,
            timestamp INTEGER,
            distance REAL
        )
    ''')
    conn.commit()
    conn.close()

if __name__ == "__main__":
    create_database()

