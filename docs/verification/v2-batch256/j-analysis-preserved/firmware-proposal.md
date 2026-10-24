# J: одна гипотеза для150k — убрать TIME callback dispatch, сохранив все чтения

24.10.2026, higher_fs_review. Только разбор сохранённого SC/source/ARM;
код, образ, прибор и тесты не менялись. Предложение требует отдельного scope.

## Факт отказа и границы вывода

I3/`build/v6i-board-02/150000`: перед Record30с источник завершился queue-full;
Record0,0154858с, получено3456кодов. Legacy136 имеет текущую nonce/gen3:
flags4, queue8, first_acquisition_reason1, ADCfault0, poll1370мкс, copy112мкс.
Это отказ150k, а не его приёмка. Меньшие poll/copy относительно3413мкс не доказывают
достаточный TX темп или отсутствие всех потерь ADC.100k в новом boot отдельно
прошли5с. Плату возвращать к прежнему образу только из этого отказа не требуется.

Legacy136 включает START/cleanup/drain и maxima, но не фазовые суммы до первого
queue-full. По нему нельзя определить долю TIME/USB/кодирования или CPU deficit.
Исторический F2 TIME mean≈13,54мкс получен с observer и перекрытиями; это не
измеренная стоимость uninstrumented SC и не прогноз выигрыша нового решения.

## Точный ARM-расход в нынешнем SC

Образ `build/v6i-fw-01`: BIN `a36f72a7…ca1c90`, ELF `c050b68d…8e308`.
`source/firmware/platform/mt_timebase.c:23–25` содержит already-inline `read_reg`,
но внутри остаётся indirect `t->io.read32(context,address)`.
В `image.dis` функция `mt_timebase_update @0x0800113C`, размер520байт вместе
с literal pool, содержит **27 BLX** для здорового полного пути.
Actual callback `mt_clock_mmio_read32 @0x08005350` — ровно:

```asm
ldr r0, [r1, #0]
bx  lr
```

Чтения в исходнике `update():80–99` и ARM идут так:

1. RCC_APB1ENR, RCC_APB1RSTR, RCC_CR, RCC_CFGR —4.
2. TIM2_CR1, CR2, SMCR, DIER, CCER, CCMR1, CCMR2, PSC, ARR —9.
3. TIM2_CNT —1.
4. Повтор тех же RCC4 и TIM2-конфигурации9 —13.

Итого27 реальных aligned32 MMIO чтений. Ни одно не предлагается убирать,
кешировать или объединять; ветви раннего fault сохраняют short-circuit порядок.
В старом ARM каждый callback добавляет загрузку функции, загрузку context,
BLX и BX:27+27+27+27 = **108 инструкций dispatch сверх27 MMIO LDR**.
Загрузка адреса регистра и проверки сюда не включены. Это счёт инструкций,
не108циклов, не WCET и не измеренное число микросекунд. Flash wait/prefetch,
APB, IRQ и новый register allocation не позволяют обещать конкретный выигрыш.

Для здорового обычного прохода SC без RX/task-induced clock callbacks:

| Ветка | Полных TIME update | MMIO чтений внутри TIME | Старых dispatch инструкций |
|---|---:|---:|---:|
| ADC_EMPTY + один DATA submit либо known-zero |15 |405 |1620 |
| Готовая DMA512 half +4 offer, тот же TX |20 |540 |2160 |

Основание15:7 runtime `live_time`,3 в ADC_EMPTY service (clock_ok до/после,
driver stamp) и5 в core `step_tx`. Full half добавляет второй driver stamp
и4 offer-now. Это условный call-path расчёт, не счётчики опыта: USB task,
RX, callbacks отказа/Stop могут добавлять наблюдения, а ранние returns — убирать.
При150k число DATA128 операций растёт на50% против100k; packed wire bytes/s
растут лишь≈2,6%. Поэтому именно фиксированные затраты обслуживающего прохода
заслуживают одной ограниченной оптимизации. Доминирование TIME пока не измерено.

## Предлагается только production specialization read_reg

Добавить явную build-опцию, например `CFG_MT_TIMEBASE_DIRECT_MMIO=1` для нового
проверяемого образа. В этом режиме `read_reg` выполняет один inline volatile
uint32 load по тому же адресу. Общий `update`/clock_matches/timer_matches,
оба снимка, CNT/wrap/service bound/fault latch остаются тем же кодом.

Специализация допустима **только при доказанном native read binding**:

- При init до первого MMIO отвергать read32, отличный от `mt_clock_mmio_read32`.
  В production `valid()` также проверяет этот binding, чтобы смена указателя
  не заставила прямой путь молча обойти новый callback.
- Проверенный backend игнорируетcontext и имеет только volatile LDR: именно
  поэтому нет пропущенных callback side effects. Actual constructor:
  `boot/mt_stream_main.c:88` native clock_io; `boot/mt_boot_time.c:59–61`
  копирует тот же reader/context в TIME. Остальные callback binding не считать native.
- По умолчанию/в generic native-моделях оставить прежний callback путь. Опция
  не должна незаметно подменять эмулирующий, instrumented или другой reader.
- write32 оставить прежним: init/Stop не являются выбранной горячей оптимизацией.
  Не менять runtime checkpoints, USB grant, ADC sample/deadlines, очередь/FIFO,
  packed10, canonical CRC, ticket, Stop или per-boot diagnostic semantics.

Новый field/buffer/таблица в SRAM не нужны. SC сейчасdata128+bss11228;
с8192stack reserve19548/20480, свободно932байта. Размер/stack нового image
нельзя объявить прежним или меньшим без exact ARM/static. Не ставить runtime
ветку выбора на каждом из27чтений: bind проверяется на границах, выбранный
read primitive компилируется отдельно. RAM объект TIME — foreground-only;
private immutable clock config можно держать в регистрах, но volatile MMIO
последовательность и публикация timestamp только после полных проверок обязательны.

## Минимальный следующий scope и необходимые доказательства

Одна новая firmware итерация: checked production reader specialization и её
явный recipe/config pin. Без увеличения буферов и без смены Fs/формата данных.
До hardware: source equivalence всех guard/check expressions; actual ARM
проверка тех же27 чтений/адресов и порядка, отсутствие27 BLX dispatch в здоровом
TIME пути, exact SRAM/stack. Один узкий TIME witness для success/fault/rollover/
wrong-binding и unchanged timestamp on fault; не повторять весь USB/host suite.
Generic callback trace отдельно от прямого production MMIO — не подменять
свидетельство одного утверждением о выполнении другого на MCU.

После software/независимого review — отдельный физический план root. Fresh boot
на каждый измеряемый сеанс, поскольку legacy136 по-прежнему one-attempt-per-boot.
Проверить сохранение50/100 и150packed10 с его прежними критериями; новый queue-full
останется отказом. Возможность устойчивых150k — гипотеза, а не следствие меньшего
числа инструкций. Current SC и I3 отрицательные данные остаются неизменными.
