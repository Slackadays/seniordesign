/* Button handling (Report 7.2.6).
 *
 * The ISR only timestamps edges and posts them to a queue; the button task
 * debounces (ignore edges within 30 ms of the previous edge on the same
 * input) and classifies a press by its duration on release: short < 500 ms,
 * long >= 1500 ms, anything between is discarded. The classifier is pure C
 * (button_classify.c) so it is tested on the host. */
#ifndef BUTTONS_H
#define BUTTONS_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

#define BTN_COUNT            3
#define BTN_POWER            0
#define BTN_CALIBRATE        1
#define BTN_FLIP             2

#define BTN_DEBOUNCE_MS      30
#define BTN_SHORT_MAX_MS     500
#define BTN_LONG_MIN_MS      1500

typedef enum { BTN_PRESS_NONE = 0, BTN_PRESS_SHORT, BTN_PRESS_LONG, BTN_PRESS_IGNORED } btn_press_t;

typedef struct {
    uint8_t  button;        /* BTN_POWER, ... */
    bool     pressed;       /* true = pressed edge (input went low), false = release */
    uint32_t t_ms;          /* timestamp from the ISR */
} btn_edge_t;

typedef struct {
    uint32_t last_edge_ms[BTN_COUNT];
    uint32_t press_start_ms[BTN_COUNT];
    bool     down[BTN_COUNT];
    bool     have_edge[BTN_COUNT];
} btn_classifier_t;

void btn_classifier_init(btn_classifier_t *c);

/* Feed one edge. Returns the press class on a release edge, BTN_PRESS_NONE
 * otherwise (including debounced edges). */
btn_press_t btn_classify(btn_classifier_t *c, const btn_edge_t *edge);

/* ESP-IDF glue (buttons.c): configure GPIOs, install the ISR, create the queue. */
typedef void (*btn_command_cb)(uint8_t button, btn_press_t press, void *ctx);
int buttons_start(const int gpio[BTN_COUNT], btn_command_cb cb, void *ctx);

#ifdef __cplusplus
}
#endif
#endif
