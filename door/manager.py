from configparser import ConfigParser
from inspect import getmodule
from meshtastic.mesh_interface import MeshInterface
from loguru import logger as log
from pubsub import pub
import math
import requests
import json

from .base_command import (
    BaseCommand,
    CommandLoadError,
    CommandRunError,
    CommandActionNotImplemented,
)

def haversine(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two points on the Earth in miles."""
    R = 3958.8  # Radius of Earth in miles
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

class DoorManager:
    # use this topic to send response messages
    dm_topic: str = "mtdoor.send.text"

    def __init__(self, interface: MeshInterface, settings: ConfigParser):
        self.interface = interface
        self.settings = settings
        self.me = interface.getMyUser()["id"]
        self.distance_filter = settings.getfloat("global", "heatmap_filter_distance", fallback=5.0)
        self.snr_filter = settings.getfloat("global", "heatmap_filter_snr", fallback=6)
        self.server_url = settings.get("global", "server_url", fallback=None)
        self.auth_token = settings.get("global", "server_auth_token", fallback=None)
        ignore = settings.get("global", "ignore_nodes", fallback=None)
        self.ignore_nodes = [node.strip() for node in ignore.split(",") if node]  # Clean and split list

        # keep track of the commands added, don't let duplicates happen
        self.commands = []

        pub.subscribe(self.on_text, "meshtastic.receive.text")
        pub.subscribe(self.on_packet, "meshtastic.receive")
        pub.subscribe(self.send_dm, self.dm_topic)

        log.info(f"DoorManager is connected to {self.me}")

    def add_command(self, command: BaseCommand):
        if not hasattr(command, "command"):
            raise CommandLoadError("No 'command' property on {command}")

        cmd: BaseCommand
        for cmd in self.commands:
            if cmd.command == command.command:
                raise CommandLoadError("Command already loaded")

        # instantiate and set some properties
        cmd = command()
        module = getmodule(cmd).__name__

        cmd.dm_topic = self.dm_topic
        cmd.interface = self.interface
        cmd.settings = self.settings

        # call "load" on the command class
        try:
            log.debug(f"Loading '{cmd.command}' command from '{module}'..")
            cmd.load()
        except CommandActionNotImplemented:
            # it's ok if they don't implement a load method
            pass
        except CommandLoadError:
            log.warning(f"Command {command.command} could not load.")
            return
        except:
            log.exception(f"Failed to load {command.command}")
            return

        # gather global and module-specific settings
        command_settings = dict(self.settings.items("global"))
        if self.settings.has_section(module):
            command_settings.update(self.settings.items(module))

        # set properties on the class
        # DANGER: this allows config file to overwrite any method or property of a command class
        # for k, v in command_settings.items():
        #     if k in UnavailableProperties:
        #         continue
        #     setattr(cmd, k, v)
        #     print(module, k, v)

        self.commands.append(cmd)

    def add_commands(self, commands: list[BaseCommand]):
        for cmd in commands:
            self.add_command(cmd)

    def get_command_handler(self, message: str):
        cmd: BaseCommand
        for cmd in self.commands:
            if len(message) >= len(cmd.command):
                if message[: len(cmd.command)] == cmd.command:
                    return cmd
        return None

    def send_dm(self, message: str, node: str):
        """
        break up the rx -> tx loop so maybe other messages can get through
        """
        if type(message) != type(""):
            log.warning("Skipping attempt to send {node} non-string: {message}")
            return
        log.info(f"TX {node} ({len(message):>3}): {message}")
        self.interface.sendText(message, node)

    def help_message(self):
        invoke_list = ", ".join([cmd.command for cmd in self.commands])
        return f"Hi, I am a bot.\n\nTry one of these commands: {invoke_list} or 'help <command>'."

    def help_command(self, command: BaseCommand) -> str:
        """build a help message for the given command
        we may or may not have 'description' or 'help' filled in
        """
        description = getattr(command, "description", None)
        help = getattr(command, "help", None)
        if description and help:
            return description + "\n\n" + help
        elif description and not help:
            return description
        elif not description and help:
            return help
        else:
            return "No help for this command"

    def on_text(self, packet, interface):
        # ignore messages not directed to the connected node
        if packet["toId"] != self.me:
            return

        node = packet["fromId"]
        snr = packet['rxSnr']
        rssi = packet['rxRssi']
        hops = packet['hopStart'] - packet['hopLimit']
        msg: str = packet["decoded"]["payload"].decode("utf-8")
        response = None

        log.info(f"RX {node} ({len(msg):>3}): {msg}")

        # show signal strength data for sending node
        if msg.lower()[:4] == "ping":
            response = f"Received ping from node {node}\nHops: {hops}\nSNR: {snr}\nRSSI: {rssi}"
            pub.sendMessage(self.dm_topic, message=response, node=node)
            return

        # show help for commands
        if msg.lower()[:5] == "help ":
            handler = self.get_command_handler(msg[5:].lower())
            if handler:
                pub.sendMessage(
                    self.dm_topic, message=self.help_command(handler), node=node
                )
                return

        # look for a regular command handler
        handler = self.get_command_handler(msg.lower())
        if handler:
            try:
                response = handler.invoke(msg, node)
            except CommandRunError:
                response = f"Command to '{handler.command}' failed."
        else:
            response = self.help_message()

        # command handlers may or may not return a response
        # they have the option of handling it themselves on long-running tasks
        # by calling CommandBase.send_dm
        if response:
            pub.sendMessage(self.dm_topic, message=response, node=node)

    def shutdown(self):
        log.debug(f"Shutting down {len(self.commands)} commands..")
        command: BaseCommand
        for command in self.commands:
            try:
                command.shutdown()
            except CommandActionNotImplemented:
                pass

    def on_packet(self, packet, interface):
        """Handle all incoming packets, focusing on 0-hop packets with position data."""

        # Step 1: Check if packet is from the local node
        node_id = packet["fromId"]
        if node_id == self.me or node_id in self.ignore_nodes:
            return

        log.info(f"Received packet from node: {node_id}")

        # Step 2: Access node_info from cached data directly as a dictionary
        node_info = self.interface.nodes.get(node_id)
        position_data = packet["decoded"].get("position")  # Attempt to get position data from packet

        # Step 3: Get latitude and longitude from position data or node_info if available
        if position_data:
            latitude = position_data.get("latitude")
            longitude = position_data.get("longitude")
            log.info(f"Position from packet: Latitude: {latitude}, Longitude: {longitude}")
        elif node_info and "position" in node_info:
            latitude = node_info["position"].get("latitude")
            longitude = node_info["position"].get("longitude")
            log.info(f"Position from node_info: Latitude: {latitude}, Longitude: {longitude}")
        else:
            log.info(f"No position data available for node {node_id}")
            return  # Skip if no position data from either source

        # Step 4: Retrieve hop count from node_info if available, otherwise calculate it
        hop_count = node_info.get("deviceMetrics", {}).get("hopsAway") if node_info else None
        if hop_count is None:
            hop_start = packet.get("hopStart", None)
            hop_limit = packet.get("hopLimit", None)
            
            if hop_start is not None and hop_limit is not None:
                hop_count = hop_start - hop_limit
            elif hop_limit is not None:
                hop_count = hop_limit
            else:
                hop_count = 0  # Default to local packet if no hop data exists

        log.info(f"hop_count: {hop_count}")

        # Step 5: Process only packets with hopCount = 0
        if hop_count != 0:
            log.info(f"Ignoring packet with hop count {hop_count}")
            return

        # Step 6: Check for SNR and RSSI
        snr = packet.get('rxSnr')
        rssi = packet.get('rxRssi')
        if snr is None or rssi is None:
            log.info(f"No SNR/RSSI data for packet from {node_id}")
            return  # Ignore packets without SNR/RSSI data

        # Get my node's position from cached data
        my_node = self.interface.nodes.get(self.me)
        if not my_node or "position" not in my_node:
            log.warning("Missing local node position data; cannot calculate distance.")
            return

        my_latitude = my_node["position"].get("latitude")
        my_longitude = my_node["position"].get("longitude")

        # Step 7: Calculate distance between my node and sending node
        distance = haversine(my_latitude, my_longitude, latitude, longitude)

        # Step 8: Apply filtering based on distance and SNR
        if distance > self.distance_filter and snr > self.snr_filter:
            log.info(
                f"Ignoring impossibly far/strong packet from {node_id} ({node_info['user'].get('longName', 'Unknown') if node_info else 'Unknown'})\n"
                f"Distance: {distance:.2f} miles, SNR: {snr}"
            )
            return

        long_name = node_info['user'].get('longName', 'Unknown') if node_info else 'Unknown'

        # Step 9: Log relevant data for packets that pass filtering
        log.info(
            f"Node: {node_id} ({long_name})\n"
            f"Distance: {distance:.2f} miles, SNR: {snr}, RSSI: {rssi}\n"
            f"Latitude: {latitude}, Longitude: {longitude}"
        )

        # Step 10: Prepare data to send to the server
        data = {
            "node_id": node_id,
            "long_name": long_name,
            "latitude": latitude,
            "longitude": longitude,
            "distance": distance,
            "snr": snr,
            "rssi": rssi,
            "timestamp": packet.get("rxTime"),
        }

        # Step 11: Post data to the server if the server URL is set
        if self.server_url:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.auth_token}" if self.auth_token else None,
            }
            
            try:
                response = requests.post(self.server_url, headers=headers, data=json.dumps(data))
                response.raise_for_status()
                log.info(f"Successfully posted data to server for node {node_id}")
            except requests.RequestException as e:
                log.error(f"Failed to post data to server: {e}")
