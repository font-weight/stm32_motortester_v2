# R3 draft: SK, последний gate-переход CDC IN,24B и first-close

27.10.2026. Отдельный проект после frozen Q2 analysis SHA256
`89237d63cd7e161d9ad4a8154014d60c1b029d7132ecdabe61a1c9aa1d007641`.
Не production/code/тесты/аппаратный допуск. R/SK build `0x5632534B`;
Q/SJ и его source/evidence не изменять.

## Зачем именно эти сведения

Одна first-close snapshot только нынешних total/queued/budget/CNT недостаточна
для **исторической причины** hold: TIM2 мог устареть уже после решения; FINAL
может относиться к предыдущему transfer; новый grant/OUT может отменить причину
в том же transfer serial. Поэтому предлагается не периодический profiler, а
один маленький current-transfer/last-gate record. Он меняется только на уже
существующей публикации, принятом решении продолжить/удержать и инвалидаторах.
Сумм/максимумов, phase timers, новых TIME loops/второго frozen bank нет.

Нужный результат при queue-full:

| Состояние | Что различает; что делать следующим, не обещая fix |
|---|---|
|Observed publication, ещё нет applicable IN decision|Передача опубликована; текущий held нельзя приписывать старому FINAL/TIME. Проверять grant/task-to-first-IN путь.|
|Active transfer + applicable HOLD_TIME, age>=500|Прежнее разрешение continuation истекло в фактически выполненной проверке. Проверять возраст окна/работу между grant и IN, сохранив6/<500.|
|Active + applicable HOLD_BUDGET, left0|Решающим был исчерпанный budget; TIME не вычислялся и неизвестен. Проверить число/границы packets, не расширять budget автоматически.|
|Known FINAL complete + applicable final IRQ-hold|До N CLOSING закончился помеченный transfer и последним применимым был final hold episode; проверить foreground event/task/rearm/grant. Это не доказывает тот же episode позднего snapshot64.|
|OTHER/status/lifecycle/timer-unavailable|Нельзя превращать в bandwidth/500us проблему; сохраняются конкретная первая ветвь и недоступные поля.|
|Cause invalidated при том же serial|Показана только historical last CDC decision. Новый grant/не-CDC ISR мог снова изменить held; старый reason не объясняет текущий held.|
|Unknown/saturated/metadata-invalid/no-active/cap|Причинная классификация неприменима либо относится к более раннему cap, а не позднему fault.|

Это не измеритель среднего bandwidth и не предписание pre-ADC grant. Нужный
wire темп≈195,56kB/s не гарантирует весь software/IRQ путь. Каждая correction
должна также иметь ограниченную работу ISR и deadline headroom:500us не WCET.

## Ровно24B, один bank, little endian

Сохранить прежние64/136 layouts; новый record читается парой24B из нового
ELF-адреса после закрытия COM. Build/nonce/gen в24B не дублируются: требуются
matching frozen64/136, exact common generated build id/image/readback, один boot.
Два равных dump подтверждают только стабильность сохранённых байт, не race proof.

|Offset|Type|Field/причина хранения|
|---:|---|---|
|0|u32|magic/version `0x4d544731` (MTG1), не равно magic64|
|4|u32|flags: phase/validity/applicability, определения ниже|
|8|u32|publication_serial: локальный monotonic id успешной новой EP0x82 transfer publication|
|12|u32|event_cycle: DWT после помеченной публикации/решения, не начало/длительность IRQ|
|16|u16|total_len этого transfer, или65535 unknown|
|18|u16|queued_len в отмеченной точке, или65535 unknown; staged-in-PMA, не delivered|
|20|u16|evaluated_age_us: moduloTIM2 age именно фактически выполненной time-проверки;65535 unknown при AGE_VALID0|
|22|u8|remaining_budget после уже существующего decrement в ISR;255 unknown|
|23|u8|decision enum: таблица ниже|

Flags low2 phase:0 EMPTY,1 LIVE,2 CLOSING,3 FROZEN. Bits2 HAS_PUBLICATION,
3 TRANSFER_ACTIVE,4 DECISION_APPLICABLE_TO_HELD,5 AGE_VALID,6 SERIAL_SATURATED,
7 METADATA_INVALID,8 LIFECYCLE_INVALID,9 UNOBSERVED_INITIAL_TRANSFER,
10 NO_ACTIVE_START,11 OBSERVATION_CAP,12 ZLP. Bits13..31 обязаны0.

Decision0 UNKNOWN,1 PUBLISHED,2 RESUMED,3 HOLD_FINAL,4 HOLD_OTHER,
5 HOLD_BUDGET,6 HOLD_TIME,7 HOLD_TIMER_UNAVAILABLE,8 HOLD_LIFECYCLE,
9 HOLD_STATUS. Enum классифицирует evaluated decision, не обещание USB tokens.
Для PUBLISHED total/queued берутся после успешного `edpt_xfer` (первый PMA load
мог уже снять64). Для IN decision tuple берётся **до** `handle_ctr_tx`, из уже
существующих `mt_total/mt_queued`; queued==total означает completion последнего
packet. Результат handler проверяется прежними current-pointer/next-index guards.
Несовпадение даёт OTHER+METADATA_INVALID, не выдуманный FINAL.

### Нормативная matrix и reset/sentinel правила

`U`=total/queued/age65535,budget255,AGE_VALID0. При AGE_VALID1 **65535 допустим**
как modulo-age. Нулевой event_cycle при HAS_PUBLICATION1 также допустим.

|Случай|serial/event/decision|tuple, age, budget; validity|
|---|---|---|
|Init ДО N ACTIVE|0/0/UNKNOWN|U; LIVE,UNOBSERVED_INITIAL1,HAS/ACTIVE/APPLICABLE0|
|Close до first new publication|0/0/UNKNOWN|U; FROZEN,UNOBSERVED_INITIAL1; late initial completion игнорируется|
|NO_ACTIVE/UNAVAILABLE|0/0/UNKNOWN|U; FROZEN,NO_ACTIVE+UNOBSERVED_INITIAL; HAS/ACTIVE/APPLICABLE/AGE/ZLP0|
|PUBLISHED data|new serial/DWT/PUBLISHED|0<total<=384,queued=min(total,64),age65535,budget255; HAS/ACTIVE1,APPLICABLE/AGE/ZLP0|
|PUBLISHED ZLP|new serial/DWT/PUBLISHED|total=queued0,age65535,budget255; HAS/ACTIVE/ZLP1,APPLICABLE/AGE0 до completion|
|RESUMED|same serial/new DWT|0<queued<total<=384,queued кратен64; age<500,budget1..5; HAS/ACTIVE/AGE1,APPLICABLE0|
|HOLD_TIME|same serial/new DWT|intermediate tuple,age>=500,budget1..5; HAS/ACTIVE/AGE/APPLICABLE1|
|HOLD_TIMER_UNAVAILABLE|same serial/new DWT|intermediate tuple,age65535,budget1..5; AGE0,HAS/ACTIVE/APPLICABLE1|
|HOLD_BUDGET|same serial/new DWT|intermediate tuple,age65535,budget0; AGE0,HAS/ACTIVE/APPLICABLE1|
|Pure HOLD_FINAL|same serial/new DWT|PRE queued==total<=384,включая0/0; age65535,budget0..5; HAS/APPLICABLE1,ACTIVE/AGE0|
|HOLD_STATUS/LIFECYCLE|same serial/new DWT|intermediate tuple; AGE0/age65535 до TIME либо AGE1/age<500 после TIME; budget1..5; sticky lifecycle исключает causal attribution|
|HOLD_OTHER mixed flags|same serial/new DWT|PRE tuple,age65535,budget0..5; AGE0,ACTIVE по фактическому завершению; не FINAL и не автоматически metadata error|
|OTHER+METADATA_INVALID|observed serial/new DWT|U; sticky-invalid,ACTIVE/APPLICABLE/AGE0; valid tuple не требуется|
|Grant/other ISR invalidation|сохранены serial/event/decision|historical tuple/age/budget/ZLP сохраняются; APPLICABLE0|
|Cancel/lifecycle|сохранена история|APPLICABLE/ACTIVE0,LIFECYCLE_INVALID sticky|
|Serial saturation при новом submit|UINT32_MAX,прежние event/decision|last-good history сохраняется, SAT sticky,ACTIVE/APPLICABLE0; не wrap и не новая publication|
|CAP close|прежняя история либо U|FROZEN,OBSERVATION_CAP1; не объясняет fault после cap|

HAS_PUBLICATION исторически sticky после first success; first достоверная
publication очищает UNOBSERVED_INITIAL. ACTIVE/APPLICABLE/AGE/ZLP обновляются
по matrix. METADATA_INVALID/LIFECYCLE_INVALID/SERIAL_SATURATED sticky до boot:
при них tuple/event/serial больше не обновляются, разрешены только invalidation
и freeze. NO_ACTIVE/CAP — terminal bits. Новая publication не очищает эти
sticky flags; обычные grant/other ISR не стирают исторические age/event/budget.

Все persistent/private/alignment поля входят в24B. Serial живёт в этом же
bank; второго счётчика, current-pointer store, ISR scratch global или копии
нет. Local scalar scratch и function frames учитываются exact stack audit.
Native static assert size24/offsets; ARM data+bss growth≤24 с reserve8192.
С нынешним spare28 ожидаемый остаток минимум4, но это проверяется ELF, не size
одной C-структуры. Если для корректного owner/identity требуется ещё persistent
поле, остановить draft и пересмотреть ABI вместо скрытого превышения24B.

## Publication identity и applicability

Один фиксированный наблюдаемый endpoint — CDC IN0x82; serial не является DATA
sequence, nonce или номером USB packet. Обычные DATA/control bytes/ZLP могут
использовать этот endpoint. Публикация через FIFO и buffer учитывается только
при success, total≤384, MPS64 и единственном корректном backing route. Она
происходит под существующим caller-held IRQ guard. Hook не вводит новый xfer.
При total>0 backing=XOR(buffer,ff). При total0 разрешены XOR и NULL/NULL
(обычный zero-buffer ZLP); оба non-NULL недопустимы. FIFO ff!=NULL с0/0 допустим.
Перед любой попыткой нового submit0x82 association/applicability старого
transfer снимаются ДО существующей перезаписи `xfer->buffer/ff/total/queued`.
Неуспешный submit оставляет association invalid, не возвращает старый cookie
новым полям; success hook создаёт новый serial до снятия caller guard.

До первой успешной наблюдённой публикации ПОСЛЕ N ACTIVE — unknown initial
transfer: late completion старого control не получаетserial1 и не наследует
никакую cause. Первая наблюдённая publication создаётserial1. Следующая успешно
публикуемая transfer увеличиваетserial, полностью заменяет tuple, очищает старые
age/cause/invalidity текущего transfer и записывает PUBLISHED. Это не очищает
sticky SERIAL_SATURATED/LIFECYCLE_INVALID или общую ошибку наблюдателя; после
lifecycle новый transfer не становится пригодной историей того же ACTIVE
окна. ПриUINT32_MAX
serial не оборачивается: SERIAL_SATURATED sticky, applicability/current validity
сняты, дальнейшие события не выдаются за новый transfer. Telemetry saturation
не останавливает ADC и не recover session.

Current association не опирается на равенство длины384: на 0x82 последующий
успешный DCD submit всегда новый serial. Порядок BUSY/claim/submit прежний,
нет параллельной новой publication до обработки предыдущего completion.
Это обязательство подтверждается exact bridge/callback bindings и моделью;
неподтверждённый или ISR-инициированный submit помечается invalid/unknown.

FINAL снимает TRANSFER_ACTIVE и фиксирует завершённый serial; applicable
HOLD_FINAL означает только текущий IRQ-hold episode завершившегося transfer,
**не active нынешнюю передачу**. Новая publication удаляет FINAL. RESUMED
не применим к held (applicability0). Любой следующий grant, любой другой ISR
entry/OUT/SETUP или cancellation снимают DECISION_APPLICABLE_TO_HELD до
возможного нового evaluated CDC decision. Historical tuple/reason сохраняется,
но decoder не называет его причиной нового held. RESET/PMAOVR/SUSP/WKUP и
cancel/close endpoint также снимают TRANSFER_ACTIVE и ставят
LIFECYCLE_INVALID; старый serial нельзя молча использовать после lifecycle.
FIRST evaluated hold сохраняется только до следующего такого изменения.

Pure FINAL требует наблюдённый current serial, EP0x82 bulk/MPS64, без RX/SETUP,
допустимый backing/ZLP, PRE queued==total и неизменные buffer/ff/total/queued
после handler. Одного queued==total недостаточно. Mixed RX+TX/SETUP → OTHER;
metadata mismatch → OTHER+METADATA_INVALID с U. Initial late completion без
наблюдённой publication остаётся UNKNOWN. Это diagnostic eligibility, не
расширение рабочего continuation predicate для final/ZLP.

## Sampling без повторных/перенесённых hardware reads

Взять exact рабочее short-circuit выражение SJ `dcd_stm32_fsdev.c:616–621`.
Обёртки возвращают переданное actual_condition без изменения значения. Они
только помечают первый **вычисленный** false в локальном scalar decision:
continue/final/other → budget → int_status → fresh ISTR DIR/ERR → lifecycle →
timer → CNTR → DADDR. На all-true — RESUMED. Downstream skipped predicates
не интерпретируются. Запись bank происходит один раз после этого решения.

AGE_VALID возможен лишь если `mt_tx_burst_time_ok` фактически дошёл до
существующего CNT read. Если timer-ready false, это HOLD_TIMER_UNAVAILABLE,
age unknown. Если earlier budget/final/other false, не читать CNT дополнительно
ради красивого age. Для сохранения elapsed допустима адресная передача уже
прочитанного scalar в optional output; count/order/alignment hardware reads,
ready predicates и elapsed<500 остаются прежними. Нельзя вычислять TIME заново
при freeze и называть его причиной прошлого hold.

**Не переносить endpoint selection/reads.** Существующие ep_id/ep_reg читаются
в прежнем месте; xfer/mt_queued/mt_total выбираются после прежнего RX handler,
там же, где SJ. Другие endpoint paths только инвалидируют applicability и
не добавляют fetch CDC fields. Не поднимать reads перед OUT/SETUP, не повторять
ISTR/EP/CNTR или TIME health checks. Source proof должен подтвердить порядок
рабочих MMIO/callback/clear/rearm операций; diagnostic stores добавляют время,
но рабочие state stores до/после них не переставляются. Абсолютно прежнее
physical timing обещать нельзя даже при byte-identical guard predicates.

## Writer/freeze гарантия

Нет записи изISR в flags64. Gate hooks читают N phase; работают только пока
N ACTIVE и gate не CLOSING/FROZEN/sticky-invalid. Init24 выполняется до
публикации N ACTIVE (ISR hooks ещё запрещены), ровно по initial row matrix.
FG publication/grant/cancel уже находятся под прежним save/restore guard.
Весь DCD ISR тоже под PRIMASK: `source/firmware/platform/mt_usb_irq.c:7–12`
делает guard_enter→tud_int_handler→restore; `mt_irq_guard.c:7–18` сохраняет
PRIMASK/CPSID и восстанавливает прежнюю маску. Это основание сильнее равных
HP/LP priority. Иные/NMI writers отсутствуют в конкретном root set.
RMW flags gate допустимы лишь под этим ownership; не ссылаться на volatile
как замену сериализации.

Source grounds: `patched/v2/transport/mt_usb_bridge.c:114–137` уже locked
xfer/fifo/open/stall/clear_stall/close_all; `app/mt_live_runtime.c:217–231`
locked grant_irq. Invalidation hooks находятся внутри этих existing guards,
новой маски нет. RESET/PMAOVR/SUSP/WKUP идут через guarded ISR. Physical unplug
этой реализации наблюдается через SUSP/event, не универсальный disconnect hook.
`dcd_disconnect/deinit` сами не locked и **не считаются** безопасными writers:
saved SJ static-bound graph не имеет пути к ним, tud_disconnect/tud_deinit/
tusb_deinit из Reset/USB IRQ roots; stream main после init только runtime loop.
Следующий exact graph/source должен сохранить unreachable факт либо admission
останавливается; неподтверждённый generic disconnect path не добавляется.

N first-close сначала публикует ACTIVE→CLOSING как сейчас. Это запрещает новые
gate stores. В existing snapshot IRQ guard gate переводится в CLOSING,
проверяется consistent phase/metadata, затем DMB и FROZEN. Никакой второй bank
не копируется. На однопроцессорном Cortex-M foreground не исполняется внутри
ISR: ранее начавшийся ISR завершён до FG close, а прерывание после N CLOSING
видит запрет. Существующий guard сериализует final stores и FG публикации.
После FROZEN все hooks no-op; поздние drain/task/publication не меняют снимок.
Freeze24 обязательно внутри existing snapshot IRQ lock **вне** успешной ветви
app_enter: при отказе scope24 всё равно FROZEN, USB64 unavailable. NO_ACTIVE
без init получает ровно no-active row под этим lock; CAP freeze тот же и не
переоткрывается поздним fault. Никакого нового dispatch/lock/health MMIO.

N CLOSING и24/64 snapshots не одновременны: до snapshot lock ISR ещё может
изменить рабочие held/CTRM, хотя уже не24. APPLICABLE24=1 + USB_VALID64/HELD0
поэтому **skew, не structural INVALID pair**; historical decision сохраняется,
current-held attribution unavailable. USB_VALID64=0 тоже исключает её.
APPLICABLE24 означает только **последний применимый episode непосредственно
до N CLOSING**, при отсутствии sticky-invalid/noactive/cap и matching identity/
window. USB_VALID64+HELD1 с ним совместим, но не доказывает тот же episode:
между CLOSING и snapshot lock другой ISR мог снять hold и снова оставитьHELD1,
а hooks24 уже запрещены. Поэтому ни HELD1, ни равенство boolean не дают
current64 causal attribution; HELD0/unknown дополнительно показывают её
недоступность. Декодер сохраняет pre-CLOSING history и отдельно поздний USB64,
не объединяя их в синхронный/current episode. No-intervening-event witness
в этом ABI отсутствует; новых полей/масок ради такой связи не добавляется.
Timestamps не выдаются за атомарное наблюдение банков или bandwidth measurement.

NO_ACTIVE/UNAVAILABLE наследуются из64: снимок FROZEN с unknown sentinel tuple,
без fabricated ACTIVE history. CAP250ms замораживает gate в ту же границу,
не останавливает ADC; поздний queue-fault этим bank не объясняется. Event DWT
проверяется только условной modulo-арифметикой с теми же external nohalt/wrap
ограничениями. Session/build берутся из matching64/136 и exact shared header.

## Минимальный gate перед отдельной реализацией

Независимо прочитать exact draft: owner/initial unknown/final invalidation/
serial saturation, skipped timer/first false и current-vs-historical cause.
После отдельного root scope — один actual-C transition/freeze model и source
MMIO-order proof, одна ARM/resources/stack проверка. В модели: publication→
TIME/BUDGET/FINAL; newserial снимаетoldcause; grant/OTHERISR того жеserial
снимаетapplicability; late initial control неизвестен; lifecycle/saturation;
CAP/noactive и FG/ISR late stores после close неизменны. Не повторять старые
whole-runtime/GUI suites. Actual hooks/field offsets и все≤24B globals должны
быть проверены по exact image, не одному header.

Только затем отдельный один физический план. Критерий диагностики — пригодный
путь gate при том же first-close, не прирост количества кадров. Это позволяет
выбрать ограниченный window/turnover fix либо признать, что single-transfer
foreground pipeline требует отдельного архитектурного решения. Новый record
сам по себе не исправляет queue-full и не принимает stable150k.
