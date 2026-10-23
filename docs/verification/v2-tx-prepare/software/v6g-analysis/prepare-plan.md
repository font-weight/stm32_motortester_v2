# V2-06g: prepare/commit TX, предварительный контракт

Software-кандидат V2SA/build0x56325341, Fs100k. База рабочего поведения S8; S9observer не компилируется при явном `active_profile_enabled=false`. Его исходники/overlays/образ сохраняются, legacy136 включён. Никаких COM/SWD/Flash.

API ядра:

- `mt_live_prepare_result mt_live_device_prepare_tx(mt_live_device *d, mt_live_tx_ticket *ticket)` возвращает `MT_LIVE_TX_EMPTY`, `MT_LIVE_TX_PREPARED` или `MT_LIVE_TX_ERROR`.
- Prepare пишет только существующие `tx[]` и относящиеся к нему `tx_*` metadata, плюс caller-owned ticket. Cached frame не перекодируется. Нет clock/write/quiesce/isolate/receive/offer callbacks, state transition, queue pop, sequence advancement, prefix/CRC commit. Encoding/sequence error записывается в ticket.error, recovery отложен.
- `int mt_live_device_step_prepared(mt_live_device *d, const mt_live_tx_ticket *ticket)` выполняется только внутри прежнего PRIMASK guard. Сохраняет порядок всех исходных now/expire/deadline, recovery, write, final time и commit. На месте прежнего build использует ticket; непосредственно перед write повторно проверяет ticket.
- `mt_live_device_step(d)` сохраняется как compatibility/oracle path, с исходным guarded построением и deferred error немедленно внутри того же guard. Native baseline собирается отдельно из exact S8; это не новый производственный путь runtime.

Ticket — bounded caller-owned stack record, без второго byte buffer/нового static. Снимок после prepare: result/error; core state, nonce/pending_nonce/generation; tx_next/exhausted/sequence/type/nonce/first_index/count/length/offset; queue head/head_index/next_index/used/sealed/head_count; wants/capture-delimiter/hardware-off; prefix_end/CRC. Поля transport epoch и soft_serial принадлежат отдельным runtime-local stamps. Предельный размер/стек подтверждаются ARM build.

Нормальный порядок runtime: исходные ADC/RX/TIME/loss/usable barriers → сохранить epoch/soft_serial → prepare → IRQ guard → проверить прежний usable (включая hardware lifecycle/actor/epoch), equality сохранённых epoch/soft_serial → prepared step → unlock → все прежние TIME/loss/flush/grant. `live_write` также сохраняет прежнюю immediate usable и whole-fit проверку внутри guard. Если transport stamp stale, core step не вызывается; затем исходная synchronize_loss обрабатывает actual loss. Stale core ticket означает known no-write/no-commit и возврат no-work; текущий допустимый cached frame не уничтожается (например Stop переводит его в drain), следующий prepare строит новый актуальный ticket. Никакой unknown acceptance не превращается в zero.

Подготовка использует sole foreground ownership: ISR меняет USB/epoch, но не core/queue/staged bytes; ни другая FG операция, ни reentrant callbacks между prepare и commit не разрешены. Ошибка prepare вызывает recover только после original argument/time/expiry guards в prepared step. Первичная причина/разделитель/известные accepted bytes/partial-write offset и prefix rules прежние. Reserve-sequence termination может сделать ticket stale; в этом проходе нет write, следующий prepare видит actual draining state. completed()/rolling prefix CRC/pop остаются guarded.

Одна narrow native model: одинаковый deterministic wire transcript S8 и V2SA при готовых данных, whole zero/partial writes и Stop/END/ACK; prepare callback purity/cached/error; stale nonce/gen/head/queue/sequence и actual runtime transport-guard seam; TIME до/после write, unknown count и prefix/delimiter. Модель не доказывает ARM WCET или100k. Не повторять GUI/host/широкий USB/driver suite. Exact ARM64KiB/20KiB/stack8192, source guard proof и независимый critic≥9.5 требуются до отдельного physical plan.

Гипотеза: убрать чистое frame build из общей IRQ-off скобки, чтобы уже разрешённый USB мог продвигаться во время encode. Общая CPU цена encode не исчезает; достаточность для100/200k неизвестна.

Ticket/device non-aliasing и запрет вмешательства FG обязательны; поля сравниваются явно без padding. ERROR обрабатывается только после match. Следующие prepare после actual Stop/HELLO входят в модель. Legacy tx_max в новом образе исключает prepare; step/poll охватывает его, старые TX maxima напрямую не сравниваются.
