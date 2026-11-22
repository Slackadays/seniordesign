# MLX90614 driver (student-developed)

Written from the Melexis MLX90614 datasheet using only the ESP-IDF
general-purpose I2C master functions. No Melexis, Adafruit, SparkFun or other
device library is used. This folder is the source for the driver appendix
and for Section 7.2.4 of the report.

| Item | Where |
| --- | --- |
| Structure | `mlx90614.c` is portable C over a one-function bus interface (`mlx90614_xfer_fn`); `mlx90614_esp.c` supplies that function from `i2c_master_transmit_receive()` |
| Protocol | SMBus read word: `S ADDR+W CMD Sr ADDR+R LSB MSB PEC P`, 100 kHz max |
| Interface configuration | `mlx90614_esp_attach()`: 7-bit address 0x5A, 100 kHz, 50 ms timeout |
| Initialisation | `mlx90614_init()` sets the handle; `mlx90614_probe()` performs the boot read (after the 250 ms power-up time) |
| Register operations | `mlx90614_read_word()`: RAM 0x06 ambient, 0x07 object |
| Data reception | 3 bytes: LSB, MSB, PEC; `T[K] = raw * 0.02`, converted to tenths of °C in integer arithmetic |
| Timing | Sensor refresh 1.44 ms; firmware samples every 100 ms; bus timeout 50 ms |
| Error handling | `MLX_ERR_BUS` (NACK/timeout), `MLX_ERR_PEC` (CRC-8 over ADDR+W, CMD, ADDR+R, LSB, MSB mismatch: data discarded), `MLX_ERR_FLAG` (bit 15 set by the sensor), `MLX_ERR_RANGE` (below −70 °C, treated as corrupt). Counters in the handle feed the status report. |

Host tests: `firmware/test/host/test_mlx90614.c` drive the driver with a
fake bus (correct PEC, corrupted PEC, NACK, error flag) and check the
conversion against datasheet example values.
