#include "buttons.h"
#include <string.h>

void btn_classifier_init(btn_classifier_t *c)
{
    memset(c, 0, sizeof(*c));
}

btn_press_t btn_classify(btn_classifier_t *c, const btn_edge_t *edge)
{
    uint8_t b = edge->button;
    if (b >= BTN_COUNT) {
        return BTN_PRESS_NONE;
    }
    /* Debounce: ignore an edge within 30 ms of the previous edge on this input. */
    if (c->have_edge[b] && (uint32_t)(edge->t_ms - c->last_edge_ms[b]) < BTN_DEBOUNCE_MS) {
        return BTN_PRESS_NONE;
    }
    c->have_edge[b] = true;
    c->last_edge_ms[b] = edge->t_ms;

    if (edge->pressed) {
        if (!c->down[b]) {
            c->down[b] = true;
            c->press_start_ms[b] = edge->t_ms;
        }
        return BTN_PRESS_NONE;
    }
    if (!c->down[b]) {
        return BTN_PRESS_NONE;            /* release without a press: noise */
    }
    c->down[b] = false;
    uint32_t held = edge->t_ms - c->press_start_ms[b];
    if (held < BTN_SHORT_MAX_MS) {
        return BTN_PRESS_SHORT;
    }
    if (held >= BTN_LONG_MIN_MS) {
        return BTN_PRESS_LONG;
    }
    return BTN_PRESS_IGNORED;             /* 0.5 to 1.5 s: deliberately discarded */
}
