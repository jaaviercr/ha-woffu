# Woffu for Home Assistant

<p align="center">
  <img src="custom_components/woffu/brand/icon.png" alt="Woffu icon" width="128">
</p>

Custom Home Assistant integration to check and manage your [Woffu](https://woffu.com/) clock-in status from your smart home.

> This project is not affiliated with, endorsed by, or supported by Woffu. Use at your own risk.

## Features

- Clock in and out from Home Assistant.
- See whether you are currently clocked in.
- Track the time worked during the current day.
- Configure several Woffu accounts, each as a separate integration entry.
- Full setup from the user interface, with English, Spanish and Catalan translations.

## Requirements

- Home Assistant 2026.2 or newer.
- A Woffu account that can log in at `gtd.woffu.com`.
- Outbound internet access from your Home Assistant instance.

## Installation

### HACS (custom repository)

1. In HACS, open the three-dot menu and choose **Custom repositories**.
2. Add `https://github.com/jaaviercr/ha-woffu` as an **Integration**.
3. Install **Woffu** and restart Home Assistant.

### Manual

1. Copy the `woffu` folder into `custom_components` inside your Home Assistant configuration directory.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings > Devices & Services > Add Integration** and search for **Woffu**.
2. Enter your Woffu username and password.

To add another account, repeat the process with different credentials. Each account creates its own device and entities.

Use **Configure** on the integration to change the scan interval. The default is 60 seconds and the minimum is 10 seconds.

If your password changes, Home Assistant asks you to re-authenticate. You can also use **Reconfigure** to update the credentials yourself.

## Entities

Each account creates one device with the following entities:

| Entity | Type | Description |
| --- | --- | --- |
| Clock in | `switch` | Turn on to clock in, turn off to clock out. |
| Worked time today | `sensor` | Hours worked during the current day, as a decimal value. |

The sensor reports hours, not minutes. For example, `4.5` means four hours and thirty minutes.

## How clocking works

Woffu decides whether a new sign is an entry or an exit based on the signs already recorded for the day. The API does not accept an explicit direction.

To avoid registering the opposite of what you asked for, the integration always reads your current status from Woffu immediately before sending a sign, and it sends nothing when you are already in the requested state. This makes the switch slightly slower, but it prevents an accidental clock-in when you meant to clock out.

## Known limitations

- Changes made outside Home Assistant, such as clocking out from the Woffu app, appear after the next update, so up to the configured scan interval.
- Only clocking and worked time are supported. Requests, absences and holidays are not.
- Worked time is calculated from the day's signs. An unusual or manually corrected sign sequence may produce an unexpected value.
- The integration talks to `gtd.woffu.com`. Other Woffu domains are not supported.

## Troubleshooting

Enable debug logging by adding this to `configuration.yaml` and restarting:

```yaml
logger:
  default: warning
  logs:
    custom_components.woffu: debug
```

When reporting a problem, include the Home Assistant version, the integration version and the relevant log lines. Remove your username, password, tokens and user id before sharing anything.

## Roadmap

- Expose clocking as a service.
- Improve caching and add a manual refresh.
- Add the day's full list of signs as entity attributes.

## Credits

Developed by JaavierCR, based on the Woffu API and the Home Assistant custom integration framework.

## License

Released under the [Apache License 2.0](LICENSE).

## Trademarks and disclaimer

Woffu is a trademark of its respective owner. This project is an independent, community-built integration and is not affiliated with, endorsed by, sponsored by, or supported by Woffu. The name is used only to describe what the integration connects to.

## Trademark Legal Notices

All product names, trademarks and registered trademarks in the images in this repository are property of their respective owners. All images in this repository are used by the Home Assistant project for identification purposes only.

The use of these names, trademarks and brands appearing in these image files does not imply endorsement.

The integration relies on the private endpoints used by the Woffu web application. Those endpoints are not a published, stable API and may change or stop working at any time. Using this integration may be subject to your agreement with Woffu and with your employer, and you are responsible for checking that. Clocking entries created through Home Assistant affect your real attendance records, so review them in Woffu. The software is provided without warranty of any kind.
