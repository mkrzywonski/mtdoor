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
MAP_TITLE = config.get("global", "map_title", fallback="Meshtastic Node Heatmap")
DATABASE = config.get("global", "node_database", fallback="nodes.db")

def store_packet(packet_data):
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    # Create the table if it doesn't exist with node_id as UNIQUE
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS packets (
            node_id TEXT PRIMARY KEY,
            long_name TEXT,
            latitude REAL,
            longitude REAL,
            snr REAL,
            rssi INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # UPSERT operation to update or insert the row
    cursor.execute("""
        INSERT INTO packets (node_id, long_name, latitude, longitude, snr, rssi, timestamp)
        VALUES (:node_id, :long_name, :latitude, :longitude, :snr, :rssi, CURRENT_TIMESTAMP)
        ON CONFLICT(node_id) DO UPDATE SET
            long_name=excluded.long_name,
            latitude=excluded.latitude,
            longitude=excluded.longitude,
            snr=excluded.snr,
            rssi=excluded.rssi,
            timestamp=CURRENT_TIMESTAMP
    """, packet_data)

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
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
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
    base_map = folium.Map(location=[30.0, -97.8], zoom_start=10)

    # Prepare data for the heatmap layer
    min_snr = -20
    max_snr = 10
    heat_data = [
        [lat, lon, (snr - min_snr) / (max_snr - min_snr)]
        for _, _, lat, lon, snr, _ in data if lat and lon
    ]
    HeatMap(heat_data).add_to(base_map)

    # Add a marker for each node with the tooltip and popup
    for node_id, long_name, lat, lon, snr, rssi in data:
        if lat and lon:
            text_width = len(node_id) * 10.5
            folium.map.Marker(
                [lat, lon],
                icon=DivIcon(
                    icon_size=(text_width, 36),
                    icon_anchor=(text_width // 2 - 10, 10),
                    html=f'<div title="SNR: {snr}, RSSI: {rssi}" style="font-size: 18px; color: blue; text-shadow: 0px 0px 10px rgba(255, 255, 255, 0.7);">{node_id}</div>',
                )
            ).add_to(base_map)

    # Render the map within a styled HTML template
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{MAP_TITLE}</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                margin: 0;
                padding: 0;
            }}
            h1 {{
                font-size: 2rem;
                margin: 20px;
                text-align: center;
            }}
            #map {{
                width: 100%;
                flex-grow: 1;
                max-width: 90vw;
                max-height: 90vh; /* Keep height within viewport */
                border-radius: 8px;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2);
            }}
            @media (max-width: 600px) {{
                h1 {{
                    font-size: 1.5rem;
                }}
            }}
        </style>
    </head>
    <body>
        <h1>{MAP_TITLE}</h1>
        <!-- Refresh Interval Controls -->
        <div id="controls">
            <label for="refreshInterval">Refresh every:</label>
            <select id="refreshInterval">
                <option value="0">Off</option>
                <option value="30">30 seconds</option>
                <option value="60" selected>1 minute</option>
                <option value="300">5 minutes</option>
            </select>
        </div>
        <div id="map">
            {{{{ map_html|safe }}}}  <!-- Corrected formatting for map_html -->
        </div>
        <script>
            let refreshTimer;

            function setRefreshInterval() {{
                const interval = parseInt(document.getElementById("refreshInterval").value);
                if (refreshTimer) clearInterval(refreshTimer);

                if (interval > 0) {{
                    refreshTimer = setInterval(() => {{
                        location.reload();
                    }}, interval * 1000);  // Convert seconds to milliseconds
                }}
            }}

            document.getElementById("refreshInterval").addEventListener("change", setRefreshInterval);

            // Set initial interval based on default dropdown value
            setRefreshInterval();
        </script>
        </body>
        </html>
    """
    return render_template_string(html_template, map_html=base_map._repr_html_())

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
