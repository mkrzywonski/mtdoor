#!/home/mike/mtdoor/.venv/bin/python3

from flask import Flask, request, jsonify, render_template_string
import configparser
import sqlite3
import folium
from folium.plugins import HeatMap
from folium.features import DivIcon
import os

# Create the Flask app instance at the top
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
    auth_header = request.headers.get("Authorization")
    if not auth_header or auth_header.split()[1] != AUTH_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    if not data:
        return jsonify({"error": "No data received"}), 400

    store_packet(data)
    return jsonify({"status": "success", "received": data}), 200

@app.route('/heatmap')
def heatmap():
    conn = sqlite3.connect("meshtastic_data.db")
    cursor = conn.cursor()
    
    # Fetch the latest data for each node
    cursor.execute('''
        SELECT node_id, long_name, latitude, longitude, snr, rssi
        FROM packets
        WHERE (node_id, timestamp) IN (
            SELECT node_id, MAX(timestamp)
            FROM packets
            GROUP BY node_id
        )
    ''')
    data = cursor.fetchall()
    conn.close()

    # Create a base map centered around a default location
    base_map = folium.Map(location=[30.0, -97.8], zoom_start=10)  # Adjust location as needed

    # Prepare data for the heatmap layer
    min_snr = -20
    max_snr = 10
    heat_data = [
        [lat, lon, (snr - min_snr) / (max_snr - min_snr)]
        for _, _, lat, lon, snr, _ in data if lat and lon
    ]

    # Add the heatmap layer with SNR values
    HeatMap(heat_data).add_to(base_map)

    # Add a marker for each node with the desired tooltip and popup
    for node_id, long_name, lat, lon, snr, rssi in data:
        if lat and lon:
            text_width = len(node_id) * 10.5  # Adjust multiplier as needed for font size
            folium.map.Marker(
                [lat, lon],
                icon=DivIcon(
                    icon_size = (text_width, 36),
                    icon_anchor = (text_width // 2 - 10, 10),
                    html=f'<div title="SNR: {snr}, RSSI: {rssi}" style="font-size: 18px; color: blue; text-shadow: 0px 0px 10px rgba(255, 255, 255, 255);">{node_id}</div>',
                )
            ).add_to(base_map)

    # Render map to HTML and return
    return render_template_string(base_map._repr_html_())


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

