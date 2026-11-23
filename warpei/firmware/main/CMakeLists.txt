idf_component_register(SRCS "main.c" "control_app.c" "control_logic.c"
                            "thermal_supervisor.c" "thermal_logic.c" "link_uart.c"
                       INCLUDE_DIRS "."
                       REQUIRES protocol mlx90614 emc2101 buttons
                       PRIV_REQUIRES esp_driver_gpio esp_driver_ledc esp_driver_uart
                                     esp_driver_i2c nvs_flash esp_timer log)
