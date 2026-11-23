"""Bench monitor for the ESP32 link. Stands in for the ROCK 5B application.

Prints every frame the control board sends (heartbeats, buttons, temperature,
faults, brightness, calibration requests), answers heartbeats so the board sees
the link as up, and lets you fake the SBC's replies from the keyboard.

    python tools/link_monitor.py /dev/ttyUSB0          # Linux
    python tools/link_monitor.py /dev/cu.usbserial-XXXX # macOS
    python tools/link_monitor.py COM5                   # Windows

Keys (press Enter after each):
    1..5   set the app state reported in HEARTBEAT_REPLY
           (1 NO_SOURCE, 2 PASSTHROUGH, 3 WARPED, 4 CALIBRATING, 5 ERROR)
    r      send READY (fake successful calibration: 12.0 -> 3.0 px, 75 %)
    e N    send CAL_ERROR with code N (1 DETECT_FAIL, 2 ACCURACY, 3 TIMEOUT, 4 ABORTED, 5 CAMERA)
    q      quit
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from warpei.link import protocol as P          # noqa: E402
from warpei.link.uart import UartLink, open_serial  # noqa: E402


def describe(msg) -> str:
    v = dict(msg.values)
    if msg.id == P.MSG_HEARTBEAT:
        v["fw_state"] = P.FwState.NAMES.get(v.get("fw_state"), v.get("fw_state"))
    elif msg.id == P.MSG_BUTTON:
        v["command"] = P.ButtonCommand.NAMES.get(v.get("command"), v.get("command"))
    elif msg.id == P.MSG_FAULT:
        v["fault_code"] = P.FaultCode.NAMES.get(v.get("fault_code"), v.get("fault_code"))
    if msg.id in (P.MSG_TEMPERATURE, P.MSG_FAULT):
        for k in list(v):
            if k.endswith("_x10"):
                v[k[:-6] + "_c"] = v.pop(k) / 10.0
    return f"{msg.name:<16} {v}"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    port = open_serial(argv[1])
    t0 = time.monotonic()

    def on_message(msg):
        print(f"[{time.monotonic() - t0:8.3f}] <- {describe(msg)}", flush=True)

    link = UartLink(port, on_message)
    link.app_state = P.AppState.PASSTHROUGH
    link.start()
    print(f"listening on {argv[1]} at {P.BAUD} baud; waiting for heartbeat (1 per second)")

    def status():
        last = None
        while True:
            up = link.link_up
            if up != last:
                print(f"[{time.monotonic() - t0:8.3f}] link {'UP' if up else 'DOWN'}", flush=True)
                last = up
            time.sleep(0.2)

    threading.Thread(target=status, daemon=True).start()

    try:
        for line in sys.stdin:
            cmd = line.strip().split()
            if not cmd:
                continue
            if cmd[0] == "q":
                break
            if cmd[0] in "12345" and len(cmd[0]) == 1:
                link.app_state = int(cmd[0])
                print(f"-> app_state = {P.AppState.NAMES[link.app_state]}")
            elif cmd[0] == "r":
                link.send_ready(12.0, 3.0, 75.0)
                print("-> READY 12.0 -> 3.0 px, 75 %")
            elif cmd[0] == "e" and len(cmd) == 2:
                code = int(cmd[1])
                link.send_cal_error(code)
                print(f"-> CAL_ERROR {P.CalError.NAMES.get(code, code)}")
            else:
                print("unknown; keys: 1-5, r, e N, q")
    finally:
        link.stop()
        port.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
