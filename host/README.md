# Приложение Мотортестера V2

Текущее приложение V2-21 — один экран подключения, графика, записи и управления
CH1; отдельным остаётся мастер калибровки. ДЕМО доступно только в «Сервис».
Пользовательская инструкция — [корневой README](../README.md) и
[работа в главном окне](../docs/unified-ui.md). Здесь собраны запуск и разработка.
Фактически выполненные проверки находятся в [прогрессе](../docs/progress.md),
а не в командах-примерах ниже.

## Окружение и первый запуск

Для текущего закреплённого набора используйте Windows x64 и обычный
**CPython 3.14.7 x64**. Free-threaded Python и 32-битное окружение не подходят
для Windows hash-lock. Команды выполняются из корня репозитория, где лежит `run_v2.cmd`:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r host\requirements-gui.txt
.\run_v2.cmd
```

`py -3.14 --version` позволяет проверить выбранную версию до создания окружения.
Активация `.venv` и изменение политики запуска PowerShell не нужны.
Если `py` не найден, установите Python с launcher или укажите полный путь
к нужному `python.exe` вместо `py -3.14`.

[requirements-gui.txt](requirements-gui.txt) фиксирует шесть зависимостей
выполнения: PySide6-Essentials, shiboken6, pyqtgraph, NumPy, colorama и pyserial.
Этот файл фиксирует версии, но не хеши файлов поставки. Полный
[requirements-win-x64.lock](packaging/v2/requirements-win-x64.lock) содержит
хеши для CPython 3.14.7 / Windows x64 и дополнительные инструменты сборки.
При необходимости установки именно полного набора вместо обычной команды `pip install`:

```powershell
.\.venv\Scripts\python.exe -m pip install --require-hashes --only-binary=:all: -r host\packaging\v2\requirements-win-x64.lock
```

Для обычного использования сборщик PyInstaller не требуется.

## Команды запуска

Из корня репозитория:

```powershell
.\run_v2.cmd
```

Или непосредственно Python:

```powershell
$env:PYTHONPATH = 'host'
.\.venv\Scripts\python.exe -m motortester.v2
```

Из папки `host`:

```powershell
..\.venv\Scripts\python.exe -m motortester.v2
```

Точка входа `motortester.v2` создаёт `unified_gui.MainWindow`. Старые окна
и исходный `motortester.gui` сохранены для совместимости и не являются текущим запуском.
При старте нет автоматического подключения или генерации сигнала.

Для отдельного файла настроек и снимка начального окна, без платы:

```powershell
.\run_v2.cmd --settings ..\build\readme-example\settings.ini --screenshot ..\build\readme-example\start.png
```

Используйте новый путь снимка. Это только изображение состояния интерфейса,
не проверка потока и не подтверждение физических измерений.

## Основные данные и компоненты

- `motortester/v2/unified_gui.py` — главный экран и общие крутилки;
  `unified_panel.py` / `stream_ui.py` — подключение, поток и просмотр.
- `inline_input.py`, `analog_profile.py`, `calibration_ui.py` — ручной выбор
  физического режима, единый пересчёт `U_CH1 = a × code + b`, мастер DC / AC.
- `segment_measurements.py`, `event_frequency.py`, `ringdown.py` — анализ
  исходных отсчётов; файлы с окончанием `_ui.py` отвечают за отображение.
- `storage.py`, потоковые модели и reader — исходные коды, время, разрывы,
  происхождение и снимок профиля. Просмотр не назначает файлу профиль новой платы.

`.mtstream` хранится с соседним `.mtstream.v2.json`; `.mtshot` содержит отдельный
захват. Прежние `.mtv2` / `.mtcap` открываются встроенным `LegacyRecordingView`
с их временной основой и профилем. Они не превращаются в новый поток событий.
Полная калибровка — `.mtcal.json`; PDF является читаемым отчётом и не заменяет raw.

При неизвестном входе показываются коды АЦП. В режиме 150 тыс. отсчётов/с
сохраняются 10 старших бит 12-битного АЦП; в модели они представлены на канонической
12-битной шкале с шагом 4. Дополнительное умножение при анализе недопустимо.
Режимы прошивки и совместимость описаны в
[selectable-profiles](../docs/streaming-selectable-profiles.md) и
[batch1024](../docs/streaming-batch1024.md). Приложение не прошивает плату.

## Адресные проверки изменений

Выбирайте проверку затронутого поведения; весь исторический набор для каждой
правки не требуется. Например, для чистой модели затухания из корня:

```powershell
$env:PYTHONPATH = 'host'
.\.venv\Scripts\python.exe -m unittest discover -s host\tests -p test_v2_ringdown.py
```

Проверка текущего сценария V2-21 в обычном окне Qt на искусственных данных:

```powershell
$env:PYTHONPATH = 'host'
.\.venv\Scripts\python.exe -m motortester.v2.ringdown_smoke build\ringdown-native-new
```

Выходной каталог должен быть новым. Сценарий создаёт учебные записи, открывает
главное окно, сохраняет снимки и `result.json`; COM и прошивку он не использует.
Он не является физической проверкой катушки, аналогового тракта или калибровки.
Для ручного знакомства используйте **«Сервис → ДЕМО для проверки → Затухающие
колебания · учебная запись»** и [инструкцию анализа](../docs/ringdown.md).

## Windows-пакет: отдельная задача

Публикация исходников не означает выпуска готового EXE. Каталог `build/`
с локальными пакетами и окружениями не входит в обычный клон.

`packaging/v2/build_windows.py` — базовый рецепт из чистого Git-состояния
для CPython 3.14.7 x64. Он устанавливает hash-lock, собирает PyInstaller-пакет
и сохраняет сопроводительные материалы. Его варианты проверки относятся
к прежним этапам и не заменяют сценарий V2-21.

`tools/build_calibration_candidate.py` от корня — текущий локальный сборщик
кандидата. Он **зависит от уже существующих** `build/v18w2/venv` и
`build/v18w2/dist/MotortesterV2/licenses`. Поэтому следующая команда применима
только в подготовленном рабочем окружении, а не сразу после чистого клонирования:

```powershell
.\.venv\Scripts\python.exe tools\build_calibration_candidate.py --verification ringdown --output build\ringdown-package-new
```

Нужен новый выходной каталог. Сборщик сохраняет снимок исходников и manifest,
а затем запускает упакованный сценарий **`--verify-ringdown`**. Этот параметр
обрабатывает `packaging/v2/launcher.py`; обычный `run_v2.cmd` его не принимает.
`--verify-event-frequency` относится к отдельному предыдущему сценарию.

Перед распространением бинарников требуется закрыть ручные пункты
[LICENSE-REVIEW.md](packaging/LICENSE-REVIEW.md). Сохранённые уведомления
не означают завершённой проверки всех Qt-компонентов и соответствующих исходников.
[MIT-область проекта](docs/project-license.md) ограничена явным перечнем;
`host/motortester/v2/` не получает MIT автоматически из `host/LICENSE`.

## Продолжение разработки

Прочитайте [AGENTS.md](../AGENTS.md), [task.md](../task.md),
[requirements.md](../requirements.md), [решения](../docs/decisions.md),
[прогресс](../docs/progress.md) и [порядок приёмки](../docs/quality-gate.md).
При параллельной работе используйте [координацию](../docs/coordination.md).
Новый интерфейс, искусственные данные, Windows-пакет и физический опыт имеют
раздельные свидетельства. Текущие ограничения и следующий шаг фиксируются
в канонических документах; прежние README доступны в истории Git.
