# ESP32 firmware setup (task 5.1)

## Toolchain

ESP-IDF 5.5.x, installed per Espressif's "Get Started" guide (the VS Code
extension or the command-line installer both work). The Arduino IDE is not
used anywhere in this project.

```bash
. ~/esp/esp-idf/export.sh          # once per terminal
cd warpei/firmware
idf.py set-target esp32
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

`sdkconfig.defaults` carries the shared settings; the generated `sdkconfig`
and `build/` are ignored by git.

## Layout

| Path | Contents |
| --- | --- |
| `main/main.c` | boot, task start, watchdog |
| `main/control_app.c` + `control_logic.c` | state machine (Off/On/Calibrating/Over-temperature/Fault), LED enable, PWM, indicators, NVS |
| `main/thermal_supervisor.c` + `thermal_logic.c` | 100 ms sensor loop, over-temperature and sensor-fault rules, fan curve |
| `main/link_uart.c` | framing, heartbeat, UART tasks |
| `main/warpei_pins.h` | pin assignment: update from the PCB schematic |
| `components/mlx90614/` | student-developed driver (report appendix) |
| `components/emc2101/` | fan controller |
| `components/buttons/` | ISR, debounce, press classification |
| `components/protocol/` | generated header + framing (shared with the ROCK 5B) |
| `test/host/` | gcc unit tests for all `*_logic.c`, the drivers and framing: `make test` |

The `*_logic.c` files and both drivers have no ESP-IDF dependency, which is
what lets the host tests run; the `*_app.c`, `*_supervisor.c`, `buttons.c`
and `mlx90614_esp.c` files are the only ones that touch ESP-IDF.

## Protocol changes

Edit `protocol/messages.json`, run `python protocol/generate.py`, and commit
the regenerated `warpei_protocol.h` and `protocol.py` together. CI fails if
they are out of date.

## First bring-up checklist

1. Dev board alone, no sensor: boots to Fault (red solid), LED enable low. Expected.
2. Add the MLX90614: boots to Off. `idf.py monitor` shows a probe `ok` line.
3. Short-press Power: On, green solid (slow blink until the ROCK 5B answers heartbeats).
4. Connect UART to a laptop with `python -m warpei.main --windowed --uart /dev/ttyUSBn`: green goes solid.
5. Run `testing/procedures/firmware_bench.md`.
