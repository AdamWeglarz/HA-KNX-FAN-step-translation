from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from typing import Any, List, Optional

import voluptuous as vol
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.typing import ConfigType
import homeassistant.helpers.config_validation as cv

DOMAIN = "knx_step_bridge"
_LOGGER = logging.getLogger(__name__)

CONF_BRIDGES = "bridges"
CONF_NAME = "name"
CONF_STEP_ADDRESS = "step_address"
CONF_PERCENT_ADDRESS = "percent_address"
CONF_MAX_STEP = "max_step"
CONF_DEBOUNCE_MS = "debounce_ms"

BRIDGE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_STEP_ADDRESS): cv.string,
        vol.Required(CONF_PERCENT_ADDRESS): cv.string,
        vol.Required(CONF_MAX_STEP): vol.All(int, vol.Range(min=1, max=255)),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_BRIDGES): vol.All(cv.ensure_list, [BRIDGE_SCHEMA]),
                vol.Optional(CONF_DEBOUNCE_MS, default=500): vol.All(
                    int, vol.Range(min=0, max=5000)
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


@dataclass
class Bridge:
    name: str
    step_address: str
    percent_address: str
    max_step: int
    last_sent_step_ts: float = 0.0       # kiedy ostatnio wysłano step (anty-echo)
    last_sent_percent_ts: float = 0.0    # kiedy ostatnio wysłano percent (anty-echo)


class KnxStepBridgeManager:
    def __init__(self, hass: HomeAssistant, debounce_ms: int) -> None:
        self.hass = hass
        self.bridges: List[Bridge] = []
        self._unsub_event = None
        self._debounce = debounce_ms / 1000.0

    def add_bridge(self, b: Bridge) -> None:
        self.bridges.append(b)

    async def async_start(self) -> None:
        self._unsub_event = self.hass.bus.async_listen("knx_event", self._handle_knx_event)
        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._async_stop)
        _LOGGER.info("%s: started with %d bridge(s)", DOMAIN, len(self.bridges))

    async def _async_stop(self, *_: Any) -> None:
        if self._unsub_event:
            self._unsub_event()
            self._unsub_event = None
        _LOGGER.info("%s: stopped", DOMAIN)

    @callback
    def _find_bridge_by_address(self, address: str) -> Optional[Bridge]:
        for b in self.bridges:
            if address == b.step_address or address == b.percent_address:
                return b
        return None

    @callback
    def _now(self) -> float:
        return asyncio.get_running_loop().time()

    async def _handle_knx_event(self, event) -> None:
        data = event.data or {}
        address = data.get("address") or data.get("destination")
        payload = data.get("data")  # zwykle "0x.." (hex) lub lista/int
        if not address or payload is None:
            return

        bridge = self._find_bridge_by_address(address)
        if not bridge:
            return

        raw = self._payload_to_int(payload)
        if raw is None:
            _LOGGER.debug("Unknown KNX payload format for %s: %r", address, payload)
            return

        now = self._now()

        if address == bridge.step_address:
            # anty-echo
            if now - bridge.last_sent_step_ts < self._debounce:
                return
            step = max(0, min(bridge.max_step, raw))
            percent = int(math.floor(step * 100 / bridge.max_step))
            await self._send_percent(bridge, percent)

        elif address == bridge.percent_address:
            # anty-echo
            if now - bridge.last_sent_percent_ts < self._debounce:
                return

            # DPT 5.001: zawsze interpretuj jako bajt 0..255
            percent = int(round((raw / 255.0) * 100))
            percent = max(0, min(100, percent))

            # % -> step: CEIL (np. 33% -> 1 przy max_step=3; 66% -> 2; 100% -> 3)
            if percent <= 0:
                step = 0
            else:
                step = int(math.ceil(percent * bridge.max_step / 100.0))
                if step > bridge.max_step:
                    step = bridge.max_step

            await self._send_step(bridge, step)

    @staticmethod
    def _payload_to_int(payload: Any) -> Optional[int]:
        if isinstance(payload, int):
            return payload
        if isinstance(payload, str):
            try:
                return int(payload, 16) if payload.startswith("0x") else int(payload)
            except ValueError:
                return None
        if isinstance(payload, (list, tuple)) and payload:
            try:
                return int(payload[0])
            except (TypeError, ValueError):
                return None
        if isinstance(payload, (bytes, bytearray)) and len(payload) >= 1:
            return payload[0]
        return None

    async def _send_percent(self, bridge: Bridge, percent: int) -> None:
        percent = max(0, min(100, percent))
        bridge.last_sent_percent_ts = self._now()
        await self.hass.services.async_call(
            "knx",
            "send",
            {
                "address": bridge.percent_address,
                "payload": percent,
                "type": "percent"
            },
            blocking=False,
        )
        _LOGGER.debug("[%s] step→percent: %s → %s%%",
                      bridge.name, bridge.step_address, percent)

    async def _send_step(self, bridge: Bridge, step: int) -> None:
        step = max(0, min(bridge.max_step, step))
        bridge.last_sent_step_ts = self._now()
        await self.hass.services.async_call(
            "knx",
            "send",
            {
                "address": bridge.step_address,
                "payload": step,
                "type": "1byte_unsigned"
            },
            blocking=False,
        )
        _LOGGER.debug("[%s] percent→step: %s → step=%s/%s",
                      bridge.name, bridge.percent_address, step, bridge.max_step)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    conf = config.get(DOMAIN)
    if not conf:
        return True

    debounce_ms: int = conf.get(CONF_DEBOUNCE_MS, 500)
    mgr = KnxStepBridgeManager(hass, debounce_ms)

    for item in conf[CONF_BRIDGES]:
        b = Bridge(
            name=item[CONF_NAME],
            step_address=item[CONF_STEP_ADDRESS],
            percent_address=item[CONF_PERCENT_ADDRESS],
            max_step=item[CONF_MAX_STEP],
        )
        mgr.add_bridge(b)

    hass.data[DOMAIN] = mgr
    await mgr.async_start()
    return True
