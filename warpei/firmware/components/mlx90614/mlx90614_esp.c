/* ESP-IDF binding for the MLX90614 driver: supplies the generic I2C transfer
 * using only the ESP-IDF i2c_master driver (a general-purpose MCU peripheral
 * API, not a device library). ESP-IDF 5.2 or later. */
#include "mlx90614_esp.h"
#include "driver/i2c_master.h"
#include "esp_log.h"

static const char *TAG = "mlx90614";

static int esp_xfer(void *ctx, uint8_t addr, const uint8_t *write, size_t wlen,
                    uint8_t *read, size_t rlen, uint32_t timeout_ms)
{
    (void)addr;   /* the device handle already carries the address */
    i2c_master_dev_handle_t dev = (i2c_master_dev_handle_t)ctx;
    esp_err_t err = i2c_master_transmit_receive(dev, write, wlen, read, rlen, (int)timeout_ms);
    if (err != ESP_OK) {
        ESP_LOGD(TAG, "transfer failed: %s", esp_err_to_name(err));
        return -1;
    }
    return 0;
}

esp_err_t mlx90614_esp_attach(mlx90614_t *sensor, i2c_master_bus_handle_t bus, uint8_t addr,
                              i2c_master_dev_handle_t *dev_out)
{
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = addr ? addr : MLX90614_DEFAULT_ADDR,
        .scl_speed_hz = 100000,          /* SMBus limit for the MLX90614 */
    };
    i2c_master_dev_handle_t dev;
    esp_err_t err = i2c_master_bus_add_device(bus, &cfg, &dev);
    if (err != ESP_OK) {
        return err;
    }
    if (dev_out) {
        *dev_out = dev;
    }
    mlx90614_init(sensor, esp_xfer, dev, cfg.device_address, 50);
    return ESP_OK;
}
