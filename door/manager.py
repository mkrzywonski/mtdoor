from configparser import ConfigParser
from inspect import getmodule
from meshtastic.mesh_interface import MeshInterface
from loguru import logger as log
from pubsub import pub
import math
import requests

from .base_command import (
    BaseCommand,
    CommandLoadError,
    CommandRunError,
    CommandActionNotImplemented,
)

class DoorManager:
    # use this topic to send response messages
    dm_topic: str = "mtdoor.send.text"

    def __init__(self, interface: MeshInterface, settings: ConfigParser):
        self.interface = interface
        self.settings = settings
        self.me = interface.getMyUser()["id"]
        self.shortName=self.interface.getMyNodeInfo()['user']['shortName']
        self.longName=self.interface.getMyNodeInfo()['user']['longName']
        self.state = {}

        # keep track of the commands added, don't let duplicates happen
        self.commands = []

        pub.subscribe(self.on_text, "meshtastic.receive.text")
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
        return f"{self.longName} ({self.shortName})\n\nTry one of these commands: {invoke_list} or 'help <command>'."

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
        command = msg.lower().split()[0]

        log.info(f"RX {node} ({len(msg):>3}): {msg}")

        # Check for ongoing session with previous command
        log.debug("New message, checking state")
        if self.state.get(node, False):
            log.debug("node state is set")
            log.debug(f"Node state: {self.state[node]}")
            handler = self.get_command_handler(self.state[node])
            if handler:
                log.debug(f"Got handler: {handler}")
                if handler.continue_session(node):
                    log.debug("Continuing session")
                    try:
                        log.debug("Calling command handler")
                        response = handler.invoke(msg, node)
                    except CommandRunError:
                        log.debug("Command handler failed")
                        response = f"Command to '{handler.command}' failed."
                else:
                    log.debug(f"Continue session: {handler.continue_session(node)}")
                    log.debug(f"Clearing node state")
                    self.state[node] = None
        else:
            log.debug("node state is NOT set")
            log.debug("Setting node state")
            self.state[node] = command
            log.debug(f"Node state: {self.state[node]}")

        if response:
            log.debug("Got response for continued session")
            pub.sendMessage(self.dm_topic, message=response, node=node)
            return

        log.debug("No response for continued session")

        # Respond to pings with signal strength
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

        # show global help info
        if msg.lower()[:4] == "help":
            response = self.help_message()
            pub.sendMessage(self.dm_topic, message=response, node=node)
            return

        # look for a regular command handler
        handler = self.get_command_handler(msg.lower())
        if handler:
            try:
                response = handler.invoke(msg, node)
            except CommandRunError:
                response = f"Command to '{handler.command}' failed."
        else:
            handler = self.get_command_handler('llm')
            if handler:
                try:
                    response = handler.invoke(f"llm {msg}", node)
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

