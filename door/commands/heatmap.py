import threading
import folium
from folium.plugins import HeatMap
from folium.features import DivIcon
from flask import Flask, render_template_string
from . import BaseCommand
from loguru import logger as log
import time

# Flask app setup for the heatmap
app = Flask(__name__)

# HTML Template for heatmap
HTML_TEMPLATE = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{{{ title }}}}</title>
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
    <h1>{{{{ title }}}}</h1>
    <!-- Refresh Interval Controls -->
    <div id="controls">
        <label for="refreshInterval">Refresh every:</label>
        <select id="refreshInterval">
            <option value="0" selected>Off</option>
            <option value="60">1 minute</option>
            <option value="300">5 minutes</option>
            <option value="900">15 minutes</option>
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

class Heatmap(BaseCommand):
    command = "heatmap"
    description = "Displays a heatmap of node positions"
    help = "Generate a web-based heatmap of Meshtastic nodes"

    def load(self):
        """Load configuration values and prepare server thread without starting."""
        self.server_thread = None
        self.is_running = False
        self.url = self.get_setting(str, "heatmap_url", "http://localhost:5000")
        self.title = self.get_setting(str, "heatmap_title", "Meshtastic Node Heatmap")
        self.port = self.get_setting(int, "heatmap_port", 5000)
        # Set up route for rendering map
        app.route('/')(self.render_map)
        self.start_server()

    def invoke(self, msg, node):
        """Handle commands like 'heatmap', 'heatmap start', 'heatmap stop', and 'heatmap restart'."""
        command = msg.strip().lower()
        if command == "heatmap":
            return f"View the heatmap at {self.url}"
        elif command == "heatmap start":
            if self.is_running:
                return "Heatmap server is already running."
            self.start_server()
            return f"Started heatmap server at {self.url}"
        elif command == "heatmap stop":
            if not self.is_running:
                return "Heatmap server is not currently running."
            self.stop_server()
            return "Stopped heatmap server."
        elif command == "heatmap restart":
            self.stop_server()
            time.sleep(1)  # Small delay to ensure server stops
            self.start_server()
            return f"Restarted heatmap server at {self.url}"
        else:
            return "Invalid command. Use 'heatmap', 'heatmap start', 'heatmap stop', or 'heatmap restart'."

    def start_server(self):
        """Start the Flask server in a new thread."""
        self.server_thread = threading.Thread(target=self._run_server)
        self.server_thread.daemon = True
        self.server_thread.start()
        self.is_running = True
        log.info("Heatmap server started.")

    def stop_server(self):
        """Stop the server by shutting down Flask."""
        # Use an internal Flask method to stop the server
        self.is_running = False
        log.info("Heatmap server stopped.")

    def _run_server(self):
        """Run the Flask server."""
        app.run(host="0.0.0.0", port=self.port)

    def render_map(self):
        """Render the heatmap using data from the node list."""
        node_data = []
        for n in self.interface.nodes.values():
            node_id = n['user']['id']
            long_name = n['user'].get('longName', 'Unknown')
            snr = n.get('snr', 0)
            
            # Check if 'hopsAway' exists and is equal to 0
            hops_away = n.get('hopsAway', None)
            #if hops_away != 0:
            #    continue  # Skip nodes that are not directly heard (hopsAway != 0)

            # Only include nodes with valid position data
            if n.get('position') and 'latitude' in n['position'] and 'longitude' in n['position']:
                latitude = n['position']['latitude']
                longitude = n['position']['longitude']
                snr_normalized = max(min(snr, 10), -20)  # Normalize SNR to [-20, 10]
                long_name = n['user'].get("longName", "Unknown")
                
                node_data.append({
                    'node_id': node_id,
                    'long_name': long_name,
                    'hopsAway': hopsAway,
                    'latitude': latitude,
                    'longitude': longitude,
                    'snr': snr_normalized
                })
                
        if node_data:
            avg_lat = sum(d['latitude'] for d in node_data if d['latitude'] is not None) / len(node_data)
            avg_lon = sum(d['longitude'] for d in node_data if d['longitude'] is not None) / len(node_data)
            base_map = folium.Map(location=[avg_lat, avg_lon], zoom_start=10)
            
            for node in node_data:
                text_width = len(node['node_id']) * 10.5
                folium.map.Marker(
                    location=[node['latitude'], node['longitude']],
                    icon=DivIcon(
                        icon_size=(text_width, 36),
                        icon_anchor=(text_width // 2 - 10, 10),
                        html=f'<div title="{node["long_name"]}\nSNR: {node["snr"]}" style="font-size: 18px; color: blue; text-shadow: 0px 0px 10px rgba(255, 255, 255, 0.7);">{node["node_id"]}</div>',
                    )
                ).add_to(base_map)
#            heat_data = [[node['latitude'], node['longitude'], node['snr']] for node in node_data]
            heat_data = [[node['latitude'], node['longitude'], node['snr']] for node in node_data if node['hopsAway'] == 0]

            folium.plugins.HeatMap(heat_data).add_to(base_map)
            
            map_html = base_map._repr_html_()
            return render_template_string(HTML_TEMPLATE, title=self.title, map_html=map_html)
        else:
            log.warning("No nodes available for mapping.")
            return "<p>No nodes available for mapping.</p>"

