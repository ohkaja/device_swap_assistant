
"""Device Swap Assistant custom integration.

Experimental helper to swap Home Assistant entity_ids from an old/broken
entity/device to a replacement entity/device.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.helpers.typing import ConfigType

from .const import (
    DOMAIN,
    ON_FINISH_DELETE,
    ON_FINISH_DISABLE,
    ON_FINISH_KEEP,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up services."""

    async def async_identify(call: ServiceCall) -> None:
        entity_id: str = call.data["entity_id"]
        await _async_identify_entity(hass, entity_id)

    async def async_swap_entities(call: ServiceCall) -> dict[str, Any]:
        return await _async_swap_entities(
            hass,
            call.data["old_entity_id"],
            call.data["new_entity_id"],
            call.data.get("on_finish", ON_FINISH_DISABLE),
        )

    async def async_swap_devices(call: ServiceCall) -> dict[str, Any]:
        return await _async_swap_devices(
            hass,
            call.data["old_device_id"],
            call.data["new_device_id"],
            call.data.get("on_finish", ON_FINISH_DISABLE),
        )

    hass.services.async_register(
        DOMAIN,
        "identify",
        async_identify,
        schema=vol.Schema(
            {
                vol.Required("entity_id"): selector.EntitySelector(
                    selector.EntitySelectorConfig()
                ),
            }
        ),
        supports_response=False,
    )

    hass.services.async_register(
        DOMAIN,
        "swap_entities",
        async_swap_entities,
        schema=vol.Schema(
            {
                vol.Required("old_entity_id"): selector.EntitySelector(
                    selector.EntitySelectorConfig()
                ),
                vol.Required("new_entity_id"): selector.EntitySelector(
                    selector.EntitySelectorConfig()
                ),
                vol.Optional("on_finish", default=ON_FINISH_DISABLE): vol.In(
                    [ON_FINISH_KEEP, ON_FINISH_DISABLE, ON_FINISH_DELETE]
                ),
            }
        ),
        supports_response=True,
    )

    hass.services.async_register(
        DOMAIN,
        "swap_devices",
        async_swap_devices,
        schema=vol.Schema(
            {
                vol.Required("old_device_id"): selector.DeviceSelector(
                    selector.DeviceSelectorConfig()
                ),
                vol.Required("new_device_id"): selector.DeviceSelector(
                    selector.DeviceSelectorConfig()
                ),
                vol.Optional("on_finish", default=ON_FINISH_DISABLE): vol.In(
                    [ON_FINISH_KEEP, ON_FINISH_DISABLE, ON_FINISH_DELETE]
                ),
            }
        ),
        supports_response=True,
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Nothing to set up; config flow performs the operation."""
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload config entry."""
    return True


async def _async_identify_entity(hass: HomeAssistant, entity_id: str) -> None:
    """Try to make an entity visually/audibly identify itself."""
    domain = entity_id.split(".", 1)[0]
    state = hass.states.get(entity_id)

    if domain == "light":
        # Most light integrations support flash=short; unsupported ones ignore/fail harmlessly.
        await hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": entity_id, "flash": "short"},
            blocking=True,
        )
        return

    if domain in {"switch", "input_boolean"}:
        was_on = state is not None and state.state == "on"
        service_domain = domain
        await hass.services.async_call(service_domain, "turn_on", {"entity_id": entity_id}, blocking=True)
        await asyncio.sleep(0.5)
        await hass.services.async_call(service_domain, "turn_off", {"entity_id": entity_id}, blocking=True)
        await asyncio.sleep(0.5)
        if was_on:
            await hass.services.async_call(service_domain, "turn_on", {"entity_id": entity_id}, blocking=True)
        return

    raise HomeAssistantError(f"Identify is not implemented for domain '{domain}'")


def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0]


def _make_old_entity_id(entity_id: str, entity_reg: er.EntityRegistry) -> str:
    """Return a free *_old entity_id for the old entity."""
    domain, object_id = entity_id.split(".", 1)
    candidate = f"{domain}.{object_id}_old"
    index = 2
    while entity_reg.async_get(candidate) is not None:
        candidate = f"{domain}.{object_id}_old_{index}"
        index += 1
    return candidate


def _copy_entity_metadata(
    entity_reg: er.EntityRegistry,
    old_entry: er.RegistryEntry,
    new_entity_id: str,
) -> None:
    """Copy user-facing metadata from old entry to new entity."""
    update_kwargs: dict[str, Any] = {
        "name": old_entry.name,
        "icon": old_entry.icon,
    }

    # Attribute availability differs a bit by HA version; only copy when present.
    if hasattr(old_entry, "area_id"):
        update_kwargs["area_id"] = old_entry.area_id
    if hasattr(old_entry, "labels"):
        update_kwargs["labels"] = old_entry.labels
    if hasattr(old_entry, "aliases"):
        update_kwargs["aliases"] = old_entry.aliases
    if hasattr(old_entry, "categories"):
        update_kwargs["categories"] = old_entry.categories

    # Remove keys with None where HA expects omission.
    update_kwargs = {k: v for k, v in update_kwargs.items() if v is not None}
    if update_kwargs:
        entity_reg.async_update_entity(new_entity_id, **update_kwargs)


async def _async_swap_entities(
    hass: HomeAssistant,
    old_entity_id: str,
    new_entity_id: str,
    on_finish: str = ON_FINISH_DISABLE,
) -> dict[str, Any]:
    """Swap one old entity_id onto one replacement entity."""
    if _domain(old_entity_id) != _domain(new_entity_id):
        raise HomeAssistantError(
            f"Domain mismatch: {old_entity_id} cannot be swapped with {new_entity_id}"
        )

    entity_reg = er.async_get(hass)
    old_entry = entity_reg.async_get(old_entity_id)
    new_entry = entity_reg.async_get(new_entity_id)

    if old_entry is None:
        raise HomeAssistantError(f"Old entity is not in entity registry: {old_entity_id}")
    if new_entry is None:
        raise HomeAssistantError(f"New entity is not in entity registry: {new_entity_id}")

    freed_old_id = _make_old_entity_id(old_entity_id, entity_reg)

    # 1) Move old entity away.
    entity_reg.async_update_entity(old_entity_id, new_entity_id=freed_old_id)

    # 2) Give new entity the old canonical entity_id.
    entity_reg.async_update_entity(new_entity_id, new_entity_id=old_entity_id)

    # 3) Copy metadata to the entity now living at old_entity_id.
    _copy_entity_metadata(entity_reg, old_entry, old_entity_id)

    # 4) Disable/delete old registry entry now living at freed_old_id.
    if on_finish == ON_FINISH_DISABLE:
        entity_reg.async_update_entity(freed_old_id, disabled_by=er.RegistryEntryDisabler.USER)
    elif on_finish == ON_FINISH_DELETE:
        entity_reg.async_remove(freed_old_id)

    # 5) Blink replacement after swap if possible.
    try:
        await _async_identify_entity(hass, old_entity_id)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Post-swap identify failed for %s: %s", old_entity_id, err)

    return {
        "old_entity_id": old_entity_id,
        "new_entity_id": new_entity_id,
        "freed_old_entity_id": freed_old_id,
        "on_finish": on_finish,
        "success": True,
    }


def _entries_by_domain(entries: list[er.RegistryEntry]) -> dict[str, list[er.RegistryEntry]]:
    by_domain: dict[str, list[er.RegistryEntry]] = defaultdict(list)
    for entry in entries:
        by_domain[_domain(entry.entity_id)].append(entry)
    for domain_entries in by_domain.values():
        domain_entries.sort(key=lambda item: item.entity_id)
    return by_domain


async def _async_swap_devices(
    hass: HomeAssistant,
    old_device_id: str,
    new_device_id: str,
    on_finish: str = ON_FINISH_DISABLE,
) -> dict[str, Any]:
    """Swap matching-domain entities between two devices."""
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    if device_reg.async_get(old_device_id) is None:
        raise HomeAssistantError(f"Old device not found: {old_device_id}")
    if device_reg.async_get(new_device_id) is None:
        raise HomeAssistantError(f"New device not found: {new_device_id}")

    old_entries = list(er.async_entries_for_device(entity_reg, old_device_id))
    new_entries = list(er.async_entries_for_device(entity_reg, new_device_id))

    old_by_domain = _entries_by_domain(old_entries)
    new_by_domain = _entries_by_domain(new_entries)

    results: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for domain, old_domain_entries in old_by_domain.items():
        new_domain_entries = new_by_domain.get(domain, [])
        for old_entry, new_entry in zip(old_domain_entries, new_domain_entries, strict=False):
            try:
                result = await _async_swap_entities(
                    hass,
                    old_entry.entity_id,
                    new_entry.entity_id,
                    on_finish,
                )
                results.append(result)
            except Exception as err:  # noqa: BLE001
                skipped.append(
                    {
                        "old_entity_id": old_entry.entity_id,
                        "new_entity_id": new_entry.entity_id,
                        "reason": str(err),
                    }
                )

        if len(old_domain_entries) > len(new_domain_entries):
            for entry in old_domain_entries[len(new_domain_entries):]:
                skipped.append(
                    {
                        "old_entity_id": entry.entity_id,
                        "reason": f"No replacement entity with domain '{domain}'",
                    }
                )

    return {
        "success": bool(results) and not skipped,
        "swapped": results,
        "skipped": skipped,
    }
