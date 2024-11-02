import os
import requests
import shutil
import subprocess
from time import sleep
from datetime import datetime
from pydantic import BaseModel
from loguru import logger
from . import BaseCommand
from loguru import logger as log

# Define constants for GitHub API and repository details
REPO_OWNER = "meshtastic"
REPO_NAME = "Meshtastic-device"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases"

class FirmwareRelease(BaseModel):
    """Data model for firmware release details."""
    version: str
    tag_name: str
    url: str
    published_at: datetime

class Firmware(BaseCommand):
    """Command to list, select, and refresh firmware releases for Meshtastic devices."""
    command = "fw"
    description = "Update Wisblock firmware"
    help = "fw list - List available releases\nfw <n> - Install release #n\nfw update - Update available firmware release list"

    def load(self):
        admins_config = self.get_setting(str, "admins")
        self.admin_nodes = [admin.strip() for admin in admins_config.split(",") if admin]  # Clean and split list
        self.initialize_releases()

    def initialize_releases(self):
        """Initialize and fetch the latest firmware releases."""
        self.releases = []
        self.fetch_firmware_releases()

    def fetch_firmware_releases(self):
        """Fetch the latest firmware releases from GitHub."""
        try:
            response = requests.get(GITHUB_API_URL)
            response.raise_for_status()
            releases_data = response.json()
            self.releases = [
                FirmwareRelease(
                    version=release['name'],
                    tag_name=release['tag_name'],
                    url=release['html_url'],
                    published_at=datetime.strptime(release['published_at'], "%Y-%m-%dT%H:%M:%SZ")
                )
                for release in releases_data
            ]
            logger.info(f"Fetched {len(self.releases)} firmware releases from GitHub.")
        except requests.RequestException as e:
            logger.error(f"Failed to fetch firmware releases: {e}")
            self.releases = []

    def enter_dfu_mode(self):
        """Command the node to enter DFU mode."""
        try:
            self.interface.enter_dfu()
            logger.info("Node has been instructed to enter DFU mode.")
            sleep(2)  # Wait for the device to enter DFU mode
            return True
        except Exception as e:
            logger.error(f"Failed to enter DFU mode: {e}")
            return False

    def list_block_devices(self):
        """List all current block devices."""
        result = subprocess.run(["lsblk", "-nr", "-o", "NAME,TYPE"], capture_output=True, text=True)
        return set(line.split()[0] for line in result.stdout.splitlines() if "disk" in line)

    def detect_new_device(self, original_devices):
        """Detect the new block device added in DFU mode."""
        sleep(2)  # Allow some time for the device to initialize
        new_devices = self.list_block_devices()
        added_devices = new_devices - original_devices
        if added_devices:
            new_device = "/dev/" + added_devices.pop()
            logger.info(f"New DFU device detected: {new_device}")
            return new_device
        else:
            logger.error("No new DFU device detected.")
            return None

    def mount_device(self, device, mount_point):
        """Mount the DFU volume to the specified mount point."""
        try:
            os.makedirs(mount_point, exist_ok=True)
            subprocess.run(["mount", device, mount_point], check=True)
            logger.info(f"Mounted {device} to {mount_point}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to mount {device}: {e}")
            return False

    def download_firmware(self, url):
        """Download the firmware file from the provided URL."""
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with open("firmware.bin", "wb") as file:
                shutil.copyfileobj(response.raw, file)
            logger.info("Firmware downloaded successfully.")
            return "firmware.bin"
        except requests.RequestException as e:
            logger.error(f"Failed to download firmware: {e}")
            return None

    def copy_firmware_to_device(self, firmware_path, mount_point):
        """Copy the firmware file to the DFU volume."""
        try:
            shutil.copy(firmware_path, os.path.join(mount_point, "firmware.bin"))
            logger.info("Firmware copied to DFU volume successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to copy firmware to DFU volume: {e}")
            return False

    def upgrade_firmware(self, url):
        """Full firmware upgrade process."""
        original_devices = self.list_block_devices()

        if not self.enter_dfu_mode():
            return "Failed to enter DFU mode."

        dfu_device = self.detect_new_device(original_devices)
        if not dfu_device:
            return "Failed to detect DFU device."

        mount_point = "/mnt/dfu_volume"
        if not self.mount_device(dfu_device, mount_point):
            return "Failed to mount DFU volume."

        firmware_path = self.download_firmware(url)
        if not firmware_path:
            return "Failed to download firmware."

        if not self.copy_firmware_to_device(firmware_path, mount_point):
            return "Failed to copy firmware to DFU volume."

        subprocess.run(["umount", mount_point], check=True)
        logger.info("Firmware upgrade completed. Node should reboot with the new firmware.")
        return "Firmware upgrade completed. Node should reboot with the new firmware."

    def invoke(self, message, sender):
        """Handle incoming messages for the firmware command."""
        if sender not in self.admin_nodes:
            return "You do not have permission to use firmware commands."
            return
        
        message = message.lower()  # Convert message to lowercase for case-insensitive matching
        
        if message == "fw update":
            self.initialize_releases()
            return "Firmware release list updated."
        elif message.startswith("fw "):
            try:
                selection = int(message.split(" ")[1]) - 1
                if 0 <= selection < len(self.releases):
                    return self.select_firmware_release(selection)
                else:
                    return "Invalid selection. Please choose a valid release number."
            except ValueError:
                return "Invalid command format. Use 'fw list', 'fw update', or 'fw <number>'."
        else:
            return self.list_firmware_releases()


    def select_firmware_release(self, index):
        """Handle the firmware release selection."""
        release = self.releases[index]
        #return self.upgrade_firmware(release.url)
        return f"{release.url} selected"

    def list_firmware_releases(self):
        """Return a numbered list of available firmware releases, showing the current version if available, limited to 200 characters."""
        current_version = self.get_current_firmware_version()
        if not self.releases:
            return "No firmware releases found."
        
        header = f"FW: {current_version}\n\nAvailable:\n"
        release_list = ""
        
        for i, release in enumerate(self.releases):
            # Extract the version number and optional "Alpha" or "Beta" label
            parts = release.version.split()
            version = parts[2]  # The numeric version number
            label = parts[3] if len(parts) > 3 and parts[3].lower() in ["alpha"] else ""
            release_entry = f"{i + 1}. {version} {label}\n"
            
            # Check if adding this release entry would exceed the 200 character limit
            if len(header) + len(release_list) + len(release_entry) > 200:
                break
            release_list += release_entry
        
        # Return the final formatted list, limited to 200 characters
        return (header + release_list).strip()


    def get_current_firmware_version(self):
        """Retrieve the firmware version from the metadata attribute."""
        
        firmware_version = "Unknown version"
        
        # Access the firmware_version in metadata, if available
        if hasattr(self.interface, 'metadata') and hasattr(self.interface.metadata, 'firmware_version'):
            firmware_version = self.interface.metadata.firmware_version
            log.info(f"Firmware version found in metadata: {firmware_version}")
        else:
            log.error("Firmware version not found in metadata.")
        
        return firmware_version

