/* GENERATED FROM protocol/messages.json BY protocol/generate.py. DO NOT EDIT. */
#ifndef WARPEI_PROTOCOL_H
#define WARPEI_PROTOCOL_H

#include <stdint.h>
#include <stddef.h>

#define WP_PROTOCOL_VERSION 2
#define WP_START_BYTE 0xA5
#define WP_MAX_PAYLOAD 32
#define WP_MAX_FRAME 37
#define WP_CRC_POLY 0x07
#define WP_CRC_INIT 0x00

#define WP_BAUD 115200
#define WP_HEARTBEAT_PERIOD_MS 1000
#define WP_HEARTBEAT_REPLY_DEADLINE_MS 100
#define WP_LINK_DOWN_MS 5000
#define WP_ACK_DEADLINE_MS 100
#define WP_ACK_RETRIES 2
#define WP_FIRMWARE_CALIBRATION_TIMEOUT_MS 200000

/* Message identifiers */
#define WP_MSG_HEARTBEAT 0x01
#define WP_MSG_HEARTBEAT_REPLY 0x02
#define WP_MSG_BUTTON 0x03
#define WP_MSG_TEMPERATURE 0x04
#define WP_MSG_FAULT 0x05
#define WP_MSG_BRIGHTNESS 0x06
#define WP_MSG_CAL_START 0x10
#define WP_MSG_CAL_ABORT 0x11
#define WP_MSG_FLIP 0x12
#define WP_MSG_CAL_STATE 0x20
#define WP_MSG_READY 0x21
#define WP_MSG_CAL_ERROR 0x22
#define WP_MSG_ACK 0x7F

/* Payload sizes */
#define WP_LEN_HEARTBEAT 1
#define WP_LEN_HEARTBEAT_REPLY 1
#define WP_LEN_BUTTON 1
#define WP_LEN_TEMPERATURE 7
#define WP_LEN_FAULT 3
#define WP_LEN_BRIGHTNESS 1
#define WP_LEN_CAL_START 0
#define WP_LEN_CAL_ABORT 0
#define WP_LEN_FLIP 1
#define WP_LEN_CAL_STATE 1
#define WP_LEN_READY 5
#define WP_LEN_CAL_ERROR 1
#define WP_LEN_ACK 1

/* button_command */
#define WP_BUTTON_COMMAND_POWER_SHORT 1
#define WP_BUTTON_COMMAND_POWER_LONG 2
#define WP_BUTTON_COMMAND_CALIBRATE_LONG 3
#define WP_BUTTON_COMMAND_FLIP_SHORT 4

/* fw_state */
#define WP_FW_STATE_BOOTING 0
#define WP_FW_STATE_OFF 1
#define WP_FW_STATE_ON 2
#define WP_FW_STATE_CALIBRATING 3
#define WP_FW_STATE_OVER_TEMPERATURE 4
#define WP_FW_STATE_FAULT 5

/* app_state */
#define WP_APP_STATE_BOOTING 0
#define WP_APP_STATE_NO_SOURCE 1
#define WP_APP_STATE_PASSTHROUGH 2
#define WP_APP_STATE_WARPED 3
#define WP_APP_STATE_CALIBRATING 4
#define WP_APP_STATE_ERROR 5

/* fault_code */
#define WP_FAULT_CODE_NONE 0
#define WP_FAULT_CODE_OVER_TEMPERATURE 1
#define WP_FAULT_CODE_SENSOR 2

/* cal_error */
#define WP_CAL_ERROR_DETECT_FAIL 1
#define WP_CAL_ERROR_ACCURACY 2
#define WP_CAL_ERROR_TIMEOUT 3
#define WP_CAL_ERROR_ABORTED 4
#define WP_CAL_ERROR_CAMERA 5

/* Payload structs: fields are little-endian on the wire; use the pack/unpack
   helpers in protocol.c rather than casting, since the ESP32 may pad structs. */
typedef struct {
    uint8_t fw_state;
} wp_heartbeat_t;
typedef struct {
    uint8_t app_state;
} wp_heartbeat_reply_t;
typedef struct {
    uint8_t command;
} wp_button_t;
typedef struct {
    int16_t object_c_x10;
    int16_t ambient_c_x10;
    uint8_t fan_pct;
    uint16_t fan_rpm;
} wp_temperature_t;
typedef struct {
    uint8_t fault_code;
    int16_t object_c_x10;
} wp_fault_t;
typedef struct {
    uint8_t level;
} wp_brightness_t;
typedef struct {
    uint8_t flip;
} wp_flip_t;
typedef struct {
    uint8_t app_state;
} wp_cal_state_t;
typedef struct {
    uint16_t rms_before_x10;
    uint16_t rms_after_x10;
    uint8_t reduction_pct;
} wp_ready_t;
typedef struct {
    uint8_t error_code;
} wp_cal_error_t;
typedef struct {
    uint8_t acked_id;
} wp_ack_t;

/* Field layout tables for the generic pack/unpack helpers */
typedef struct { uint8_t size; uint8_t is_signed; } wp_field_t;
typedef struct { uint8_t id; uint8_t length; uint8_t nfields; const wp_field_t *fields; } wp_msgdef_t;

static const wp_field_t wp_fields_heartbeat[] = { {1, 0} };
static const wp_field_t wp_fields_heartbeat_reply[] = { {1, 0} };
static const wp_field_t wp_fields_button[] = { {1, 0} };
static const wp_field_t wp_fields_temperature[] = { {2, 1}, {2, 1}, {1, 0}, {2, 0} };
static const wp_field_t wp_fields_fault[] = { {1, 0}, {2, 1} };
static const wp_field_t wp_fields_brightness[] = { {1, 0} };
static const wp_field_t wp_fields_flip[] = { {1, 0} };
static const wp_field_t wp_fields_cal_state[] = { {1, 0} };
static const wp_field_t wp_fields_ready[] = { {2, 0}, {2, 0}, {1, 0} };
static const wp_field_t wp_fields_cal_error[] = { {1, 0} };
static const wp_field_t wp_fields_ack[] = { {1, 0} };
static const wp_msgdef_t wp_msgdefs[] = {
    { WP_MSG_HEARTBEAT, WP_LEN_HEARTBEAT, 1, wp_fields_heartbeat },
    { WP_MSG_HEARTBEAT_REPLY, WP_LEN_HEARTBEAT_REPLY, 1, wp_fields_heartbeat_reply },
    { WP_MSG_BUTTON, WP_LEN_BUTTON, 1, wp_fields_button },
    { WP_MSG_TEMPERATURE, WP_LEN_TEMPERATURE, 4, wp_fields_temperature },
    { WP_MSG_FAULT, WP_LEN_FAULT, 2, wp_fields_fault },
    { WP_MSG_BRIGHTNESS, WP_LEN_BRIGHTNESS, 1, wp_fields_brightness },
    { WP_MSG_CAL_START, WP_LEN_CAL_START, 0, NULL },
    { WP_MSG_CAL_ABORT, WP_LEN_CAL_ABORT, 0, NULL },
    { WP_MSG_FLIP, WP_LEN_FLIP, 1, wp_fields_flip },
    { WP_MSG_CAL_STATE, WP_LEN_CAL_STATE, 1, wp_fields_cal_state },
    { WP_MSG_READY, WP_LEN_READY, 3, wp_fields_ready },
    { WP_MSG_CAL_ERROR, WP_LEN_CAL_ERROR, 1, wp_fields_cal_error },
    { WP_MSG_ACK, WP_LEN_ACK, 1, wp_fields_ack },
};
#define WP_NUM_MSGDEFS 13

#endif /* WARPEI_PROTOCOL_H */
