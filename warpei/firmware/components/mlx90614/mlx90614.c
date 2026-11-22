/* MLX90614 driver, student-developed from the datasheet. See mlx90614.h. */
#include "mlx90614.h"

/* CRC-8 with polynomial 0x07 (X^8 + X^2 + X + 1), init 0, as the SMBus PEC
 * in datasheet section 8.4.3. Same routine as the UART link CRC. */
uint8_t mlx90614_pec(const uint8_t *bytes, size_t n)
{
    uint8_t crc = 0;
    for (size_t i = 0; i < n; i++) {
        crc ^= bytes[i];
        for (int b = 0; b < 8; b++) {
            crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
        }
    }
    return crc;
}

/* Datasheet 8.4.5: T[K] = raw * 0.02; C = K - 273.15. In tenths of a degree:
 * c_x10 = raw * 0.2 - 2731.5 = raw / 5 - 2731.5. Round to nearest. */
int16_t mlx90614_raw_to_c_x10(uint16_t raw)
{
    int32_t k_x100 = (int32_t)raw * 2;               /* kelvin * 100 */
    int32_t c_x100 = k_x100 - 27315;
    int32_t c_x10 = (c_x100 >= 0) ? (c_x100 + 5) / 10 : (c_x100 - 5) / 10;
    return (int16_t)c_x10;
}

const char *mlx90614_err_str(mlx90614_err_t e)
{
    switch (e) {
    case MLX_OK: return "ok";
    case MLX_ERR_BUS: return "bus";
    case MLX_ERR_PEC: return "pec";
    case MLX_ERR_FLAG: return "flag";
    case MLX_ERR_RANGE: return "range";
    case MLX_ERR_ARG: return "arg";
    }
    return "?";
}

mlx90614_err_t mlx90614_init(mlx90614_t *dev, mlx90614_xfer_fn xfer, void *ctx,
                             uint8_t addr, uint32_t timeout_ms)
{
    if (!dev || !xfer) {
        return MLX_ERR_ARG;
    }
    dev->xfer = xfer;
    dev->ctx = ctx;
    dev->addr = addr ? addr : MLX90614_DEFAULT_ADDR;
    dev->timeout_ms = timeout_ms ? timeout_ms : 50;
    dev->reads = dev->pec_errors = dev->bus_errors = dev->flag_errors = 0;
    return MLX_OK;
}

mlx90614_err_t mlx90614_read_word(mlx90614_t *dev, uint8_t command, uint16_t *value)
{
    if (!dev || !value) {
        return MLX_ERR_ARG;
    }
    uint8_t rx[3];                                  /* LSB, MSB, PEC */
    dev->reads++;
    if (dev->xfer(dev->ctx, dev->addr, &command, 1, rx, 3, dev->timeout_ms) != 0) {
        dev->bus_errors++;
        return MLX_ERR_BUS;
    }
    /* PEC covers the whole transaction as seen on the bus (datasheet 8.4.3). */
    uint8_t covered[5] = {
        (uint8_t)(dev->addr << 1),          /* ADDR + W */
        command,
        (uint8_t)((dev->addr << 1) | 1),    /* ADDR + R */
        rx[0], rx[1]
    };
    if (mlx90614_pec(covered, 5) != rx[2]) {
        dev->pec_errors++;
        return MLX_ERR_PEC;
    }
    *value = (uint16_t)(rx[0] | (rx[1] << 8));
    return MLX_OK;
}

static mlx90614_err_t read_temp(mlx90614_t *dev, uint8_t reg, int16_t *c_x10)
{
    uint16_t raw;
    mlx90614_err_t e = mlx90614_read_word(dev, reg, &raw);
    if (e != MLX_OK) {
        return e;
    }
    if (raw & 0x8000) {                             /* error flag, datasheet 8.4.5 */
        dev->flag_errors++;
        return MLX_ERR_FLAG;
    }
    /* Object range -70..380 C (raw 0x27AD..0x7FFF); ambient -40..125 C. Anything
     * outside the object range is treated as corrupt rather than trusted. */
    if (raw < 0x27AD) {
        return MLX_ERR_RANGE;
    }
    *c_x10 = mlx90614_raw_to_c_x10(raw);
    return MLX_OK;
}

mlx90614_err_t mlx90614_read_object_c_x10(mlx90614_t *dev, int16_t *c_x10)
{
    return read_temp(dev, MLX90614_RAM_TOBJ1, c_x10);
}

mlx90614_err_t mlx90614_read_ambient_c_x10(mlx90614_t *dev, int16_t *c_x10)
{
    return read_temp(dev, MLX90614_RAM_TA, c_x10);
}

mlx90614_err_t mlx90614_probe(mlx90614_t *dev)
{
    int16_t t;
    return mlx90614_read_ambient_c_x10(dev, &t);
}
