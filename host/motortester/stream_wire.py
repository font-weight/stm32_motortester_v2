"""Isolated HOST codec for the unaccepted wire 0.2 stream draft.

Pinned prose: PR192 08172114403273ecfac2fb1e8e49d92f9c68756f;
SHA256 174aed3c570a204d865c1a446c7878c628a972222d00ef8f60d33ad9c92c998a.
No transport, firmware, application or storage integration is provided.
"""
from dataclasses import dataclass
from enum import IntEnum
import struct
import zlib

DRAFT_COMMIT = "08172114403273ecfac2fb1e8e49d92f9c68756f"
DRAFT_SHA256 = "174aed3c570a204d865c1a446c7878c628a972222d00ef8f60d33ad9c92c998a"
MAX_PAYLOAD, MAX_DECODED, MAX_ENCODED, MAX_FRAME = 512, 540, 543, 544
MAX_BLOCK, U32_MAX, U64_MAX = 128, 0xffffffff, 0xffffffffffffffff
COUNTER_RESERVE = 0xffffff00
HEADER = struct.Struct("<BBBBHHQII")
# V2S4–V2S7 use the same wire framing and DATA block size. The CAPS
# numerator selects the nominal timebase; it does not certify the ADC clock.
LEGACY_SAMPLE_RATES = frozenset((50_000, 100_000, 200_000))
SUPPORTED_SAMPLE_RATES = LEGACY_SAMPLE_RATES | {150_000}
MODE_TABLE = {1: (50_000, 12, 1), 2: (100_000, 12, 1), 3: (150_000, 10, 2)}
MODE_REVISION = "0.3-modes-20261024"


def supported_caps(values):
    """Admit only the supported fixed CH1 rates, with exact integer fields."""
    return (type(values) is tuple and len(values) == 8 and
            all(type(value) is int for value in values) and
            values[4] in LEGACY_SAMPLE_RATES and
            values[:4] == (1, 1, 0, 12) and values[5:] == (1, 128, 1))


def supported_mode_caps(values):
    if (type(values) is not tuple or len(values) != 10 or
            any(type(value) is not int for value in values)):
        return False
    mode = values[0]
    if mode not in MODE_TABLE:
        return False
    rate, retained, encoding = MODE_TABLE[mode]
    return values == (mode, mode, 0, 12, rate, 1, 128, 1, retained, encoding)


def caps_values(caps):
    names = ("config_id", "profile", "channel", "adc_bits", "fs_num", "fs_den", "max_block", "flags")
    values = tuple(getattr(caps, name) for name in names)
    return values + (caps.retained_bits, caps.encoding) if caps.revision == "0.3" else values


def unpack10(packed, count):
    """Decode the transmitted bits into ADC12 code units, never restore lost LSBs."""
    if len(packed) != (10 * count + 7) // 8:
        raise WireError("payload_length")
    bits = int.from_bytes(packed, "little")
    if bits >> (count * 10):
        raise WireError("padding")
    return tuple(((bits >> (10 * n)) & 1023) << 2 for n in range(count))


def pack10(canonical):
    if not 1 <= len(canonical) <= MAX_BLOCK or any(
            type(c) is not int or not 0 <= c <= 4092 or c % 4 for c in canonical):
        raise WireError("code")
    bits = sum((c >> 2) << (10 * n) for n, c in enumerate(canonical))
    return bits.to_bytes((10 * len(canonical) + 7) // 8, "little")


class Kind(IntEnum):
    HELLO = 1
    GET_CAPS = 2
    STOP = 5
    START = 8
    HELLO_ACK = 129
    CAPS = 130
    STOP_ACK = 133
    START_ACK = 136
    DATA = 152
    END = 153
    ERROR = 255


HOST_KINDS = frozenset((Kind.HELLO, Kind.GET_CAPS, Kind.STOP, Kind.START))
DEVICE_KINDS = frozenset(set(Kind) - HOST_KINDS)


class WireError(ValueError):
    """Fixed diagnostic code; never includes arbitrary bytes/transport details."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def uint(value: int, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def cobs_encode(raw: bytes) -> bytes:
    if type(raw) is not bytes or len(raw) > MAX_DECODED:
        raise WireError("framing")
    out = bytearray((0,))
    code_at, code = 0, 1
    for byte in raw:
        if byte == 0:
            out[code_at] = code
            code_at, code = len(out), 1
            out.append(0)
        else:
            out.append(byte)
            code += 1
            if code == 255:
                out[code_at] = code
                code_at, code = len(out), 1
                out.append(0)
    out[code_at] = code
    return bytes(out)


def cobs_decode(encoded: bytes) -> bytes:
    if type(encoded) is not bytes or not 1 <= len(encoded) <= MAX_ENCODED:
        raise WireError("framing")
    out, pos = bytearray(), 0
    while pos < len(encoded):
        code = encoded[pos]
        if code == 0 or pos + code > len(encoded):
            raise WireError("framing")
        chunk = encoded[pos + 1:pos + code]
        if 0 in chunk:
            raise WireError("framing")
        out.extend(chunk)
        pos += code
        if code < 255 and pos < len(encoded):
            out.append(0)
        if len(out) > MAX_DECODED:
            raise WireError("framing")
    return bytes(out)


@dataclass(frozen=True, slots=True)
class Frame:
    kind: Kind
    nonce: int
    sequence: int
    request_id: int
    payload: bytes
    encoded: bytes  # Exact bytes, including delimiter, for immediate-duplicate checks.
    revision: str = "0.2"


def decode_frame(framed: bytes, direction: str | None = None, *, allow_unknown_revision=False) -> Frame:
    """Validate envelope only; payload/state validation follows nonce/correlation."""
    if type(framed) is not bytes or not 2 <= len(framed) <= MAX_FRAME or framed[-1] != 0:
        raise WireError("framing")
    raw = cobs_decode(framed[:-1])
    if len(raw) < HEADER.size + 4:
        raise WireError("length")
    if zlib.crc32(raw[:-4]) != struct.unpack_from("<I", raw, len(raw) - 4)[0]:
        raise WireError("crc")
    major, minor, kind, r1, size, r2, nonce, seq, req = HEADER.unpack_from(raw)
    if not allow_unknown_revision and (major, minor) not in ((0, 2), (0, 3)):
        raise WireError("version")
    if r1 or r2:
        raise WireError("reserved")
    if size > MAX_PAYLOAD or len(raw) != HEADER.size + size + 4:
        raise WireError("length")
    try:
        kind = Kind(kind)
    except ValueError:
        raise WireError("type") from None
    if direction not in (None, "host", "device"):
        raise ValueError("direction")
    if direction == "host" and kind not in HOST_KINDS or direction == "device" and kind not in DEVICE_KINDS:
        raise WireError("direction")
    if seq == 0:
        raise WireError("sequence")
    return Frame(kind, nonce, seq, req, raw[24:-4], framed, f"{major}.{minor}")


@dataclass(frozen=True, slots=True)
class Hello:
    nonce: int
    mode: int = 0


@dataclass(frozen=True, slots=True)
class HelloAck:
    firmware_build: int
    capabilities: int = 1


@dataclass(frozen=True, slots=True)
class Caps:
    config_id: int = 1
    profile: int = 1
    channel: int = 0
    adc_bits: int = 12
    fs_num: int = 50000
    fs_den: int = 1
    max_block: int = 128
    flags: int = 1
    retained_bits: int = 12
    encoding: int = 1
    revision: str = "0.2"


@dataclass(frozen=True, slots=True)
class StartAck:
    generation: int
    config_id: int
    first_index: int


@dataclass(frozen=True, slots=True)
class Data:
    generation: int
    config_id: int
    first_index: int
    samples: tuple[int, ...]

    @property
    def end_index(self) -> int:
        return self.first_index + len(self.samples)

    @property
    def raw_samples(self) -> bytes:
        return struct.pack("<" + "H" * len(self.samples), *self.samples)


@dataclass(frozen=True, slots=True)
class End:
    generation: int
    config_id: int
    prefix_end: int
    produced_end: int | None
    last_data_sequence: int
    prefix_crc32: int
    reason: int
    flags: int
    stop_request_id: int


@dataclass(frozen=True, slots=True)
class StopAck:
    generation: int
    prefix_end: int
    terminal_sequence: int
    flags: int


@dataclass(frozen=True, slots=True)
class Error:
    rejected_type: Kind
    code: int
    generation: int


def _unpack(fmt: str, payload: bytes) -> tuple:
    if len(payload) != struct.calcsize(fmt):
        raise WireError("payload_length")
    return struct.unpack(fmt, payload)


def decode_payload(frame: Frame) -> object:
    """Strict fixed-profile semantics. Cross-frame identities belong to endpoint."""
    k, p = frame.kind, frame.payload
    if frame.revision not in ("0.2", "0.3"):
        raise WireError("version")
    modes = frame.revision == "0.3"
    if k == Kind.HELLO:
        if modes:
            nonce, mode, reserved = _unpack("<QHH", p)
            if mode not in MODE_TABLE or reserved:
                raise WireError("profile")
        else:
            nonce, = _unpack("<Q", p)
            mode = 0
        if not nonce or (frame.nonce, frame.sequence, frame.request_id) != (0, 1, 1):
            raise WireError("hello")
        return Hello(nonce, mode)
    if k == Kind.GET_CAPS:
        _unpack("<", p)
        return None
    if k == Kind.START:
        if modes:
            config, = _unpack("<I", p)
            if config not in MODE_TABLE:
                raise WireError("config")
            return config
        profile, reserved = _unpack("<HH", p)
        if reserved:
            raise WireError("reserved")
        if profile != 1:
            raise WireError("profile")
        return profile
    if k == Kind.STOP:
        generation, = _unpack("<I", p)
        if not generation:
            raise WireError("generation")
        return generation
    if k == Kind.HELLO_ACK:
        major, minor, channels, bits, maximum, block, build, caps = _unpack("<BBBBHHII", p)
        if (major, minor) != (0, 3 if modes else 2):
            raise WireError("version")
        if (channels, bits, maximum, block) != (1, 12, 512, 128) or caps not in ((1,) if modes else (1, 3)):
            raise WireError("caps")
        return HelloAck(build, caps)
    if k == Kind.CAPS:
        if modes:
            config, profile, channel, bits, numerator, denominator, block, retained, encoding, flags = _unpack("<IHBBIIHBBI", p)
            values = (config, profile, channel, bits, numerator, denominator, block, flags, retained, encoding)
            if not supported_mode_caps(values):
                raise WireError("caps")
            return Caps(*values, "0.3")
        config, profile, channel, bits, numerator, denominator, block, reserved, flags = _unpack("<IHBBIIHHI", p)
        if reserved:
            raise WireError("reserved")
        values = (config, profile, channel, bits, numerator, denominator, block, flags)
        if not supported_caps(values):
            raise WireError("caps")
        return Caps(*values)
    if k == Kind.START_ACK:
        generation, config, first = _unpack("<IIQ", p)
        if not generation:
            raise WireError("generation")
        if config not in (MODE_TABLE if modes else (1,)):
            raise WireError("config")
        if first != 0:
            raise WireError("sample_gap")
        return StartAck(generation, config, first)
    if k == Kind.DATA:
        if len(p) < 20:
            raise WireError("payload_length")
        generation, config, first, count, reserved = struct.unpack_from("<IIQHH", p)
        if not 1 <= count <= MAX_BLOCK:
            raise WireError("count")
        if reserved:
            raise WireError("reserved")
        if not generation:
            raise WireError("generation")
        if config not in (MODE_TABLE if modes else (1,)):
            raise WireError("config")
        if first + count > U64_MAX:
            raise WireError("overflow")
        if modes and config == 3:
            samples = unpack10(p[20:], count)
        else:
            if len(p) != 20 + 2 * count:
                raise WireError("payload_length")
            samples = struct.unpack_from("<" + "H" * count, p, 20)
        if any(sample > 4095 for sample in samples):
            raise WireError("code")
        return Data(generation, config, first, samples)
    if k == Kind.END:
        generation, config, prefix, produced, last, crc, reason, flags, stop = _unpack("<IIQQIIHHI", p)
        if not generation:
            raise WireError("generation")
        if config not in (MODE_TABLE if modes else (1,)):
            raise WireError("config")
        if reason > 6 or flags & ~7:
            raise WireError("terminal")
        if flags & 1:
            if produced or not flags & 2:
                raise WireError("terminal")
        elif produced < prefix or produced != prefix and not flags & 2:
            raise WireError("terminal")
        if not reason and not stop:
            raise WireError("terminal")
        if not prefix and (last or crc) or prefix and not last:
            raise WireError("terminal")
        return End(generation, config, prefix, None if flags & 1 else produced, last, crc, reason, flags, stop)
    if k == Kind.STOP_ACK:
        generation, prefix, terminal, flags = _unpack("<IQII", p)
        if not generation or not terminal or flags & ~3:
            raise WireError("terminal")
        return StopAck(generation, prefix, terminal, flags)
    if k == Kind.ERROR:
        rejected, code, reserved, generation = _unpack("<BBHI", p)
        if reserved:
            raise WireError("reserved")
        if rejected not in HOST_KINDS or not 1 <= code <= 5:
            raise WireError("error")
        return Error(Kind(rejected), code, generation)
    raise WireError("type")


def encode_frame(kind: Kind, nonce: int, sequence: int, request_id: int, payload: bytes, *, revision="0.2") -> bytes:
    """Encode a strictly checked message; test negatives use independent byte builders."""
    if not isinstance(kind, Kind) or type(payload) is not bytes or len(payload) > MAX_PAYLOAD:
        raise WireError("type")
    if not uint(nonce, U64_MAX) or not uint(sequence, U32_MAX) or not uint(request_id, U32_MAX) or sequence == 0:
        raise WireError("counter")
    if revision not in ("0.2", "0.3"):
        raise WireError("version")
    raw = HEADER.pack(0, int(revision[-1]), kind, 0, len(payload), 0, nonce, sequence, request_id) + payload
    framed = cobs_encode(raw + struct.pack("<I", zlib.crc32(raw))) + b"\0"
    decode_payload(decode_frame(framed))
    return framed
