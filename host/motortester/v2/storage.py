"""Versioned raw V2 files and explicit legacy conversion, independent of GUI."""
import csv
from dataclasses import asdict, fields
import hashlib
import hmac
import io
import json
from pathlib import Path
import struct
from .. import recording as legacy
from .data import Recording, SignalBlock, CaptureSettings, MAX_SAMPLES, MAX_BLOCKS
from .input import InputProfile, UNKNOWN_PROFILE, V2Error

MAGIC = b"MTV2RAW\x00"
HEADER = struct.Struct("<8sII")
MAX_METADATA = 1_048_576
MAX_FILE = HEADER.size + MAX_METADATA + MAX_SAMPLES * 2 + 32


def metadata(recording):
    result = {f.name: getattr(recording, f.name) for f in fields(Recording)
              if f.name not in ("blocks", "channel_name", "input_profile", "capture_settings")}
    result.update(format_version=2, sample_encoding="uint16-le", adc_bits=12,
                  sample_count=recording.sample_count,
                  channels=[{"channel_id": "CH1", "name": recording.channel_name,
                             "input_profile": asdict(recording.input_profile)}],
                  capture_settings=asdict(recording.capture_settings),
                  blocks=[{"start_index": b.start_index, "sample_rate_hz": b.sample_rate_hz,
                           "sample_count": len(b.samples), "quality_flags": b.quality_flags,
                           "gap_before": b.gap_before} for b in recording.blocks])
    return result


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def encode(recording):
    if type(recording) is not Recording:
        raise V2Error("Требуется запись V2")
    meta = _json(metadata(recording))
    if len(meta) > MAX_METADATA:
        raise V2Error("Метаданные превышают предел")
    payload = HEADER.pack(MAGIC, len(meta), recording.sample_count) + meta
    payload += b"".join(struct.pack(f"<{len(block.samples)}H", *block.samples) for block in recording.blocks)
    return payload + hashlib.sha256(payload).digest()


def _keys(value, expected, description):
    if type(value) is not dict or set(value) != set(expected):
        raise V2Error(f"{description}: неизвестные или отсутствующие поля")


def _tuple_flags(value):
    if type(value) is not list:
        raise V2Error("Флаги качества должны быть массивом")
    return tuple(value)


def from_legacy(capture):
    """Raw legacy codes remain unconfigured, including device captures."""
    return Recording(
        blocks=(SignalBlock(0, capture.nominal_fs_hz, capture.samples, capture.quality_flags),),
        source="demo" if capture.origin == "simulator" else "device",
        input_profile=InputProfile(profile_id="legacy-unconfigured", sensor=capture.sensor),
        session_id=capture.session_id,
        created_at_utc=capture.received_at_utc, firmware_version=capture.firmware_version,
        protocol_version=capture.protocol_version, application_version=capture.application_version,
        time_basis="nominal_unverified", legacy_format="mtcap-v1", legacy_sequence=capture.sequence,
        trigger_index=capture.trigger_index, quality_flags=capture.quality_flags,
        capture_settings=CaptureSettings(
            threshold_v=None, edge=capture.trigger_edge, holdoff_s=0,
            pretrigger_fraction=capture.pretrigger_samples / len(capture.samples),
            window_s=len(capture.samples) / capture.nominal_fs_hz,
            hardware_threshold_code=capture.trigger_level_code, trigger_kind=capture.trigger_kind),
    )


def decode(data):
    if type(data) is not bytes:
        raise V2Error("Требуется бинарное содержимое записи")
    if data.startswith(legacy.MAGIC):
        return from_legacy(legacy.decode(data))
    if not HEADER.size + 32 <= len(data) <= MAX_FILE:
        raise V2Error("Недопустимый размер файла")
    magic, meta_size, count = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise V2Error("Неизвестный формат записи")
    if not 1 <= meta_size <= MAX_METADATA or not 1 <= count <= MAX_SAMPLES:
        raise V2Error("Размер записи превышает предел")
    if len(data) != HEADER.size + meta_size + count * 2 + 32:
        raise V2Error("Файл обрезан или содержит лишние данные")
    if not hmac.compare_digest(hashlib.sha256(data[:-32]).digest(), data[-32:]):
        raise V2Error("Нарушена целостность записи (SHA-256)")
    try:
        meta = json.loads(data[HEADER.size:HEADER.size + meta_size].decode("utf-8"),
                          object_pairs_hook=legacy._object, parse_constant=legacy._invalid_number)
        base_keys = {f.name for f in fields(Recording)} - {"channel_name", "input_profile"}
        _keys(meta, base_keys | {"format_version", "sample_encoding", "adc_bits", "sample_count", "channels"},
              "Метаданные")
        for name, expected in (("format_version", 2), ("sample_encoding", "uint16-le"),
                               ("adc_bits", 12), ("sample_count", count)):
            actual = meta.pop(name)
            if type(actual) is not type(expected) or actual != expected:
                raise V2Error(f"Неподдерживаемое поле: {name}")
        channels = meta.pop("channels")
        if type(channels) is not list or len(channels) != 1:
            raise V2Error("Поддерживается один канал")
        channel = channels[0]
        _keys(channel, {"channel_id", "name", "input_profile"}, "Канал")
        if channel["channel_id"] != "CH1":
            raise V2Error("Поддерживается только CH1")
        _keys(channel["input_profile"], {f.name for f in fields(InputProfile)}, "Профиль входа")
        profile = InputProfile(**channel["input_profile"])
        _keys(meta["capture_settings"], {f.name for f in fields(CaptureSettings)}, "Настройки захвата")
        settings = CaptureSettings(**meta.pop("capture_settings"))
        descriptions = meta.pop("blocks")
        if type(descriptions) is not list or not 1 <= len(descriptions) <= MAX_BLOCKS:
            raise V2Error("Некорректный список блоков")
        offset = HEADER.size + meta_size
        blocks, total = [], 0
        for descriptor in descriptions:
            _keys(descriptor, {"start_index", "sample_rate_hz", "sample_count", "quality_flags", "gap_before"}, "Блок")
            size = descriptor.pop("sample_count")
            if type(size) is not int or not 1 <= size <= count - total:
                raise V2Error("Некорректный размер блока")
            raw = struct.unpack_from(f"<{size}H", data, offset)
            descriptor["quality_flags"] = _tuple_flags(descriptor["quality_flags"])
            blocks.append(SignalBlock(samples=raw, **descriptor))
            total += size
            offset += size * 2
        if total != count:
            raise V2Error("Сумма блоков не совпадает с числом отсчётов")
        meta["quality_flags"] = _tuple_flags(meta["quality_flags"])
        return Recording(blocks=tuple(blocks), channel_name=channel["name"],
                         input_profile=profile, capture_settings=settings, **meta)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, struct.error) as exc:
        if isinstance(exc, V2Error):
            raise
        raise V2Error(f"Некорректные метаданные записи: {exc}") from exc


def save(path, recording, *, overwrite=False):
    legacy.atomic_write(path, encode(recording), overwrite=overwrite)


def load(path):
    with open(path, "rb") as stream:
        return decode(stream.read(MAX_FILE + 1))


def export_csv(path, recording, *, overwrite=False):
    """CSV keeps source indices/time; JSON contains the complete profile/gaps.

    The JSON contains CSV SHA-256 so readers can reject a mismatched pair after
    an interrupted overwrite. The .mtv2 file is the single atomic primary file.
    """
    path = Path(path)
    sidecar = path.with_suffix(path.suffix + ".json")
    if not overwrite and (path.exists() or sidecar.exists()):
        raise FileExistsError("CSV или файл метаданных уже существует")
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(("sample_index", "time_s", "adc_code", "voltage_v", "block_index", "gap_before"))
    profile = recording.input_profile
    previous = recording.start_index
    for block_number, block in enumerate(recording.blocks):
        gap = block.gap_before or ("missing_samples" if block.start_index > previous else "")
        for offset, code in enumerate(block.samples):
            index = block.start_index + offset
            writer.writerow((index, format(index / block.sample_rate_hz, ".17g"), code,
                format(profile.voltage(code), ".17g") if profile.configured else "",
                block_number, gap if offset == 0 else ""))
        previous = block.end_index
    raw = out.getvalue().encode("utf-8")
    meta = metadata(recording)
    meta.update(export_format="motortester-csv-v1", csv_sha256=hashlib.sha256(raw).hexdigest(),
                gaps=[asdict(gap) for gap in recording.gaps], voltage_unit="V",
                time_origin="source_sample_index_zero", voltage_unknown=not profile.configured)
    legacy.atomic_write(path, raw, overwrite=overwrite)
    legacy.atomic_write(sidecar, _json(meta), overwrite=overwrite)
    return path, sidecar
