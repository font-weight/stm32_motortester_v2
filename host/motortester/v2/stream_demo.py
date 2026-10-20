"""Paced synthetic wire 0.2 peer; no serial port, MCU or measured clock."""
import math
import struct
import time
import zlib

from ..stream_wire import Kind, decode_frame, decode_payload, encode_frame


class PacedStreamPeer:
    """Receiver-owned byte peer, with bounded backlog and absolute raw indices.

    The synthetic clock schedules 50,000 codes/s. A delayed receiver may catch
    up within 32,768 samples (655.36 ms); a larger delay produces a visible
    overrun terminal. This is a synthetic scheduling allowance, not a claim
    about a physical ADC/USB queue.
    Only the final DATA may contain fewer than the wire maximum of 128 codes.
    """
    sample_rate_hz = 50_000
    max_backlog_samples = 32768

    def __init__(self, waveform="oscilloscope", *, clock=time.monotonic,
                 unknown_tail=False):
        if waveform not in ("oscilloscope", "ignition"):
            raise ValueError("Unknown synthetic waveform")
        self.waveform, self.clock, self.unknown_tail = waveform, clock, unknown_tail
        self._period_samples = 200 if waveform == "oscilloscope" else 2000
        # Only one deterministic period is retained. The receiver later copies
        # raw bytes in at most two slices, without per-sample maths or packing.
        self._period_raw = struct.pack("<" + "H" * self._period_samples,
                                       *(self._sample(i) for i in range(self._period_samples)))
        self._incoming, self._tx = bytearray(), bytearray()
        self._nonce, self._sequence, self._generation = 0, 1, 0
        self._next, self._crc, self._last_data = 0, 0, 0
        self._started_at = None
        self._target = self._produced = None
        self._reason = self._flags = self._stop_request = 0
        self._end_sequence = None

    def _enqueue(self, kind, payload, request=0):
        frame = encode_frame(kind, self._nonce, self._sequence, request, payload)
        if len(self._incoming) + len(frame) > 2048:
            raise RuntimeError("Synthetic control queue overflow")
        self._sequence += 1
        self._incoming.extend(frame)

    def write(self, data):
        if type(data) is not bytes or len(data) > 544 or len(self._tx) + len(data) > 1088:
            raise ValueError("Bounded wire bytes required")
        self._tx.extend(data)
        while 0 in self._tx:
            stop = self._tx.index(0) + 1
            encoded = bytes(self._tx[:stop])
            del self._tx[:stop]
            if encoded == b"\0":
                continue
            frame = decode_frame(encoded, direction="host")
            payload = decode_payload(frame)
            if frame.kind == Kind.HELLO:
                self._incoming.clear()
                self._nonce, self._sequence = payload.nonce, 1
                self._generation = self._next = self._crc = self._last_data = 0
                self._started_at = self._target = self._produced = self._end_sequence = None
                self._reason = self._flags = self._stop_request = 0
                self._enqueue(Kind.HELLO_ACK,
                    struct.pack("<BBBBHHII", 0, 2, 1, 12, 512, 128, 0x5632444D, 1),
                    frame.request_id)
            elif frame.nonce != self._nonce:
                continue
            elif frame.kind == Kind.GET_CAPS:
                self._enqueue(Kind.CAPS,
                    struct.pack("<IHBBIIHHI", 1, 1, 0, 12, 50000, 1, 128, 0, 1),
                    frame.request_id)
            elif frame.kind == Kind.START:
                self._generation = frame.request_id
                self._started_at = self.clock()
                self._enqueue(Kind.START_ACK, struct.pack("<IIQ", self._generation, 1, 0),
                              frame.request_id)
            elif frame.kind == Kind.STOP and payload == self._generation:
                self._stop_request = frame.request_id
                if self._end_sequence is not None:
                    self._ack()
                elif self._target is None:
                    self._terminate()
        return len(data)

    def _due(self):
        return max(self._next, int((self.clock() - self._started_at) * self.sample_rate_hz))

    def _terminate(self, *, overrun=False):
        self._produced = self._due()
        overrun |= self._produced - self._next > self.max_backlog_samples
        self._target = self._next if overrun else self._produced
        self._reason = 1 if overrun else 0
        self._flags = 3 if self.unknown_tail else 2 if overrun else 0

    def _sample(self, index):
        if self.waveform == "oscilloscope":
            return round(2048 + 1100 * math.sin(2 * math.pi * (index % 200) / 200))
        phase = index % 2000
        if phase < 10:
            return round(550 + 3150 * math.exp(-phase / 2))
        if phase < 85:
            return round(1100 - 2 * (phase - 10))
        return round(550 + 280 * math.exp(-(phase - 85) / 12) *
                     math.sin((phase - 85) / 2))

    def _data(self, count):
        first = (self._next % self._period_samples) * 2
        raw = self._period_raw[first:first + count * 2]
        if len(raw) < count * 2:
            raw += self._period_raw[:count * 2 - len(raw)]
        self._last_data = self._sequence
        self._enqueue(Kind.DATA, struct.pack("<IIQHH", self._generation, 1,
                                             self._next, count, 0) + raw)
        self._crc = zlib.crc32(raw, self._crc)
        self._next += count

    def _ack(self):
        self._enqueue(Kind.STOP_ACK, struct.pack("<IQII", self._generation,
                      self._next, self._end_sequence, self._flags), self._stop_request)

    def _produce_one(self):
        if self._started_at is None or self._end_sequence is not None:
            return
        if self._target is None:
            due = self._due() - self._next
            if due > self.max_backlog_samples:
                self._terminate(overrun=True)
            elif due >= 128:
                self._data(128)
                return
            else:
                return
        remaining = self._target - self._next
        if remaining:
            self._data(min(128, remaining))
            return
        self._end_sequence = self._sequence
        self._enqueue(Kind.END, struct.pack("<IIQQIIHHI", self._generation, 1,
            self._next, 0 if self.unknown_tail else self._produced,
            self._last_data, self._crc, self._reason, self._flags, self._stop_request))
        if self._stop_request:
            self._ack()

    def read(self, maximum):
        if type(maximum) is not int or not 0 <= maximum <= 544:
            raise ValueError("Bounded read required")
        if not self._incoming:
            self._produce_one()
        result = bytes(self._incoming[:maximum])
        del self._incoming[:maximum]
        return result
