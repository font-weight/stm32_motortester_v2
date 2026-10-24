# V2-06i — независимое ревью выбираемых профилей

**PASS 9,60/10 — программная логика и точный ARM-кандидат. PASS 9,59/10 — Windows-пакет в ограниченном сценарии новых профилей.** Дата: 24.10.2026. Критик `stream200_critic` не писал реализацию, модели, сборщик или его исправление. Это два программных уровня по [quality-gate](../quality-gate.md), **не допуск Flash и не подтверждение физических режимов V2SC**. COM/SWD критик не использовал, новых сборок и динамических прогонов не выполнял.

## Точное состояние

Проверены V2-STR14/15, task V2-06i и принятый [контракт](../streaming-selectable-profiles.md), SHA256 `eb84ef5fea2c36da9de397f7a17a0c4d3671a4da8748834a4b09b5b6e14b62f1`.
Source приложения/прошивки/ZIP — `310d53b10c79a48ddc45357ff65d88c686aef883`, base — `c3407c1bbc2bd152a2e9ae193eb0628aa421ec0a` (принятый H2/SB).
Отдельное исправление **внешнего проверяющего скрипта**, без изменения приложения/прошивки/ZIP: `03eb4bb5ff3d4f359a5e41c61d563e6f6e10cfe3`.

| Артефакт | SHA256 |
|---|---|
| Firmware freeze `build/v6i-freeze.json` | `ae1d2ab6b741cbfd76baf7557c656477c7c7c17646ea143bdc8a189c6681c7cc` |
| Host freeze `build/v6i-host-freeze.json` | `39825f1561beb32a6612f6c9534de93464afd448de70bc3cd37a7c8b23dc0231` |
| V2SC/build0x56325343, BIN38188 байт | `a36f72a772c03c5cbfd85767e5f07f0abc3ad2f2ffd7d1ee1c43143d20ca1c90` |
| ELF | `c050b68d4ffff5d30ba741d7d38f23401f584e26e2500078346aac99e0b8e308` |
| ZIP61194649 байт | `e6b40293e25eb0d27c008ff5d63337a678d8a5c963ac8124f34b5782ed8cb47e` |
| `source.zip` | `c85a71a6e3137602f4403f2c082efc417f57d68060f72fdc9c872b84f7b79a7f` |
| GUI EXE | `0a4dc48d1515c3136590f216ff309ba22d08c079dd23d8afd1ff7418ad266df9` |

Побайтно проверены архивы [firmware, 32 пары](../verification/v2-selectable-profiles/firmware-01/manifest.json), [host, 10 пар](../verification/v2-selectable-profiles/host-01/manifest.json), [source GUI, 9 пар](../verification/v2-selectable-profiles/gui-01/manifest.json), [пакет, 16 пар](../verification/v2-selectable-profiles/package-01/manifest.json). Последний manifest имеет SHA256 `6f518b019acfefc0084cbdfb5739bdb43ab5f0e40fabb6b14f775d61a915da43`. Точные хеши всех четырёх manifest и результаты личной сверки — в [critic-source-checks.json](../verification/v2-selectable-profiles/critic-source-checks.json).

## Программная логика и ARM

Лично прочитаны девять firmware overlays, итоговые core/queue/wire/driver/ADC-adapter, таблица профилей, native-модель и её runner; на стороне host — wire/endpoint, identity, journal/provenance, bridge/controller, отображение, новые проверки и packaging. Для изменённых путей проверены следующие свойства.

- Discovery wire0.2 не запускает захват; новый сеанс wire0.3 получает свежую nonce и выбранный mode. Current/pending/tx mode и revision участвуют в ticket и HELLO_ACK commit. Частично отправленный старый ACK не подтверждает новый mode. Bounded envelope/CRC/header проверяются до фильтра stale nonce; неверная revision текущего сеанса закрывает его с ошибкой.
- Оба ADC ingress, включая хвост Stop, сначала проверяют допустимый ADC12-код, затем для150k получают `code & 4092`. Packed10 передаёт старшие биты, END CRC считается по каноническим u16le. Кратность4, диапазон0…4092 и padding проверяются; неизвестные исходные два LSB не восстанавливаются. `U_CH1=a*code+b` остаётся в прежнем кодовом домене, края квантизации не названы доказанным насыщением ADC.
- Descriptor задаёт50/100/150k, PSC/ARR71/19,71/9,47/9. Период150k —20/3 мкс; deadline3413 и CEN5/6 не подменяют его округлённым периодом. Смена descriptor запрещена при работающем/владеющем периферией драйвере. H runtime, DCD и TIME сохранены.
- Journal magic3/4 хранит intrinsic identity/quantization; legacy1/2 читает строго прежние поля. Открытие без companion сохраняет10-битную отметку. Каждый восстанавливаемый блок проходит проверку кодов/identity; CSV считает время через индекс/Fs. UI выбирает режим до Connect и блокирует выбор при владении сеансом. Неизвестный хвост и ненастроенный физический вход остаются явными.

Лично сверены91 firmware freeze pins,18 host source pins и8 host evidence pins. Все38 неизменных пар исходников H→SC совпали побайтно. Нормализованные доказательства core guard/step_tx/completed и ADC start/read_block прочитаны: они удаляют только перечисленные mode/revision/descriptor изменения, а не произвольные различия. Новые ветви проверены отдельно чтением. Это не повтор физической периферии.

Авторские **ARM01/static и native01 — единственные и PASS**. RAM: data128+bss11228+stack reserve8192 =19548/20480, запас932 байта. Условная граница стека6068/aligned6072 ниже резерва; это не измеренный стек и не WCET. Legacy136 находится по **0x20002BD4**, active512 profile выключен. Подготовительный generator ранее остановился до компиляции на неоднозначной замене; это сохранено и не выдано за ARM-отказ.

Native использует actual core/queue/wire/driver с явно логическими callback/clock/register seams. Три группы покрывают discovery/nonce/revision/partial ACK/ticket, все три DATA-профиля с128 и хвостами1/2/3/CRC/невалидным ADC, а также таймеры, rational20/3,150k deadline3412/3413 и CEN5/6/wrap. Неизменённые H/DCD/guard-пути не перепрогонялись широкой suite. Result SHA256 `9f68c319d18724696208ffc721e206b1a9cfd96da5bc0c9d4cb98f6ea5569f05`.

Финальные четыре host-группы (`build/v6i-host-unit-03/tests.log`, PASS0,048с) проверяют независимые literal packed vectors/padding, handshake/legacy/mismatch/revision, intrinsic journal/CSV/codes и независимые старые header/hashchain fixtures. Дополнительно Python прочитал actual-C DATA128+tail3/END: все131 канонический код и CRC совпали. Один offline Open исторического H2 magic2/companion2 подтвердил3001803 отсчёта; SHA оригинального файла и companion до/после совпали. Это свидетельства авторских прогонов, лично прочитанные и привязанные хешами; критик их повторно не запускал.

## Windows-пакет

Одна сборка из310d53b закончилась упаковкой, но первоначальная команда завершилась exit1 **до первого frozen-вызова**: внешний helper импортировал одноимённый старый `host/packaging/build_windows.py`. Исправление03eb4bb передаёт пять функций явно. Лично прочитаны этот малый diff и `build/v6i-resume-package.py`: явная загрузка правильных модулей, проверка исходного manifest/ZIP/деревьев, отсутствие прежнего frozen-output, один вызов проверки, контроль неизменности после него. Пересборки EXE/ZIP не было. [Первоначальный traceback](../verification/v2-selectable-profiles/package-01/receipts/initial-builder-error.txt) сохранён из захваченного tool output; его происхождение и связь с неизменным manifest указаны в [дополнении](../verification/v2-selectable-profiles/package-01/failure-supplement.json).

Первый/единственный frozen flow прошёл за10,946с: Windows10.0.19045, Qt native `windows`, `win32`, другой рабочий каталог, перенос в путь с кириллицей, PATH толькоSystem32. Команда — перенесённый `MotortesterV2.exe --verify-profiles <frozen-profiles>`; исходная команда сборки и точное продолжение закреплены в build.log/resume receipts. Source GUI01 ранее также прошёл; после него изменились nonce/revision, platform field и две фразы, поэтому финальные PNG и receipt проверены отдельно.

Шесть flow-checks PASS, `owners_closed=true`, COMcalls0, errors/callback_errors пусты. Синтетический150k Record/Open дал **402123 канонических кода**, весь raw совпал с источником; SHA raw `c06643d69de028e14bbbb68188e480c3ab9cf165076814ac6fe77e446ee675a3`. Копия журнала без companion сохранила intrinsic quantization. Для CSV проверены count, metadata, SHA, колонки и первые два времени/шаг1/150000; совпадение каждого экспортированного ADC-кода отдельно не заявляется. Темп150022/с за2,1424с относится только к синтетическому планированию host, не к USB/ADC.

Лично просмотрены все три **финальные** PNG:150000,6.66667мкс,10 сохранённых/2 потерянных бита, ненастроенная шкала и неизвестный хвост читаемы, перекрытий нет. Legacy mismatch сообщает правильную последовательность закрыть/открыть окно/выбрать fixedFs/подключиться; START при несовпадении не выполняется.

Лично пересчитаны ZIP/source SHA и CRC архивов; все475 файлов совпали между ZIP, dist, перенесённой папкой и сохранённым before-tree; manifest содержит474 файла, исключая собственный хеш. До/после совпадают ZIP/source/tree. Проверены хеши девяти smoke-артефактов, verifier inputs, build/resume reports и67 архивных пар плюс traceback supplement. Это только read-only сверка, без нового GUI/COM запуска. Среда критика — Windows10.0.19045, Python3.14.7. Inspect EXE входит в проверенное дерево, но в данном focused flow отдельно не запускался.

## Замечания и пределы

Ранние существенные замечания закрыты: несогласованное platform field; отказ unknown revision до stale nonce; отсутствие отдельного legacy companion2 evidence. Адресные исправления/добавки проверены, история в промежуточном critic-source-findings сохранена. Внешний import-отказ также устранён с сохранением первоначального неуспеха. **Открытых P0/P1 в двух заявленных программных областях нет.**

Обычный selector предлагает только50/100/150k. Legacy200 поддержан wire/file API, но обычный GUI не создаёт пункт200k; не заявляется возможность его выбрать при обычном повторном подключении. Sticky fault требует повторного открытия окна, теперь это объяснено. Прежняя полная picker suite не повторялась; чистая Windows-машина, публичный релиз, новый физический50/100/150k, электрическая точность/полоса/калибровка не проверены. Рабочий H2/SB100k не переносит свой физический PASS на SC. Ни срок наблюдения synthetic flow, ни балл не являются гарантией длительной устойчивости.

## Рубрика и итог

| Критерий | Вес | Logic/ARM | Windows-пакет | Основание |
|---|---:|---:|---:|---|
| C1 |30%|9,7|9,6|Явные режимы/коды/время и окончательное отображение без подмены legacy |
| C2 |20%|9,6|9,5|Fail-closed границы, bounded RAM, Record/Open и закрытие владельцев; аппаратные сроки/чистая машина отдельно |
| C3 |25%|9,5|9,6|Exact ARM/native/host crosscheck с явными seams; первый frozen flow, raw/CSV/PNG/ZIP evidence |
| C4 |15%|9,5|9,6|Общий descriptor, intrinsic identity и понятный selector; сохранённые ограничения legacy fault |
| C5 |10%|9,7|9,7|Точные source/base/verifier/хеши/команды и сохранённые неудачные действия |

Взвешенные итоги до округления: **9,60 и9,59**, оба≥9,5. Машиночитаемые вердикты: [software](../verification/v2-selectable-profiles/critic-source.json) и [Windows-пакет](../verification/v2-selectable-profiles/critic-package.json). Физическая приёмка SC — **NOT_REVIEWED, score=null**. Следующий узел требует отдельного точного аппаратного плана и независимого допуска образа; этот отчёт Flash не разрешает.
