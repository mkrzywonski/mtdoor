#!/home/mike/mtdoor/.venv/bin/python3

from flask import Flask, request, jsonify
import configparser
import sqlite3
import os

app = Flask(__name__)

# Load configuration from server.ini
config = configparser.ConfigParser()
config.read("server.ini")
AUTH_TOKEN = config.get("global", "auth_token", fallback="")

def store_packet(data):
    """Insert packet data into the SQLite database."""
    conn = sqlite3.connect("meshtastic_data.db")
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO packets (node_id, long_name, latitude, longitude, snr, rssi, timestamp, distance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data.get("node_id"),
        data.get("long_name"),
        data.get("latitude"),
        data.get("longitude"),
        data.get("snr"),
        data.get("rssi"),
        data.get("timestamp"),
        data.get("distance")
    ))

    conn.commit()
    conn.close()

@app.route('/api/packet-data', methods=['POST'])
def receive_packet_data():
    # Check for the Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header or auth_header.split()[1] != AUTH_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    # Process the incoming JSON data
    data = request.json
    if not data:
        return jsonify({"error": "No data received"}), 400

    # Store the data in the SQLite database
    store_packet(data)

    # Respond with success
    return jsonify({"status": "success", "received": data}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
