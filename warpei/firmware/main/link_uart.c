#include "link_uart.h"
#include "warpei_pins.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include <string.h>

static const char *TAG = "link";

typedef struct { uint8_t frame[WP_MAX_FRAME]; uint8_t len; } tx_item_t;

static QueueHandle_t s_tx;
static link_rx_cb s_cb;
static void *s_ctx;
static volatile int64_t s_last_reply_us = -1;
static volatile uint8_t s_peer_state = WP_APP_STATE_BOOTING;

int link_send(uint8_t id, const int32_t *fields, uint8_t nfields)
{
    tx_item_t item;
    uint8_t payload[WP_MAX_PAYLOAD];
    uint8_t len = nfields ? wp_pack(id, fields, nfields, payload) : 0;
    if (nfields && len == 0) {
        return -1;
    }
    item.len = (uint8_t)wp_encode(id, payload, len, item.frame, sizeof item.frame);
    if (item.len == 0 || !s_tx) {
        return -1;
    }
    return xQueueSend(s_tx, &item, pdMS_TO_TICKS(20)) == pdTRUE ? 0 : -1;
}

bool link_is_up(void)
{
    return s_last_reply_us >= 0 && (esp_timer_get_time() - s_last_reply_us) < (int64_t)WP_LINK_DOWN_MS * 1000;
}

uint8_t link_peer_state(void)
{
    return s_peer_state;
}

static void tx_task(void *arg)
{
    (void)arg;
    tx_item_t item;
    for (;;) {
        if (xQueueReceive(s_tx, &item, portMAX_DELAY) == pdTRUE) {
            uart_write_bytes(UART_PORT, item.frame, item.len);
        }
    }
}

static void rx_task(void *arg)
{
    (void)arg;
    wp_decoder_t dec;
    wp_decoder_init(&dec);
    wp_message_t msg;
    uint8_t buf[64];
    for (;;) {
        int n = uart_read_bytes(UART_PORT, buf, sizeof buf, pdMS_TO_TICKS(50));
        for (int i = 0; i < n; i++) {
            if (!wp_decoder_feed(&dec, buf[i], &msg)) {
                continue;
            }
            if (msg.id == WP_MSG_HEARTBEAT_REPLY) {
                s_last_reply_us = esp_timer_get_time();
                s_peer_state = msg.len ? msg.payload[0] : s_peer_state;
                continue;
            }
            if (msg.id == WP_MSG_ACK) {
                continue;
            }
            if (s_cb) {
                s_cb(&msg, s_ctx);
            }
        }
        if (dec.crc_errors && (dec.crc_errors % 100) == 1) {
            ESP_LOGW(TAG, "crc errors %lu resyncs %lu", (unsigned long)dec.crc_errors, (unsigned long)dec.resyncs);
        }
    }
}

static void heartbeat_task(void *arg)
{
    (void)arg;
    extern uint8_t control_current_fw_state(void);
    for (;;) {
        int32_t st = control_current_fw_state();
        link_send(WP_MSG_HEARTBEAT, &st, 1);
        vTaskDelay(pdMS_TO_TICKS(WP_HEARTBEAT_PERIOD_MS));
    }
}

int link_start(link_rx_cb cb, void *ctx)
{
    s_cb = cb;
    s_ctx = ctx;
    uart_config_t cfg = {
        .baud_rate = WP_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    ESP_ERROR_CHECK(uart_driver_install(UART_PORT, 1024, 1024, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(UART_PORT, &cfg));
    ESP_ERROR_CHECK(uart_set_pin(UART_PORT, PIN_UART_TX, PIN_UART_RX, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    s_tx = xQueueCreate(16, sizeof(tx_item_t));
    xTaskCreate(tx_task, "link_tx", 3072, NULL, 6, NULL);
    xTaskCreate(rx_task, "link_rx", 4096, NULL, 6, NULL);
    xTaskCreate(heartbeat_task, "link_hb", 2048, NULL, 4, NULL);
    return 0;
}
