import asyncio
import configparser
import logging
import logging.config
import time
from kasa import SmartPlug, Discover

# Disable existing loggers to suppress noisy libs
logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': True,
})

# Configure logging
logger = logging.getLogger('battsave')
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')


class PlugState:
    def __init__(self, name, ip_address, config):
        self.name = name
        self.ip_address = ip_address
        self.sample_duration = int(config.get("sample_duration", 300))
        self.cooldown_duration = int(config.get("cooldown_duration", 600))
        self.power_threshold = float(config.get("power_threshold", 5.0))
        self.enabled = config.get("enabled", "true").lower() == "true"

        self.last_state = "off"
        self.timer = 0

    def reset_timer(self):
        self.timer = 0


async def get_device(ip, name, username, password):
    try:
        plug = await Discover.discover_single(ip, username=username, password=password)
        await plug.update()
        return plug
    except Exception as e:
        logger.warning(f"[{name}] Could not connect to {ip}: {e}")
        return None


async def control_plug(plug, state: PlugState):
    try:
        await plug.update()
        if not plug.is_on:
            logger.info(f"[{state.name}] Relay on for sampling.")
            await plug.turn_on()
            await asyncio.sleep(1)

        readings = []
        num_samples = state.sample_duration

        for i in range(num_samples):
            await plug.update()
            try:
                power = plug.emeter_realtime.get("power_mw", 0) / 1000
            except Exception:
                power = 0.0
            readings.append(power)
            await asyncio.sleep(1)

        avg_power = sum(readings[1:]) / max(1, len(readings) - 1)
        logger.info(f"[{state.name}] Average power: {avg_power:.2f} W")

        if any(x == 0.0 for x in readings[1:]):
            logger.info(f"[{state.name}] Device plugged/unplugged. Keeping relay on.")
            return

        if avg_power < state.power_threshold:
            logger.info(f"[{state.name}] Below threshold. Relay off.")
            await plug.turn_off()
            state.last_state = "cooldown"
            state.timer = state.cooldown_duration
        else:
            logger.info(f"[{state.name}] Charging. Keeping relay on.")
            state.last_state = "on"
            state.timer = 0

    except Exception as e:
        logger.warning(f"[{state.name}] Error during control: {e}")


async def main():
    config = configparser.ConfigParser()
    config.read("config.ini")

    if not config.has_section("global"):
        logger.error("Missing [global] section in config file.")
        return
    
    if not config['global'].get("username"):
        logger.error("Missing username in [global] section in config file.")
        return
    
    if not config['global'].get("password"):
        logger.error("Missing password in [global] section in config file.")
        return

    username = config['global'].get('username')
    password = config['global'].get('password')

    plug_states = {}

    # Parse plug configuration
    for section in config.sections():
        if section.startswith("plug:"):
            name = section.split(":", 1)[1]
            ip_address = config[section].get("ip")
            if not ip_address:
                logger.warning(f"[{name}] No IP specified.")
                continue
            plug_states[name] = PlugState(name, ip_address, config[section])

    if not plug_states:
        logger.error("No plug configurations found. Use [plug:<name>] sections in the ini file.")
        return

    logger.info("Starting battery saver control loop.")

    while True:
        for name, state in plug_states.items():
            if not state.enabled:
                continue

            plug = await get_device(state.ip_address, name, username, password)
            if not plug:
                continue

            try:
                await plug.update()
            except Exception as e:
                logger.warning(f"[{name}] Failed to update plug: {e}")
                continue

            if state.last_state == "cooldown" and state.timer > 0:
                if plug.is_on:
                    logger.info(f"[{name}] Plug is on during cooldown. Resetting timer.")
                    state.timer = 0
                    state.last_state = "on"
                else:
                    state.timer -= 1
                    logger.info(f"[{name}] Cooldown: {state.timer} seconds remaining.")
            else:
                await control_plug(plug, state)

        await asyncio.sleep(1)


def main_wrapper():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down.")


if __name__ == "__main__":
    main_wrapper()
