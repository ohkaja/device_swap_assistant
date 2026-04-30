
"""Config flow for Device Swap Assistant."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .const import (
    CONF_NEW_DEVICE,
    CONF_OLD_DEVICE,
    DOMAIN,
    ON_FINISH_DELETE,
    ON_FINISH_DISABLE,
    ON_FINISH_KEEP,
)

from . import _async_identify_entity, _async_swap_devices


class DeviceSwapAssistantFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Device Swap Assistant flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._old_device_id: str | None = None
        self._new_device_id: str | None = None
        self._on_finish: str = ON_FINISH_DISABLE
        self._result: dict[str, Any] | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            self._old_device_id = user_input[CONF_OLD_DEVICE]
            self._new_device_id = user_input[CONF_NEW_DEVICE]
            self._on_finish = user_input.get("on_finish", ON_FINISH_DISABLE)

            if self._old_device_id == self._new_device_id:
                errors["base"] = "same_device"
            else:
                return await self.async_step_identify_old()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_OLD_DEVICE): selector.DeviceSelector(
                        selector.DeviceSelectorConfig()
                    ),
                    vol.Required(CONF_NEW_DEVICE): selector.DeviceSelector(
                        selector.DeviceSelectorConfig()
                    ),
                    vol.Optional("on_finish", default=ON_FINISH_DISABLE): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": ON_FINISH_KEEP, "label": "Alte Entities behalten"},
                                {"value": ON_FINISH_DISABLE, "label": "Alte Entities deaktivieren"},
                                {"value": ON_FINISH_DELETE, "label": "Alte Entities löschen"},
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_identify_old(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            if user_input.get("identify"):
                await self._identify_first_entity(self._old_device_id)
            return await self.async_step_identify_new()

        return self.async_show_form(
            step_id="identify_old",
            data_schema=vol.Schema(
                {
                    vol.Optional("identify", default=True): selector.BooleanSelector(),
                }
            ),
        )

    async def async_step_identify_new(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            if user_input.get("identify"):
                await self._identify_first_entity(self._new_device_id)
            return await self.async_step_confirm()

        return self.async_show_form(
            step_id="identify_new",
            data_schema=vol.Schema(
                {
                    vol.Optional("identify", default=True): selector.BooleanSelector(),
                }
            ),
        )

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input.get("confirm"):
                return self.async_abort(reason="user_cancelled")
            try:
                self._result = await _async_swap_devices(
                    self.hass,
                    self._old_device_id,
                    self._new_device_id,
                    self._on_finish,
                )
            except HomeAssistantError:
                errors["base"] = "swap_failed"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title="Device Swap Assistant - letzter Swap",
                    data={
                        CONF_OLD_DEVICE: self._old_device_id,
                        CONF_NEW_DEVICE: self._new_device_id,
                        "on_finish": self._on_finish,
                        "result": self._result,
                    },
                )

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {
                    vol.Required("confirm", default=False): selector.BooleanSelector(),
                }
            ),
            errors=errors,
        )

    async def _identify_first_entity(self, device_id: str | None) -> None:
        """Identify the first light/switch entity on a device."""
        if device_id is None:
            return

        from homeassistant.helpers import entity_registry as er

        entity_reg = er.async_get(self.hass)
        entries = list(er.async_entries_for_device(entity_reg, device_id))

        for entry in entries:
            if entry.entity_id.startswith(("light.", "switch.")):
                await _async_identify_entity(self.hass, entry.entity_id)
                return

        raise HomeAssistantError("No identifiable light/switch entity found")
