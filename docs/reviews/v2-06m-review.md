# V2-06m: локальное состояние serializer — PASS

**PASS, 9,625/10**, 27.10.2026. Независимый критик `stream200_critic`, не автор
реализации. Область — одна программная оптимизация `mt_batch1024_step`, её
подключение к actual core и точный ARM-образ V2SF. Не Flash-допуск и не
подтверждение устойчивых 150k. Отказ L2 и NOT_RUN 50/100 на SE сохраняются.

## Точная область

Source `bad4bfb4c39a0a2c5510b6305d033bd64eb48e03`, рабочая база
`878ee6fe3833269cb4aa9dfdec67173a7f19605b`; сравниваемая функциональная SE —
`67b57bfaabbf7cf9290225058f2e8bca3b0964d8`.
Требования V2-STR14/V2-STR17, [контракт M](../streaming-serializer-local.md),
[DATA1024](../streaming-batch1024.md), [quality-gate](../quality-gate.md).
Полные pins и рубрика — [critic-source.json](../verification/v2-serializer-local/critic-source.json).

| Артефакт | SHA256 |
|---|---|
| Freeze | `badbd5cead757e325b0597df788b7d4f91034fe25a50e04c906f0fe7a64c01c9` |
| Production C | `d0d19b559fdf7558827d0eda1c2de33dbfc04dab9bfa0235b6b3a237ff4f37f7` |
| V2SF BIN, 42480 байт | `580cfaa40fd782a96d798285f3df7c9a3e2f2f0e126ec61023a89266207be29e` |
| ELF | `73150965208b9c7c9c9790939601258e3ede8a63c207b2ef0ea11b66ca01cc75` |
| Native result | `564d588a289a55f03276de76a8dc9aa1d449f751bc3693995921859c91f3dc8c` |
| Static bound | `055fd094f81649f754a2f1b4e75f4e23f4b233a56fb3f10f0561e984fa9c520c` |

Лично сверены 711 уникальных pinned файлов, 229740473 байта, включая554
recipe inputs,116 dependencies,117 native inputs и32 ARM objects.
В [production-01](../verification/v2-serializer-local/production-01/manifest.json)
побайтно совпали518 пар/4228927 байт; SHA manifest
`105655d6bf471ec4f26d375cc5273545a5ff8f334a3607c8c9b90227ca908027`.
Это чтение сохранённых файлов, не повторный запуск проверок продукта.

## Разбор изменения

Меняется только `mt_batch1024_step`: read/write/mark/code/raw_length и
rolling frame CRC живут в локальных переменных одного синхронного вызова.
State и storage по прежнему API раздельны; `restrict` не добавлен.
Проверены все выходы: CRC исчерпывает только свою фазу и возвращает управление;
COBS сохраняет code254→255 и uint16 wrap65535→0. При defensive ошибке уже
потреблённый read и предыдущие изменения write/mark/code публикуются перед
`-1`; destructive storage не скрывается откатом cursor. Bounds перед записью,
delimiter, length/offset и budget1…512 сохраняются.

Остальные семь функций serializer точно совпали с SE; API token-identical.
Лично побайтно сверены49 неизменных patched файлов: core, очередь, runtime,
TIME/ADC/DMA/USB и прежние ownership/final-TIME/Stop/HELLO/epoch границы.
Config меняет только firmware build и USB product на V2SF/`0x56325346`;
recipe явно выбирает новый production C, прежний SE/prototype сохранён.
Host, формат данных, размеры очереди/FIFO и расписание не оптимизировались.

Прочитаны actual model и runner. Первый сохранённый combined native01 — PASS:
1546 допустимых кадров,60061 step,86264 API-сравнения return/state32/всего
storage1336/защитных полей. Есть budget1…512, нули/ненулевые/смешанные данные,
хвосты, границы CRC/COBS, code255/wrap, безопасно адресуемые ошибочные состояния
и consumed-cursor/partial-store error. Модель линкует обе actual реализации
SE/SF под разными именами; алгоритм внутри oracle не переписан.

Четыре прежние actual-core группы исполняют новый модуль через реальные
prepare→step_prepared: staged/committed ownership, Stop/хвосты, HELLO/epoch,
zero/partial/unknown и последний TIME после необратимой записи.
Clock/IO/Stop — логические seams; CRC/COBS lifecycle частично реконструируется,
это не полный runtime или USB-периферия. Native io build оставлен SE для
сравнения fixture; SF identity подтверждается отдельно ARM config.
Actual-core C1153 fixture1614 байт побайтно совпал с SE, SHA
`cf62a2d6153aa7f59e4c886e9f487e950381ac6d6cbafa1ca285d19f22333013`.
Поэтому прежние host/GUI/Windows-проверки не повторялись.

## ARM и пределы вывода

ARM01 и native01 прошли с первого запуска; сохранённые116 ARM и7 native
команд имеют exit0, input drift отсутствует. Критик лично прочитал изменённый
ARM step: повторяющийся CRC-путь11 инструкций против16 у SE, обычный COBS
nonzero21 против29, zero19 против28; обращений к state внутри этих циклов0.
Входы/выходы, special branches, IRQ и память вне state не входят в этот счёт.
Это **не** измерение времени кадра, CPU-доли или WCET.

Точный образ: text42352/data128/bss12068. С резервом стека8192:
20388 из20480 байт,92 байта сверх резерва; state32/TX1336 прежние.
Собственный frame step вырос24→32 байта; новый полный conditional bound
по exact ELF заново получен6156,6160 с выравниванием. Прежняя цифра не просто
перенесена. Условия: pinned callbacks, cold reset/Thread MSP/STKALIGN,
USB HP/LP одинакового приоритета без взаимного вложения, штатные exception
пути, отсутствие повреждения SRAM/чужого DMA/отладочных прерываний.
Это не физический high-water. Legacy136 остаётся по`0x20002F1C`, один attempt
на boot; отдельный512-byte профиль отключён.

Шесть внутренних quantum по-прежнему выполняются в одном prepare.
Сокращение операций не доказывает устранение длинного burst или причины L2.
Новый положительный физический результат отсутствует; старый P1-L2-01
остаётся открытым вне данного программного scope. Других P0/P1 в M не найдено.

| Критерий | Вес | Балл | Основание |
|---|---:|---:|---|
| C1 | 0,30 | 9,65 | Exact state/bytes/return и неизменные wire/ownership границы подтверждены. |
| C2 | 0,20 | 9,60 | Ошибочные выходы, финальный commit и ресурсы сохранены; bounds условные, физический запас не заявлен. |
| C3 | 0,25 | 9,65 | Один differential/actual-core и точный ARM; необходимые seams и пределы явно указаны. |
| C4 | 0,15 | 9,55 | Узкое изменение, явный общий error-publication path; документация отделяет цикл от производительности прибора. |
| C5 | 0,10 | 9,65 | Source/freeze/recipe/команды и архив совпадают, SE и отрицательные данные сохранены. |

Итог **9,625**, выше9,5, без открытых P0/P1 внутри программной области M.
Критик выполнял только чтение кода/assembly/receipts и byte/hash-сверки в
Windows PowerShell с локальным Python; тесты, COM/SWD не запускал.
Приёмка Windows-пакета L остаётся прежней; новый пакет не создавался.
Следующий аппаратный шаг требует нового exact SF-плана и независимого допуска.
