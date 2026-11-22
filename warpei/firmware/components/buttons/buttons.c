/* ESP-IDF glue: GPIO interrupts on both edges, a queue, and a task that runs
 * the classifier. Nothing but a timestamp and a queue post happens in the ISR. */
#include "buttons.h"
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

static QueueHandle_t s_queue;
static int s_gpio[BTN_COUNT];
static btn_command_cb s_cb;
static void *s_ctx;

static void IRAM_ATTR isr_handler(void *arg)
{
    uint8_t button = (uint8_t)(uintptr_t)arg;
    btn_edge_t edge = {
        .button = button,
        .pressed = gpio_get_level(s_gpio[button]) == 0,   /* pull-up: pressed reads low */
        .t_ms = (uint32_t)(esp_timer_get_time() / 1000),
    };
    BaseType_t woken = pdFALSE;
    xQueueSendFromISR(s_queue, &edge, &woken);
    if (woken) {
        portYIELD_FROM_ISR();
    }
}

static void button_task(void *arg)
{
    (void)arg;
    btn_classifier_t cls;
    btn_classifier_init(&cls);
    btn_edge_t edge;
    for (;;) {
        if (xQueueReceive(s_queue, &edge, portMAX_DELAY) == pdTRUE) {
            btn_press_t p = btn_classify(&cls, &edge);
            if ((p == BTN_PRESS_SHORT || p == BTN_PRESS_LONG) && s_cb) {
                s_cb(edge.button, p, s_ctx);
            }
        }
    }
}

int buttons_start(const int gpio[BTN_COUNT], btn_command_cb cb, void *ctx)
{
    s_cb = cb;
    s_ctx = ctx;
    s_queue = xQueueCreate(32, sizeof(btn_edge_t));
    if (!s_queue) {
        return -1;
    }
    uint64_t mask = 0;
    for (int i = 0; i < BTN_COUNT; i++) {
        s_gpio[i] = gpio[i];
        mask |= 1ULL << gpio[i];
    }
    gpio_config_t cfg = {
        .pin_bit_mask = mask,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_ANYEDGE,
    };
    if (gpio_config(&cfg) != ESP_OK) {
        return -1;
    }
    gpio_install_isr_service(0);
    for (int i = 0; i < BTN_COUNT; i++) {
        gpio_isr_handler_add(gpio[i], isr_handler, (void *)(uintptr_t)i);
    }
    return xTaskCreate(button_task, "buttons", 3072, NULL, 5, NULL) == pdPASS ? 0 : -1;
}
