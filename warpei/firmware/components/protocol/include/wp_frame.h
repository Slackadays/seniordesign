/* Frame encoding and byte-wise decoding for the Warpei UART link.
 * Pure C, no ESP-IDF dependency: compiled on the host for tests and on the
 * ESP32 for the link task. Mirrors sbc/warpei/link/framing.py. */
#ifndef WP_FRAME_H
#define WP_FRAME_H

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include "warpei_protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

/* CRC-8, polynomial 0x07, init 0x00, no reflection. Shared with the MLX90614 PEC. */
uint8_t wp_crc8(const uint8_t *data, size_t len);
uint8_t wp_crc8_update(uint8_t crc, uint8_t byte);

/* Build a frame: START ID LEN PAYLOAD CRC. Returns the frame length or 0 if
 * the payload is too long or out is too small. out must hold WP_MAX_FRAME. */
size_t wp_encode(uint8_t id, const uint8_t *payload, uint8_t len, uint8_t *out, size_t out_size);

/* Pack / unpack little-endian fields by message id using the generated
 * tables. Field values are passed as int32_t regardless of width. Return
 * the payload length, or 0 for an unknown id or wrong field count. */
uint8_t wp_pack(uint8_t id, const int32_t *fields, uint8_t nfields, uint8_t *payload);
uint8_t wp_unpack(uint8_t id, const uint8_t *payload, uint8_t len, int32_t *fields, uint8_t max_fields);

/* Incremental decoder. Feed bytes; when a frame completes, wp_decoder_feed
 * returns true and the frame is in msg. */
typedef struct {
    uint8_t id;
    uint8_t len;
    uint8_t payload[WP_MAX_PAYLOAD];
} wp_message_t;

typedef struct {
    uint8_t buf[WP_MAX_FRAME];
    uint8_t n;              /* bytes in buf */
    uint32_t frames;
    uint32_t crc_errors;
    uint32_t bad_length;
    uint32_t resyncs;
} wp_decoder_t;

void wp_decoder_init(wp_decoder_t *d);
bool wp_decoder_feed(wp_decoder_t *d, uint8_t byte, wp_message_t *msg);

#ifdef __cplusplus
}
#endif
#endif
