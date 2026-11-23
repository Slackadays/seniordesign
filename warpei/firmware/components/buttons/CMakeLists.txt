idf_component_register(SRCS "button_classify.c" "buttons.c"
                       INCLUDE_DIRS "include"
                       PRIV_REQUIRES esp_driver_gpio esp_timer)
