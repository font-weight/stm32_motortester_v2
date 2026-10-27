# Черновой S9 profile ABI1, единственный банк512байт

Нормативные имена/enum/offsetof — `mt_stream_profile.h`. Типы только uint32,
64-битные индексы — lo/hi. Всё добавленное static состояние помещается в
`volatile mt_stream_profile_record mt_stream_profile`; второго frozen-банка,
внешних helper globals или snapshot на стеке нет. Размер512, alignment4.

| Байт/слова | Содержимое | Writer |
|---|---|---|
|0…63 /0…15|magic/version/bytes/build/state; fg_flags; irq_flags; generation/epoch/nonce_lo/hi; start_before/after; end_before/after; close_kind_reason|FG, кроме irq_flags — только ISR|
|64…231 /42слова|14×{count,cycles_sum,cycles_max}, порядок enum MT_P_*|FG, кроме USB_ISR и GRANT_FIRST_IN_DELAY — ISR|
|232…319 /22слова|enum MT_P_C_*|FG 0…5,7; protected FG8…12; ISR6,13…21|
|320…351 /8слов|initial head/next/prefix/ADC index lo/hi|FG на ACTIVE|
|352…431 /20слов|first snapshot:4indices; used/remaining/last_poll; packed core_state/first_reason; packed ADC_state/first_fault; core.local_error; TXoffset/length;4partial cycles|FG на первом close|
|432…511 /20слов|private table ниже|как ниже|

close_kind_reason: high16 close kind, low16 **переданный первичный reason**.
RECOVERY7: primary=mt_live_local_error, ADC8: primary=mt_adc_dma_fault_t;
FAULT1: protocol source reason, STOP2/CAP3:0, TIME4:protocol clock3,
TRANSPORT5:0, NO_START6:0. NO_START не имеет active elapsed/partial durations;
при закрытии ARMED pre-active open tickets очищаются до публикации CLOSING.
`mt_profile_attempt(generation,nonce,epoch)` сохраняет identity в ARMED после
возврата настоящей start transaction, в том числе при неудаче; не включает
ACTIVE. Begin повторяет те же метаданные на успешном запуске.
Это независимо от snapshot core.first_reason: при queue-full до terminate
последний может быть0. packed state low16 / reason high16; исходные enum
проверять на16-битную представимость и поднимать metadata-invalid при отказе.
FG/ISR flags не используют общий RMW. После CLOSING оба банка стабильны;
decoder проверяет каждый отдельно, не смешивает benign partial/history flags
с invalid/saturation.

| Private word | Значение и ticket | Writer |
|---:|---|---|
|0,1,2|FG phase id/start/open; open0=нет,1=полный,2=synthetic start partial|FG|
|3,4|STEP start/open с теми же0/1/2|FG|
|5,6|TIME start/open; TIME не рекурсивна|FG|
|7,8|grant start/open|FG внутри существующего IRQ guard|
|9|grant seen-IN; reset0 на grant, set1 на первом IN|reset FG под прежним guard, set ISR|
|10,11|write kind/действительный known accepted этого TX; UNKNOWN accepted=0|FG|
|12,13|initial FG/STEP partial cycles, отдельно от completed-call stats|FG|
|14,15|min/max32 raw-read **пар**, units cycles per pair|FG до ACTIVE|
|16,17|ARM32 адреса постоянных device/ADC объектов, bound init|FG до ACTIVE|
|18|begin phase id для synthetic partial|FG на ACTIVE|
|19|last-IN-completion cycle, HAVE_IN в irq_flags определяет валидность|ISR|

GRANT_START/OPEN читаются ISR, обновляются FG только в существующем IRQ guard.
GRANT_SEEN_IN — явное исключение single-writer: FG reset под тем же guard,
ISR set после него; новой блокировки нет. Все остальные поля FG/ISR раздельны.
USB_ISR измеряет C-body dcd_int_handler; exception stacking/наружный tusb
wrapper в него не входят и остаются в wall/residual, не «нулевая цена».

Начало внутри RX/STEP: при ARMED phase/step entry не тратит raw-read, только
обозначает текущий FG phase. На ACTIVE их start синтетически=start_after,
open=2. Первый возврат сохраняет clipped remainder в private12/13 и не
выдаёт его за полную длительность вызова. Если до возврата пришёл first-close,
остаток сохраняется в first.open_* по end_before, ticket2 остаётся видимым.

После ACTIVE→CLOSING ни один ISR/FG/time/step/grant эпилог не пишет **ничего**,
включая open flags. Сохраняются открытые stamps; первая причина неизменна.
Partial TX имеет generic phase TX и write-kind/accepted10/11: положительные
байты не становятся автоматически committed DATA; ошибки TIME/OTHER не
обнуляют уже accepted. Freeze из live_write/TIME не планируется, но сохранённый
open TIME stamp позволяет декодировать и такой частичный интервал без поздней
записи. В production-binding нет ожидания/реентера/новых масок IRQ.

IN publication — FG counters, IN completion — ISR counters. Из-за граничных
transfers эти величины не являются conservation invariant wire/raw. Максимум
IN completion gap в counter6 измеряется modulo32 между наблюдёнными IN,
не от ACTIVE до первого IN и не как доказанный host stall. Самый первый IN
ставит HAVE_IN. Это заменяет избыточный live_time-call counter; полные TIME
updates по-прежнему имеют count/sum/max.

Cap — target checkpoint18000000cycles. Actual elapsed/overshoot выводить из
end_before-start_after; границы start/end bracket расширяют неопределённость.
Ничего не обрезать искусственно до250мс. Read-pair calibration × reads/2 —
только heuristic indicator части observer cost, не lower bound всех hooks.
Decoder не вычитает его из фаз. Профиль не квалифицирует100k/200k.
