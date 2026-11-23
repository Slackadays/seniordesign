# esp_driver_i2c is a public requirement because mlx90614_esp.h exposes
# i2c_master_bus_handle_t to callers.
idf_component_register(SRCS "mlx90614.c" "mlx90614_esp.c"
                       INCLUDE_DIRS "include"
                       REQUIRES esp_driver_i2c
                       PRIV_REQUIRES esp_common log)
