# V2-06f — проект ограниченного профилирования S9

Статус: **проект измерительной итерации; реализации и аппаратного допуска нет**.
Основа — точный S8 `build/v6e-fw-01`, BIN SHA256
`80a5ed8d064a2d0559f063d6650fb4edab078de4c233ea66ef2cb0e1ac62cf20`.
100000/1, DATA128, DMA1024/half512, deadline5120мкс, очередь8, whole-fit,
FIFO384, USB burst6/<500мкс, протокол и приложение остаются прежними.

S8 физически завершился queue-full: 7552 полученных отсчёта, в журнале5120
отсчётов диапазона[2432,7552), ADC fault0,
queue high-water8. Его общий диагностический интервал включает запуск,
аварийную остановку и drain. Он не определяет доли затрат в активном приёме.
Повторные TIME-проверки были обоснованной гипотезой, но их удаление не
обеспечило100k. S9 должен измерить причины; успешность его диагностики не
является физической приёмкой100k и не доказывает невозможность200k.

## Минимальный состав

Сохранить старую `mt_stream_diagnostics` ABI1/136байт и её поведение.
Добавить отдельную одноразовую структуру профиля с собственными magic,
version, size, build, generation/nonce/epoch, flags и причиной закрытия.
Не печатать профиль в CDC, не добавлять wire-команд, не менять raw/индексы.
После обычной остановки root читает его по адресу **нового точного ELF**.

Для каждого интервала хранить `uint32 count, cycles_sum, cycles_max`:

| Интервал | Точная измерительная граница |
|---|---|
| TASK | один существующий `tud_task_ext(0,false)` |
| ADC_EMPTY / ADC_BLOCK | один оставшийся `mt_live_adc_service`; классификация по фактическому0/1; ошибочный незаконченный вызов — отдельный обрезанный интервал |
| RX | существующее чтение carry и цикл receive; Stop остаётся внутри него |
| TX_ACCEPT / TX_ZERO / TX_OTHER | весь прежний IRQ-guarded `mt_live_device_step`, включая build/CRC/commit; positive/known-zero/нет write или error различать по новому **наблюдённому в этом вызове** результату live_write, не по оставшемуся старому `last_write_accepted` |
| FLUSH | прежний app scope/usable/write_flush |
| GRANT_CALL | весь существующий финальный guard/snapshot/allow_ctr/irq_grant/unlock; не называть его длительностью асинхронной USB-серии |
| TIME_UPDATE | каждый настоящий `mt_timebase_update`, в том числе из live_time/core/ADC; все нормальные и fault-выходы, без повторных валидаций |
| USB_ISR | исполнение `dcd_int_handler` от входа до выхода; только существующие IRQ, все выходы |
| GRANT_INTERVAL | grant→следующий grant: полный wall-интервал, включающий foreground, ожидание host и ISR; последний незаконченный интервал сохраняется при freeze |
| GRANT_FIRST_IN_DELAY | grant→первый IN-пакет этого grant; один результат на grant, при отсутствии IN не выдумывать задержку |
| STEP | полный активный `mt_live_runtime_step`; отдельно учитывать начатый/законченный за пределами окна частичный step |

Это14 троек,168байт. TASK/ADC/RX/TX/FLUSH/GRANT_CALL — раздельные
foreground-фазы. STEP содержит их, TIME_UPDATE вложен в несколько фаз,
USB_ISR пересекает прерванную foreground-фазу. **Их суммы нельзя складывать
как независимые доли CPU.** GRANT_INTERVAL — wall delay, а не CPU cost.
Для неинструментированных промежутков показывать residual, не называть его
автоматически TIME или USB. Первая/последняя частичная фаза видимы отдельно.

До22 простых счётчиков, по одному владельцу каждого поля:

- foreground: успешно предложенные ADC-отсчёты; committed DATA-отсчёты;
  known-zero из-за FIFO free; zero по другому admission; unknown write;
  принятые байты; foreground raw-DWT reads;
- foreground в существующем IRQ guard: разрешённые/запрещённые CTR grants;
  опубликованные IN-transfers/сумма их total_len; ZLP-transfers;
- USB ISR: IN-пакеты/их полезные байты; burst resume; hold final; hold OUT/SETUP/other;
  hold budget; hold time/timer; hold lifecycle/error; ISR raw-DWT reads;
  максимум IN-completion gap вместо избыточного wrapper-call counter.

Все increments saturating с flag `SATURATED`; wrap счётчика не маскировать.
Для hold фиксировать **первую реально вычисленную false-ветвь** исходного
short-circuit, без повторного чтения ISTR/TIM2/RCC/EP и без переоценки guard.
`hold_time_timer` допускается единым счётчиком: он уже отвечает, ограничивает
ли этот guard серию. Более мелкая причина потребуется лишь при его доминировании.
IN-transfer metadata брать в уже существующей публикации, endpoint0x82:
это foreground-вызов DCD под прежним bridge guard, **не ISR writer**.
Завершённые IN packet bytes брать из уже захваченных total/queued/MPS
обработчика CTR: последняя короткая длина=total%64, полная=64, ZLP=0.
Невозможные metadata дают flag; не читать PMA/регистры заново ради длины.
Новых FIFO/DCD операций наблюдатель не выполняет.

## Окно и первая причина

Профиль инициализировать **до START**, пока он ARMED. Единственный запуск
за boot, повторный HELLO/START никогда не стирает сохранённый результат.
ACTIVE публикуется после успешного возврата настоящей start transaction
и финального clock_ok: CEN уже установлен и подтверждён драйвером. Записать
пару raw-DWT start-before/start-after вокруг публикации ACTIVE и исходные
prefix/head/next/ADC index. Это начало наблюдения, не метка физического CEN.
Если запуск не удался — профиль `NO_ACTIVE_START`, исходная диагностика
продолжает описывать отказ; нельзя выдавать пустой профиль за нормальный.

Главная точка freeze: `mt_live_device_offer`, непосредственно после
`mt_sample_queue_push == FULL`, **до terminate/raw_barrier/quiesce**.
Первый latch закрывает профиль, сохраняет код QUEUE_FULL и RAM-only снимок:
head_index, next_index, prefix_end, ADC first_sample_index, queue.used,
драйверные last_remaining/last_poll_us, core/ADC state/first_fault,
tx_offset/tx_length и текущую открытую фазу с её циклическим остатком.
Не читать CNDTR/USB/FIFO повторно. Состояние текущего DCD после drain не
подменяет состояние в момент первой ошибки.

Остальные закрытия: первый source fault/дедлайн, runtime TIME fault,
transport/epoch loss или normal Stop — **перед первым физическим Stop**,
на входе существующего terminate/recover/transport_lost/time_fault пути.
Общая функция latch сохраняет только первое закрытие. Не переставлять
проверки и не менять first_reason/error/accepted-prefix в рабочем коде.
Reason разделяет `FIRST_FAULT`, `NORMAL_STOP`, `CAPTURE_LIMIT`,
`NO_ACTIVE_START`; подробный source reason хранится отдельно.

Целевой предел сбора —250мс номинального DWT (18000000циклов при72MHz).
Проверять его только в уже существующем foreground checkpoint, не создавать
IRQ/таймер. CAPTURE_LIMIT замораживает **только наблюдение**, не останавливает
устройство, запись или USB и не скрывает последующую source error.
Это checkpoint, не жёсткая wall-граница: actual elapsed/overshoot берутся
из фактического end; суммы не обрезаются искусственно до250мс.
Начатый до freeze ADC/TX/RX/STEP/grant интервал сохранять как частичный
до freeze, не дожидаться возврата из Stop. После freeze не добавлять ни
tail, ни drain, ни последующий Stop/ACK в active-суммы/счётчики.

## DWT, IRQ и отсутствие гонок

Новый raw-reader — одно прямое aligned volatile чтение CYCCNT.
Не вызывать `mt_timebase_update`, snapshot, live_time и старый
`mt_stream_diag_cycle` из profiler hooks: последний имеет foreground-owned
изменяемое состояние и после старого freeze возвращает константу.
Контроль DWT CTRL/DEMCR выполнить перед ACTIVE и при freeze/после остановки;
их ошибки и отказы прежней DWT-диагностики отражать в validity flags.
Внутри фазы не добавлять полную проверку TIME/clock/MMIO.

Foreground и USB ISR пишут **разные** статистики/счётчики. USB IRQ с прежним
одинаковым priority0 не вкладываются друг в друга; при изменении этого
условия ISR-профиль недействителен до отдельного решения. Grant bookkeeping
обновлять внутри уже существующего PRIMASK guard. Не добавлять IRQ-mask,
spinlock, atomic64, printf, allocation или общий writer для суммы циклов.
Суммы32бит достаточны для250мс; uint64 indices хранить двумя32-битными
словами только в foreground-owned снимке и считать валидными вместе с
финальным publication flag.

На freeze foreground сначала сохраняет `end_before=CYCCNT`, затем одной
aligned записью переводит ACTIVE→CLOSING, затем читает `end_after=CYCCNT`.
ISR уже завершился, когда foreground исполняет эту последовательность;
последующий ISR видит CLOSING и профиль не пишет. IRQ между двумя метками
может попасть по одну сторону latch — поэтому **разность end_after-before
есть явная погрешность границы**, а не точная граница CPU. Аналогично начало.
Никакая новая критическая секция ради точности профиля не нужна. Открытую
foreground-фазу обрезать по end_before; интервал неопределённости показывать
отдельно. Если это значимая доля окна, результат не годится для атрибуции.
После записи всех полей — DMB и окончательный FROZEN, который не меняется.
Включая **все** поздние эпилоги: при CLOSING/FROZEN они не меняют даже
private open flags. В памяти остаётся один блок, а не live+frozen копии.
Public record/флаг — volatile32; публикация использует compiler memory barrier
и DMB. Частичный TX хранит наблюдённый в нём write kind/accepted, включая
UNKNOWN/OTHER; эти байты не превращаются автоматически в DATA prefix.
По этому проекту freeze не вызывается из TIME-update или live_write:
там только наблюдение фактического возврата, закрытие на ближайшем исходном
пути **перед Stop**. Это позволяет учесть уже необратимо accepted байты.
Если реализация всё же закрывает профиль внутри вложенного TIME, она обязана
сохранить его открытый stamp/flag; его обрезанный интервал тоже показывается
отдельно и не дописывается поздним эпилогом.

Разности raw-DWT вычислять uint32 modulo. Один переход через0 допустим;
пропущенный полный оборот59,65с при72MHz восстановить нельзя. Условие:
каждый измеряемый интервал <2^32 циклов, без debugger halt/live-watch.
250мс cap не спасает от не вернувшегося callback; такой результат —
незавершённый профиль, а не максимальная оценка времени. Частоту72MHz
считать номинальной; DWT/системная конфигурация не калибруют генератор.

## Память и observer effect

Расчётный ABI только из32-битных слов: header16слов64байта;
14stats×3слова168;22counters88; first-event20слов80;
начальные4×uint64 indices=32; private/scratch≤20слов80. Итого≤512байт.
Private включает одновременно открытые STEP/foreground/TIME/grant,
grant-first-IN state, текущий write kind/accepted, частичный первый segment
и две calibration величины. ISR entry stamp — scalar на стеке, не вторая
копия записи. Жёсткий потолок **всего** нового static состояния512байт
включает helper globals и выравнивание; дополнительных банков/arrays нет.
S8 имеет948байт сверх data+bss+8192резерва. При потолке512 остаётся≥436;
это предварительный расчёт, не доказанный новый linker layout. Перед опытом
обязательны exact ELF/map/static:64KiB Flash,20KiB RAM, стек8192, полный
call graph ISR/foreground; большие snapshots не копировать на стек.

Raw timestamps и обновления stats тоже занимают CPU. Перед START допустима
одна ограниченная калибровка32 пустых пар raw-read, результаты min/max в
private words; max не WCET. Min cycles одной пары × raw-read-count/2 —
только heuristic indicator части observer cost, не доказанная нижняя граница
всех hooks или затрат CPU. Исходные суммы показывать без вычитания
«накладных расходов». Отчёт включает число probes, калибровку, дополнительный
код и факт, что профилирование может приблизить queue-full. Если heuristic
indicator >5% окна либо boundary uncertainty >1%, атрибуция признаётся
observer-limited: следующая **отдельно согласованная** версия реже измеряет
TIME, но оставляет все counts и первое событие. Порог — правило качества
этого опыта, не допуск прибора. Малый indicator не доказывает его
верхнюю границу.

## Один ограниченный опыт и критерии

До flash: независимое ревью плана, новый точный buildID/образ, узкая проверка
freeze/partial/window/wrap/saturation/races и неизменности работающих guards,
exact static и отдельный аппаратный допуск. Старые образы/отказы сохраняются.
Потом root один использует SWD/COM; PA0 пуст, прежнее питание и отладчик.
Один физический100k диагностический сеанс, например1с до Stop при отсутствии
source error; профиль заканчивается на первом checkpoint после250мс
или раньше по первой причине. Не выполнять серию пробных Fs.
Сохранить wire/raw/журнал, exact readback, новый frozen profile дважды и
старые136байт/registers после Stop. При source error или невалидном профиле
вернуть S4 по прежнему проверенному пути. Ошибка источника в таком опыте
может быть полезным диагностическим результатом и всё равно остаётся FAIL
для непрерывного100k. Ни один диагностический PASS её не переименовывает.

Приёмка **диагностики**: известные generation/nonce/build; равные frozen
копии; валидный DWT/нет saturation; первая причина и последовательность
offered/committed/queue согласуются с wire-префиксом; отсутствует добавление
после close; сохранён partial interval; суммы/единицы/overlap явно разобраны.
Если этого нет — сначала исправлять измерение, не выбирать оптимизацию.

## Точки будущих hooks в точном S8

Пути ниже относительны `build/v6e-fw-01/`; строки относятся к этому снимку,
новый overlay должен закрепить SHA и сохранить порядок всех исходных условий.

| Место | Hook и основной риск |
|---|---|
| `patched/v2/app/mt_live_adc.c:37` start_binding, успех перед return:48 | ACTIVE только при resultOK+финальном clock_ok; не на входе START/предварительном Stop |
| `patched/v2/app/mt_live_runtime.c:200` step | границы task, service:222, RX:227, guarded TX:247, flush:252; иметь ticket каждого span, не считать после close |
| тот же runtime, `mt_live_runtime_step`:260 / grant:274 | STEP и GRANT_CALL; grant interval не путать с коротким вызовом enable |
| тот же runtime, live_time/live_write | только счётчик wrapper и фактический result; positive acceptance фиксируется до возможного recover, без повторной записи FIFO |
| `source/firmware/platform/mt_timebase.c:80` | TIME_UPDATE на каждом существующем выходе; не менять ранние отказы, не добавлять вызов update из probe |
| `patched/v2/protocol/mt_live_device.c:447` offer, push:451 | successful offered count; FULL latch сразу перед terminate, не после остановки |
| тот же core, completed:363 / pop:371 | committed DATA count по сохранённым128, после фактического commit; drain вне ACTIVE игнорируется |
| тот же core, terminate/recover/transport_lost и runtime time_fault | общий first-close до первой quiesce; не переписать первичную queue-full последующим Stop |
| `patched/dcd_stm32_fsdev.c:180` irq_grant | публикация grant stamp/счётчиков внутри уже существующего guard, без новой маски |
| тот же DCD:481 IRQ entry / все исходные exits | отдельный ISR sum, scalar stamp; не вызывать старую foreground diagnostic-cycle функцию |
| тот же DCD:557…624 CTR/continuation | IN completion и первая false guard-причина из уже прочитанных metadata/условий; сохранить short-circuit и MMIO read count |
| тот же DCD:990 dcd_edpt_xfer_fifo | только0x82, успешная существующая публикация transfer; foreground owner, не перепутать с повторным пакетом одного transfer |

Без нового source patch и этих проверок этот проект не является готовой
инструментальной прошивкой. Не нужно повторять неизменные широкие USB/host suites.

Проект offsetof/flags/owner/tickets закреплён нормативными header+ABI ниже.
Остаётся TBD **до допуска образа**: фактическая реализация каждого early-exit,
и какой source/epoch/Stop путь первым вызывает общий latch. До физического
допуска — реальные new ELF RAM/stack, observer read-pair baseline и отдельный
review образа. Возможность100k/200k этим проектом не определяется.

Возможные решения по фактам, без заранее выбранного победителя:

| Наблюдение | Следующее ограниченное действие |
|---|---|
| TIME остаётся велик даже после условного вычитания всего наблюдённого USB_ISR из TIMEwall | проект консолидации проверок с сохранением CLOCK/TIME fault semantics; это включает probes/иные IRQ, а не доказанная чистая доля CPU |
| TX_ACCEPT дорог, TX_ZERO част и occupancy растёт | отделить стоимость CRC/build/commit от ожидания FIFO; при необходимости второй узкий TX breakdown |
| Много zero-space при малом USB ISR time и частом hold_time/budget | проверить фактический expiry/grant cadence; менять только доказанно ограничивающий gate при сохранении Stop/lifecycle/ADC deadlines |
| В основном hold_final и много transfers на один DATA/малые total_len | проверять whole-transfer completion/task handshake и публикацию FIFO |
| TASK или RX занимает большую часть окна | изучить конкретную очередь событий/объём RX; не приписывать её USB PHY без transfer-данных |
| Длинные grant→first IN при малом CPU/ISR и без частых hold | возможны host scheduling/NAK/PHY; нужны отдельные transport-наблюдения, одним MCU CPU-профилем причина не устанавливается |
| ADC_BLOCK/copy или poll gap нарушает5120 | исправлять приобретение/обслуживание; такой опыт не годится для непрерывного сигнала |

При отсутствии однозначного доминирования вывод — «не установлено» и один
адресный дополнительный измеритель. Профиль не выбирает автоматически75/100/200k,
не меняет аналоговую полосу и не подтверждает напряжение/зажигание.

Exact ABI/owner/tickets — `firmware/v2-stream/profile/mt_stream_profile.h`
и `profile/ABI.md`. FG/ISR validity+saturation banks раздельные. IN publication
и completion counters не обязаны сходиться из-за граничных transfers;
raw/queue conservation отдельно по initial/first indices и offered/committed.
