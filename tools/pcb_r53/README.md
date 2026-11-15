# Утилиты компактной платы R5.3

Для открытия платы утилиты не нужны: открыть
`hardware/v2-input/r53-compact-20261102/analog-input-r53.kicad_pro` в KiCad 10.
Прежняя R5.2 остаётся отдельным проектом.

`build_board.py` **перезаписывает** CAD и локальные библиотеки R5.3. Сначала
сохранить ручные изменения вне этого каталога или коммитом. Генерация создаёт
новые UUID; это воспроизведение геометрии, не побайтовой копии. Готовая плата
уже сохранена с заливкой, и для просмотра её не нужно генерировать заново.

Входы: `data/placement.json`, `data/routes.json`, `data/jumpers.json`.
Электрические соединения/номиналы читаются из неизменённого R5.1 XML в
`docs/design/analog-r5-1/kicad`; символы — непосредственно из исходного ZIP.
В JSON перемычек заданы настоящие пути и стороны проводов. Дубли номеров
площадок означают обязательный физический провод, а не готовую медную связь.

Команды ниже — PowerShell из корня репозитория. Рабочая среда: KiCad 10.0.6
(`D:/Programs/bin/python.exe`, `D:/Programs/bin/kicad-cli.exe`), Python проекта
`.venv/Scripts/python.exe`. Пути CLI/Python/Poppler в скриптах при другой
установке нужно изменить. Временные результаты попадают в
`build/analog-r53-compact/`.

## Проверка сохранённой платы

```powershell
& 'D:/Programs/bin/python.exe' 'tools/pcb_r53/check_parity.py'
& 'D:/Programs/bin/kicad-cli.exe' pcb drc --schematic-parity --format json --exit-code-violations --output 'build/analog-r53-compact/final-drc.json' 'hardware/v2-input/r53-compact-20261102/analog-input-r53.kicad_pcb'
& 'D:/Programs/bin/python.exe' 'tools/pcb_r53/metrics.py'
```

Для анализа земли нужны Shapely 2.1.2 и NumPy 2.5.4 в окружении Python
проекта. Можно установить их изолированно:

```powershell
& '.venv/Scripts/python.exe' -m pip install --target 'build/analog-r53-compact/deps' 'shapely==2.1.2' 'numpy==2.5.4'
& 'D:/Programs/bin/python.exe' 'tools/pcb_r53/ground_analysis.py' --final-check
& '.venv/Scripts/python.exe' 'tools/pcb_r53/check_s1_distance.py'
```

В этой рабочей среде также поддержан уже имеющийся каталог зависимостей
`build/analog-r52-pcb/deps`. Проверка читает заполненную медь и реальные
AGND-провода; длины ломаных проводов взяты по Fab-сегментам. Сужение меди
на 0,499 мм проверяет сохранение связности около ширины 1 мм, но не учитывает
сверловку колец, погрешности травления и распределение высокочастотного тока.
Два пути C6 измеряются отдельно по фактическим дорожкам без обхода по заливке.
`check_s1_distance.py` использует этот снимок меди и проверяет расстояния
от подключённых площадок S1 до всей меди IN_A/обратных связей и тела U1.
Физический тумблер, форма припоя и внешние провода проверяются отдельно.

## Намеренная повторная генерация

```powershell
& 'D:/Programs/bin/python.exe' 'tools/pcb_r53/build_board.py' --zone
& 'D:/Programs/bin/python.exe' 'tools/pcb_r53/finish_labels.py'
& 'D:/Programs/bin/kicad-cli.exe' pcb drc --refill-zones --save-board --schematic-parity --format json --exit-code-violations --output 'build/analog-r53-compact/final-drc.json' 'hardware/v2-input/r53-compact-20261102/analog-input-r53.kicad_pcb'
```

После генерации повторить проверки выше и печать. `adjust_local_keepout.py`
сохранён как точечная миграция промежуточного кандидата; актуальный генератор
уже содержит исправленный локальный контур, отдельно запускать миграцию
при обычной генерации не требуется.

Для новых вариантов можно запустить `router.py` на созданном
`build/analog-r53-compact/router-input.json`. Кандидат маршрутов не подменяет
готовую плату автоматически. DRC остаётся обязательным: флаг `failed: []`
не доказывает правильность итоговой меди, посадок или земли.

## Печатные карты

`export_prints.py` использует ReportLab, pypdf, pdfplumber и Poppler из
установленного окружения Codex. Он читает PCB и обновляет только `print/`:

```powershell
& "$env:USERPROFILE/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe" 'tools/pcb_r53/export_prints.py'
& '.venv/Scripts/python.exe' 'tools/pcb_r53/render_overview.py'
```

Второй скрипт использует PySide6 и создаёт иллюстрации, не шаблоны травления.
PDF содержит четыре страницы в масштабе 1:1. Только страница 1 предназначена
для переноса тонера; страница 2 зеркальная для осмотра/нижних проводов.
После изменения CAD обязательно заново просмотреть все страницы, проверить
соответствие подписей и обновить свидетельства с независимым ревью.
Результаты конкретного выпуска находятся в `docs/progress.md`, а не здесь.
