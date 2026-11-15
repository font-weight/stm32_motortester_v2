"""Read-only calibration excerpts from hash-bound, completed stream journals.

The nominal or measured scale stored with the source proves only the operator's
declared switch position. It is never applied to the raw codes used for fitting.
"""
from pathlib import Path

from .analog_profile import RawFormat
from .calibration import SampleWindow
from .stream_files import open_stream


def import_window(path, plan, offset_samples, count):
    path = Path(path)
    # Calibration needs a short steady recording, not an hours-long journal.
    # Bound validation work as well as the retained array (GUI runs it off-thread).
    if not 0 < path.stat().st_size <= 64 * 1024 * 1024:
        raise ValueError("Для калибровки сохраните короткую запись размером до 64 МиБ")
    if type(offset_samples) is not int or offset_samples < 0 or type(count) is not int or not 128 <= count <= 16384:
        raise ValueError("Нужны начальное смещение ≥0 и 128…16384 отсчёта")
    verified, result = open_stream(path)
    archive = result.recording if hasattr(result, "recording") else result
    if archive is None or archive.recovery_issue or archive.discarded_tail_bytes:
        raise ValueError("Запись пуста или повреждена; используйте завершённую запись")
    terminal = archive.terminal
    # Current wire0.3 reports a stopped, contiguous RECEIVED prefix but cannot
    # count the generated tail. Unknown total production is not a gap in this
    # explicitly selected prefix, nor evidence that no unseen data were lost.
    if (terminal is None or terminal.reason != "stopped" or not terminal.stop_requested or
            not terminal.terminal_observed or terminal.failure is not None or
            terminal.device_transmitted_end_sample_index != archive.end_sample_index or
            terminal.loss_samples not in (None, 0)):
        raise ValueError("Нужна запись со штатной остановкой и целостным принятым участком")
    snapshot = verified.context.analog_snapshot
    if not verified.companion_present or snapshot is None:
        raise ValueError("В записи нет подтверждённого режима и экземпляра входа. Перед новой записью настройте «Аналоговый вход CH1…»")
    raw_format = RawFormat.from_identity(archive.identity)
    if (raw_format != plan.raw_format or snapshot.mode_id != plan.mode_id or
            snapshot.hardware_instance_id != plan.hardware_instance_id):
        raise ValueError("Запись относится к другому режиму, частоте АЦП или экземпляру платы")
    if archive.identity.origin != plan.origin:
        raise ValueError("Происхождение записи не соответствует выбранному опыту")
    if plan.origin == "device" and (verified.connection is None or verified.connection.execution_kind != "physical"):
        raise ValueError("Нет сохранённого физического соединения STM32; искусственный источник не подходит")
    start = archive.first_sample_index + offset_samples
    codes = tuple(archive.read_samples(start, count))
    # The journal hash survives renaming/copying; interval overlap cannot be
    # hidden by choosing the same recording under another filename.
    return SampleWindow(codes=codes, source_id=verified.journal_sha256,
        raw_format=raw_format, mode_id=snapshot.mode_id,
        hardware_instance_id=snapshot.hardware_instance_id, origin=archive.identity.origin,
        first_sample_index=start, has_gaps=False, settled_confirmed=True)
