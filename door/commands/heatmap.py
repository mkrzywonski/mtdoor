import threading
import folium
from flask import Flask, render_template_string
from . import BaseCommand
from loguru import logger as log
import time

# Flask app setup for the heatmap
app = Flask(__name__)

# HTML Template for heatmap
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{{ title }}</title>
    <style>
        #map {
            width: 100%;
            height: 90vh;
            margin: 0 auto;
        }
    </style>
</head>
<body>
    <h1>{{ title }}</h1>
    <div id="map">{{ map_html|safe }}</div>
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
        node_data = [
            {
                'node_id': n.user.id,
                'latitude': n.position.latitude if n.position else None,
                'longitude': n.position.longitude if n.position else None,
                'snr': n.snr
            }
            for n in self.interface.nodes.values()
            if n.position
        ]

        if node_data:
            avg_lat = sum(d['latitude'] for d in node_data) / len(node_data)
            avg_lon = sum(d['longitude'] for d in node_data) / len(node_data)
            base_map = folium.Map(location=[avg_lat, avg_lon], zoom_start=10)
            
            for node in node_data:
                folium.Marker(
                    location=[node['latitude'], node['longitude']],
                    popup=f"SNR: {node['snr']}",
                    tooltip=f"Node ID: {node['node_id']}"
                ).add_to(base_map)
            
            heat_data = [[node['latitude'], node['longitude'], node['snr']] for node in node_data]
            folium.plugins.HeatMap(heat_data).add_to(base_map)
            
            map_html = base_map._repr_html_()
            return render_template_string(HTML_TEMPLATE, title=self.title, map_html=map_html)
        else:
            return "<p>No nodes available for mapping.</p>"
