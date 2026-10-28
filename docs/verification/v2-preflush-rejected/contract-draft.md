# T/SM: предварительный flush — NO-GO по штатному CDC пути

28.10.2026. Только проект дельты к принятому S
`docs/streaming-postcopy-handoff.md`, SHA
`521e91d88b8234be6f8db7cbecfd79b6f4bd4c47dbb38dd871242a0d97b1b149`.
Предложенная identity — SM/`0x5632534d`, config → общий generated header.
**Реализацию не начинать:** необходимое полезное состояние не достигается
рассмотренными healthy S/CDC переходами. Production, native, ARM и аппаратура
по T не изменялись/не запускались; SL остаётся установленной. Это отказ от
одной гипотезы, не вывод о невозможности устойчивых150k.

## 1. Гипотеза и решение

Предлагалось в selected S handoff, после actual private512, cached-final
mode5 ticket и consumed markers, выполнить один `tud_cdc_n_write_flush(0)`
перед прежними sole grant/cached TX. Old postflush, final-TIME commit, Q и
offers оставались бы на месте. Ожидание: раньше начать buffered transfer и
освободить FIFO до единственной write opportunity.

S2 сохранил поздний FIFO384, исторический RESUMED PRE320→POST384 и
непринятый остаток183. Он не сохранил вход hint, endpoint state при write или
время освобождения FIFO. Эти данные не доказывают полезность T.

**NO-GO:** preflush не обслуживает completion task. Большой buffered FIFO
в healthy reachable пути уже автоматически отправляется либо endpoint
остаётся BUSY до task, который сам немедленно запускает этот FIFO. Flush
между этими переходами не создаёт новой возможности. Полезный
buffered+claimable endpoint нельзя назначить в модели произвольно.

## 2. Основание по exact SL source

Строки относятся к `build/v6s-fw-02/`. TinyUSB root —
`source/firmware/third_party/usb/vendor/tinyusb/src/`.

| Переход | Действие |
|---|---|
| `tusb.c:425–434`, stream write | После FIFO write вызывает write_xfer при count≥MPS64. |
| `tusb.c:401–421`, write_xfer | Count>0 → claim; ep_buf=NULL → xfer текущего FIFO count. Task не вызывается. |
| `tusb.c:227–241`, claim | BUSY или CLAIMED запрещают claim. |
| `patched/usbd.c:219–228,1595–1618` | CDC xfer_isr=NULL: completion ISR не снимает BUSY. |
| `patched/usbd.c:842–862` | Completion task снимает BUSY/CLAIMED и сразу вызывает class callback. |
| `class/cdc/cdc_device.c:515–523` | CDC callback немедленно вызывает write_xfer buffered FIFO, иначе рассматривает ZLP. |
| Там же `:91–93` | Weak tx_complete пустой; override в SL firmware не найден. |
| `patched/v2/app/mt_live_runtime.c:433–454` | tud_task_ext находится до ADC/private-copy/handoff. Другой foreground writer внутри CDC callback отсутствует. |

Последовательность healthy передачи:

1. Write с FIFO≥64 уже попытался xfer. Успешный submit ставит BUSY;
   начальный PMA64 и дальнейшие IN извлекают bytes из FIFO.
2. До task обработки final completion BUSY сохраняется, даже после ISR.
   T flush вернёт0 из claim и не ускорит обработку completion.
3. Task снимает BUSY и в том же foreground вызове CDC callback отправляет
   buffered FIFO. После callback endpoint опять BUSY либо FIFO пуст.
4. Completion, пришедший после task во время ADC copy, снова означает п.2.

FIFO<64 не даёт контрпример S2: при остатке183 недостаток места означает
FIFO count>201, то есть auto-flush порог пройден. Штатные mode5 full offers384
дают cached-final offset1152/остаток≤183 при tx_length≤1335. Whole-fit admission
проверен под прежним IRQ guard, foreground writer один. Ошибочную partial/
unknown ветвь нельзя считать новым healthy состоянием ради T.

Submit failure/epoch loss, teardown/stall, чужой writer или искусственное
снятие BUSY требуют quarantine либо меняют предпосылки. Малый FIFO между
write и old postflush не предоставляет другому runtime handoff точку входа
в том же foreground. Это source-вывод при заявленном ownership/lifecycle,
не измерение CPU и не установленная единственная причина S2 queue-full.

## 3. Условная дельта и outcomes — не допуск реализации

Сохраняем границу отвергнутой идеи: возобновление требует конкретного healthy
source counterexample к §2 и нового ревью, а не удобного synthetic initial state.

Точка — `postcopy_handoff:398–408`, после actual ticket и
`handoff_consumed=1; grant_attempted=1`, old fresh TIME/identity, перед grant.
Одна nested same-actor app scope, одна flush, LIFO leave на любом исходе.
Затем новые fresh live_time/saved epoch/soft/session/actor checks, не stored
healthy() и не bare synchronize_loss→IDLE с pending512. Далее прежние
grant→postbarrier→guarded cached TX→final TIME→postflush→Q→offers. Не добавлять
T в modes1–4, control, uncached/EMPTY или отменённый hint. Не большой PRIMASK.

| Исход | Диспозиция |
|---|---|
| Scope отказал, old identity/TIME пригодны | Пропустить только preflush; прежняя одна S opportunity, без scope retry. |
| Empty/BUSY/claim отказ, return0 | Продолжить S один раз. Нуль не различает эти причины и submit error; не ждать. |
| Flush positive≤384 | Scheduled stream bytes, не FIFO acceptance/delivery. Не менять N positive, offset/sequence/CRC/prefix/Q. |
| Submit fault, TIME/epoch/raw lifecycle loss | Postcheck → typed TIME/hard-loss S abort; pending ABORTED, не IDLE с забытым private512. |
| Невозможный count>384 | Transport contract failure/quarantine, не CLOCK/source2; без повторного submit. |
| Нет IN/места для remainder | Actual write known0; commit/Q нет, offers либо честный queue-full, no spin. |
| Actual positive DATA | Прежний core считает acceptance; final prefix только после прежнего последнего TIME. |
| Partial/unknown/final error после escaped bytes | Прежние recovery/delimiter/unknown tail; без rollback prefix и второго DATA. |

Flush необратимо меняет claim/BUSY/FIFO read/DCD/PMA; rollback/retry после loss
запрещён. Return384 не означает FIFO free384: сначала PMA получает≤64, прочее
требует IN. Consumed markers не сбрасывать даже при0 actual grant/write;
next-pass lifecycle fallback наследуется от S. Каждый pending exit —
PUBLISHED либо explicit ABORTED; до disposition нет RX/второго read/reinit.
Старые stores до наблюдения asynchronous loss карантинируются до следующего
wire/new identity/normal END. Невозможность таких stores не обещается.

## 4. Неподвижные границы и цена

Old service/driver/DCD/MMIO/TIME, bridge/core/queue/serializer/wire,
Q certificate/collect≤512, postflush и136/64/24 ABI сохранялись бы exact.
Deadline3413 от исходного last_poll_us без refresh; grant6/<500 прежний.
500 — continuation admission, не whole-IRQ WCET. Maxpoll2939 не квалифицирует
новый flush/barriers/PMA work.

0newstatic, FIFO384/staging1336/queue8 и reserve8192. В SL
12284static+8192=20476 из20480:4B не бюджет новой телеметрии. При возможном
возобновлении нужны exact linked RAM/stack/common SM identity. Старые
prepare/TX/Q spans остаются: preflush входит в step/poll wall, но не TX stamp.

## 5. Gate исследования и практический отказ

**Текущий gate — NO-GO на source review**, без нового executable/образа.
Добавлять redundant API call и аппаратный опыт числом S2 пакетов не обосновано.

Если предъявлен counterexample, одна focused actual-runtime модель должна
вывести его реальными CDC write/autoflush/completion переходами, actual
stream claim/BUSY/FIFO и явными PMA64/IN стадиями. Не назначать BUSY0/FIFO320
и не заменять flush/grant присваиванием fifo_free384. В том же executable
actual core должен показать certificate/Q/pending disposition. BUSY/no-IN,
scope/loss/final-error — отказ без второй opportunity. Только после witness
оправданы ARM/resources, SM24/64+synthetic136, exact critic≥9,5 и отдельный
root hardware plan; old broad suites не нужны.

Аппаратный успех при будущем новом допуске — весь запрошенный непрерывный150k
интервал без source fault. Queue-full/deadline не принимать по числу DATA.
Не начинать серию новых flush/grant перестановок по одному snapshot: текущий
NO-GO требует другого объяснённого изменения пропускного пути и нового scope.
