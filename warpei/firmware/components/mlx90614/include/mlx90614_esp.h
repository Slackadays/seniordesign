#ifndef MLX90614_ESP_H
#define MLX90614_ESP_H
#include "mlx90614.h"
#include "esp_err.h"
#include "driver/i2c_master.h"

/* Add the sensor to an existing i2c_master bus and bind the driver to it. */
esp_err_t mlx90614_esp_attach(mlx90614_t *sensor, i2c_master_bus_handle_t bus, uint8_t addr,
                              i2c_master_dev_handle_t *dev_out);
#endif
