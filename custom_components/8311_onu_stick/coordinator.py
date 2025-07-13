from __future__ import annotations

import logging
import math
import re
from datetime import timedelta
from typing import Any

import paramiko
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_HOST, CONF_KEY_PATH, CONF_USER, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

class OnuDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data via SSH from the ONU stick."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.config = entry.data
        self.entry = entry
        # Get scan interval from options first, then from data (for backward compatibility), then default
        scan_interval = timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, 
                                                          entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)))
        _LOGGER.debug("Initializing coordinator with scan interval: %s seconds (options: %s, data: %s, default: %s)", 
                     scan_interval.total_seconds(), entry.options.get(CONF_SCAN_INTERVAL), 
                     entry.data.get(CONF_SCAN_INTERVAL), DEFAULT_SCAN_INTERVAL)
        super().__init__(hass, _LOGGER, name=f"ONU Stick {entry.data[CONF_HOST]}", update_interval=scan_interval)

    def update_scan_interval(self) -> None:
        """Update the scan interval from the config entry options."""
        new_interval = timedelta(seconds=self.entry.options.get(CONF_SCAN_INTERVAL, 
                                                               self.entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)))
        _LOGGER.debug("Updating scan interval to %s seconds (options: %s, data: %s, default: %s)", 
                     new_interval.total_seconds(), self.entry.options.get(CONF_SCAN_INTERVAL), 
                     self.entry.data.get(CONF_SCAN_INTERVAL), DEFAULT_SCAN_INTERVAL)
        self.update_interval = new_interval
        _LOGGER.debug("Updated scan interval to %s seconds", new_interval.total_seconds())

    def _run_ssh_command(self, client, command):
        """Helper to run a command over SSH and return its output."""
        _LOGGER.debug("Running SSH command: %s", command)
        try:
            _LOGGER.debug("Executing command with 10 second timeout...")
            _, stdout, stderr = client.exec_command(command, timeout=10)
            _LOGGER.debug("Command executed, reading output...")
            
            error = stderr.read().decode("utf-8").strip()
            if error:
                _LOGGER.error("SSH command '%s' error: %s", command, error)
                return None
            
            output = stdout.read().decode("utf-8").strip()
            _LOGGER.debug("SSH command output length: %d characters", len(output))
            return output
        except Exception as e:
            _LOGGER.error("Failed to run command '%s': %s", command, e)
            return None



    def _pon_state(self, status_code):
        """Translates PON state code to a human-readable string."""
        states = {
            0: "O0, Power-up state", 10: "O1, Initial state", 11: "O1.1, Off-sync state",
            12: "O1.2, Profile learning state", 20: "O2, Stand-by state", 23: "O2.3, Serial number state",
            30: "O3, Serial number state", 40: "O4, Ranging state", 50: "O5, Operation state",
            51: "O5.1, Associated state", 52: "O5.2, Pending state", 60: "O6, Intermittent LOS state",
            70: "O7, Emergency stop state", 71: "O7.1, Emergency stop off-sync state",
            72: "O7.2, Emergency stop in-sync state", 81: "O8.1, Downstream tuning off-sync state",
            82: "O8.2, Downstream tuning profile learning state", 90: "O9, Upstream tuning state",
        }
        return states.get(status_code, f"Unknown ({status_code})")

    def _dbm(self, mw):
        """Converts milliwatts to dBm."""
        if mw is None or mw <= 0:
            return None
        return round(10 * math.log10(mw), 2)

    def _parse_uptime(self, uptime_str):
        """Parse uptime string into a human-readable format."""
        try:
            match = re.match(r".*up\s+(((\d+)\s*day[s]?,\s*)?(\d+):(\d{2}))", uptime_str)
            if match:
                days = int(match.group(3)) if match.group(3) else 0
                hours = int(match.group(4))
                minutes = int(match.group(5))
                parts = []
                if days > 0: parts.append(f"{days} d")
                if hours > 0: parts.append(f"{hours} h")
                if minutes > 0: parts.append(f"{minutes} m")
                return ", ".join(parts) or "less than a minute"
            return "unknown"
        except Exception as e:
            _LOGGER.error(f"Failed to parse uptime: {e}")
            return "unknown"

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from ONU."""
        all_data = {}
        _LOGGER.debug("Starting data update for ONU at %s", self.config[CONF_HOST])
        _LOGGER.debug("SSH username: %s", self.config[CONF_USER])
        
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            _LOGGER.debug("Created SSH client")

            connect_kwargs = {
                "hostname": self.config[CONF_HOST],
                "username": self.config[CONF_USER],
                "timeout": 10,
                "key_filename": self.config[CONF_KEY_PATH],
            }
            _LOGGER.debug("SSH connection kwargs: %s", connect_kwargs)

            _LOGGER.debug("Attempting SSH connection...")
            await self.hass.async_add_executor_job(lambda: client.connect(**connect_kwargs))
            _LOGGER.debug("SSH connection successful")

            delimiter = "---Boundary-ONU-exporter---"
            commands = [
                "pon psg", "cat /sys/class/thermal/thermal_zone0/temp", "cat /sys/class/thermal/thermal_zone1/temp",
                "xxd -p /sys/class/pon_mbox/pon_mbox0/device/eeprom50", "xxd -p /sys/class/pon_mbox/pon_mbox0/device/eeprom51",
                "cat /sys/class/net/eth0_0/speed", "uci get gpon.ponip.pon_mode", ". /lib/8311.sh && get_8311_module_type",
                ". /lib/8311.sh && active_fwbank", "uptime", "free -m", "cat /proc/cpuinfo",
                "cat /etc/8311_version", ". /lib/8311.sh && get_8311_lct_mac", ". /lib/8311.sh && get_8311_gpon_sn",
            ]
            _LOGGER.debug("Commands to execute: %s", commands)
            chained_command = f"; echo '{delimiter}'; ".join(commands)
            _LOGGER.debug("Chained command length: %d characters", len(chained_command))
            
            _LOGGER.debug("Executing SSH command...")
            full_output = await self.hass.async_add_executor_job(self._run_ssh_command, client, chained_command)
            _LOGGER.debug("SSH command completed, output length: %d characters", len(full_output) if full_output else 0)

            client.close()

            if not full_output:
                _LOGGER.error("No output received from SSH command")
                raise UpdateFailed("No output from SSH command")

            _LOGGER.debug("Raw SSH output (first 500 chars): %s", full_output[:500])
            
            outputs = full_output.split(delimiter)
            outputs = [output.strip() for output in outputs]
            _LOGGER.debug("Split outputs count: %d (expected: %d)", len(outputs), len(commands))

            if len(outputs) < len(commands):
                _LOGGER.error("Mismatch in command output count. Got %d, expected %d", len(outputs), len(commands))
                _LOGGER.debug("Outputs: %s", outputs)
                raise UpdateFailed("Mismatch in command output count")

            # Parsing logic from the original script
            _LOGGER.debug("Parsing PLOAM status from: %s", outputs[0])
            ploam_match = re.search(r"current=(\d+)", outputs[0])
            ploam_status = self._pon_state(int(ploam_match.group(1)) if ploam_match else 0)
            all_data["ploam_status"] = ploam_status
            _LOGGER.debug("PLOAM status: %s", ploam_status)
            
            _LOGGER.debug("Parsing CPU temps from: %s, %s", outputs[1], outputs[2])
            all_data["temp_cpu0"] = (int(outputs[1]) / 1000) if outputs[1].isdigit() else None
            all_data["temp_cpu1"] = (int(outputs[2]) / 1000) if outputs[2].isdigit() else None
            _LOGGER.debug("CPU temps: %s, %s", all_data["temp_cpu0"], all_data["temp_cpu1"])

            optic_temp, voltage, tx_bias, tx_mw, rx_mw = None, None, None, None, None
            _LOGGER.debug("Parsing optical data from eeprom51: %s", outputs[4][:100] if outputs[4] else "None")
            if outputs[4]:
                eep51 = bytes.fromhex(outputs[4].replace('\n', ''))
                _LOGGER.debug("eeprom51 length: %d bytes", len(eep51))
                if len(eep51) >= 106:
                    optic_temp = eep51[96] + eep51[97] / 256
                    voltage = ((eep51[98] << 8) + eep51[99]) / 10000
                    tx_bias = ((eep51[100] << 8) + eep51[101]) / 500
                    tx_mw = ((eep51[102] << 8) + eep51[103]) / 10000
                    rx_mw = ((eep51[104] << 8) + eep51[105]) / 10000
                    _LOGGER.debug("Optical data parsed: temp=%s, voltage=%s, tx_bias=%s, tx_mw=%s, rx_mw=%s", 
                                 optic_temp, voltage, tx_bias, tx_mw, rx_mw)
                else:
                    _LOGGER.warning("eeprom51 too short: %d bytes (need 106)", len(eep51))
            else:
                _LOGGER.warning("No eeprom51 data available")

            all_data["rx_power"] = self._dbm(rx_mw)
            all_data["tx_power"] = self._dbm(tx_mw)
            all_data["tx_bias"] = round(tx_bias, 2) if tx_bias is not None else None
            all_data["temp_optic"] = optic_temp
            all_data["voltage"] = voltage
            _LOGGER.debug("Optical sensors: rx_power=%s, tx_power=%s, tx_bias=%s, temp_optic=%s, voltage=%s", 
                         all_data["rx_power"], all_data["tx_power"], all_data["tx_bias"], 
                         all_data["temp_optic"], all_data["voltage"])
            
            _LOGGER.debug("Parsing network data: eth_speed=%s, pon_mode=%s, active_bank=%s", 
                         outputs[5], outputs[6], outputs[8])
            all_data["eth_speed"] = int(outputs[5]) if outputs[5].isdigit() else None
            all_data["pon_mode"] = (outputs[6] or "xgspon").upper().replace("PON", "-PON")
            all_data["active_bank"] = outputs[8] or "A"
            _LOGGER.debug("Network data: eth_speed=%s, pon_mode=%s, active_bank=%s", 
                         all_data["eth_speed"], all_data["pon_mode"], all_data["active_bank"])

            _LOGGER.debug("Parsing system data from uptime: %s", outputs[9])
            load_match = re.search(r"load average:\s*([\d.]+)", outputs[9])
            all_data["cpu_load"] = float(load_match.group(1)) if load_match else 0.0
            all_data["uptime"] = self._parse_uptime(outputs[9])
            _LOGGER.debug("System data: cpu_load=%s, uptime=%s", all_data["cpu_load"], all_data["uptime"])

            _LOGGER.debug("Parsing memory data: %s", outputs[10])
            mem_match = re.search(r"Mem:\s*(\d+)\s*(\d+)\s*(\d+)", outputs[10])
            if mem_match:
                total, used, _ = map(float, mem_match.groups())
                all_data["memory_total"] = total / 1024
                all_data["memory_used"] = used / 1024
                all_data["memory_available"] = (total - used) / 1024
                all_data["memory_percent"] = (used / total) * 100 if total > 0 else 0.0
                _LOGGER.debug("Memory data: total=%s, used=%s, available=%s, percent=%s", 
                             all_data["memory_total"], all_data["memory_used"], 
                             all_data["memory_available"], all_data["memory_percent"])
            else:
                _LOGGER.warning("Could not parse memory data from: %s", outputs[10])

            _LOGGER.debug("Parsing CPU info: %s", outputs[11][:200])
            system_type_match = re.search(r"system type\s*:\s*(.*)", outputs[11])
            machine_match = re.search(r"machine\s*:\s*(.*)", outputs[11])
            all_data["soc_arch"] = system_type_match.group(1).strip() if system_type_match else "unknown"
            all_data["soc_model"] = machine_match.group(1).strip().rstrip('-SFP-PON') if machine_match else "unknown"
            _LOGGER.debug("SoC info: arch=%s, model=%s", all_data["soc_arch"], all_data["soc_model"])

            _LOGGER.debug("Parsing device identifiers: mac=%s, serial=%s", outputs[13], outputs[14])
            all_data["mac_address"] = outputs[13]
            all_data["pon_serial"] = outputs[14].strip() if outputs[14] else "unknown"
            all_data["ip_address"] = self.config[CONF_HOST]
            _LOGGER.debug("Device identifiers: mac=%s, serial=%s, ip=%s", 
                         all_data["mac_address"], all_data["pon_serial"], all_data["ip_address"])

            _LOGGER.debug("Parsing vendor info from eeprom50: %s", outputs[3][:100] if outputs[3] else "None")
            eep50_hex = outputs[3]
            vendor_name, vendor_pn, vendor_rev = "", "", ""
            if eep50_hex:
                eep50 = bytes.fromhex(eep50_hex.replace('\n', ''))
                vendor_name = eep50[20:36].decode('utf-8', 'ignore').strip()
                vendor_pn = eep50[40:56].decode('utf-8', 'ignore').strip()
                vendor_rev = eep50[56:60].decode('utf-8', 'ignore').strip()
                _LOGGER.debug("Vendor info: name=%s, pn=%s, rev=%s", vendor_name, vendor_pn, vendor_rev)
            else:
                _LOGGER.warning("No eeprom50 data available")

            _LOGGER.debug("Parsing firmware info: module_type=%s, version_output=%s", outputs[7], outputs[12][:200])
            module_type = outputs[7] or "bfw"
            version_output = outputs[12]
            fw_version = re.search(r"FW_VERSION=(.*)", version_output)
            fw_revision = re.search(r"FW_REVISION=(.*)", version_output)
            fw_variant = re.search(r"FW_VARIANT=(.*)", version_output)

            all_data["device_model"] = f"{vendor_name} {vendor_pn}"
            all_data["device_hw_version"] = f"{vendor_rev} [{module_type}]"
            all_data["device_sw_version"] = f"8311 [{fw_variant.group(1).strip() if fw_variant else 'unknown'}] - {fw_version.group(1).strip() if fw_version else 'unknown'} ({fw_revision.group(1).strip() if fw_revision else 'unknown'})"
            _LOGGER.debug("Device info: model=%s, hw_version=%s, sw_version=%s", 
                         all_data["device_model"], all_data["device_hw_version"], all_data["device_sw_version"])

            _LOGGER.debug("Successfully fetched data from ONU: %s", list(all_data.keys()))
            return all_data

        except FileNotFoundError as err:
            _LOGGER.error("SSH key file not found: %s", err)
            raise UpdateFailed("SSH key file missing - please reconfigure the integration") from err
        except Exception as err:
            _LOGGER.error("Error communicating with ONU: %s", err)
            raise UpdateFailed(f"Error communicating with API: {err}") from err
