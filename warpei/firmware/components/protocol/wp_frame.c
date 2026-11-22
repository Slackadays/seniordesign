#include "wp_frame.h"
#include <string.h>

uint8_t wp_crc8_update(uint8_t crc, uint8_t byte)
{
    crc ^= byte;
    for (int i = 0; i < 8; i++) {
        crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ WP_CRC_POLY) : (uint8_t)(crc << 1);
    }
    return crc;
}

uint8_t wp_crc8(const uint8_t *data, size_t len)
{
    uint8_t crc = WP_CRC_INIT;
    for (size_t i = 0; i < len; i++) {
        crc = wp_crc8_update(crc, data[i]);
    }
    return crc;
}

size_t wp_encode(uint8_t id, const uint8_t *payload, uint8_t len, uint8_t *out, size_t out_size)
{
    if (len > WP_MAX_PAYLOAD || out_size < (size_t)(4 + len)) {
        return 0;
    }
    out[0] = WP_START_BYTE;
    out[1] = id;
    out[2] = len;
    if (len) {
        memcpy(&out[3], payload, len);
    }
    out[3 + len] = wp_crc8(&out[1], (size_t)(2 + len));
    return (size_t)(4 + len);
}

static const wp_msgdef_t *find_def(uint8_t id)
{
    for (size_t i = 0; i < WP_NUM_MSGDEFS; i++) {
        if (wp_msgdefs[i].id == id) {
            return &wp_msgdefs[i];
        }
    }
    return NULL;
}

uint8_t wp_pack(uint8_t id, const int32_t *fields, uint8_t nfields, uint8_t *payload)
{
    const wp_msgdef_t *d = find_def(id);
    if (!d || nfields != d->nfields) {
        return 0;
    }
    uint8_t pos = 0;
    for (uint8_t i = 0; i < d->nfields; i++) {
        uint32_t v = (uint32_t)fields[i];
        for (uint8_t b = 0; b < d->fields[i].size; b++) {
            payload[pos++] = (uint8_t)(v >> (8 * b));
        }
    }
    return pos;
}

uint8_t wp_unpack(uint8_t id, const uint8_t *payload, uint8_t len, int32_t *fields, uint8_t max_fields)
{
    const wp_msgdef_t *d = find_def(id);
    if (!d || len != d->length || d->nfields > max_fields) {
        return 0;
    }
    uint8_t pos = 0;
    for (uint8_t i = 0; i < d->nfields; i++) {
        uint32_t v = 0;
        uint8_t size = d->fields[i].size;
        for (uint8_t b = 0; b < size; b++) {
            v |= (uint32_t)payload[pos++] << (8 * b);
        }
        if (d->fields[i].is_signed && size < 4 && (v & (1u << (8 * size - 1)))) {
            v |= 0xFFFFFFFFu << (8 * size);     /* sign-extend */
        }
        fields[i] = (int32_t)v;
    }
    return len;
}

void wp_decoder_init(wp_decoder_t *d)
{
    memset(d, 0, sizeof(*d));
}

/* Drop the first byte and shift, so a false start resynchronises on the next candidate. */
static void drop_first(wp_decoder_t *d)
{
    if (d->n > 1) {
        memmove(d->buf, d->buf + 1, d->n - 1);
    }
    d->n--;
    /* skip forward to the next start byte, if any */
    uint8_t i = 0;
    while (i < d->n && d->buf[i] != WP_START_BYTE) {
        i++;
    }
    if (i) {
        memmove(d->buf, d->buf + i, d->n - i);
        d->n -= i;
    }
}

bool wp_decoder_feed(wp_decoder_t *d, uint8_t byte, wp_message_t *msg)
{
    if (d->n == 0) {
        if (byte != WP_START_BYTE) {
            d->resyncs++;
            return false;
        }
        d->buf[d->n++] = byte;
        return false;
    }
    if (d->n >= WP_MAX_FRAME) {       /* should not happen; defensive */
        d->n = 0;
        return false;
    }
    d->buf[d->n++] = byte;
    if (d->n < 3) {
        return false;
    }
    uint8_t len = d->buf[2];
    if (len > WP_MAX_PAYLOAD) {
        d->bad_length++;
        drop_first(d);
        return false;
    }
    uint8_t total = (uint8_t)(4 + len);
    if (d->n < total) {
        return false;
    }
    if (wp_crc8(&d->buf[1], (size_t)(2 + len)) != d->buf[3 + len]) {
        d->crc_errors++;
        drop_first(d);
        return false;
    }
    msg->id = d->buf[1];
    msg->len = len;
    memcpy(msg->payload, &d->buf[3], len);
    d->frames++;
    d->n = 0;
    return true;
}
