# Blueprints

Blueprints are optional Home Assistant automations that complement Omnibattery. They are not part of the integration configuration and do not change its code. Import one from **Settings → Automations & scenes → Blueprints** using its link below, then create an automation from it.

For manual installation, copy the YAML file to `/config/blueprints/automation/omnibattery/` and reload blueprints. See [Installation](installation.md#blueprint-installation) for the general steps.

## Central status webhook reporter

[Import blueprint](https://raw.githubusercontent.com/ffunes/Omnibattery/main/blueprints/central_status_webhook_reporter_blueprint.yaml)

Reports selected Omnibattery and Home Assistant sensors from each installation to a central HTTP endpoint. This is useful for a single dashboard covering several homes or batteries.

Choose a unique site ID, the sensors to report (for example SOC, battery power, grid power, and integration state), and a reporting interval. A report is also sent when Home Assistant starts. Each report contains the site ID, timestamp, and every selected entity's state, name, unit, and device class.

Home Assistant requires the outgoing HTTP command to be defined once in `configuration.yaml`; a blueprint cannot create it itself:

```yaml
rest_command:
  omnibattery_status_report:
    url: !secret omnibattery_status_webhook_url
    method: POST
    content_type: application/json
    payload: "{{ report }}"
```

Store the URL in `secrets.yaml`, restart Home Assistant, and retain the default REST command service in the blueprint unless you chose a different name. Use HTTPS and treat the endpoint URL as a secret.

## Different grid target for charge and discharge

[Import blueprint](https://raw.githubusercontent.com/ffunes/Omnibattery/main/blueprints/different_grid_target_blueprint.yaml)

Sets **PD Target Grid Power** according to the active battery direction. By default it sets `-50 W` while charging (a small grid export) and `+50 W` while discharging (a small grid import). This can help avoid oscillation around a zero-grid target or implement a deliberate import/export bias.

Select the system charge and discharge power sensors plus the **PD Target Grid Power** number. The active-power threshold ignores noise near zero. Optionally, set an idle target; otherwise the existing target is left unchanged while the system is idle. The automation runs when power crosses the threshold and when Home Assistant starts.

## Peak shaving limit sync

[Import blueprint](https://raw.githubusercontent.com/ffunes/Omnibattery/main/blueprints/peak_shaving_limit_sync_blueprint.yaml)

Synchronizes Omnibattery's **Capacity Protection Limit** with a monthly-peak sensor. It is intended for tariffs or demand-management setups where the allowed peak follows a measured monthly value.

Select the monthly-peak sensor and the Capacity Protection Limit number. The source can use either `kW` or `W`; the blueprint converts `kW` to watts automatically. It checks on changes and every 15 seconds, and only writes the number when its value differs from the measured peak.

## Peak shaving recharge to SOC

[Import blueprint](https://raw.githubusercontent.com/ffunes/Omnibattery/main/blueprints/peak_shaving_recharge_blueprint.yaml)

Optionally replenishes the battery from the grid while **Capacity Protection** (peak shaving) is active. When system SOC falls below the configured floor, it moves PD Target Grid Power to a positive import value, causing the battery to charge. It restores the idle target when SOC reaches the recovery target or capacity protection ends.

Select the system SOC and integration-status sensors and the PD Target Grid Power number. Configure the SOC floor, a higher SOC recovery target, charge power, and idle target. The automation only restores the idle target when the recharge target is still in place, so it does not overwrite a later manual change or a different automation's target.

## Forward persistent notifications to Telegram

[Import blueprint](https://raw.githubusercontent.com/ffunes/Omnibattery/main/blueprints/persistent_notification_to_telegram_blueprint.yaml)

Forwards new or updated Home Assistant persistent notifications to a selected Telegram notify entity. It sends the notification title, ID, and message with HTML-safe escaping.

Choose a `telegram_bot` notify entity and, optionally, an ID-prefix filter. The default `marstek_venus_` preserves compatibility with notifications created by the earlier integration; clear the filter to forward every persistent notification, or replace it with another prefix. Existing notifications are not resent when Home Assistant restarts.

## Dismiss predictive charging notifications

[Import blueprint](https://raw.githubusercontent.com/ffunes/Omnibattery/main/blueprints/dismiss_predictive_charging_notifications_blueprint.yaml)

Automatically dismisses persistent notifications about predictive grid charging, including evaluations, price-slot starts, and evening re-evaluations. It leaves battery alarms, cell-balance messages, and manual-mode notifications untouched.

The notification may be visible briefly before Home Assistant executes the automation. Disable the automation at any time to receive predictive-charging notifications again.

## Solar forecast reserve discharge

[Import blueprint](https://raw.githubusercontent.com/ffunes/Omnibattery/main/blueprints/solar_forecast_reserve_discharge_blueprint.yaml)

Maintains a night SOC reserve by controlling Omnibattery's **Allow Discharge** switches. It blocks discharge at the reserve unless the remaining solar forecast is sufficient to recharge from the configured minimum SOC back to the reserve during a specified daytime window.

Select all Allow Discharge switches to control, the system SOC and total-energy sensors, a *remaining* solar-forecast sensor in kWh, and the minimum-SOC numbers for the controlled batteries. Configure the reserve, release hysteresis, forecast margin, and daytime window. The calculation includes a fixed 78% charge-efficiency assumption and the safety margin. The blueprint only toggles Allow Discharge; it never writes Modbus registers or forces battery modes.
