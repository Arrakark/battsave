import asyncio
import configparser
import logging
import time
from kasa import Discover
import logging.config
logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': True,
})

# Configure logging
logger = logging.getLogger('battsave')
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

class PlugState:
    def __init__(self, name, config):
        self.name = name
        self.sample_duration = int(config.get("sample_duration", 300))
        self.cooldown_duration = int(config.get("cooldown_duration", 600))
        self.keep_charging_if_unplugged = config.get("keep_charging_if_unplugged", "false").lower() == "true"
        self.power_threshold = float(config.get("power_threshold", 5.0))
        self.enabled = config.get("enabled", "true").lower() == "true"

        self.last_state = "off"
        self.timer = 0

    def reset_timer(self):
        self.timer = 0

async def get_device_map(username, password, interface):
    devices = await Discover.discover(username=username, password=password, interface=interface)
    result = {}
    for dev in devices.values():
        try:
            await dev.update()
            result[dev.alias] = dev
        except Exception as e:
            logger.warning(f"Failed to update device during discovery: {e}")
    return result

async def control_plug(plug, state: PlugState, lost_contact_count, poll_interval):
    try:
        await plug.update()
        if not plug.is_on:
            logger.info(f"[{state.name}] Turning on for sampling.")
            await plug.turn_on()
            await asyncio.sleep(1)  # small delay to allow state update

        sample_interval = poll_interval  # seconds between power samples
        readings = []
        num_samples = state.sample_duration // sample_interval

        for i in range(num_samples):
            await plug.update()
            power = plug.emeter_realtime.get("power_mw", 0) / 1000
            readings.append(power)
            # logger.info(f"[{state.name}] Sample {i+1}: {power:.2f} W")
            await asyncio.sleep(sample_interval)

        avg_power = sum(readings[1:]) / max(1, len(readings) - 1)  # exclude first sample
        logger.info(f"[{state.name}] Average power: {avg_power:.2f} W")

        if state.keep_charging_if_unplugged and any(x == 0.0 for x in readings[1:]):
            logger.info(f"[{state.name}] Device unplugged. Relay on.")
            pass
        elif avg_power < state.power_threshold:
            logger.info(f"[{state.name}] Below threshold. Relay off.")
            await plug.turn_off()
            state.last_state = "cooldown"
            state.timer = state.cooldown_duration
        else:
            logger.info(f"[{state.name}] Relay on.")
            state.last_state = "on"
            state.timer = 0

    except Exception as e:
        logger.warning(f"[{state.name}] Error: {e}")

async def main():
    config = configparser.ConfigParser()
    config.read("config.ini")

    if not config.has_section("global"):
        logger.error("Missing [global] section in config file.")
        return

    poll_interval = int(config["global"].get("poll_interval", 10))
    lost_contact_count = int(config["global"].get("lost_contact_count", 1))
    interface = int(config["global"].get("interface", "eth0"))
    username = config["global"].get("username")
    password = config["global"].get("password")

    plug_states = {}

    # Load config for each plug
    for section in config.sections():
        if section.startswith("plug:"):
            name = section.split(":", 1)[1]
            plug_states[name] = PlugState(name, config[section])

    if not plug_states:
        logger.error("No plug configurations found. Use [plug:<name>] sections in the ini file.")
        return

    logger.info("Starting battery saver control loop.")

    while True:
        device_map = await get_device_map(username, password, interface)

        for name, state in plug_states.items():
            if not state.enabled:
                continue
            plug = device_map.get(name)
            if not plug:
                logger.info(f"[{name}] Plug not found on network. Cooldown reset.")
                state.reset_timer()
                continue

            if state.last_state == "cooldown" and state.timer > 0:
                state.timer -= poll_interval
                logger.info(f"[{name}] Cooldown: {state.timer} samples remaining.")
            else:
                await control_plug(plug, state, lost_contact_count, poll_interval)

        await asyncio.sleep(poll_interval)

def main_wrapper():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Shutting down.")

if __name__ == "__main__":
    main_wrapper()