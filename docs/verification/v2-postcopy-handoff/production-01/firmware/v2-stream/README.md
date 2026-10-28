# Кандидат V2SL: передача после private ADC copy

V2-06s/build `0x5632534C`, product `Motortester V2 Postcopy SL` проверяет
одну гипотезу [post-copy handoff](../../docs/streaming-postcopy-handoff.md).
Только mode5 с cached final DATA1024 и недостатком queue slots: после
проверенного private DMA512 copy существующая одна grant/TX opportunity и
прежний flush/Q могут освободить slots до четырёх contiguous DATA128 offers.
RX/новый read до разрешения pending блока запрещены. Healthy cancellation
сохраняет original offers; loss требует explicit quarantine, а не skip512.

Modes1–4, старый service/driver/DCD/core, wire, ABI136/64/24 и общий generated
build ID сохраняются. Новых static bytes нет; local receipt/stack и сроки
проверяются exact ARM. Deadline3413 и6/<500 не расширяются,500 не WCET.
Новые TIME barriers требуют времени: программный результат не подтверждает
устойчивый150k. Фактические результаты — только progress и review.

```powershell
.\.venv\Scripts\python.exe -I -B firmware\v2-stream\build_windows.py --output build\v6s-fw-NEW
```

Одна integrated actual-C boundary модель и exact resources предшествуют
независимому source review и отдельному аппаратному плану. Сборка не открывает
COM/SWD; offline decode SL требует явно переданного ожидаемого build.

## Сохранённый V2SK:24B диагностика последнего gate-перехода USB

V2-06r/build `0x5632534B`, product `Motortester V2 USB Gate SK` сохраняет
рабочий SJ и добавляет только [gate observer](../../docs/streaming-usb-gate.md).
Один24B bank хранит наблюдённую публикацию CDC0x82 и последний фактически
вычисленный gate branch. Skipped TIME остаётся unknown; новый submit/grant/
иной IRQ инвалидирует старую причинную применимость. Final mixed RX/SETUP
не выдаётся за чистый FINAL. Serial не оборачивается, invalidity явная.

Прежние64/136 ABI сохранены, common build identity генерируется из config.
Все gate stores прекращаются после N CLOSING, затем bank замораживается под
existing guard даже при отказе app scope. APPLICABLE означает episode до этой
границы; поздний USB64 даже при HELD1 не доказывает тот же episode.
SK не исправляет queue-full и не подтверждает150k.24B включают всю новую
static память; exact ARM должен сохранить reserve8192. ISR stores и DWT reads
имеют observer effect,500мкс не становится WCET. Wire/ADC/очередь/6/<500 и
расписание SJ неизменны; новых фазовых timers, flush/task/grant нет.

```powershell
.\.venv\Scripts\python.exe -I -B firmware\v2-stream\build_windows.py --output build\v6r-fw-NEW
```

Сборка не открывает COM/SWD. Нужны один адресный transition/freeze/read-order
model и exact resources, затем независимое ревью и отдельный аппаратный план.
Точные результаты и установленная прошивка — только в progress/review.

## Сохранённый V2SJ: сбор следующих отсчётов после TX commit

V2-06q/build `0x5632534A`, product `Motortester V2 Prefetch SJ` проверяет
одну гипотезу [post-commit prefetch](../../docs/streaming-postcommit-prefetch.md).
После последнего успешного write уже cached полного mode5 DATA1024 и прежнего
USB flush сертификат final-TIME commit допускает collect-only до512 следующих
отсчётов в существующий staging. Сбор выполняется до следующего ADC poll,
вне PRIMASK, с fresh TIME/epoch/soft/scope до и после. Он не делает seal,
frameCRC/COBS, второй DATA/write/grant и не продвигает accepted prefix.

Modes1–4, обычный prepare, Stop/HELLO, ADC deadline3413мкс, IRQ6/<500мкс,
FIFO384/queue8 и wire сохраняются. Packing и локальный prefixCRC требуют
времени и могут задержать следующий poll; это не подтверждение150k/WCET.
Новой static памяти нет; точный stack проверяется для нового helper.
Shared config-derived identity и ABI64/136 сохранены; prepare-span включает
также prefetch. Для offline decode нужен explicit `--build-id 0x5632534A`.

```powershell
.\.venv\Scripts\python.exe -I -B firmware\v2-stream\build_windows.py --output build\v6q-fw-NEW
```

Сборка не открывает COM/SWD. Нужны одна адресная actual-core/runtime модель,
exact ARM/resources и независимое ревью до отдельного физического плана.
Точные результаты и установленная прошивка — только в progress/review.

## Сохранённый V2SI: единая build-привязка board и observer

V2-06p/build `0x56325349`, product `Motortester V2 Build Binding SI` исправляет
только P1-O2-02: `config.json.firmware_build` генерирует общий
`generated/mt_firmware_build.h` для board и observer. При включённой диагностике
нет fallback на старый SG id: отсутствие generated header/macro — ошибка сборки.
Actual C binding должен принять SI и отвергнуть прежние SG/SH при той же
session identity. Прежние64B/136B layout и first-close semantics сохраняются.

В SH старая observer-константа SG отклоняла запуск записи64B; нулевой банк
не является валидной диагностикой. Сохранённые SH source/image/результат O2
не исправляются задним числом. SI сохраняет functional SH: late grant,
ADC/TIME/USB, очереди, wire и сырой префикс. Исправление измерителя не означает
исправление queue-full или подтверждение устойчивых150k.

```powershell
.\.venv\Scripts\python.exe -I -B firmware\v2-stream\build_windows.py --output build\v6p-fw-NEW
```

Нужны exact ARM/resource, одна адресная actual-C binding/freeze проверка и
независимый review до отдельного физического плана. Сборка не обращается к плате.
Точные результаты и установленная прошивка — только в progress/review.

## Сохранённый V2SH: поздний grant для нового полного DATA1024

V2-06o/build `0x56325348`, product `Motortester V2 Late Grant SH` проверяет
одну гипотезу расписания USB по [границам O](../../docs/streaming-late-grant.md).
Conservative hint выбирает только mode5/STREAMING без cached/control TX,
способный заполнить1024 в текущем collect≤512. Такой проход получает ту же
единственную grant-попытку после prepare. До неё и после IRQ выполняются
свежие TIME/epoch/lifecycle проверки; actual ticket остаётся условием write.
Отмена hint через RX Stop/HELLO не разрешает старую DATA; cached bytes сохраняются.
При отказе scope wrapper не выдаёт второй reset; следующий проход сохраняет
обычный fallback. Cached/collect/control и modes1–4 сохраняют ранний H путь.

Предел6/<500мкс, FIFO384, queue8×128, ADC/TIME checks, wire/CRC/Stop и N64 ABI
не меняются. Старый in-flight transfer в выбранном проходе тоже ждёт дольше;
перенос не доказывает deadline/WCET или устойчивые150k. Прежние136/новые64B
снимки сохраняют границы и влияние измерителя. Для offline decode SH требуется
явный `--build-id 0x56325348`; значение по умолчанию декодера остаётся SG.

```powershell
.\.venv\Scripts\python.exe -I -B firmware\v2-stream\build_windows.py --output build\v6o-fw-NEW
```

Сборка не открывает COM/SWD. Нужны адресная actual-runtime модель новой границы,
exact ARM/RAM/stack и независимый review до отдельного физического плана.
Точные результаты и установленная прошивка — только в progress/review.

## Сохранённый V2SG: диагностика до первого отказа очереди

V2-06n/build `0x56325347`, product `Motortester V2 Progress SG` добавляет
один64B foreground-only снимок рядом с прежней136B диагностикой.
Алгоритмы SF, wire, очередь, ADC/TIME и grant не меняются. Формат/пределы —
[progress/ABI.md](progress/ABI.md). FIFO acceptance не равен USB delivery;
inclusive cycles не являются долями CPU. First-close выполняется до Stop/drain,
и последующие эпилоги снимок не изменяют. Один attempt/boot;250ms cap
останавливает только наблюдение. Образ не подтверждает устойчивые150k.

```powershell
.\.venv\Scripts\python.exe -I -B firmware\v2-stream\build_windows.py --output build\v6n-fw-NEW
```

Нужны exact RAM/stack, одна адресная проверка новых hooks/freeze и независимое
ревью до отдельного физического плана. Сборка не открывает COM/SWD.
Точные результаты и установленная прошивка — только в progress/review.

## Сохранённый V2SF: локальные счётчики подготовки DATA1024

V2-06m/build `0x56325346`, product `Motortester V2 Batch1024 SF`, по
[контракту M](../../docs/streaming-serializer-local.md) и
[контракту1024](../../docs/streaming-batch1024.md). Новый mode5/config5:
150k/ADC12/retained10, packed10 и прежний wire0.3 layout, maxDATA1024.
Discovery cap15/maxblock1024/maxpayload1300; selected ACK/CAPS явно связывают
mode5. Старые1..4 сохраняют границы, RX/previous543 и общий control codec544.
Public150 требует обновлённых приложения и прошивки, без rate fallback.

Относительно сохранённой SE меняется только реализация одного bounded
serializer step: CRC/cursors/code держатся в локальных переменных и точно
публикуются при каждом возврате, включая destructive error. Budget, bytes,
проверки и ABI прежние; restrict не добавлен. Production recipe явно выбирает
`batch1024/production/mt_batch1024.c`; frozen prototype/SE C сохранён отдельно.
Это сокращение скомпилированной работы, не подтверждение устойчивых150k.

Только TX увеличен544→1336 и добавлен state32. Queue8×128/DMA1024/half512/
FIFO384/MPS64/burst6/<500мкс и H runtime/TIME/ADC/USB остаются прежними.
Подготовка переносит до512 samples из queue в packed staging до IRQ guard.
Queue pop теперь обозначает ownership transfer, а не delivery. Глобальный
prefix/CRC не продвигается. Actual count известен до первого отправленного
байта:1024 либо конечный short1..1023 после Stop/seal, без padding/пауз ADC.

Raw размещается со смещением7 внутри TX; CRC и in-place COBS не выделяют
большой raw/message на стеке. До6 внутренних quanta512 обрабатывают полный
CRC/COBS в том же prepare, без6 дополнительных полных runtime loops. Это
ограничение работы, не измеренный ADC service/WCET. Реальная задержка по-прежнему
должна укладываться в3413мкс; deadline не расширяется ради размера пакета.
Stale epoch/TIME после destructive COBS требует abort всего in-flight staging;
rollback старого cursor поверх изменённых raw запрещён.

Один frame≤1335 передаётся immutable fragments≤384 с прежними whole-fit/
known0/partial/unknown/pre-post TIME rules. Sequence расходуется на первом
positive byte, как SD. Mode5 completion сначала вычисляет локальный pending
результат; global end/cachedCRC/lastseq публикуются только после последнего
успешного core now/bound, фиксированными stores. Late TIME после escapedFULL
не выдаётся за cleanStop: recovery без prefix commit и нормального END/ACK.

Stop сохраняет staging и drain очереди; END5 только hardware_off+queueempty+
stageempty. Fresh HELLO accepted0 отбрасывает непереданный staging; partialold
immutable DATA заканчивается под старой identity перед новым ACK. Loss/Abort
не переносит staging в новую nonce. Неизвестный хвост остаётся неизвестным.
Legacy136 по-прежнему один attempt/boot; tx_max исключает prepare.

```powershell
.\.venv\Scripts\python.exe -I -B firmware\v2-stream\build_windows.py --output build\v6m-fw-candidate
```

Изолированный prototype/native01 и SE сохранены отдельно. Serializer
differential/actual-core model, exact ARM/static20KiB с8192 reserve,
программный critic≥9,5 и отдельный аппаратный план обязательны.
При побайтно неизменном wire повторный GUI/Windows-пакет не требуется.
Сборка не открывает COM/SWD.
Кандидат не подтверждает stable150k/аналоговую полосу/точность или зажигание.
Фактические проверки находятся в progress и независимых review.

## Сохранённая V2SD: непрерывные DATA256 для 150k

V2-06k/build `0x56325344`, product `Motortester V2 Batch SD`, реализует
[контракт batch256](../../docs/streaming-batch256.md). Новый mode4/config4
сохраняет 150k/ADC12/retained10, но объединяет два существующих блока по128
в один DATA256. ADC/DMA продолжают работать непрерывно; пауз между окнами нет.
Режимы1/2/3 и их DATA128 остаются прежними. TIME-оптимизация J не включена.

Discovery HELLO0.2 объявляет capability7/global256. После fresh nonce
HELLO0.3 полный ACK/CAPS объявляет выбранные128 или256. Mode3 не меняет
значение. Старые приложения отвергают новый discovery до START.
В STREAMING mode4 ждёт оба блока128. Только после Stop/fault, синхронного
снимка хвоста и seal очереди допускается последний DATA1..255; остаток257
передаётся как256+1. Неизвестный потерянный хвост остаётся неизвестным.

Два borrowed view проверяются до любого изменения prefixCRC/head. Один
atomic pop_span фиксирует оба блока только после полного принятия кадра;
known-zero, partial, unknown acceptance, TIME/epoch и cached partial через
HELLO_PENDING сохраняют прежние ограничения. Дополнительного буфера256
отсчётов нет: два вызова прежнего packer128 заполняют существующий staging.
Полный packed DATA256 занимает не более371 байта с COBS/delimiter и помещается
в прежний FIFO384. END CRC считается по canonical u16le, как в mode3.

Runtime H, FIFO384/MPS64/burst6/<500мкс, DMA1024/half512, queue8, ADC и TIME
не изменены. Guarded CRC512 и старение раннего IRQ grant во время prepare
остаются затратами; расчёт размера пакета не доказывает физическую скорость.
Legacy136 по-прежнему требует нового boot между независимо проверяемыми
сеансами. `tx_max_cycles` исключает prepare и не измеряет всю стоимость TX.

```powershell
.\.venv\Scripts\python.exe -I -B firmware\v2-stream\build_windows.py --output build\v6k-fw-candidate
```

До отдельного аппаратного плана нужны одна адресная actual-core/queue модель,
source guard proof, exact ARM/static64KiB/20KiB с8192 stack reserve и независимый
critic≥9,5. Сборка не открывает COM/SWD. Фактические результаты — в progress
и ревью; этот текст не подтверждает устойчивые150k.

## Сохранённая V2SC: выбираемые50/100/150k до START

V2-06i/build `0x56325343`, product `Motortester V2 Modes SC`. Это новый
software-кандидат по [контракту профилей](../../docs/streaming-selectable-profiles.md).
Неизменённая V2SB и её30-секундная физическая проверка сохранены отдельно;
приёмкаSB не переносится автоматически на этот многорежимный образ.

Новыйapp начинает с discoveryHELLO0.2. V2SC отвечает capability3, требует
freshnonceHELLO0.3 с mode1/2/3; только выбранные CAPS и STARTconfig_id
разрешают приём. Discovery не запускаетADC. Старыйapp отвергает capability3
доSTART; новыйapp отдельно поддерживает старую fixed-Fs wire0.2 прошивку.
Выбор режима меняется через Stop/закрытие/новое подключение, без горячей
перенастройки. UI-профили «Осциллограф»/«Зажигание» независимы от этого выбора.

Все режимы используют физическийADC12.50/100k передают все12битu16le;
150k передаёт10старших плотной упаковкой4кода/5байт. ДваLSB необратимо
отбрасываются при проверенном копировании в transport queue; DMA snapshot
не меняется. Канонические сохранённые коды `(ADC12>>2)<<2`, ENDCRC поu16le
этих кодов. Явные retained10/quantization/sourceADC12 метаданные обязательны.
Это не изменение разрешенияADC, не калибровка и не исходные полные12бит.

TIM3PSC/ARR:50k=71/19,100k=71/9,150k=47/9 приnominal72MHz; ADC12MHz,
sample41.5cycles прежний. Период150k —20/3мкс, не округлённые6/7мкс;
deadlinehalf512 — консервативные3413мкс, CENbracket5TIM2ticks (6отказ).
Driver/Stop/epoch/TIME/whole-fit/partial guards сохранены. RuntimeSB,
FIFO384/MPS64/burst6/<500мкс, DMA1024/half512, queue8 не переписываются.
Legacy136 остаётся; `tx_max_cycles` исключаетprepare. Плотная упаковка
не гарантирует150k: DATAопераций становитсяна50%больше, deadlineкороче.

```powershell
.\.venv\Scripts\python.exe -I -B firmware\v2-stream\build_windows.py --output build\v6i-fw-candidate
```

Нужны одна адресная actual-core/queue/driver модель, sourceguardproof,
exactARM/static64KiB/20KiB с8192stack reserve и независимыйcritic≥9,5.
Отдельный аппаратный план допускает толькоroot. Сборка не открываетCOM/SWD.
Фактически выполненные проверки и дальнейшие шаги — вprogress и ревью.

## Сохранённая V2SB: одна ранняя USB opportunity после ADC

V2-06h/build `0x56325342`, product `Motortester V2 100k USBB`: обычный IRQ
grant переносится после ADC и существующих TIME/stable/loss проверок, до
RX/prepare. Так IN, опубликованный task, может продвигаться во время
подготовки TX. За runtime step допускается одна попытка: на раннем return
сохраняется wrapper fallback; после ранней попытки второй reset6/500мкс
не выполняется, включая false/FRES. После возможного IRQ — свежие
TIME/stable/loss проверки **до чтения/перезапуска RX** и до любого core TX.
Actor/app scope сохраняет владельца, сменаepoch ведёт в прежний cleanup.
Если task ещё не опубликовал transfer, его раннее6/<500мкс окно уже стареет
во время RX/encode/TX. Повторного reset нет; ускорение первого transfer и
startup не гарантируется. Модель порядка не подтверждает throughput.

100k/ADC512half/DATA128/queue8/FIFO384/MPS64/burst, wire/CRC/prepare-commit
V2SA и DCD guard прежние; дополнительные буферы не добавляются. S9profile
выключен, legacy136 остаётся. Его `tx_max_cycles` исключает prepare, общий
step/poll включает его. Это schedule-гипотеза после сохранённого G2 отказа,
не физически принятые100/200k и не разрешение наFlash. Возврат старого образа
не автоматический: только при конкретной необходимости в отдельном плане.

```powershell
.\.venv\Scripts\python.exe -I -B firmware\v2-stream\build_windows.py --output build\v6h-fw-candidate
```

До аппаратного плана нужны одна actual-runtime order model, exact source
сравнение с SA, ARM/static и независимыйcritic. Никаких COM/SWD из сборки.

## Сохранённая V2SA


V2-06g проверяет одну ограниченную гипотезу после сохранённого S9 queue-full.
Build `0x56325341`, product `Motortester V2 100k USBA`;100k/ADC512half/
DATA128/queue8/FIFO384/burst и wire S8 сохранены. Физические100k/200k ещё
не приняты. Код не открывает COM/SWD и не прошивает плату.

`mt_live_device_prepare_tx` строит отсутствующий кадр в существующем staging
перед PRIMASK, без callbacks/clock/recovery/sequence/prefix/queue commit.
Ticket проверяется под старым guard до deferred error и непосредственно
перед write; runtime повторно проверяет epoch/soft lifecycle/usable.
`mt_live_device_step_prepared` сохраняет исходные TIME/deadline и атомарность
от irreversible write через final time до completed CRC/pop/state publication.
Legacy `tx_max_cycles` теперь измеряет guarded submit после prepare и исключает
кодирование. Он не сопоставим напрямую с TX maxima S8/S9; общий step/poll
по-прежнему включает подготовку. Это измерительный смысл, не доказательство
ускорения. Stale ticket ничего не отправляет. Cached/partial кадр сохраняет фактический
accepted prefix и старые delimiter/unknown acceptance правила.

`active_profile_enabled=false` в config явно исключает512-byte S9 observer и
его hooks из нового образа. `diagnostics=true` сохраняет legacy136. Исходники,
overlays, старые receipts/образы S9 сохранены; их firmware recipe воспроизводит
S9 отдельно. Для другого режима нужен отдельно проверенный config/build.

```powershell
.\.venv\Scripts\python.exe -I -B firmware\v2-stream\build_windows.py --output build\v6g-fw-candidate
```

Адресная actual-core native модель сопоставляет wire с S8 и проверяет
stale/epoch/zero/partial/unknown/TIME. Точные commands и результаты находятся
в receipt/progress после выполнения. Неизменные GUI/host/USB suites не
повторяются. Exact SRAM/stack и независимое ревью образа обязательны до
отдельного аппаратного плана; runtime throughput этой сборкой не доказан.

## Сохранённая диагностическая S9


V2-06f1 добавляет измерение затрат к сохранённому S8/100k после его физического
queue-full. **Это диагностический образ, а не приёмка устойчивых100k.**
Build `0x56325339`, product `Motortester V2 100k USB9`. Частота, ADC/DMA,
проверки сроков/потерь, очередь, S8 schedule, whole-fit/FIFO384/burst и wire
прежние. Наблюдатель не меняет raw и не пишет в CDC.

Новый отдельный `mt_stream_profile` ABI1/512байт описан в
[profile/ABI.md](profile/ABI.md). Он считает активные wall-интервалы фаз,
TIME updates и USB ISR/grants, accepted/zero/transfer progress и hold causes.
Первое queue-full и другие отказы закрывают его **до физической остановки**;
последующие tail/drain/ACK не дописываются. Частичные интервалы и synthetic
начальные RX/STEP видимы отдельно. Foreground и ISR flags/counters имеют
раздельных writers; grant-seen shared только под прежним IRQ guard.

18000000DWT cycles — целевой checkpoint250мс при номинальных72MHz, не жёсткий
wall deadline. Он останавливает только сбор; actual elapsed/overshoot выводятся
из меток. TIME/ISR/STEP/grant интервалы пересекаются и не складываются как
независимые проценты CPU. Калибровка raw-read пары — heuristic observer
indicator, не поправка/граница всех накладных расходов. Данные читаются root
после Stop по адресу **конкретного нового ELF**; старый diag136 неизменён.

```powershell
.\.venv\Scripts\python.exe -I -B firmware\v2-stream\build_windows.py --output build\v6f-fw-candidate
.\.venv\Scripts\python.exe -I -B tests\v2-stream-firmware\check_stream_profile.py --image build\v6f-fw-candidate --baseline build\v6e-fw-01 --zig PATH_TO_LOCAL_ZIG_EXE --output build\v6f-native-profile
```

Узкая логическая проверка исполняет actual profiler: lifecycle/first-close,
partial и поздние эпилоги, cap/overshoot, modulo wrap/saturation и owners.
Рабочие тела/guard-условия сопоставляются с S8 после удаления observer hooks.
Сборка/static обязаны подтвердить64KiB/20KiB со стеком8192 и всего512 новых
static bytes. Ни логическая модель, ни successful diagnostics не квалифицируют
физический100k/200k, аналоговый вход или допустимое напряжение. Нужны отдельное
ревью точного образа, аппаратный допуск и сохранённый откат S4.

## Сохранённая основа V2S8: 100 kS/s с расписанием S4

V2-06e проверяет конкретную гипотезу после сохранённых отказов S5/S6/S7:
повторные ADC/TIME-проверки могут ограничивать опустошение очереди. Новый
`schedule-s4.json` накладывает один точный патч поверх S7: тело `step`
побайтно возвращается к S4, неиспользуемый `adc_checkpoint` удаляется.
Исходные барьеры TIME/loss/epoch/Stop вокруг task/RX/TX/flush и итоговый
IRQ grant сохраняются. Убираются две дополнительные ADC opportunities
с дополнительными TIME/loss парами, введённые для кандидата200k S5.

- Build `0x56325338`, USB product `Motortester V2 100k USB8`.
- Fs100000/1, TIM3 PSC71/ARR9, ADC12MHz/41,5+12,5 такта, DMA1024/half512,
  строгое обслуживание/копирование <5120мкс, queue8×DATA128 и Stop tail
  остаются точными S7. Whole-fit, FIFO384 и ограниченная IN-серия не меняются.
- В healthy DATA-проходе с пустым DMA 14 вместо22 полных TIME update;
  один update читает27 MMIO. Это подсчёт операций, не измерение CPU/USB
  и не доказательство, что100k стали устойчивыми. Более редкое обслуживание
  ADC не снимает проверку дедлайна; нарушения по-прежнему останавливают поток.
- До аппаратного опыта нужны независимый допуск exact BIN и сохранённый
  возврат S4. Сборка/native не открывают COM/SWD и не подтверждают АЦП,
  точность частоты, полосу или допустимое напряжение.

```powershell
.\.venv\Scripts\python.exe -I -B firmware\v2-stream\build_windows.py --output build\v6f-fw-candidate
.\.venv\Scripts\python.exe -I -B tests\v2-stream-firmware\check_schedule_s4.py --image build\v6e-fw-candidate --baseline build\v5-fw-10 --previous build\v6d-fw-01 --zig PATH_TO_LOCAL_ZIG_EXE --output build\v6e-native-schedule
```

Контроль сопоставляет exact step/21 runtime functions и неизменные S7
driver/core/USB guards. Узкая логическая модель исполняет извлечённый runtime
с граничными ADC/USB/core callbacks: готовый ADC, Stop/неудавшаяся остановка,
epoch/TIME loss и известный0 whole-fit. Физические DMA/USB/throughput модель
не исполняет. Неизменные host и широкие native USB suites не повторяются.

## Сохранённая основа V2S7: 100 kS/s и приём целого кадра

V2-06d — промежуточный программный кандидат после сохранённых отказов S5/S6.
Номинальные100000/1 дают шаг10мкс и период DATA1281280мкс. Это ещё не
физически проверенная скорость; допуск точного BIN и ограниченный опыт
оформляются отдельно. Установленный образ и фактический статус — в progress.

- Build `0x56325337`, TIM3 72MHz/(71+1)/(9+1)=100kS/s, ADC12MHz с прежней
  выборкой41,5+12,5=4,5мкс. CEN-скобка≤10мкс не равна задержке первогоADC.
- DMA1024/half512 и DATA128 прежние; срок обслуживания/копирования строго
  **<5120мкс**, то есть512/100000. Очередь8×128 даёт10,24мс вместимости,
  но не устраняет недостаточную среднюю пропускную способность.
- Под прежним core IRQ/epoch guard `live_write` проверяет FIFO free до
  необратимого копирования. Если free меньше остатка кадра, возвращается
  известный0, FIFO/tx_offset/prefix/sequence не продвигаются. Так callback
  CDC не получает незавершённый фрагмент следующего DATA. При достаточном
  месте выполняется прежняя запись с сохранением действительного accepted
  count, включая защиту от неизвестного результата и epoch loss после copy.
- FIFO384, descriptor maxpacket64, bounded IN0x82 continuation6/<500мкс,
  DTR/lifecycle/Stop/TIME и обнаружение потерь сохранены. Ни физическая
  устойчивость100k, ни невозможность200k не следуют из этой сборки.

`rate-100k-whole-fit.json` — шесть новых точных патчей поверх сохранённого
S6. Старые rate200k/USB-overlays не переписываются. Необходимая новая проверка:

```powershell
.\.venv\Scripts\python.exe -I -B tests\v2-stream-firmware\check_rate_100k.py --image build\v6d-fw-candidate --zig PATH_TO_LOCAL_ZIG_EXE --output build\v6d-native-rate
```

Она исполняет точные driver/adapter/core/live_write: конфиг100k, CEN10/11,
deadline5119/5120, известный0 при free<остатка, один целый DATA/CRC при
точном месте,383/384/385 и epoch denial/positive acceptance после copy.
Это логическая MMIO/CDC модель; измерение CPU/USB/АЦП и физический допуск
в неё не входят. Неизменённые FIFO/DCD guards сопоставляются по пинам S6,
их прежние модели не заменяют отрицательный физический результат S6.

## Сохранённая USB-основа V2S6

V2-06b сохраняет Fs200000/1, DMA1024/half512 и DATA128, но передаёт целый
DATA-кадр одной foreground-операцией до384 байт. Это отдельный программный
кандидат после физического переполнения очереди V2S5; аппаратного допуска
и утверждения об устойчивых200kS/s по этой сборке нет. Сохранённый V2S4
и исходный V2S5 не переписываются; установленный образ указан в progress.

- Build `0x56325336` (V2S6), CAPS/wire и неизвестный produced-end прежние.
  Очередь не увеличена. Дополнительный `usb-burst.json` закрепляет шесть
  точных патчей поверх сохранённого слоя V2S5.
- CDC FIFO384, параметр TX_EPSIZE384, descriptor maxpacket64. На STM32F103
  `CFG_TUD_EDPT_DEDICATED_HWFIFO=1`: отдельный384-байтный RAM EP-buffer
  не выделяется, передача идёт через `xfer->ff`. Её total_len фиксируется
  при публикации; последующие FIFO append не расширяют текущий transfer.
- Один core offer/live_write — до384 байт; partial/zero/SIZE_MAX сохраняют
  прежние правила accepted-prefix, sequence, fencing и неизвестного хвоста.
- Только промежуточные IN0x82 уже опубликованного transfer до384 байт
  могут продолжаться без полного foreground. Буфер либо FIFO должны быть
  единственным неизменным источником; total_len и шаг queued_len проверяются.
  Не более6 пакетов между foreground grants; final/OUT/SETUP/другой endpoint,
  lifecycle, USB error или непредвиденный прогресс оставляют NVIC held.
- Перед продолжением проверяется elapsed TIM2 <500мкс от foreground grant,
  gate/reset/CR1/PSC71/ARR65535, а также повторно аппаратные lifecycle-флаги.
  Это условие разрешить следующий IRQ после пакета, не жёсткий предел
  длительности последнего handler, не доказанный IRQ-off/WCET/1ms TX bound.
  Модульная арифметика не обнаруживает пропущенные полные обороты TIM2;
  отсутствие debugger halt и обслуживание основной TIME обязательны.

Узкие проверки нового кандидата (Zig только для нативной модели):

```powershell
.\.venv\Scripts\python.exe -I -B tests\v2-stream-firmware\check_usb_burst.py --image build\v6b-fw-candidate --zig PATH_TO_LOCAL_ZIG_EXE --output build\v6b-native-burst
.\.venv\Scripts\python.exe -I -B tests\v2-stream-firmware\check_rate_200k.py --bulk --image build\v6b-fw-candidate --zig PATH_TO_LOCAL_ZIG_EXE --output build\v6b-native-core
```

Первая исполняет извлечённые gate/ISR/handle_ctr_tx/bridge тела с логическими
NVIC/MMIO/PMA-progress: оба источника buffer/FIFO, final/short/ZLP,384/385,
счёт6, время499/500мкс и переполнение16бит, lifecycle/OUT/SETUP/error,
сохранённый отрицательный контроль отсутствия ISR hold. PMA payload и PHY
не исполняются. Вторая дополнительно проверяет реальный core/live_write
bulk/partial/zero/unknown-accept и точные TinyUSB FIFO/stream-write функции
с depth384, опубликованной границей transfer, short/full/ZLP. Нативный CPU
и модель очереди не измеряют пропускную способность STM32/USB.

## Сохранённая частотная основа V2S5

V2-06 меняет номинальную частоту одного PA0 на **200 000 отсчётов/с**
(шаг 5 мкс). Это программный кандидат; физически проверенный прежний V2S4
и способ возврата сохраняются отдельно, фактический статус — в progress.
Сборка ниже не загружает прошивку и не открывает COM/ST-Link.

## Контракт V2S5

- Build ID `0x56325335`; wire 0.2 и DATA128 uint16 сохраняются.
  CAPS `(config=1, profile=1, channel=0, bits=12, fs=200000/1, block=128, flags=1)`.
  Новый host должен явно поддерживать этот профиль; старый host его отвергнет.
- TIM3: 72 МГц / (71+1) / (4+1) = 200 kS/s. ADC1: 12 МГц,
  выборка 41,5 такта + преобразование 12,5 = 4,5 мкс. Сокращение выборки
  требует отдельной проверки установления сигнала и выходного сопротивления
  аналогового тракта; 12 бит кодов не означают подтверждённую точность.
- DMA1024, стабильный half512. Адаптер сразу предлагает четыре DATA128
  в исходном порядке. Обслуживание и копирование обязаны укладываться в
  **строго меньше 2560 мкс**: 512/200000. Проверки флагов обеих половин,
  изменения CNDTR, переполнения индексов и истории сохранены. Неверный
  порядок/позднее обслуживание вызывают ошибку, а не склейку пропусков.
- Очередь 8×128 (2048 байт кодов) освобождает SRAM для увеличенного DMA
  и Stop scratch. Это 5,12 мс очереди, без обещания USB throughput.
  До и после дорогостоящих участков USB/TX добавлены ADC opportunities;
  epoch/lifecycle/DTR допуск и обнаружение потерь остаются обязательными.
- Остановка сохраняет до 1023 завершённых DMA-переносов в 8 tail chunks;
  это не известный произведённый конец ADC. При переполнении очереди в любом
  из четырёх offer сохраняется префикс и причина, последующие chunks не
  публикуются через разрыв. Возможности физического Stop проверяются отдельно.
- Узкая скобка CEN ограничена **5 мкс**, то есть новым периодом отсчёта.
  Она не измеряет задержку первого ADC и полный запрет IRQ. Большой локальный
  scratch предварительного Stop вынесен в `quiesce_before_start` с noinline,
  чтобы его время жизни закончилось до START/terminate/recovery; итоговый
  стек и вся память проверяются по точному ELF.

`overlays/rate-200k.json` закрепляет девять точных патчей поверх сохранённого
слоя V2S4: драйвер/API, адаптер, runtime, queue/API и core/API. Патч queue.c
компилируется вместе с его V2-заголовком: исходная единица с локальным include
не должна случайно получить старый размер 16 slots. Старый upstream-архив
и предыдущие overlay не переписываются.

Необходимый узкий контроль (после сборки; новый каталог вывода для каждого):

```powershell
.\.venv\Scripts\python.exe -I -B tests\v2-stream-firmware\check_rate_200k.py --image build\v6-fw-candidate --zig PATH_TO_LOCAL_ZIG_EXE --output build\v6-native-rate
.\.venv\Scripts\python.exe -I -B tests\v2-stream-firmware\check_cen_transaction.py --image build\v6-fw-candidate --zig PATH_TO_LOCAL_ZIG_EXE --output build\v6-native-cen
```

Первая модель исполняет точные C-драйвер/adapter/queue/core: clock/выборка,
две половины, четыре DATA на half, Stop tail обеих половин, реальный wire/raw,
отказ на каждом месте queue-full и deadline. Вторая проверяет CEN на границах
5/6 мкс, переполнения счётчиков и исходного actor. Логическая MMIO не
подтверждает исполнение DMA, ADC, CPU, USB PHY или пропускную способность.

## Сборка и сохранённая история транспорта

Это сборка для подготовки ограниченного опыта с **неподключённым A0**.
Сборка и статический анализ не разрешают прошивку автоматически и не подтверждают
измерение напряжения, отсутствие потерь или работу с зажиганием. Перед загрузкой
нужны отдельный отчёт критика для точного BIN, условия платы и проверенный откат.
Скрипт не содержит команд COM, ST-Link, сброса или прошивки.

Из корня V2, Python из существующей среды:

```powershell
.\.venv\Scripts\python.exe -I -B firmware\v2-stream\build_windows.py --output build\v6e-fw-candidate
```

Каталог вывода должен быть новым. Ошибочный вывод сохраняется. По умолчанию используется
Windows GCC 12.3.1 из CubeIDE 1.15.0; `--toolchain` допускает другое расположение **тех же
байтов**. `toolchain-win.json` фиксирует 174 файла: компилятор, assembler, binutils и
деревья C-заголовков. Это не герметичная сборка ОС: Python, Git и их версии/хеши
фиксируются в receipt, системные библиотеки Windows отдельно не закреплены.

## Исходники и отличие V2

`git archive` читает только commit
`c10884fa39ad1a10ce0fcfc9d6e17f170e1e0bf0` исходного проекта, firmware tree
`cffe4ee61a7e47885c825521ea6fd679abd75fdf`. История этого commit должна быть доступна
в локальном клоне V2. Настройка `core.autocrlf` принудительно отключается **только для
архивирования**, чтобы Windows не меняла закреплённые файлы. Архив распаковывается
в `build/<имя>/source`; рабочие исторические `firmware/` и `protocol/` не изменяются.
Все USB-патчи применяются без fuzz/offset и проверяются исходным, patch и итоговым SHA.

Состав — отдельный потоковый entrypoint, runtime, ADC adapter, очередь и wire 0.2,
30 объектных файлов вместе с DWT-диагностикой. Оконный runtime не входит в образ.
V2 генерирует собственные board/timing definitions и накладывает отдельный
NVIC-патч `overlays/usb-nvic.json`, CEN-патч `overlays/adc-cen.json`
и CRC-патч `overlays/crc32.json`;
build ID `0x56325339` (`V2S9`), USB product `Motortester V2 100k USB9`.
Это декларация прошивки,
не способ аутентификации платы. Старые STR1 ELF/BIN/attestations не экспортируются.

Сохранены upstream compiler flags по компонентам, freestanding/soft-float/no-LTO;
добавлены запрет unwind/stack-protector/PIC и `-fno-jump-tables`,
`-fno-tree-switch-conversion`. Последние позволяют проверять управление стеком
без неразобранных вычисляемых переходов; влияние на физическое время ещё неизвестно.
Используются только Flash 64 КиБ, SRAM 20 КиБ, резерв стека 8192 байта.

`config.json` явно содержит **предположения**, не caller attestations:
HSE 8 МГц crystal, fixed USB pull-up, шина USB 100 мА, priority 0, DTR обязателен.
Имена `verified_*` сохранены лишь в структуре ABI upstream и не означают измерение.
Номинальная шкала V2S5 TIM3 200 квыб/с, 12-битный ADC1/PA0,
DMA1024/half512, транспортный блок128. История V2S2…V2S4 ниже описывает
прежний профиль50к; её физические результаты на V2S5 не переносятся.
В/мВ не назначаются: аппаратный профиль и калибровка остаются unconfigured.

## V2S2: ограничение USB IRQ

Исходный CTR-патч выключал только `USB_CNTR.CTRM`, оставляя необслуженный CTR.
В [RM0008, §23.5.1, USB_ISTR](https://www.st.com/resource/en/reference_manual/rm0008-stm32f101xx-stm32f102xx-stm32f103xx-stm32f105xx-and-stm32f107xx-advanced-armbased-32bit-mcus-stmicroelectronics.pdf)
описан отдельный запрос конечной точки, независимый от CTRM. Поэтому этот
способ не гарантирует возвращение CPU в foreground. Фактическая история первого
опыта и его ограничения находятся в [progress.md](../../docs/progress.md).

V2S2 при входе **в каждое** USB-прерывание удерживает NVIC19/20 выключенными.
Общий `fsdev_int_enable` проверяет hold: его не обходят OSAL и прямой `ep_write`.
После обслуживания foreground разрешает одну следующую IRQ opportunity.
При непустой очереди, неоконченной очистке epoch или soft pause разрешены только
lifecycle-события; CTR остаётся нетронутым. Поэтому RESET/PMAOVR/SUSP/WKUP могут
продвигаться и во время карантина. Дополнительная проверка ещё не обработанных
аппаратных lifecycle-флагов блокирует dispatch, публикацию конфигурации и app I/O
по устаревшему epoch. Прежние проверки actual Stop/epoch/TX сохраняются.
Если SUSP приходит после уже разрешённого CTR-кванта, ISR может принять одну
CTR-итерацию в очередь; `pending_soft` и физическая проверка запрещают её
dispatch/app I/O до обработки lifecycle. Отсутствие такого ingress не заявляется.

Это квант по числу операций, **не измеренная длительность** выключенных IRQ.
Предел TIME 32 мс не расширяется; обнаруженный TIME_FAULT остаётся sticky,
без выдачи новых IRQ-квантов, до сброса MCU. Автоматическое восстановление из него
не обещается. Пять V2-патчей проверяют SHA входа, diff и результата; исходный
архив c108 остаётся неизменным. Receipt перечисляет эту дополнительную цепочку.

Узкий нативный контроль использует извлечённые из конкретной сборки C-функции
gate/ISR/bridge, логические NVIC/MMIO и исходную метаинформацию epoch:

```powershell
.\.venv\Scripts\python.exe -I -B tests\v2-stream-firmware\check_usb_gate.py --image build\v5-fw-candidate --zig PATH_TO_LOCAL_ZIG_EXE --output build\v5-native-gate
```

Модель проверяет pending CTR при CTRM=0, обходы enable, один IRQ-квант,
RESET/PMAOVR и SUSP/WKUP при удерживаемой очереди. Удаление нового ISR hold
должно быть отвергнуто тем же контролем. Модель не исполняет USB PHY, полную
обработку дескрипторов и payload-copy; она не подтверждает enumeration или WCET.
Host-компилятор относится только к этой проверке; ARM-образ остаётся GCC 12.3.1.

## V2S3: точная граница включения TIM3

В прежнем V2S3 предел `start_after_us - start_before_us <= 20` сохранялся.
В V2S5 он сокращён до 5 мкс. Эти метки
охватывают запись CEN, а не всю проверку допуска и не первый результат ADC.
Фактическое основание изменения — сохранённый разбор
`build/v5-board-stream-02/start-failure-analysis.json`; текущий статус опыта
записывает основной агент в `docs/progress.md`.

Новый отдельный API `mt_adc_dma_start_transaction` не меняет структуру старого
guard или смысл `timed_allowed`. Весь старый generic путь сохранён. Потоковый
runtime явно выбирает транзакцию: полная проверка TIME и исходного USB actor →
свежий TIM2 CNT → TIM3 CEN и readback → свежий TIM2 CNT → полная проверка TIME,
того же actor, epoch/soft serial, DTR и аппаратных lifecycle-флагов.
Прежний guard сохраняет/восстанавливает PRIMASK; его длительность не объявляется
равной узкому CEN-интервалу.

Оба сырых CNT сопоставляются с окружающими полностью проверенными наблюдениями:
`0 <= before_delta <= after_delta <= outer_delta <= 32000`, причём приращение
16-битного CNT должно совпасть с приращением 32-битного TIME. Это учитывает оба
переполнения. Ограничение обслуживания меньше полного оборота TIM2 и запрет
debug halt остаются внешними условиями. Нельзя восстановить пропущенные обороты.
До окончательного успеха, включая предел 20 мкс и readback TIM3/DMA/ADC,
новые метки локальны; TIME не откатывается. При неудаче прежние поля меток
не считаются результатом нового запуска: `stream_history_valid=false`.
После отказа, в том числе уже после CEN, исходный драйвер сначала восстанавливает
маску, затем выключает ADC/TIM3/DMA с readback. История не становится валидной.
Проверки конфигурации и предел TIME32мс не удаляются; CEN-предел V2S5 — 5 мкс.

Пять дополнительных diff меняют драйвер, ADC adapter, runtime и два API-заголовка;
конструкторы и размеры постоянных структур сохраняются. Новых link objects нет.
Численное изменение стека вычисляет checker для каждого нового ELF.
Узкий нативный контроль использует фактические CEN-функции из выбранной сборки,
полные драйвер/TIME и логическую MMIO-модель:

```powershell
.\.venv\Scripts\python.exe -I -B tests\v2-stream-firmware\check_cen_transaction.py --image build\v5-fw-candidate --zig PATH_TO_LOCAL_ZIG_EXE --output build\v5-native-cen
```

Он проверяет границу 20/21 мкс, переполнения, дорогие внешние проверки и отказ
после CEN. Он не измеряет CPU/шины/ADC, не подтверждает физическое время,
не заменяет новый допуск критика и отдельный опыт с точным BIN.

## V2S4: вычисление CRC без изменения wire

Оба побитовых расчёта IEEE CRC32 заменены одной общей неизменяемой таблицей
256×32 бит в Flash: CRC кадра в `mt_wire.c` и накопительный CRC кодов в
`mt_live_device.c`. Для одного DATA128 это 300 + 256 обрабатываемых байт.
Полином `0xedb88320`, отражение, исходное состояние, окончательный XOR и порядок
младший/старший байт каждого кода сохраняются. Очереди, wire-кадры, частота50к,
порция TX64, IRQ grants, пределы TIME/ADC/Stop и порядок публикации не меняются.
Два source diff закреплены в `overlays/crc32.json`; константа имеет одну
дефиницию в wire translation unit, новых link objects и RAM-таблиц нет.

Оптимизация сокращает вычислительную работу; достаточную пропускную способность
и запас она сама не доказывает. Результат отдельного физического опыта должен
включать продолжительность, очередь, интервалы обслуживания и проверку raw.
Узкая нативная проверка сравнивает фактические новые C-функции с исходным
побитовым oracle, полными wire-кадрами и raw сохранённого опыта:

```powershell
.\.venv\Scripts\python.exe -I -B tests\v2-stream-firmware\check_crc_equivalence.py --image build\v5-fw-candidate --traffic build\v5-board-stream-03\run\traffic.bin --zig PATH_TO_LOCAL_ZIG_EXE --output build\v5-native-crc
```

Нативное время на ПК не является оценкой скорости Cortex-M3; ARM ABI, таблица
в Flash и стек проверяются по новому точному ELF.

## Проверяемая граница

Результат содержит ELF, BIN, HEX, map, дизассемблирование каждого объекта и образа,
`.su`, исходный архив, копию рецепта, hashes, команды и receipt. Векторы/Reset,
ARM ABI и секции проверяются функциями исходного `tests/boot-link`; checker не
запускает его полный test suite. `check_static.py` дополнительно сверяет:

- Все input code sections, включая оставшиеся анонимные weak bodies; их `.su`
  сопоставляются с обходом SP/CFG, выходы восстанавливают стек, call SP кратен 8.
- Каждый косвенный вызов имеет явное множество целей из закреплённых constructors;
  CDC table и OSAL lock pointers проверяются в ELF. Для отсутствующих CDC ISR/SOF
  и недостижимого deferred-function event используются явно записанные исключения.
- Нет рекурсии, неизвестных целей/PC/SP writes, динамических кадров или скрытых
  switch tables. К foreground максимуму добавляется один USB software frame и
  три аппаратных exception frame по 36 байт. NMI/HardFault — terminal Default_Handler.

Численный результат относится к **точному ELF** и предположениям отчёта.
Это не измеренный high-water mark. Изменение compiler/config/source требует новой
сборки и анализа. Проверка запечатанных артефактов возможна отдельно:

```powershell
.\.venv\Scripts\python.exe -I -B firmware\v2-stream\check_static.py build\v5-fw-candidate
```

IRQ ownership и Stop взяты из одного foreground runtime: он обслуживает TIME/USB,
немедленно передаёт не более одного ADC блока в очередь; при потере epoch/DTR
останавливает аппаратный источник; не освобождает DMA storage при неудачном Stop.
Остановка выключает TIM3/ADC/DMA и проверяет фактический off. Это source contract,
его исполнение на данной плате до опыта не подтверждено.

## Открыто до и во время ограниченного опыта

Полный `mt_live_device_step` пока сохраняет исходный PRIMASK guard ради атомарного
учёта bytes/epoch. Recovery может вызвать quiesce с ожиданием до 1000 мкс плюс
обвязка. Параметр `transaction_bound_ms=1` — **предварительный**, не WCET.
Его нельзя выдавать за доказанный срок Stop или отсутствие потерь.
Реальный интервал обслуживания DMA должен быть меньше 2560 мкс; USB CTR fairness
сам по себе не доказывает это при lifecycle IRQ. Изменение границы блокировки
требует отдельного анализа гонок USB reset и irreversible accepted bytes.

`produced_known=0` остаётся намеренно: DMA-prefix не доказывает последний отсчёт ADC.
Даже нормальный END означает неизвестный хвост, а не полную запись без потерь.
Проверка транспорта может подтвердить доставку/сохранение полученного префикса.
Последующая низковольтная проверка потребует известного безопасного сигнала,
определённого аппаратного входа и отдельной калибровки.
