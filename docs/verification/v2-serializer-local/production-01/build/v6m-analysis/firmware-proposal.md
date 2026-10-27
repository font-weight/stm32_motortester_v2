# M: сократить обращения к state внутри CRC/COBS, сохранив расписание SE

26.10.2026, higher_fs_review. Offline-разбор точной SE и сохранённого L2.
До записи этого предложения production, тесты и аппаратура не изменялись.
Предлагается одна оптимизация serializer; это ещё не доказательство stable150k.

## Вход и установленный факт

SE/source `67b57bfaabbf7cf9290225058f2e8bca3b0964d8`, build `0x56325345`.
Exact ARM04: BIN42444байта SHA
`c1d2c5909341b010d0869f6f7a818d8dd46525bd18d6075e0dda780a9e23b9df`, ELF
`359754708f712b1d7d668b3b7c2b41b1cec59025761e05b9291035103030b3eb`.

L2 `build/v6l-board-01/150000/`: nonce `208e96bd934fe70d`, generation3,
8 полных DATA1024 =8192 принятых Preview-кодов, затем END reason1/flags3,
queue high-water8/8. Record не привязан: его таймаут и probe wall5,738с
не являются длительностью непрерывной записи. Raw/индексы/CRC доставленного
префикса совпали; произведённый хвост неизвестен. SE оставлена на плате.

Legacy136: step91, TX91, poll65, copy17; maxstep239935cycles,
maxpoll3337мкс, copy130мкс, guarded-TX14950cycles, ADCfault0. При номинальных
72МГц maxstep≈3332,43мкс и guarded-TX≈207,64мкс. TX-скобка начинается
ПОСЛЕ prepare, а step/poll включают prepare и возможные IRQ. Разность двух
максимумов не является стоимостью кодирования: они могут относиться к разным
проходам. Ноль ADCfault означает только отсутствие пойманного driver fault.
Запас3337 до strict3413 —76мкс в данном наблюдении, не WCET.

Legacy136 не содержит сумм/счётчиков отдельных фаз до первого queue-full.
Она не разделяет устойчивый дефицит CPU, transient USB паузу и service burst.
Поэтому далее отдельно указаны исходный факт, ARM-счёт и гипотеза.

## Что реально делает prepare в ARM04

`patched/v2/protocol/mt_live_device.c:383–429`, `batch_prepare`:

1. Забирает не более четырёх queue128, валидирует canonical12, затем
   `collect` повторно валидирует исходные коды, упаковывает10MSB и считает
   кандидат canonical-prefix CRC. Максимум512 кодов за эту часть.
2. Когда накоплено1024 либо quiesced Stop-tail, известный count записывается
   в header. Начинается frame CRC по44header/meta +1280packed =1324байтам.
3. До шести вызовов `step(...,512)` в ТОМ ЖЕ prepare завершают frame CRC
   и forward in-place COBS по1328 raw байтам. Это не шесть runtime-проходов:
   ADC service/TIME checkpoint между ними отсутствуют.

Полный последний quantum может включать512samples pack+canonicalCRC,
1324 frame-CRC bytes и1328 COBS bytes. Функция batch_prepare встроена компилятором
в build_tx; six-turn loop виден в `disassembly-24-mt_live_device.stdout`
по смещениям build_tx+0x294..0x2ba. Generic memset544 находится в другой ветви:
mode5 не выполняет его перед каждым новым DATA.

Замена count1024 пакетами не устраняет работу с каждым исходным байтом.
Пока READY/частично принятый кадр отправляется, cached-TX путь не собирает
следующий staging. Полный кадр до1335 требует минимум четырёх whole-fit
предложений не более384; отсутствие нового collect в этих проходах сохранено.

### Точный горячий цикл serializer

`disassembly-28-mt_batch1024.stdout` показывает:

| Путь | Смещения mt_batch1024_step | Декодированных инструкций на обычную итерацию | Обращений к state в этой итерации |
|---|---|---:|---:|
| Frame CRC, ещё не достигнут конец |0x44..0x6a |16 |4: read cursor/CRC, store CRC/cursor |
| COBS, ненулевой байт, code не достигает255 |0xa8..0xd0,0x114..0x126,0xe2..0xe4 |29 |7 |
| COBS, нулевой байт |0xa8..0xe4 |28 |10 |

CRC1324 даёт21184 таких инструкций горячего цикла, не считая входов/переходов.
COBS1328 при условном обычном ненулевом пути даёт38512. Это условные
instruction-path оценки, не измеренные cycles, не точный счёт всего кадра:
нули, code255, завершение quantum и IRQ меняют путь. Четыре state-access
на каждый CRC-byte и как минимум семь на обычный COBS-byte — конкретные
повторные LDR/STR в уже скомпилированном коде, которые можно убрать.

Причина в форме C: `uint8_t *storage` вправе alias state, поэтому после
записи байта компилятор снова загружает state.read/raw_length/write/code.
В действующем API header:38–39 state/storage/identity/input уже объявлены
непересекающимися; actual core держит state и tx в разных членах объекта,
а ISR не меняет queue/storage (`batch_prepare`:380–382). Предложение ниже
не добавляет restrict и не полагается на новое alias-правило компилятора.

### Сопоставление с TIME

SE `source/firmware/platform/mt_timebase.c:80–96` сохраняет два снимка
RCC4+TIM2config9 и CNT между ними:27 aligned32 MMIO чтений на здоровый update.
`disassembly-02-mt_timebase.stdout` сохраняет27 BLX. Native reader — LDR+BX;
старый dispatch добавляет загрузку function pointer/context, BLX и BX:
108 dispatch-инструкций сверх27 MMIO LDR на один полный update. Это не108циклов.

Условный healthy runtime путь (без дополнительных task/RX callbacks):7 явных
runtime live_time; ADC_EMPTY service добавляет3, готовая half512 с4offer —8;
core DATA/known-zero submit добавляет5 now, EMPTY prepare —2. Таким образом,
DATA submit даёт15/20 полных update для ADC_EMPTY/half512, а ещё не полный
COLLECT с EMPTY ticket —12/17. Это исходный call-path счёт, не измеренный
счёт L2. Cleanup/drain/early returns/RX добавляют или убирают вызовы.

Следовательно, фиксированная TIME цена остаётся существенным кандидатом,
но L2 не измеряет её CPU-долю. Старый J direct-reader proposal остаётся
отдельной альтернативой; одновременно с M его не включаем. Выигрыш от M
должен определяться ARM после изменения и отдельным аппаратным опытом.

## Одно выбранное изменение

**Перенести горячие локальные cursor/CRC/code в scalar locals внутри одного
bounded `mt_batch1024_step`, публиковать их в state на выходах quantum.**

- CRC: локальные read/end/rollingCRC; тот же byte order, та же таблица,
  тот же budget1..512. CRC-state и cursor сохраняются после обработанного
  quantum; переход к COBS, четыре CRC-byte и все bounds остаются прежними.
- COBS: локальные read/write/mark/code/raw_length; перед каждой записью
  сохраняются обе нынешние проверки headroom/frame bound, затем прежние
  patch/code/delimiter stores. Публикация cursor/state на return сохраняет
  точное прежнее состояние и при ошибочном defensive bounded шаге.
- Не копировать1328байт, не добавлять state/таблицу/buffer, не менять32B ABI,
  scheduler, шесть внутренних quantum, collect, canonicalCRC, deferred final
  TIME commit, known-zero/partial/unknown, TIME, ADC, USB, wire или host.
- Не вводить restrict. Caller foreground-only/nonoverlap — прежний контракт;
  текущий state во время синхронной функции не используется ISR. На ошибке
  нельзя скрыть уже разрушенную in-place storage откатом старого cursor.
- Сохранить frozen SE/prototype C и предыдущие evidence. Новая production
  serializer C лежит отдельно; build recipe явно выбирает её. Build V2SF
  `0x56325346` (в текущих firmware/tests/docs такого id ещё нет).

Предел статических данных остаётся жёстким:128data+12068bss+8192stack reserve
=20388/20480, только92байта сверх резерва. M не планирует рост .data/.bss.
Новые locals могут поменять spills/stack, поэтому прежний6156/6160 stack bound
не переносится автоматически; нужен exact ARM анализ нового образа.

### Почему не фазировать сейчас и не считать frame CRC при collect

Один CRC/COBS quantum на runtime-проход сократил бы единичный burst, но добавил
бы до пяти полных проходов наDATA1024, до≈732,4 прохода/с при150k. Каждый вновь
несёт TIME/RX/USB/guard работу и может ухудшить средний темп; увеличение
буфера это не исправляет. Двухфазное расписание менее дорого, но его достаточность
для3413мкс и среднего темпа пока также не измерена. M сначала уменьшает саму
работу, не добавляя проходов. Если останется burst, scheduler — отдельная задача.

Canonical-prefix CRC уже считается при collect. Это CRC по u16le canonical,
а frame CRC идёт по late header/meta и packed10: подменять один другим нельзя.
Чтобы убрать полный проход frame CRC, потребуются отдельный packed CRC и
доказанное CRC-concatenation/late-header решение; Stop-tail меняет count/length.
Это другая алгоритмическая оптимизация с новыми ошибочными границами, не M.

## Минимальный следующий scope и предел приёмки

После согласования root: одна focused differential проверка против frozen SE
serializer для одинаковых state/storage/возврата/ошибочных границ и fragmented
budget, включая shared-byte retry; существующая actual-core модель ownership,
Stop/HELLO/epoch/final-TIME на новом module; один успешный exact ARM build.
Проверить уменьшение state-access в CRC/COBS loops, неизменные остальные
functions/core/runtime/TIME/ADC/USB, static64K/20K и8192 stack reserve.
Не повторять host/GUI/package, если wire fixture побайтно совпадает.
Нужен независимый software critic≥9,5 до отдельного физического допуска.

Новый образ не объявляется stable150k по меньшему assembly. Сохранённый L2
остаётся отрицательным физическим результатом; ADC/USB не останавливать ради
скрытых окон, queue/FIFO не увеличивать, автоматический rollback не выполнять.

## Pins основных прочитанных входов

- frozen serializer C: `3e13f073e933ba08c7112ad943a4d14bb0520fef1e2349b569f1e656af87440e`;
- ARM serializer disassembly: `856c57ac0533adc215186f2896631a643733b54e0bdb4b844cb316c0721e74d5`;
- ARM TIME disassembly: `8bd94b6004293b8b50d6020a1f8b0356449df53a668f1a4779449db6fd85cf19`;
- actual core C: `c47e0ab27f185ac63248f9707633fa2d49a5bb246dedc15a03d2f6cc0208eeff`;
- L2 decoded136: `2201c2d8647b32be2178eba8f11c1209cc8696ec90ce7ab0e5e8608a968f63e2`.
