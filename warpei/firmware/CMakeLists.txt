# Warpei control board firmware. ESP-IDF 5.5.x, target esp32 (ESP32-WROOM-32E).
#     idf.py set-target esp32
#     idf.py build flash monitor
cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(warpei_firmware)
