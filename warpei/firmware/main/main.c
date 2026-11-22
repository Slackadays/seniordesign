/* Warpei control board firmware entry point (Report 7.2.1).
 *
 * Tasks: sensor (prio 8), control (7), link rx/tx (6), buttons (5),
 * heartbeat (4). The task watchdog covers the sensor task; if it stalls the
 * chip resets and comes up in Fault with the LED off. */
#include "control_app.h"
#include "thermal_supervisor.h"
#include "link_uart.h"
#include "buttons.h"
#include "warpei_pins.h"
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "esp_system.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "main";

static void on_button(uint8_t button, btn_press_t press, void *ctx)
{
    (void)ctx;
    control_post_button(button, press);
}

static void on_link_message(const wp_message_t *msg, void *ctx)
{
    (void)ctx;
    control_post_link(msg);
}

void app_main(void)
{
    esp_err_t e = nvs_flash_init();
    if (e == ESP_ERR_NVS_NO_FREE_PAGES || e == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }
    esp_reset_reason_t why = esp_reset_reason();
    ESP_LOGI(TAG, "boot, reset reason %d", why);

    esp_task_wdt_config_t wdt = { .timeout_ms = 2000, .idle_core_mask = 0, .trigger_panic = true };
    esp_task_wdt_reconfigure(&wdt);

    control_start();                                   /* LED enable low before anything else */
    link_start(on_link_message, NULL);
    const int btn_gpio[BTN_COUNT] = { PIN_BTN_POWER, PIN_BTN_CALIBRATE, PIN_BTN_FLIP };
    buttons_start(btn_gpio, on_button, NULL);

    bool sensor_ok = thermal_start();
    if (why == ESP_RST_TASK_WDT || why == ESP_RST_WDT) {
        sensor_ok = false;                             /* watchdog fired: cannot prove the heatsink is safe */
    }
    control_boot_done(sensor_ok);
    ESP_LOGI(TAG, "running, sensor %s", sensor_ok ? "ok" : "FAULT");
}
