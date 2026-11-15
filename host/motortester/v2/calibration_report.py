"""Human-readable PDF projection of a calibration record, never a certificate.

Qt is already part of the desktop app. A report retains the model's origin,
scope and failed/pending control; it never edits samples or applies coefficients.
"""
import hashlib
from html import escape
import json
import os
from pathlib import Path
import tempfile

from PySide6 import QtCore, QtGui

from .calibration import CalibrationRecord


def _number(value):
    return format(value, '.10g').replace('.', ',')


def _text(value):
    return escape(str(value), quote=True)


def _row(name, value):
    return f'<tr><td width="31%"><b>{_text(name)}</b></td><td>{_text(value)}</td></tr>'


def _hash(value):
    return '<span class="hash">' + '<br/>'.join(_text(value[i:i+32]) for i in range(0, len(value), 32)) + '</span>'


def _report_html(record):
    if type(record) is not CalibrationRecord:
        raise ValueError('Нужна запись калибровки')
    # Revalidate into a separate immutable instance. __post_init__ caches
    # summaries, so invoking it on the user's record would mutate that cache.
    payload = record.to_dict()
    checked = CalibrationRecord.from_dict(payload)
    p, fmt = checked.plan, checked.plan.raw_format
    origin = ('ИСКУССТВЕННЫЕ ДАННЫЕ - НЕ КАЛИБРОВКА ПРИБОРА' if p.origin == 'synthetic'
              else 'ДАННЫЕ ОПЕРАТОРА - ПРОИСХОЖДЕНИЕ НЕ АТТЕСТОВАНО')
    states = {
        'fit_pending_validation': 'ПОДБОР КОЭФФИЦИЕНТОВ. Независимый контроль ещё не выполнен.',
        'control_failed': 'КОНТРОЛЬ НЕ ПРОЙДЕН. Результат нельзя применить к прибору.',
        'synthetic_verified': 'Учебный контроль пройден. Результат нельзя применить к прибору.',
        'validated_operator': 'Контроль по данным оператора пройден в указанных условиях.',
    }
    applicability = ('Применение допускается моделью только к тому же экземпляру, режиму и формату приёма.'
                     if checked.can_apply else 'НЕ ПРИМЕНЯТЬ К РЕАЛЬНОМУ ВХОДУ.')
    rate = f'{fmt.sample_rate_hz:,}'.replace(',', ' ')
    format_text = (f'{rate} отсчётов/с; АЦП {fmt.source_adc_bits} бит; '
                   f'сохранено {fmt.retained_bits} бит; коды ADC12 0…{fmt.canonical_max}, шаг {fmt.canonical_step}')
    if fmt.retained_bits == 10:
        format_text += '. Два младших бита утрачены; повторное умножение на четыре не выполняется.'
    else:
        format_text += '. Все 12 бит сохранены.'
    settings = ''.join((_row('Физический режим', p.mode_id.replace('_', ' + ')),
        _row('Экземпляр входа', p.hardware_instance_id), _row('Формат приёма', format_text),
        _row('Контрольный прибор', p.instrument), _row('Условия опыта', p.conditions),
        _row('Опорная погрешность', _number(p.reference_uncertainty_v)+' В'),
        _row('Допустимая граница контроля', _number(p.tolerance_v)+' В')))
    if p.mode_id != 'DC_WIDE':
        settings += _row('Синусоида', f'{_number(p.frequency_hz)} Гц; амплитуда {p.amplitude_kind}; знак передачи {p.polarity:+d}')
        settings += _row('Основание знака', p.polarity_basis)
    rows = []
    factor = {'Vpk': 1., 'Vpp': 2., 'Vrms': 2**-.5}[p.amplitude_kind]
    for index, (point, reference) in enumerate(zip(checked.summaries, checked.reference_values)):
        ac = p.mode_id != 'DC_WIDE' and index != 0
        value = (abs(checked.a)*point.amplitude_pk_codes*factor if ac
                 else checked.a*point.mean_code+checked.b)
        role = ('Независимый контроль' if index == 2 else
                'Ноль CH1-AGND' if p.mode_id != 'DC_WIDE' and index == 0 else f'Подбор {index+1}')
        feature = ('Aпик = '+_number(point.amplitude_pk_codes) if ac else 'Среднее = '+_number(point.mean_code))
        quantity = p.amplitude_kind if ac else 'DC'
        cells = (role, quantity, _number(reference), _number(value), _number(value-reference), feature)
        rows.append('<tr>'+''.join('<td>'+_text(cell)+'</td>' for cell in cells)+'</tr>')
    control = '<p>Независимой третьей точки ещё нет. Ошибка, бюджет и итоговая граница контроля не определены.</p>'
    if checked.control_error_v is not None:
        error, bound = checked.control_error_v, checked.control_bound_v
        budget = bound-abs(error)
        control = ('<table width="100%" cellspacing="0" cellpadding="5">' +
                   _row('Ошибка контроля', _number(error)+' В') +
                   _row('Бюджет погрешностей', _number(budget)+' В') +
                   _row('|Ошибка| + бюджет', _number(bound)+' В') +
                   _row('Критерий', f'{_number(bound)} ≤ {_number(p.tolerance_v)} В: '+
                        ('выполнен' if bound <= p.tolerance_v else 'НЕ выполнен'))+'</table>')
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(',', ':'), allow_nan=False).encode('utf-8')
    digest = hashlib.sha256(canonical).hexdigest()
    sources = []
    for index, summary in enumerate(checked.summaries):
        data = (_row('Источник участка', summary.source_id)+
                _row('Исходные индексы', f'[{summary.first_sample_index}, {summary.first_sample_index+summary.count}); {summary.count} отсчётов')+
                _row('Подготовлен на ПК, UTC', summary.prepared_at_utc))
        data += '<tr><td><b>SHA-256 исходных кодов</b></td><td>'+_hash(summary.raw_sha256)+'</td></tr>'
        sources.append(f'<h3>Участок {index+1}'+(' - независимый контроль' if index == 2 else '')+
                       '</h3><table width="100%" cellspacing="0" cellpadding="4">'+data+'</table>')
    limits = ('DC WIDE: две постоянные опорные точки определяют a и b; третья независимая точка '
              'проверяет результат и не участвует в подгонке. Три точки не подтверждают линейность всего диапазона.'
              if p.mode_id == 'DC_WIDE' else
              'AC: отдельный ноль и известная синусоида задают коэффициенты; контроль использует другую амплитуду '
              'на той же частоте. Постоянная составляющая CH1 не измеряется. Vpp/Vpk/Vrms относятся к синусоиде. '
              'Результат не подтверждает всю полосу или форму импульса; калибровка DC автоматически не переносится.')
    stamp = _row('Критерии заданы, UTC', p.created_at_utc)+_row('Коэффициенты подобраны, UTC', checked.fit_at_utc)
    if checked.control_checked_at_utc:
        stamp += _row('Контроль рассчитан, UTC', checked.control_checked_at_utc)
    # Long free-text source identifiers can legitimately take several lines.
    # Keep the provenance/conclusions section together on a new page then.
    trace_break = ' style="page-break-before: always"' if sum(len(s.source_id) for s in checked.summaries) > 400 else ''
    trace_origin = f'<p class="origin">{_text(origin)}</p>' if trace_break else ''
    return '''<html><head><meta charset="utf-8"/><style>
      body { font-family: "Segoe UI"; font-size: 9pt; color: #172b39; }
      h1 { font-size: 19pt; margin-bottom: 5px; color: #103e51; }
      h2 { font-size: 12pt; margin-top: 12px; margin-bottom: 5px; color: #103e51; }
      h3 { font-size: 10pt; margin-top: 10px; margin-bottom: 4px; }
      table { border-collapse: collapse; } td, th { border: 1px solid #c4d4db; vertical-align: top; }
      th { background-color: #eaf1f4; } p { margin-top: 5px; margin-bottom: 6px; }
      .origin { font-size: 12pt; font-weight: bold; color: #9c3520; }
      .status { background-color: #edf4f6; padding: 8px; }
      .hash { font-family: Consolas; font-size: 8pt; }
      .small { font-size: 8pt; color: #455e6a; }
    </style></head><body>''' + f'''
      <h1>Мотортестер V2 · отчёт калибровки CH1</h1>
      <p class="origin">{_text(origin)}</p>
      <p class="status"><b>{_text(states[checked.state])}</b><br/>{_text(applicability)}</p>
      <p class="small">Напряжение на разъёме CH1 перед делителем, В/мВ. Не напряжение PA0 и не киловольты зажигания.</p>
      <h2>Условия и формат</h2><table width="100%" cellspacing="0" cellpadding="5">{settings}</table>
      <h2>Коэффициенты</h2>
      <p><b>U_CH1 = a × код + b</b><br/>a = {_number(checked.a)} В/код; b = {_number(checked.b)} В.</p>
      <h2>Опорные точки и независимый контроль</h2>
      <table width="100%" cellspacing="0" cellpadding="4"><tr><th>Роль</th><th>Величина</th><th>Опорное, В</th><th>Расчёт, В</th><th>Разность, В</th><th>Исходные коды</th></tr>{''.join(rows)}</table>
      <h2>Критерий контроля</h2>{control}
      <p class="small">Бюджет учитывается моделью программы; это не метрологический сертификат.</p>
      <h2 style="page-break-before: always">Исходные участки и границы отчёта</h2>
      <p class="origin">{_text(origin)}</p>
      <p class="small">Все участки приняты моделью без отметок пропусков и с подтверждением установления.
      Полные коды и признаки качества остаются в .mtcal.json.</p>
      {''.join(sources)}
      <h2{trace_break}>Прослеживаемость</h2>{trace_origin}
      <table width="100%" cellspacing="0" cellpadding="4">{stamp}
      <tr><td><b>SHA-256 канонической записи</b></td><td>{_hash(digest)}</td></tr></table>
      <p class="small">Время подготовки участка и расчёта не является временем физического измерения.
      SHA-256 выявляет изменение данных, но не удостоверяет их физическое происхождение.
      Исходные массивы хранятся в .mtcal.json; PDF не заменяет этот файл.</p>
      <h2>Область результата</h2><p>{_text(limits)}</p>
      <p><b>Отчёт не подтверждает защиту входа, допустимое напряжение, полосу,
      изоляцию или готовность к подключению к автомобилю.</b></p>
      <p class="small">Версия записи: {checked.format_version}; алгоритм: {_text(checked.algorithm)}.
      Исходные отсчёты и запись калибровки не изменены.</p>
      </body></html>'''


def _write_pdf(path, html):
    writer = QtGui.QPdfWriter(str(path))
    writer.setResolution(96)
    writer.setPageSize(QtGui.QPageSize(QtGui.QPageSize.PageSizeId.A4))
    writer.setPageMargins(QtCore.QMarginsF(16, 14, 16, 14), QtGui.QPageLayout.Unit.Millimeter)
    writer.setTitle('Мотортестер V2 - отчёт калибровки CH1')
    writer.setCreator('Мотортестер V2')
    doc = QtGui.QTextDocument()
    doc.setDefaultFont(QtGui.QFont('Segoe UI', 9))
    # Paginate in the PDF device's printable area. Otherwise QTextDocument's
    # unpaginated print path adds another 2 cm inside our explicit margins.
    doc.setDocumentMargin(0)
    doc.setPageSize(QtCore.QSizeF(writer.width(), writer.height()))
    option = doc.defaultTextOption()
    option.setWrapMode(QtGui.QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    doc.setDefaultTextOption(option)
    doc.setHtml(html)
    doc.print_(writer)
    # End the PDF device before the completed file is atomically published.
    del writer


def export_calibration_report(path, record):
    """Create an exclusive PDF. Requires the application's QGuiApplication.

    A same-directory temporary file is fully written and flushed first. The
    hard-link publication is atomic and refuses an existing destination even
    if another process creates it during rendering. Unsupported filesystems
    fail without silently falling back to an overwrite-prone operation.
    """
    if not isinstance(QtCore.QCoreApplication.instance(), QtGui.QGuiApplication):
        raise RuntimeError('Экспорт PDF требует запущенного графического приложения Qt')
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise FileExistsError('Выберите новое имя PDF: существующий файл не заменяется')
    html = _report_html(record)
    fd, temporary = tempfile.mkstemp(prefix='.motortester-report-', suffix='.pdf', dir=target.parent)
    os.close(fd)
    try:
        _write_pdf(temporary, html)
        with open(temporary, 'r+b') as handle:
            if handle.read(5) != b'%PDF-':
                raise OSError('Qt не сформировал PDF')
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size-256))
            if b'%%EOF' not in handle.read():
                raise OSError('PDF не завершён')
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target
