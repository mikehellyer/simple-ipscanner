# Simple-IPScanner

Finds the devices on your network, like Angry IP Scanner, for Linux, macOS and Windows.

- **Scan** any range (`192.168.1.1 - 192.168.1.254`, `192.168.1.10-50`, `192.168.1.0/24`, or several separated by commas). **My network** fills in this computer's own network.
- For each device that's on, you get the ping time, hostname, MAC address, maker (from the IEEE list, bundled), and any open ports you've asked it to check (Tools → Settings).
- Devices that ignore pings, such as phones, are still found: the scanner knocks on a few common TCP ports, and on Linux it also counts a device that has just answered the network's address lookup (ARP).
- **Switched off since last scan**: a device that was on at the last scan and is off now shows as a red row, with the name and MAC it had. One that has been switched on shows in green. The last scan is remembered between runs. Use **Show** to list only the changes.
- **Ping…** (or double-click a device) opens a ping window that pings once a second and shows each reply, plus loss and min/avg/max times.
- **Watch**: right-click a device → *Watch — beep when it…* → *goes offline*, *comes online*, or both. Watched devices are checked every few seconds on the **Watching** tab. When one changes, it beeps (falling notes for offline, rising for online) and shows a red banner. A device only counts as offline after 2 missed replies in a row, so one lost ping doesn't set off the alarm. In Settings you can change the check interval, the number of missed replies, the volume, and whether it keeps beeping until you click Silence.
- **Name** any device (the name follows its MAC address). Export the results as CSV.

## Running from source

```bash
python3 -m venv venv
venv/bin/pip install -r requirements-dev.txt -e .
venv/bin/simple-ipscanner
```

Tests: `venv/bin/pytest`

## Building

- Linux .deb on this machine: `bash packaging/linux/build-local.sh` (bumps the patch version and commits).
- All three installers: push a `v*` tag. GitHub Actions builds the .deb, .dmg and Windows setup and attaches them to a release, which the in-app update check looks for.

The MAC maker list comes from the IEEE. To refresh it, download `oui.csv` from https://standards-oui.ieee.org/oui/oui.csv and run `venv/bin/python tools/build_oui.py oui.csv`.
