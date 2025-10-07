Raspberry Pi setup: auto-start and ACT LED blink
===============================================

This folder contains a systemd service template and a small helper script to blink the Raspberry Pi ACT LED once the server has started.

Files
- `competitions.service` - systemd unit template. Install as `/etc/systemd/system/competitions.service` and customize paths.

Instructions (summary)
1. Copy this repo to your Raspberry Pi (e.g. `/home/pi/competitions`).
2. Create a Python virtual environment and install dependencies inside the project:

```powershell
# on Pi (bash):
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Install the systemd service (edit paths if needed):

```bash
sudo cp deploy/raspberrypi/competitions.service /etc/systemd/system/competitions.service
sudo systemctl daemon-reload
sudo systemctl enable competitions.service
sudo systemctl start competitions.service
```

4. Verify status and logs:

```bash
sudo systemctl status competitions.service
journalctl -u competitions.service -f
```

Notes
- The service runs `startup.py` using the repo `.venv` Python. Make sure `.venv` exists and dependencies are installed.
- The service additionally runs the `app/pi_act_blink.py` as an ExecStartPost to blink the ACT LED once the main process reports started.
- On some Pi OS images the ACT LED device may be at `/sys/class/leds/led0` (default). If different, set `PI_ACT_LED_PATH` in the service file.
