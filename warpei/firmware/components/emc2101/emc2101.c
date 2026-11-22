#include "emc2101.h"

uint8_t emc2101_pct_to_setting(uint8_t pct)
{
    if (pct > 100) {
        pct = 100;
    }
    return (uint8_t)((pct * 63 + 50) / 100);
}

uint16_t emc2101_count_to_rpm(uint16_t count)
{
    if (count == 0 || count == 0xFFFF) {      /* 0xFFFF = no tach pulses: stopped */
        return 0;
    }
    uint32_t rpm = EMC2101_TACH_CONSTANT / count;
    return rpm > 65535 ? 65535 : (uint16_t)rpm;
}

static int write_reg(emc2101_t *dev, uint8_t reg, uint8_t val)
{
    uint8_t w[2] = { reg, val };
    return dev->xfer(dev->ctx, dev->addr, w, 2, NULL, 0, 50);
}

static int read_reg(emc2101_t *dev, uint8_t reg, uint8_t *val)
{
    return dev->xfer(dev->ctx, dev->addr, &reg, 1, val, 1, 50);
}

int emc2101_init(emc2101_t *dev, mlx90614_xfer_fn xfer, void *ctx)
{
    dev->xfer = xfer;
    dev->ctx = ctx;
    dev->addr = EMC2101_ADDR;
    /* PWM output, tach input enabled (config bit 2 = 0), fan setting register
     * drives the duty (fan config bit 5 = 1), 25 kHz-class PWM. */
    if (write_reg(dev, EMC2101_REG_CONFIG, 0x00)) return -1;
    if (write_reg(dev, EMC2101_REG_FAN_CONFIG, 0x20)) return -1;
    if (write_reg(dev, EMC2101_REG_PWM_FREQ, 0x1F)) return -1;
    return 0;
}

int emc2101_probe(emc2101_t *dev)
{
    uint8_t id = 0;
    if (read_reg(dev, EMC2101_REG_MFG_ID, &id)) {
        return -1;
    }
    return id == 0x5D ? 0 : -2;
}

int emc2101_set_duty_pct(emc2101_t *dev, uint8_t pct)
{
    return write_reg(dev, EMC2101_REG_FAN_SETTING, emc2101_pct_to_setting(pct));
}

int emc2101_read_rpm(emc2101_t *dev, uint16_t *rpm)
{
    uint8_t lsb, msb;
    if (read_reg(dev, EMC2101_REG_TACH_LSB, &lsb)) return -1;   /* read LSB first: latches MSB */
    if (read_reg(dev, EMC2101_REG_TACH_MSB, &msb)) return -1;
    *rpm = emc2101_count_to_rpm((uint16_t)(lsb | (msb << 8)));
    return 0;
}
