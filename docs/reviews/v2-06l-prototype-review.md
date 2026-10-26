# V2-06l: независимая приёмка изолированного DATA1024 и host logic

26.10.2026. **PASS — 9,6075/10** только для описанного программного результата. Требование V2-STR17 выполнено частично: принят изолированный serializer и поддержка его формата в host. Production runtime, полный firmware image, GUI, Windows-пакет, Flash и устойчивость150k этим заключением **не приняты**.

Критик `/root/stream200_critic` не автор реализации и не оператор платы. База репозитория `bbe297e584d4cb5f22bd090980f721aaa933233a`, функциональная firmware база SD/source `cb4757940b3ee9968f953becfbc3ca8caea102d7`. Проверяемое состояние закреплено двумя manifests, а не предположением о будущем commit.

| Точный вход | SHA256 |
|---|---|
| Prototype freeze | `3b4e3493ffd548d23c00888018e8354e4f65b25547fd9672c67dc561c14fcf0b` |
| Host draft freeze | `aa794fbd7aa0db0ffcf4050551f546b49f75c6bd24ab74404f1a65b8eef0d52a` |
| Serializer C / header | `3e13f073e933ba08c7112ad943a4d14bb0520fef1e2349b569f1e656af87440e` / `330b317fb893ae0385e7a6cc8b1ace1e81c4c9e0e14984a4f8c0b20b1484aeb0` |
| Native result | `9715e3edbc09acd6ba4900dbff208089216262c3e01ebfdf5bf82ca8117a75bc` |
| C→host/file/CSV result | `b35f41d6dcf932f6e8d7e203a1683f2c75975769224ac945f42fdb83e89d6f7c` |
| Прочитанный draft contract | `acd3c8d4171e2cb364d5f4130301da18e0bd7bbdab829629c091340fc0b8a599` |

## Лично проверенные свидетельства

Прочитаны actual C/header, native model/runner, изменённые host codec/endpoint/identity/UI error text, связанные неизменные storage/provenance участки, четыре группы host tests и C→host script. Проверены размеры/SHA 35 уникальных pinned файлов, включая инструменты сборки:180943976 байт, без mismatch. Дополнительно сверены crosscheck inputs/output pins и равенство before/after.

Архивные копии сверены с оригиналами побайтно и по SHA/размеру:31 пара,161238 байт:

- [prototype-01](../verification/v2-batch1024/prototype-01/manifest.json),26 пар/104850 байт, SHA `b130d0a8c3daacb7b3377ca2e55e3e2a0bfc6ac1f2266398bbcb660ed3399e25`;
- [cross-01](../verification/v2-batch1024/cross-01/manifest.json),2 пары/18712 байт, SHA `34d54072e75f59b8f46cec553552337463705c728a1aaab1a783d75e605f8e4d`;
- [cross outputs](../verification/v2-batch1024/cross-01/output-manifest.json),3 пары/37676 байт, SHA `e3a4107f3f44c74f8ea95d4abf25c6d5234ef9139f52cfb1eeb03d9ec762a88e`.

Критик выполнял только чтение и hash/byte-copy аудит через PowerShell/Python в Windows. Не повторял native/unit/crosscheck, не собирал образ и не обращался к COM/SWD. Один ошибочный запрос чтения по предполагаемому имени crosscheck скрипта завершился «файл отсутствует»; затем прочитан правильный путь из manifest. Это не запуск продукта или неудачная проверка реализации.

## Что принимается

Изолированный модуль упаковывает до1024 исходных ADC12 кодов в один wire0.3/config5 DATA с явно сохранёнными10MSB: canonical `(code>>2)<<2`. Count фиксируется до первого отправленного байта; zero-count DATA не создаётся. TX1336 содержит raw с отступом7 и forward in-place COBS, максимум1335 байт с единственным delimiter. CRC/COBS quantum ограничен512 входными байтами; collection —512 отсчётами. Это предел работы вызова, не измеренный WCET.

Collection меняет только work-state и свободную область TX; она не выполняет queue.pop или prefix commit. Candidate canonical CRC считается заранее. Передача выдаёт immutable fragments≤384; known0 не продвигает offset, известный partial учитывает только принятые байты, unknown/over-acceptance отклоняются. Commit требует полный offset, совпадение first/seed и внешний final-guards predicate. Реальный epoch/TIME/lifecycle predicate находится **вне модуля**.

В первоначальном черновике критик нашёл загрязнение общего packed-байта после отклонённого speculative append: значение1023 могло сохраниться при retry с нулём. Автор до первого native исправил маску: сохраняются только уже принадлежащие опубликованному состоянию low bits. Точный witness добавлен в существующую третью группу и прошёл. Для destructive COBS отдельно зафиксировано: прежний cursor нельзя повторять на изменённом storage; после invalidation нужен abort всего кадра. Abort witness также прошёл. Открытых P0/P1 **в изолированной области** не осталось.

Host допускает payload1300/frame1335 только для DATA0.3/config5; старые control/режимы сохраняют512/544. Envelope CRC/header проверяются до фильтра nonce. Чтение за один receive остаётся544; samples не публикуются до полного delimiter и проверок identity/count/padding/index. Discovery15/1024/1300 и selected ACK/CAPS связаны строго; public150 требует mode5, SC/SD отклоняются до START без скрытого fallback. Исторические mode3/4 и их intrinsic markers не переопределены. Mode5 marker хранит10-bit quantization независимо от companion.

## Достаточные адресные проверки

Авторский native run — один, первая попытка PASS. Actual serializer проверен независимыми COBS/CRC/padding oracle: полный1024, tails1/2/3/127/128/129/1023, quantum1/17/128/512, worst frame1335, canaries, известные partial/zero/unknown, отказ final predicate, invalid ADC до masking, gap, quantum513, пустой кадр, speculative shared-byte retry и destructive abort. Очередь/ADC/USB callbacks здесь не исполняются; synthetic END сделан существующим generic C encoder.

Отдельный ARM object Cortex-M3 прошёл строгую компиляцию: text1208/data0/bss0; state32; `.su` статические, максимум36 байт отдельной функции. Это **не linked firmware и не общий stack bound**. Расчёт `19564+792+32=20388` оставляет92 байта при прежнем резерве8192, но полный linker map/stack после интеграции ещё обязателен. Отсутствие linked image не является пробелом приёмки этого изолированного узла.

Четыре host группы — одна попытка PASS за0,200 с: независимые packing vectors/large-envelope negatives; discovery/selected ACK/CAPS/legacy; no-early-publish/cut-frame/short-terminal; intrinsic journal без companion, CSV и прежние схемы. Полный legacy suite не запускался.

Actual C fixture1614 байт содержит DATA1024+DATA129+synthetic END, frame sizes1332/212/70; nonce503/gen3/config5, sequences4/5/6. Host сверил все1153 canonical кода с независимой формулой: raw SHA `1f5c9f712929bceae1a09adb39de4cec43d31ef4abe2d99cc8b63531af417b7d`, END CRC1967919874. Direct journal затем fresh Open без companion вернул те же raw и unknown produced tail. В этом небольшом crosscheck проверены **все** CSV индексы, коды и времена `i/150000`; шаг20/3 мкс номинальный, не калиброванный такт. Build label `f0102401` синтетический, не получен от платы.

Команды авторских проверок закреплены в freeze/result: `python -I -B tests/v2-stream-firmware/batch1024_check.py --output <новая папка build>`; точная unittest команда — в host draft manifest; crosscheck — `python -I -B build/v6l-host-crosscheck.py`. Они приведены для воспроизведения в новой выходной папке/с сохранением исходных свидетельств, а не как указание повторить сейчас.

## Следующая отдельная область

До production необходимо конкретно реализовать и проверить queue→staging ownership, Stop/HELLO/Abort/fault на стадиях COLLECT/CRC/COBS/partial send, актуальность ticket/epoch и итогового commit, порядок обслуживания ADC, полный SRAM/stack. Пустая очередь не означает отсутствие неотправленного staging. Invalidation destructive stage не может откатить один state. Изолированный predicate не заменяет actual runtime guards.

Четырёхкратное снижение DATA frames/s даёт около10% уменьшения worst wire bytes/s, а не четырёхкратное ускорение USB. Единственный TX занят encoding/send, очередь прежняя; half-DMA deadline не увеличивается до длительности пакета1024. Скорость и устойчивость остаются будущим физическим свидетельством. K2 сохраняет FAIL после20,602 с, установленная SD не изменена; 50/100 на SD остаются NOT_RUN. GUI helper mode4, новый Windows-пакет и новая прошивка не принимались.

| Критерий | Балл | Основание |
|---|---:|---|
| C1,30% | 9,6 | Формат, count, canonical CRC, неизменные старые режимы и точная host identity соответствуют ограниченному контракту. |
| C2,20% | 9,5 | Проверены bounded stages, canaries/partials/abort и найденный shared-byte дефект; требования к caller явно отделены. |
| C3,25% | 9,7 | Один actual C run, ARM object, четыре host группы и C→file/CSV; ограничения не подменены аппаратным успехом. |
| C4,15% | 9,55 | Малый модуль без дополнительного массива; смысл владения/необратимых шагов описан, integration остаётся отдельной задачей. |
| C5,10% | 9,7 | Exact manifests, исходники проверок, commands, архивы и сохранённые output pins проверены лично. |

Итог без округления: **9,6075/10, PASS**. Это основание продолжить отдельное проектирование интеграции; не разрешение Flash и не завершение пользовательской цели stable150k.
