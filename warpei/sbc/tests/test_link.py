"""Task 5.6, ROCK 5B side: framing, CRC, decoder resync, link behaviour.

Acceptance: 10,000 frames with no corrupted frame accepted; injected CRC
errors dropped with the next frame still received; heartbeat loss detected
within 5 s; a button press reaches the application.
"""

from __future__ import annotations

import random

import pytest

from warpei.link import framing, protocol as P
from warpei.link.uart import LoopbackPort, UartLink


def test_crc8_test_vector_and_examples():
    assert framing.crc8(b"123456789") == 0xF4
    assert framing.encode(P.MSG_CAL_START) == bytes.fromhex("A5 10 00 57")
    assert framing.encode(P.MSG_FLIP, flip=1) == bytes.fromhex("A5 12 01 01 66")
    assert framing.encode(P.MSG_HEARTBEAT, fw_state=P.FwState.ON) == bytes.fromhex("A5 01 01 02 70")


def test_encode_decode_every_message():
    rng = random.Random(1)
    for d in P.MESSAGES.values():
        fields = {}
        for name, code in zip(d.fields, d.fmt[1:]):
            lo, hi = {"B": (0, 255), "b": (-128, 127), "H": (0, 65535), "h": (-32768, 32767),
                      "I": (0, 2**32 - 1), "i": (-2**31, 2**31 - 1)}[code]
            fields[name] = rng.randint(lo, hi)
        frame = framing.encode(d.id, **fields)
        assert len(frame) == 4 + d.length <= P.MAX_FRAME
        msgs = framing.Decoder().feed(frame)
        assert len(msgs) == 1 and msgs[0].id == d.id and msgs[0].values == fields


def test_encode_rejects_wrong_fields():
    with pytest.raises(ValueError):
        framing.encode(P.MSG_FLIP)
    with pytest.raises(ValueError):
        framing.encode(P.MSG_FLIP, flip=1, extra=2)


def test_ten_thousand_frames_no_corruption_accepted():
    rng = random.Random(7)
    dec = framing.Decoder()
    sent = []
    stream = bytearray()
    for _ in range(10_000):
        t = rng.randint(-300, 300)
        frame = framing.encode(P.MSG_TEMPERATURE, object_c_x10=t, ambient_c_x10=250, fan_pct=50, fan_rpm=1500)
        sent.append(t)
        stream.extend(frame)
    # deliver in random chunk sizes, as a serial port would
    got = []
    i = 0
    while i < len(stream):
        n = rng.randint(1, 40)
        got.extend(m.object_c_x10 for m in dec.feed(bytes(stream[i:i + n])))
        i += n
    assert got == sent
    assert dec.crc_errors == 0 and dec.resyncs == 0


def test_injected_crc_errors_are_dropped_and_stream_recovers():
    rng = random.Random(3)
    dec = framing.Decoder()
    good = 0
    for i in range(1000):
        frame = bytearray(framing.encode(P.MSG_BUTTON, command=P.ButtonCommand.FLIP_SHORT))
        corrupt = i % 100 == 50
        if corrupt:
            frame[-1] ^= 0xFF
        else:
            good += 1
        msgs = dec.feed(bytes(frame))
        assert len(msgs) == (0 if corrupt else 1)
    assert dec.frames == good == 990 and dec.crc_errors == 10


def test_garbage_and_false_start_bytes():
    dec = framing.Decoder()
    noise = bytes([0xA5, 0xFF, 0x7F]) + bytes(range(50))     # start byte, bad length
    assert dec.feed(noise) == []
    assert dec.feed(framing.encode(P.MSG_CAL_START))[0].id == P.MSG_CAL_START


def test_unknown_id_is_counted_not_crashing():
    body = bytes([0x55, 0x00])
    dec = framing.Decoder()
    assert dec.feed(bytes([P.START_BYTE]) + body + bytes([framing.crc8(body)])) == []
    assert dec.unknown_id == 1


class FakeClock:
    def __init__(self): self.t = 100.0
    def __call__(self): return self.t


def test_link_heartbeat_ack_and_delivery():
    lp = LoopbackPort()
    rock, esp = lp.side("a"), lp.side("b")
    clock = FakeClock()
    received = []
    link = UartLink(rock, on_message=received.append, clock=clock)
    link.app_state = P.AppState.WARPED
    assert not link.link_up

    # ESP32 sends a heartbeat: ROCK replies with its state and the link is up
    esp.write(framing.encode(P.MSG_HEARTBEAT, fw_state=P.FwState.ON))
    link.process(rock.read(64))
    reply = framing.Decoder().feed(esp.read(64))
    assert reply[0].id == P.MSG_HEARTBEAT_REPLY and reply[0].app_state == P.AppState.WARPED
    assert link.link_up and link.fw_state == P.FwState.ON
    assert link.status_text() == "controller on"

    # a button press is delivered and ACKed
    esp.write(framing.encode(P.MSG_CAL_START))
    link.process(rock.read(64))
    assert received[-1].id == P.MSG_CAL_START
    ack = framing.Decoder().feed(esp.read(64))
    assert ack[0].id == P.MSG_ACK and ack[0].acked_id == P.MSG_CAL_START

    # 5 s without a heartbeat: link down
    clock.t += 4.9
    assert link.link_up
    clock.t += 0.2
    assert not link.link_up and link.status_text() == "controller offline"


def test_ready_message_rounding_and_clamping():
    lp = LoopbackPort()
    rock, esp = lp.side("a"), lp.side("b")
    link = UartLink(rock)
    link.send_ready(20.37, 3.04, 85.1)
    m = framing.Decoder().feed(esp.read(64))[0]
    assert (m.rms_before_x10, m.rms_after_x10, m.reduction_pct) == (204, 30, 85)
    link.send_ready(1e9, 0, -5)
    m = framing.Decoder().feed(esp.read(64))[0]
    assert (m.rms_before_x10, m.reduction_pct) == (65535, 0)


def test_handler_exception_does_not_stop_processing():
    lp = LoopbackPort()
    rock, esp = lp.side("a"), lp.side("b")
    def boom(msg): raise RuntimeError("bug")
    link = UartLink(rock, on_message=boom)
    esp.write(framing.encode(P.MSG_FLIP, flip=1) + framing.encode(P.MSG_FLIP, flip=0))
    assert len(link.process(rock.read(64))) == 2
