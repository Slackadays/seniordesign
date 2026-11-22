/* UART link task (Report 7.2.7, 7.5). Frames and sends messages posted by
 * the control task; parses incoming bytes into messages for it. */
#ifndef LINK_UART_H
#define LINK_UART_H

#include <stdint.h>
#include <stdbool.h>
#include "wp_frame.h"

typedef void (*link_rx_cb)(const wp_message_t *msg, void *ctx);

int  link_start(link_rx_cb cb, void *ctx);
/* Thread-safe: may be called from any task. Returns 0 if queued. */
int  link_send(uint8_t id, const int32_t *fields, uint8_t nfields);
bool link_is_up(void);
uint8_t link_peer_state(void);      /* last app_state reported by the ROCK 5B */

#endif
