# Device Swap Assistant

Experimental HACS custom integration for Home Assistant.

## What it does

- Select old/broken device and replacement device
- Optionally identify old/new entity by blinking/toggling
- Match entities by domain (`light` -> `light`, `switch` -> `switch`, `sensor` -> `sensor`)
- Move old entity IDs to `*_old`
- Move new entities to the old canonical entity IDs
- Copy friendly name, icon, area, labels where supported by your Home Assistant version
- Optionally keep, disable or delete the old registry entries

## Install

Copy this folder to:

```text
config/custom_components/device_swap_assistant/
```

Restart Home Assistant.

Then go to:

```text
Settings → Devices & services → Add integration → Device Swap Assistant
```

## Services

```yaml
service: device_swap_assistant.identify
data:
  entity_id: light.kueche_decke
```

```yaml
service: device_swap_assistant.swap_entities
data:
  old_entity_id: light.kueche_decke
  new_entity_id: light.neue_lampe
  on_finish: disable
```

```yaml
service: device_swap_assistant.swap_devices
data:
  old_device_id: OLD_DEVICE_ID
  new_device_id: NEW_DEVICE_ID
  on_finish: disable
```

## Warning

This modifies the Home Assistant entity registry. Make a backup first.
