# V2-06l1 — независимое ревью production DATA1024

**PASS, 9,6025/10**, 26.10.2026. Область: программная логика V2SE, точная
ARM-сборка и условный статический предел стека, actual-core модель,
приложение и source Qt GUI в Windows 10. Критик `stream200_critic` не автор
реализации. Windows-пакет, Flash и физическая устойчивость150k принимаются
отдельно. Этот результат не закрывает аппаратную часть V2-STR17.

## Точное состояние

Проверенный source commit `67b57bfaabbf7cf9290225058f2e8bca3b0964d8`;
база рабочего дерева `07862595ce96d19d8a95361f7db3f7ea3da336af`,
функциональная база SD `cb4757940b3ee9968f953becfbc3ca8caea102d7`.
Проверены manifests точных файлов, а не только исходный HEAD. Полные pins,
рубрика и ограничения — [critic-source.json](../verification/v2-batch1024/critic-source.json).
Требования: V2-STR17 с сохранением V2-STR14/15/16; task L1;
[quality-gate](../quality-gate.md), [контракт](../streaming-batch1024.md),
[принятый проект r2](v2-06l-integration-plan-review.md).

| Артефакт | SHA256 |
|---|---|
| Firmware freeze | `0b7979e47bd867dd2f8108a033e47eeec325315bd8ee81815c5acb2fdb447eba` |
| Host/source GUI freeze | `aee5232236b4181d1641bfef2c267f3a589f6c99307f3a6436335022f7d7e1a5` |
| V2SE BIN, 42444 байта | `c1d2c5909341b010d0869f6f7a818d8dd46525bd18d6075e0dda780a9e23b9df` |
| ELF | `359754708f712b1d7d668b3b7c2b41b1cec59025761e05b9291035103030b3eb` |
| Static bound | `00ced5b6b7a3998caeda9e25b09743e64833e13a62acea97e8405e6bc85229cc` |
| Actual-core native result | `7eb61d4daa2f69389d1f6e3cb411227fe32d803c28f55de98434d9600f4ca7c0` |
| Source equivalence | `70fd376916dbdcc312ee803acd98e63332617adf01b8b5d5da8457f6782aaf16` |
| Source GUI result | `4db16bd6f5ce056dbdcf3973c8c818da9d1a95d1e01626b88745bd1c1f9d7e12` |

Лично сверены SHA/размеры 738 уникальных pinned файлов,243311577 байт:
553 recipe inputs,116 dependencies и110 native inputs входят в эту сумму.
Лично побайтно сверены1309 пар/8887407 байт
[production-01](../verification/v2-batch1024/production-01/manifest.json)
(SHA `092accd177f10d9414b31cc0bf0cd32b31ee80c325b36884a1a36349d3cfab91`)
и12 пар/12170066 байт [gui-01](../verification/v2-batch1024/gui-01/manifest.json)
(SHA `650d45fa3b3c3abd7e6d77ba5153809e50067b16d227e73c0b79a0da6f08ae9e`).
Несовпадений нет. Это проверки сохранённых файлов, не новые продуктовые тесты.

## Корректность реализации

Mode5/config5 явно согласует DATA1024, discovery15/max1024/payload1300,
selected ACK/CAPS1024. Modes1..4 и их сохранённые файлы не переопределены.
Host читает прежними порциями544, собирает большой envelope только для
DATA0.3/config5 и публикует отсчёты после полной проверки кадра. Public150
на старых SC/SD отклоняется до START. Потеря двух LSB сохраняется внутри
journal и экспорта, время150k остаётся номинальным20/3мкс.

Критик прочитал конечные core/queue/header overlays, recipe/config/profile,
actual-core модель и runner. Новый `peek_many/pop_many` проверяет все1..4
view, включая четвёртый при wrap7→0, до изменения очереди. Подготовка
копирует до512 отсчётов за проход и переносит владение из очереди в packed
TX. Она не публикует accepted prefix и не вызывает TIME/IO. Ticket включает
все поля state32; stale epoch запрещает submit, последующая очистка
инвалидирует staging целиком. Деструктивный in-place COBS не откатывается
одной старой копией курсора.

Stop достраивает текущий пакет из подтверждённой очереди/хвоста; последний
short допустим только в конце. Source fault сохраняет причину и не склеивает
поздний хвост через пропуск. END mode5 требует hardware_off, пустую очередь
и пустой staging. HELLO при нулевом acceptance отбрасывает старый staging;
частично принятый immutable DATA заканчивается со старой identity перед
новым HELLO_ACK. Старые lifecycle/TIME/write guards сохранены.

Полный known acceptance mode5 сначала готовит локальный pending completion.
`prefix_end`, canonical CRC и `last_data_sequence` обновляются только после
**последнего** now/bound. После него — постоянное число stores, без CRC,
pop или callbacks. Модель лично прочитана: на обеих post-write проверках
она наблюдает старый prefix; при поздней ошибке часов или deadline после
выхода полного DATA prefix остаётся старым, normal END/ACK не появляется.
Zero/partial/unknown acceptance также проверены.

Runtime/ADC/DMA/TIME/DCD/FIFO/USB исходники побайтно совпадают с SD;
18 сохранённых core bodies и старые queue APIs сравниваются по токенам.
Нормализация `step_tx` удаляет только явно показанный deferred mode5 участок,
после чего прежние guards совпадают. Это не утверждение об одинаковом времени
исполнения: новое encode и увеличенный TX меняют нагрузку.

## Сборка, память и необходимые проверки

Финальная ARM04: build`0x56325345`,text42316,data128,bss12068.
`128+12068+8192=20388` из20480 байт;92 байта свободны **сверх** прежнего
8192-байтного резерва стека. Точный ELF-анализ даёт6156, с выравниванием6160
байт; проверены receipt, map/nm/SU и assumptions анализа. Это условный
статический предел при закреплённых callbacks, cold reset/MSP/STKALIGN,
равноприоритетных USB IRQ и завершении NMI/HardFault, а не измеренный
stack high-water или WCET. Новое статическое хранилище требует нового
бюджета. Legacy frozen136 находится по`0x20002F1C`, один attempt на boot.

Сохранены неудачные ARM01 (строгий warning двух if в одной строке), ARM02
(нехватка source→patched mapping нового serializer) и ARM03 (прежняя
проверка31 objects отклонила32). Исправления конкретны, ARM04 — первый
принятый полный образ. Native actual-core — один compile и один run,
четыре адресные группы: ownership/старые modes; Stop/tails/source fault;
HELLO/epoch/ticket; late final TIME/acceptance. Команды/compiler pins находятся
в архивированных receipt/result; компилятор модели Zig0.15.2.

Модель исполняет actual `prepare_tx→step_prepared`, реальные core/queue/module
и извлечённый runtime admission helper. IO/clock/Stop — логические callbacks;
полный runtime/peripheral loop не исполняется. CRC/COBS Stop states созданы
реальными API как допустимые состояния продолжения; это не моделирование
прерывания подготовки обработчиком RX.

Actual-core fixture1614 байт точно совпал с прежним изолированным C fixture:
`cf62a2d6153aa7f59e4c886e9f487e950381ac6d6cbafa1ca285d19f22333013`.
DATA1024+129 и END покрывают1153 canonical кода, CRC1967919874.
Поэтому прежнее C→host/journal/bareOpen/CSV свидетельство применимо к этим
точным байтам без повторного прогона. Его script проверял все1153 CSV
индекса/времени/кода; это отдельно от более ограниченной GUI-проверки CSV.

Source GUI выполнен автором один раз в Windows10.0.19045/Qt windows:
9 checks PASS,401 полных DATA1024+tail398,largest frame1330,370062 кода
после fresh Open равны источнику; bare Open без companion сохраняет
identity/raw. GUI CSV проверяет count/metadata и первый дробный шаг, не все
CSV-коды. Real COM opens0, owners closed, errors/callback errors пусты.
Критик лично просмотрел все5 PNG: режим/квантизация/график/Open читаемы,
сообщения SC/SD150 и legacy mismatch не обрезаны. Synthetic обозначен явно;
host pacing не назван измерением USB/ADC.

Прежние четыре узкие host группы не перепускались. Критик не запускал
модель, GUI, ARM или аппаратный опыт повторно; личная проверка — чтение кода,
логов/артефактов, hash/byte comparisons и просмотр PNG.

## Пакет и границы

`profiles_package_check.py` SHA
`99e816031192c52297f916ccadb27d3541e768c22b4015a150bda56d0241b80b`
проверен как исходник: точные mode5/ACK/CAPS/wire receipts, raw/file hashes,
CSV count/первый шаг, frozen platform/executable, sealed ZIP/tree и закрытие
владельцев. Portable README SHA
`704bb453b68bd55ec2a8c74e44b4edd7723cedf55c56418845065f0e40d09737`
правильно предупреждает о несовместимых SC/SD150 и отдельно требуемой
физической устойчивости. Сам frozen пакет этим отчётом не принят.

Открытых P0/P1 нет. Малое замечание L1-N1: в контракте сохранён исторический
заголовок «ещё не реализованы»; реализация теперь подтверждена данным
freeze, статус находится в progress. Переписывать frozen проект ради
заголовка и пересобирать образ не требуется. Ограничение L1-N2 —92 байта
сверх резерва; оно не отменяет статический PASS, но запрещает предполагать
пространство для новых globals.

## Рубрика и вердикт

| Критерий | Балл | Основание |
|---|---:|---|
| C1,30% |9,65|Явный mode5, ownership и final commit согласованы с контрактом и actual-core witnesses; старые режимы сохранены.|
| C2,20% |9,55|Atomic views, lifecycle, partial/unknown/TIME отказы и linked memory проверены; запас SRAM для расширений мал.|
| C3,25% |9,60|Exact ARM/static, actual-core, неизменный C fixture и source GUI; seams и отсутствие физического timing названы явно.|
| C4,15% |9,55|Разделены queue/staging/accepted prefix, GUI читаем; историческая формулировка проекта требует чтения вместе с текущим статусом.|
| C5,10% |9,65|Закреплены inputs/архивы/команды/отказы/образ; source package checker и инструкции согласованы.|

Итог до округления **9,6025/10 — PASS в заданной программной области**.
Устойчивые150k, ADC deadlines,1мс transaction bound, отсутствие физических
потерь, точность/полоса входа, зажигание и автомобиль не подтверждены.
Далее: отдельное ревью точного Windows-пакета и допуск точного аппаратного
плана. Это заключение само не разрешает Flash или START.
