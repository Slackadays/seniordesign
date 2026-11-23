#include "sdkconfig.h"
#include "thermal_supervisor.h"
#include "thermal_logic.h"
#include "control_app.h"
#include "link_uart.h"
#include "warpei_pins.h"
#include "mlx90614_esp.h"
#include "emc2101.h"
#include "driver/i2c_master.h"
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "thermal";

static mlx90614_t s_sensor;
static emc2101_t s_fan;
static i2c_master_dev_handle_t s_fan_dev;
static th_supervisor_t s_th;
static volatile int16_t s_last_obj = 0, s_last_amb = 0;
static volatile uint8_t s_fan_request = 100;
static volatile uint16_t s_fan_rpm = 0;
static bool s_fan_present = false;
static bool s_bench_fake = false;      /* CONFIG_WARPEI_BENCH_NO_SENSOR and no sensor found */

static int fan_xfer(void *ctx, uint8_t addr, const uint8_t *w, size_t wlen, uint8_t *r, size_t rlen, uint32_t to)
{
    (void)addr;
    i2c_master_dev_handle_t dev = ctx;
    esp_err_t e = rlen ? i2c_master_transmit_receive(dev, w, wlen, r, rlen, (int)to)
                       : i2c_master_transmit(dev, w, wlen, (int)to);
    return e == ESP_OK ? 0 : -1;
}

void thermal_set_fan_request(uint8_t pct)
{
    s_fan_request = pct > 100 ? 100 : pct;
}

int16_t thermal_last_object_c_x10(void)
{
    return s_last_obj;
}

static void sensor_task(void *arg)
{
    (void)arg;
    esp_task_wdt_add(NULL);
    uint32_t n = 0;
    for (;;) {
        int16_t obj = 0, amb = 0;
        mlx90614_err_t e = s_bench_fake ? MLX_OK : mlx90614_read_object_c_x10(&s_sensor, &obj);
        bool ok = e == MLX_OK;
        if (s_bench_fake) {
            obj = 250; amb = 250;                  /* 25.0 C, constant */
            s_last_obj = obj; s_last_amb = amb;
        } else if (ok) {
            s_last_obj = obj;
            if (mlx90614_read_ambient_c_x10(&s_sensor, &amb) == MLX_OK) s_last_amb = amb;
        } else {
            ESP_LOGW(TAG, "read error: %s", mlx90614_err_str(e));
        }
        th_event_t evt = th_sample(&s_th, ok, obj);
        if (evt != TH_EVT_NONE) {
            control_post_thermal(evt, obj);
        }
        /* Fan: the higher of the control request and the thermal curve; full in any fault. */
        uint8_t duty = th_fan_duty_pct(&s_th);
        if (s_fan_request > duty) duty = s_fan_request;
        if (s_fan_present) {
            emc2101_set_duty_pct(&s_fan, duty);
            uint16_t rpm; if (emc2101_read_rpm(&s_fan, &rpm) == 0) s_fan_rpm = rpm;
        }
        if (++n % 10 == 0) {                       /* TEMPERATURE every 1 s */
            int32_t f[4] = { s_last_obj, s_last_amb, duty, s_bench_fake ? 0xFFFF : s_fan_rpm };
            link_send(WP_MSG_TEMPERATURE, f, 4);
        }
        esp_task_wdt_reset();
        vTaskDelay(pdMS_TO_TICKS(TH_SAMPLE_PERIOD_MS));
    }
}

bool thermal_start(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .i2c_port = I2C_PORT,
        .sda_io_num = PIN_I2C_SDA,
        .scl_io_num = PIN_I2C_SCL,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_new_master_bus(&bus_cfg, &bus));

    vTaskDelay(pdMS_TO_TICKS(MLX90614_POWER_UP_MS));
    ESP_ERROR_CHECK(mlx90614_esp_attach(&s_sensor, bus, MLX90614_DEFAULT_ADDR, NULL));
    mlx90614_err_t pe = mlx90614_probe(&s_sensor);
    ESP_LOGI(TAG, "MLX90614 probe: %s", mlx90614_err_str(pe));
#if CONFIG_WARPEI_BENCH_NO_SENSOR
    if (pe != MLX_OK) {
        s_bench_fake = true;
        pe = MLX_OK;
        ESP_LOGW(TAG, "BENCH MODE: no MLX90614, faking 25.0 C. Do not use on the projector.");
    }
#endif

    i2c_device_config_t fcfg = { .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = EMC2101_ADDR, .scl_speed_hz = 100000 };
    if (i2c_master_bus_add_device(bus, &fcfg, &s_fan_dev) == ESP_OK) {
        s_fan_present = emc2101_init(&s_fan, fan_xfer, s_fan_dev) == 0 && emc2101_probe(&s_fan) == 0;
        ESP_LOGI(TAG, "EMC2101 %s", s_fan_present ? "ok" : "not found");
    }
    th_init(&s_th);
    xTaskCreate(sensor_task, "sensor", 4096, NULL, 8, NULL);     /* highest priority: safety */
    return pe == MLX_OK;
}
