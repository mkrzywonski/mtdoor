import threading
import logging
import folium
from folium.plugins import HeatMap
from folium.features import DivIcon
from flask import Flask, render_template_string, request
from . import BaseCommand
from loguru import logger as log
import time
from datetime import datetime
import pytz

local_tz = pytz.timezone('America/Chicago')

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
        table {{
            margin-top: 20px;
            border-collapse: collapse;
            width: 90%;
            max-width: 800px;
        }}
        th, td {{
            padding: 12px 20px; /* Adjust padding to increase space */
            border: 1px solid #ddd;
            text-align: center;
        }}
        th {{
            background-color: #f4f4f4;
            font-weight: bold;
        }}
        @media (max-width: 600px) {{
            h1 {{
                font-size: 1.5rem;
            }}
        }}
    </style>
    <script>
        function toggleShowAll() {{
            let showAll = document.getElementById("showAllCheckbox").checked;
            window.location.href = `?show_all=${{showAll}}`;
        }}
    </script>
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
        <label>
            <input type="checkbox" id="showAllCheckbox" onchange="toggleShowAll()" {{% if show_all %}} checked {{% endif %}}>
            Show all nodes
        </label>
    </div>
    <div id="map">
        {{{{ map_html|safe }}}}  <!-- Corrected formatting for map_html -->
    </div>
    <!-- Node Data Table -->
    <table>
        <thead>
            <tr>
                <th>Node ID</th>
                <th>Long Name</th>
                <th>Short Name</th>
                <th>Hops Away</th>
                <th>Latitude</th>
                <th>Longitude</th>
                <th>Last Heard</th>
                <th>SNR</th>
            </tr>
        </thead>
        <tbody>
            {{% for node in node_data %}}
            <tr>
                <td>{{{{ node['node_id'] }}}}</td>
                <td>{{{{ node['long_name'] }}}}</td>
                <td>{{{{ node['short_name'] }}}}</td>
                <td>{{{{ node['hopsAway'] }}}}</td>
                <td>{{{{ node['latitude'] }}}}</td>
                <td>{{{{ node['longitude'] }}}}</td>
                <td>{{{{ node['age'] | default("N/A") }}}}</td>
                <td>{{{{ node['snr'] }}}}</td>
            </tr>
            {{% endfor %}}
        </tbody>
    </table>
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
    description = "Generate a web-based heatmap of Meshtastic nodes"
    help = "heatmap - displays the URL of the web server"

    def load(self):
        """Load configuration values and prepare server thread without starting."""
        self.server_thread = None
        self.url = self.get_setting(str, "heatmap_url", "http://localhost:5000")
        self.port = self.get_setting(int, "heatmap_port", 5000)
        # Set up route for rendering map
        app.route('/')(self.render_map)
        self.start_server()

    def invoke(self, msg, node):
        """Handle command"""
        command = msg.strip().lower()
        if command == "heatmap":
            return f"View the heatmap for this node at {self.url}"
        else:
            return "Invalid command. Use 'heatmap' to display the URL of the heatmap web server."

    def start_server(self):
        """Start the Flask server in a new thread."""
        self.server_thread = threading.Thread(target=self._run_server)
        self.server_thread.daemon = True
        self.server_thread.start()
        log.info("Heatmap server started.")

    def _run_server(self):
        """Run the Flask server."""
        app.run(host="0.0.0.0", port=self.port)

    def render_map(self):
        """Render the heatmap using data from the node list."""
        
        title = f"Meshtastic Node Heatmap for {self.interface.getMyUser()['longName']} ({self.interface.getMyUser()['shortName']})"
        show_all = request.args.get('show_all', 'false').lower() == 'true'

        node_data = []
        for n in self.interface.nodes.values():
            node_id = n['user']['id']
            long_name = n['user'].get('longName', 'Unknown')
            short_name = n['user'].get('shortName', 'Unknown')
            snr = n.get('snr', 0)
            hops_away = n.get('hopsAway', 'n/a')
            if n.get('lastHeard'):
                age = f"{int((int(time.time()) - int(n.get('lastHeard'))) / 60)} minutes ago"
            else:
                age = "n/a"

            # Only include nodes with valid position data and less that one day old
            if n.get('position') and 'latitude' in n['position'] and 'longitude' in n['position']:
                latitude = n['position']['latitude']
                longitude = n['position']['longitude']
                snr_normalized = max(min(snr, 10), -20)  # Normalize SNR to [-20, 10]
                long_name = n['user'].get("longName", "Unknown")
                
                if hops_away == 0 or show_all:
                    node_data.append({
                        'node_id': node_id,
                        'long_name': long_name,
                        'short_name': short_name,
                        'hopsAway': hops_away,
                        'latitude': latitude,
                        'longitude': longitude,
                        'lastHeard': n.get('lastHeard', None),
                        'age': age,
                        'snr': snr_normalized
                    })
                
        if node_data:
            avg_lat = sum(d['latitude'] for d in node_data if d['latitude'] is not None) / len(node_data)
            avg_lon = sum(d['longitude'] for d in node_data if d['longitude'] is not None) / len(node_data)
            base_map = folium.Map(location=[avg_lat, avg_lon], zoom_start=10)
            
            for node in node_data:
                text_width = len(node['short_name']) * 10.5
                if node['hopsAway'] == 0:
                    tooltip = f"{node['long_name']}\nSNR: {node['snr']}"
                else:
                    tooltip = f"{node['long_name']}\nHops: {node['hopsAway']}"
                timestamp = ""
                if node['lastHeard']:
                    timestamp = f"\n{datetime.fromtimestamp(node['lastHeard'], local_tz).strftime('%Y-%m-%d %H:%M:%S')}"
                folium.map.Marker(
                    location=[node['latitude'], node['longitude']],
                    icon=DivIcon(
                        icon_size=(text_width, 36),
                        html=f'<div title="{tooltip}{timestamp}" style="font-size: 18px; color: blue; text-shadow: 0px 0px 10px rgba(255, 255, 255, 0.7);">{node["short_name"]}</div>',
                    )
                ).add_to(base_map)

            heat_data = [[node['latitude'], node['longitude'], node['snr']] 
                for node in node_data if node['hopsAway'] == 0]
            folium.plugins.HeatMap(heat_data).add_to(base_map)

            folium.plugins.Fullscreen(
                position="topright",
                title="Full Screen",
                title_cancel="Exit Full Screen",
                force_separate_button=True,
            ).add_to(base_map)
            
            map_html = base_map._repr_html_()
            return render_template_string(HTML_TEMPLATE, title=title, map_html=map_html, show_all=show_all, node_data=node_data)
        else:
            return "<p>No nodes available for mapping.</p>"

