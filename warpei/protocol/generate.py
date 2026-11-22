#!/usr/bin/env python3
"""Generate the C header and the Python module from messages.json.

    python protocol/generate.py            # writes both files
    python protocol/generate.py --check    # exit 1 if either file is out of date

Outputs:
    firmware/components/protocol/include/warpei_protocol.h
    sbc/warpei/link/protocol.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SPEC = HERE / "messages.json"
C_OUT = ROOT / "firmware" / "components" / "protocol" / "include" / "warpei_protocol.h"
PY_OUT = ROOT / "sbc" / "warpei" / "link" / "protocol.py"

C_TYPES = {"u8": "uint8_t", "i8": "int8_t", "u16": "uint16_t", "i16": "int16_t",
           "u32": "uint32_t", "i32": "int32_t"}
SIZES = {"u8": 1, "i8": 1, "u16": 2, "i16": 2, "u32": 4, "i32": 4}
BANNER = "GENERATED FROM protocol/messages.json BY protocol/generate.py. DO NOT EDIT."


def payload_size(msg: dict) -> int:
    return sum(SIZES[t] for _, t in msg["fields"])


def gen_c(spec: dict) -> str:
    out = [f"/* {BANNER} */", "#ifndef WARPEI_PROTOCOL_H", "#define WARPEI_PROTOCOL_H", "",
           "#include <stdint.h>", "#include <stddef.h>", "",
           f"#define WP_PROTOCOL_VERSION {spec['version']}",
           f"#define WP_START_BYTE 0x{spec['frame']['start_byte']:02X}",
           f"#define WP_MAX_PAYLOAD {spec['frame']['max_payload']}",
           f"#define WP_MAX_FRAME {spec['frame']['max_frame']}",
           f"#define WP_CRC_POLY 0x{spec['frame']['crc']['polynomial']:02X}",
           f"#define WP_CRC_INIT 0x{spec['frame']['crc']['init']:02X}", ""]
    for k, v in spec["link"].items():
        out.append(f"#define WP_{k.upper()} {v}")
    out += ["", "/* Message identifiers */"]
    for m in spec["messages"]:
        out.append(f"#define WP_MSG_{m['name']} 0x{m['id']:02X}")
    out += ["", "/* Payload sizes */"]
    for m in spec["messages"]:
        out.append(f"#define WP_LEN_{m['name']} {payload_size(m)}")
    for ename, values in spec["enums"].items():
        out += ["", f"/* {ename} */"]
        for k, v in values.items():
            out.append(f"#define WP_{ename.upper()}_{k} {v}")
    out += ["", "/* Payload structs: fields are little-endian on the wire; use the pack/unpack",
            "   helpers in protocol.c rather than casting, since the ESP32 may pad structs. */"]
    for m in spec["messages"]:
        if not m["fields"]:
            continue
        out.append(f"typedef struct {{")
        for fname, ftype in m["fields"]:
            out.append(f"    {C_TYPES[ftype]} {fname};")
        out.append(f"}} wp_{m['name'].lower()}_t;")
    out += ["", "/* Field layout tables for the generic pack/unpack helpers */",
            "typedef struct { uint8_t size; uint8_t is_signed; } wp_field_t;",
            "typedef struct { uint8_t id; uint8_t length; uint8_t nfields; const wp_field_t *fields; } wp_msgdef_t;", ""]
    for m in spec["messages"]:
        if m["fields"]:
            items = ", ".join(f"{{{SIZES[t]}, {1 if t.startswith('i') else 0}}}" for _, t in m["fields"])
            out.append(f"static const wp_field_t wp_fields_{m['name'].lower()}[] = {{ {items} }};")
    out.append("static const wp_msgdef_t wp_msgdefs[] = {")
    for m in spec["messages"]:
        tbl = f"wp_fields_{m['name'].lower()}" if m["fields"] else "NULL"
        out.append(f"    {{ WP_MSG_{m['name']}, WP_LEN_{m['name']}, {len(m['fields'])}, {tbl} }},")
    out += ["};", f"#define WP_NUM_MSGDEFS {len(spec['messages'])}", "", "#endif /* WARPEI_PROTOCOL_H */", ""]
    return "\n".join(out)


def gen_py(spec: dict) -> str:
    out = [f'"""{BANNER}"""', "", "from __future__ import annotations", "",
           "import struct", "from dataclasses import dataclass", "",
           f"PROTOCOL_VERSION = {spec['version']}",
           f"START_BYTE = 0x{spec['frame']['start_byte']:02X}",
           f"MAX_PAYLOAD = {spec['frame']['max_payload']}",
           f"MAX_FRAME = {spec['frame']['max_frame']}",
           f"CRC_POLY = 0x{spec['frame']['crc']['polynomial']:02X}",
           f"CRC_INIT = 0x{spec['frame']['crc']['init']:02X}", ""]
    for k, v in spec["link"].items():
        out.append(f"{k.upper()} = {v}")
    out += ["", "", "@dataclass(frozen=True)", "class MessageDef:", "    id: int", "    name: str",
            "    direction: str", "    fields: tuple[str, ...]", "    fmt: str   # struct format, little-endian", "",
            "    @property", "    def length(self) -> int:", "        return struct.calcsize(self.fmt)", "", "",
            "MESSAGES: dict[int, MessageDef] = {"]
    for m in spec["messages"]:
        fmt = "<" + "".join(spec["types"][t] for _, t in m["fields"])
        names = ", ".join(f'"{n}"' for n, _ in m["fields"])
        out.append(f'    0x{m["id"]:02X}: MessageDef(0x{m["id"]:02X}, "{m["name"]}", "{m["direction"]}", ({names}{"," if len(m["fields"]) == 1 else ""}), "{fmt}"),')
    out += ["}", "BY_NAME: dict[str, MessageDef] = {m.name: m for m in MESSAGES.values()}", ""]
    for m in spec["messages"]:
        out.append(f"MSG_{m['name']} = 0x{m['id']:02X}")
    for ename, values in spec["enums"].items():
        out += ["", "", f"class {''.join(w.title() for w in ename.split('_'))}:"]
        for k, v in values.items():
            out.append(f"    {k} = {v}")
        out.append(f"    NAMES = {{{', '.join(f'{v}: \"{k}\"' for k, v in values.items())}}}")
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    ids = [m["id"] for m in spec["messages"]]
    assert len(ids) == len(set(ids)), "duplicate message id"
    assert all(payload_size(m) <= spec["frame"]["max_payload"] for m in spec["messages"])
    outputs = {C_OUT: gen_c(spec), PY_OUT: gen_py(spec)}
    stale = [p for p, text in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
    if args.check:
        for p in stale:
            print(f"out of date: {p.relative_to(ROOT)}")
        return 1 if stale else 0
    for p, text in outputs.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        print(f"wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
