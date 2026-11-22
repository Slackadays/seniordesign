idf_component_register(SRCS "mlx90614.c" "mlx90614_esp.c"
                       INCLUDE_DIRS "include"
                       REQUIRES driver esp_common log)
