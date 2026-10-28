# V2-06r / R2 — независимое ревью физического результата

28.10.2026. **Устойчивый150k/30с: REWORK6,375/10.** Сохранение и ограниченная
интерпретация диагностических свидетельств: отдельно **PASS9,60/10**.
Причина USB-задержки этим опытом **не установлена**. P1-M2-01 остаётся OPEN.
Критик `stream200_critic` не автор реализации и не аппаратный оператор.

## Привязки и личная проверка

Точный [план R2](../verification/v2-usb-gate/plan-01/build/v6r-board-01/plan.json)
`f7d751dcc2a52e6046cbfaeacd7e4bdc0aa4d97a89e32d2249f5dc95e10ec8ec`, source
`bc851d6ee7b16663db95acb32733cacff7a50f36`, SK/`0x5632534B`.
[Physical archive](../verification/v2-usb-gate/physical-01/manifest.json):
SHA256 `996a92f75e5e5bf0703a594bf5b1b33685e0c68d301c2685046b2fca81754b31`.
Лично пассивно сверены все90 пар/342955байт: исходники и архив совпадают.
Прочитаны результат, offline-анализ, decoded banks, invocation logs и
[root observations](../verification/v2-usb-gate/physical-01/build/v6r-board-01/150000/root-observations.md).
Новых тестов, повторного decoder/Open, сборок, COM/SWD или аппаратных действий
критик не выполнял. Fresh Open/CRC/raw evidence подтверждено сохранённым
offline result, а не объявлено новым запуском критика.

Full readback46820байт лично сравнён с принятым BIN; SHA256
`dd6e8322488a1d4ada50c2c722820f971b4b4782c303bdafb1410180e2efc8f1`.
Program/verify, readback и Reset27.10 завершены exit0. Новый фактический ответ
пользователя на `call_2bb73a17ab2045fe8b6f8c0c91e97507` связан с reset log;
свежая inventory28.10 03:50:58UTC показывает expected COM6/code0, owners=[].
Время ручного cold cycle независимо не измерялось. Root отдельно подтверждает
отсутствие последующих Flash/Reset и SWD/halt во время приёма. Это процедурное
свидетельство оператора, не вывод из равенства бинарных файлов.

## Отрицательный физический результат

Единственная команда опыта03:51:17.400011–03:51:18.591850UTC, whole wall1,1918345с;
на wire ровно один START. Получены21 полных DATA1024 =21504 canonical кода.
Record19456 отсчётов `[2048,21504)`, host Record wall0,1324486998с.
Запрошенные30с не достигнуты. Nominal Fs150000, mode5, ADC12/retained10;
два младших разряда уже потеряны, canonical raw не полные исходные ADC12.

Nonce`7266eaaa454327da`, generation3; discovery nonce отдельный. ENDseq25,
reason1/flags3/prefix21504/CRC2237768949 пришёл **до** STOPreq4, matching
ACKseq26 подтверждает terminal25/prefix21504. `normal_stop_exchange=false`,
`produced_end=null`: это явный source failure, не нормальная30-секундная запись
и не доказательство отсутствия потерь. Число неполученных измерений неизвестно.

[Offline analysis](../verification/v2-usb-gate/physical-01/build/v6r-board-01/150000/physical-analysis.json)
PASS с issues=[] только для сохранённых данных: contiguous21504,
raw SHA256 `3fe40cc95a99437db46d6ca71ad8271444b28d41295766a80f70fcc46e78711c`;
selected wire/journal19456 byte-equal,
SHA256 `b63b051b7cdcc364dbc71c22be38028bf4b07c7ca2ec08e1dac77f3050eebae1`.
Fresh Open/companion согласованы, discarded tail0, recovery issue отсутствует.
Оригинальные файлы before/after одинаковы. Host timestamps и краткий наклон
приёма не являются независимым измерением Fs или устойчивости.

## Снимки и остановка

После `cleanup_finished=true`, `phase=closed` и offline END/ACK root выполнил
шесть чтений136/64/24 с03:51:54.263UTC, затем регистры. Invocation timestamps
позже завершения команды, адреса соответствуют плану, ADC_DR не входит в дампы.
Вся последовательность/no-SWD-active дополнительно зафиксирована root.

| Пара | SHA256 одинаковых first/second |
|---|---|
| Legacy136 | `07f2fdd151164476e59abdeb5db0d891d9e6deeb404431c8cb8912b83d1cf471` |
| Progress64 | `8f118506e10303870f99e461e165dba34c7d61f7f8db4f35c22a13c4c9a7f462` |
| Gate24 | `1857ff62ab1e8fb96b5fe27ca6f24584c6f75a3851fc5b19a2fc2d1eddc22fb6` |

Пары лично сравнены и распакованы по ABI. Legacy/64 согласуют SK/nonce/gen;
у24 нет собственной identity, его привязка обеспечивается exact readback,
одним boot/сеансом, адресами и root chronology. Legacy flags4, firstreason1,
queue8, ADCfault0, maxpoll2907мкс, copy166мкс. Poll ниже3413 не доказывает
успешное освобождение очереди или WCET. Stopped checks всеtrue:
TIM3 CEN0/PSC47/ARR9, ADC_CR2=0, DMA EN0, нужные clock/reset bits согласованы.

64: first-close queue8, stage READY1024, TX1152/1335, FIFO free64,
held/deferred=true, task_ready=false. Elapsed10580665 cycles;
prepare4203334/158, positive26517bytes/79, zero-space45/other0,
max-positive-gap701587cycles. Это inclusive nominal timing и FIFO acceptance,
не CPU share, доставка, полный produced prefix или доказанная причина отказа.

24: flags15, serial82, **PUBLISHED**, total384/queued64, ACTIVE1,
**APPLICABLE0**. TIME age и budget неизвестны;65535/255 здесь sentinel,
а не фактические измерения. Event593390271, N end593408768:
разница18497 cycles, номинально256,903мкс при72MHz и сохранённых DWT условиях.
Запись `VALID_WITH_LIMITS` с предупреждением historical_not_applicable.
Она не содержит применимого HOLD_TIME/BUDGET/FINAL. Поздний USB64 held1
не связывает снимки с одним episode; current64 attribution и same-episode proof
отсутствуют. Нельзя выводить из PUBLISHED причину переполнения или отсутствие
любых USB IN событий. Observer effect сохраняется;21 против18 DATA прошлого
опыта не доказывают улучшение или изолированный эффект R.

## Вердикты и рубрика

Физический P1-M2-01: очередь переполнилась до30с. Требование150k не выполнено,
но явный отказ, сохранение префикса, согласованный Stop ACK и остановка работают.
Нового P1 о подмене identity/снимков в этом результате не обнаружено.

| Критерий | Вес | Физический результат | Диагностические свидетельства |
|---|---:|---:|---:|
| C1 |0,30|3,0 —30с не достигнуты|9,7 — identity/ABI/history честно связаны|
| C2 |0,20|4,0 — queue-full сохраняется, отказ явный|9,6 — пары/closed/off согласованы|
| C3 |0,25|9,5 — точное отрицательное свидетельство|9,6 — байты/логи подтверждены, causal предел явный|
| C4 |0,15|9,0 — отказ и сохранение разделены|9,4 — historical labels и внешняя хронология оговорены|
| C5 |0,10|9,5 — исходный отказ сохранён|9,6 — exact archive/plan/image/root procedure|

Физический итог: `0,30×3 + 0,20×4 + 0,25×9,5 + 0,15×9 + 0,10×9,5 = 6,375`,
**REWORK**. Диагностический итог: `9,60`, **PASS только как пригодная история
и подтверждение сохранения/остановки**. Это не PASS установлению USB-причины
и не перенос программного балла на устойчивость.

На плате оставлена остановленная SK. После опыта нет новых START/Flash/Reset,
50/100k или rollback. План R2 израсходован; повтор этим отчётом не разрешается.
Старая подпись SJ в pinned offline Markdown сохранена, фактический build — SK.
