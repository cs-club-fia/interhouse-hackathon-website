#!/usr/bin/env python3
"""Simple helper to blink the Raspberry Pi ACT LED once the server has started.

This script is safe: it will try to preserve the original trigger if possible and
will fail gracefully if it lacks permissions (run as root or as a systemd ExecStartPost).
"""
import os
import time
import sys


def blink_led(led_path='/sys/class/leds/led0'):
    trigger_path = os.path.join(led_path, 'trigger')
    brightness_path = os.path.join(led_path, 'brightness')
    original_trigger = None
    try:
        if os.path.exists(trigger_path):
            try:
                with open(trigger_path, 'r') as f:
                    original_trigger = f.read()
            except Exception:
                original_trigger = None

            # Try to take manual control
            try:
                with open(trigger_path, 'w') as f:
                    f.write('none')
            except PermissionError:
                print('PermissionError: cannot write trigger (need root).', file=sys.stderr)
        # Blink sequence (short triple flash)
        if os.path.exists(brightness_path):
            try:
                for _ in range(3):
                    with open(brightness_path, 'w') as b:
                        b.write('1')
                    time.sleep(0.18)
                    with open(brightness_path, 'w') as b:
                        b.write('0')
                    time.sleep(0.12)
            except PermissionError:
                print('PermissionError: cannot write brightness (need root).', file=sys.stderr)
        else:
            print('Brightness path not found at', brightness_path, file=sys.stderr)
    except Exception as e:
        print('Unexpected error while blinking LED:', e, file=sys.stderr)
    finally:
        # Restore trigger if we were able to read it
        try:
            if original_trigger and os.path.exists(trigger_path):
                with open(trigger_path, 'w') as f:
                    f.write(original_trigger)
        except Exception:
            # ignore failures restoring
            pass


if __name__ == '__main__':
    led = os.getenv('PI_ACT_LED_PATH', '/sys/class/leds/led0')
    blink_led(led)
