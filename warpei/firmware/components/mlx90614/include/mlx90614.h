/* MLX90614 infrared thermometer driver: student-developed (Report 7.2.4).
 *
 * Written from the Melexis MLX90614 datasheet, section "SMBus communication".
 * Uses only a generic I2C/SMBus transfer function supplied by the caller
 * (on the ESP32: the ESP-IDF general-purpose i2c_master driver, see
 * mlx90614_esp.c). No manufacturer or third-party device library.
 *
 * Protocol summary (datasheet 8.4.x):
 *   Read word:  S | ADDR+W | CMD | Sr | ADDR+R | LSB | MSB | PEC | P
 *   PEC: CRC-8, polynomial X^8+X^2+X^1+1 (0x07), over
 *        [ADDR+W, CMD, ADDR+R, LSB, MSB]
 *   RAM: 0x06 = Ta (ambient), 0x07 = Tobj1 (object); T[K] = raw * 0.02
 *   An error is flagged by bit 15 of the data word (datasheet 8.4.5).
 *   Bus: SMBus, up to 100 kHz. Power-on to first valid read: 0.25 s.
 */
#ifndef MLX90614_H
#define MLX90614_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MLX90614_DEFAULT_ADDR   0x5A
#define MLX90614_RAM_TA         0x06
#define MLX90614_RAM_TOBJ1      0x07
#define MLX90614_RAM_TOBJ2      0x08
#define MLX90614_EEPROM_ID1     0x3C   /* ID numbers, used by the boot probe */
#define MLX90614_POWER_UP_MS    250
#define MLX90614_MIN_READ_GAP_MS 2     /* keep reads apart; the sensor refreshes every ~1.44 ms */

typedef enum {
    MLX_OK = 0,
    MLX_ERR_BUS,          /* NACK or timeout from the bus layer */
    MLX_ERR_PEC,          /* packet error check mismatch: data discarded */
    MLX_ERR_FLAG,         /* sensor set its error bit */
    MLX_ERR_RANGE,        /* value outside the sensor's physical range */
    MLX_ERR_ARG,
} mlx90614_err_t;

/* Bus abstraction: one SMBus "read word" transaction.
 *   write[0..wlen) is sent after ADDR+W, then a repeated start and rlen bytes
 *   are read after ADDR+R. Returns 0 on success, nonzero on NACK/timeout. */
typedef int (*mlx90614_xfer_fn)(void *ctx, uint8_t addr,
                                const uint8_t *write, size_t wlen,
                                uint8_t *read, size_t rlen, uint32_t timeout_ms);

typedef struct {
    mlx90614_xfer_fn xfer;
    void *ctx;
    uint8_t addr;
    uint32_t timeout_ms;
    /* statistics for the report's error-handling section */
    uint32_t reads;
    uint32_t pec_errors;
    uint32_t bus_errors;
    uint32_t flag_errors;
} mlx90614_t;

/* Set up the handle. Does not touch the bus. */
mlx90614_err_t mlx90614_init(mlx90614_t *dev, mlx90614_xfer_fn xfer, void *ctx,
                             uint8_t addr, uint32_t timeout_ms);

/* Boot probe: reads the ambient register once and checks PEC and flags. */
mlx90614_err_t mlx90614_probe(mlx90614_t *dev);

/* Raw register read with PEC verification. */
mlx90614_err_t mlx90614_read_word(mlx90614_t *dev, uint8_t command, uint16_t *value);

/* Temperatures in tenths of a degree Celsius (e.g. 912 = 91.2 C). */
mlx90614_err_t mlx90614_read_object_c_x10(mlx90614_t *dev, int16_t *c_x10);
mlx90614_err_t mlx90614_read_ambient_c_x10(mlx90614_t *dev, int16_t *c_x10);

/* Pure helpers, exposed for tests. */
uint8_t mlx90614_pec(const uint8_t *bytes, size_t n);
int16_t mlx90614_raw_to_c_x10(uint16_t raw);
const char *mlx90614_err_str(mlx90614_err_t e);

#ifdef __cplusplus
}
#endif
#endif
