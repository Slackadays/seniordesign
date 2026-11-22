/* EMC2101 fan controller: duty out, tachometer in. Uses the same generic
 * I2C transfer signature as the MLX90614 driver. Register addresses from the
 * Microchip EMC2101 datasheet; verify against the revision on the PCB. */
#ifndef EMC2101_H
#define EMC2101_H

#include <stdint.h>
#include <stddef.h>
#include "mlx90614.h"     /* for mlx90614_xfer_fn: one transfer signature for both devices */

#ifdef __cplusplus
extern "C" {
#endif

#define EMC2101_ADDR            0x4C
#define EMC2101_REG_CONFIG      0x03
#define EMC2101_REG_TACH_LSB    0x46
#define EMC2101_REG_TACH_MSB    0x47
#define EMC2101_REG_FAN_CONFIG  0x4A
#define EMC2101_REG_FAN_SETTING 0x4C   /* 0..63 */
#define EMC2101_REG_PWM_FREQ    0x4D
#define EMC2101_REG_PRODUCT_ID  0xFD   /* 0x16 or 0x28 */
#define EMC2101_REG_MFG_ID      0xFE   /* 0x5D */
#define EMC2101_TACH_CONSTANT   5400000UL   /* RPM = constant / count */

typedef struct {
    mlx90614_xfer_fn xfer;   /* generic transfer; see mlx90614.h */
    void *ctx;
    uint8_t addr;
} emc2101_t;

int emc2101_init(emc2101_t *dev, mlx90614_xfer_fn xfer, void *ctx);
int emc2101_probe(emc2101_t *dev);                    /* checks the manufacturer id */
int emc2101_set_duty_pct(emc2101_t *dev, uint8_t pct);
int emc2101_read_rpm(emc2101_t *dev, uint16_t *rpm);  /* 0 when stopped */

/* Pure helpers for tests */
uint8_t emc2101_pct_to_setting(uint8_t pct);
uint16_t emc2101_count_to_rpm(uint16_t count);

#ifdef __cplusplus
}
#endif
#endif
