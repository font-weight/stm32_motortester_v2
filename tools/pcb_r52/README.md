# Утилиты платы R5.2

Для открытия и ручного редактирования платы эти утилиты **не нужны**. Откройте
`hardware/v2-input/r52-lut-20261102/analog-input-r52.kicad_pro` в KiCad.

**`build_board.py` перезаписывает PCB, схему с назначениями посадочных мест,
проект, правила и локальную библиотеку R5.2. При генерации меняются UUID объектов;
это не побайтовое воспроизведение сохранённой платы. Ручные правки CAD будут
потеряны. Перед намеренной повторной генерацией сохраните их отдельной копией или
коммитом.**

## Входы и результаты

- `data/placement.json` — изменения размещения относительно координат в генераторе;
  `data/jumpers.json` — физические изолированные провода; `data/routes.json` —
  сохранённые маршруты B.Cu. W1/W2 обязательны, W3 оставлена как необязательный
  резерв AGND в данном варианте геометрии.
- Электрические связи и значения берутся из
  `docs/design/analog-r5-1/kicad/analog-input-r5.net.xml`, схема — из соседнего
  `analog-input-r5.kicad_sch`. Библиотека символов и `sym-lib-table` читаются
  непосредственно из исходного `Analog_LUT_R5_1_2026-10-29_REVIEW.zip` в
  `docs/design/analog-r5-1/`; прежняя временная распаковка не требуется.
- `router-input.json`, `placement-used.json`, `parity.json` и каталог
  `ground-analysis/` создаются в `build/analog-r52-pcb/`. Путь вычисляется от
  корня репозитория, а не от текущего каталога запуска.
- `router.py` использует стандартную библиотеку Python. Остальные скрипты
  запускаются интерпретатором, поставляемым с **KiCad 10.0.6**:
  `D:/Programs/bin/python.exe`. Анализ полигонов запускает отдельный
  `.venv/Scripts/python.exe` (в рабочей среде Python 3.14) и читает Shapely 2.1.2
  и NumPy 2.5.4 из `build/analog-r52-pcb/deps/`.

Команды ниже — PowerShell из корня репозитория. При иной установке KiCad
поправьте пути к Python/CLI и константу `CLI` в `check_parity.py`.

## Проверка существующей сохранённой платы

При отсутствии зависимостей анализа установите их в служебный каталог:

```powershell
& '.venv/Scripts/python.exe' -m pip install --target 'build/analog-r52-pcb/deps' 'shapely==2.1.2' 'numpy==2.5.4'
```

Проверка соответствия исходной схемы, текущей схемы и назначений площадок PCB:

```powershell
& 'D:/Programs/bin/python.exe' 'tools/pcb_r52/check_parity.py'
```

DRC с проверкой связи PCB и схемы; эта команда не сохраняет изменения платы:

```powershell
New-Item -ItemType Directory -Force -Path 'build/analog-r52-pcb' | Out-Null
& 'D:/Programs/bin/kicad-cli.exe' pcb drc --schematic-parity --format json --exit-code-violations --output 'build/analog-r52-pcb/routed-drc.json' 'hardware/v2-input/r52-lut-20261102/analog-input-r52.kicad_pcb'
```

Геометрический анализ уже **заполненной и сохранённой** земли:

```powershell
& 'D:/Programs/bin/python.exe' 'tools/pcb_r52/ground_analysis.py' --final-check
```

Он создаёт снимок платы, исходные контуры меди, `final-ground-graph.json/.md` и
`return-path.svg`, проверяя неизменность исходного PCB при чтении. CAD не
перезаписывается. Поиск по сетке дополнен фактическими концами дорожек;
отдельно измеряются осевые длины ветвей C6 → U1. Сужение меди на 0,499 мм —
геометрическая проверка связности около ширины 1 мм, с указанными в отчёте
ограничениями по отверстиям и допускам ЛУТ. Ни DRC, ни эта оценка не подтверждают
физическую работоспособность, подавление помех, защиту или разрешение на изготовление.

## Намеренная повторная генерация

После сохранения ручных правок вне целевого каталога:

```powershell
& 'D:/Programs/bin/python.exe' 'tools/pcb_r52/build_board.py' --zone
```

Генератор загружает сохранённые маршруты из `data/routes.json`; сам поиск
маршрутов здесь не запускается. Для заполнения и **сохранения** новой заливки,
затем проверки используйте реальные параметры CLI KiCad 10.0.6:

```powershell
& 'D:/Programs/bin/kicad-cli.exe' pcb drc --refill-zones --save-board --schematic-parity --format json --exit-code-violations --output 'build/analog-r52-pcb/routed-drc.json' 'hardware/v2-input/r52-lut-20261102/analog-input-r52.kicad_pcb'
```

После изменения размещения можно отдельно построить кандидат маршрутов:

```powershell
& '.venv/Scripts/python.exe' 'tools/pcb_r52/router.py' 'build/analog-r52-pcb/router-input.json' 'build/analog-r52-pcb/routes-proposed.json'
```

Кандидат сам не попадает в CAD. Его перенос в `data/routes.json`, новая генерация
и повторная проверка — осознанная отдельная итерация. Заявленные
`connected_pad_groups` означают реально предусмотренные дорожки/провода;
алгоритм не создаёт для них медь автоматически. Значения `failed` и длины
маршрутов — диагностические сведения алгоритма, а не замена KiCad DRC.

## Печатный комплект

`export_prints.py` читает сохранённый PCB и перезаписывает только каталог
`hardware/v2-input/r52-lut-20261102/print/`. Требуются ReportLab, pypdf,
pdfplumber и Poppler; пути `CLI`, `KIPY`, `POPPLER` указаны в начале скрипта.
В рабочей Windows-среде команда:

```powershell
& "$env:USERPROFILE/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe" 'tools/pcb_r52/export_prints.py'
```

Экспорт сохраняет масштаб 1:1; зеркален только лист осмотра снизу.
После любого изменения CAD повторно проверить соответствие PDF и PCB,
визуально просмотреть страницы и обновить свидетельства/независимое ревью.
Автоматическая проверка размеров не заменяет просмотр текста и обозначений.

Фактические проверки выпуска и границы готовности находятся в
`docs/progress.md` и отчёте независимого критика.
