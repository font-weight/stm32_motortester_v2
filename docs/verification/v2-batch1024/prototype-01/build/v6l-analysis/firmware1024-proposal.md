# L: изолированный TX-only прототип DATA1024

25.10.2026. Это предложение и прототип, не изменение установленной SD и не
приёмка150k. Вход: SD source `cb4757940b3ee9968f953becfbc3ca8caea102d7`,
`build/v6k-fw-01`, сохранённый K2. Root отдельно разрешил эту область после
возобновления работы пользователем. COM/SWD/Flash не входят.

K2 передал3077376 canonical кодов, затем queue-full через20,602с Record.
Wire/файл совпали, ENDreason1/flags3, queue8, ADCfault0, poll1572мкс,
copy156мкс. Это отрицательный опыт; он не доказывает ни средний CPU deficit,
ни отдельную причину задержки. Коды/неизвестный хвост не переопределяются.

## Выбранный узкий путь

Сохранить wire0.3 layout, новый явно согласуемый mode5/max1024. Передавать
первый байт DATA только после известного count:1024 или фактический короткий
хвост после Stop/seal. ADC продолжает работу; collection постепенно переносит
владение128-блоками в packed TX staging. Queue pop означает этот перенос,
**а не** принятие wire или продвижение committed prefix. Это новый контракт
владения, который должен пройти отдельное ревью перед интеграцией.

Metadata20 + packed1280 + header24 + frameCRC4 =1328 raw. COBS worst с
delimiter1335. TX capacity1336. Не менять общий FRAME_MAX544: rx и previous
остаются прежними. Иначе три массива увеличились бы минимум на2373байта,
превысив свободные916байт. Текущий whole-fit384 применяется к каждому
неизменяемому фрагменту одного кадра, а не ко всему1335: до384байт, затем
следующий offset, один итоговый delimiter. Это один DATA, не четыре DATA256.

Количество полных DATA/с:146,484375 вместо585,9375. Worst wirebytes/с:
195556,640625 вместо217382,8125, сокращение около10%, не в4раза.
Минимум четыре writes384 на полный1024 остаются примерно столь же частыми,
как четыре прежних DATA256. Размер пакета сам по себе не доказывает150k.

## Конкретная память

| Объект | SD | Прототип/предложение |
|---|---:|---:|
| RX / previous |543 /543|без изменения|
| TX |544|1336, +792|
| Новый pointer-free state |0|32|
| Queue / DMA / CDC FIFO |8×128 /1024 /384|без изменения|
| Static data+bss |11372|расчёт12196|
| Static +8192 stack reserve |19564|расчёт20388 из20480, остаётся92|

Это арифметический бюджет, **не** exact linked map. Размер state закреплён
`_Static_assert`. Изменения общего message/raw массива запрещены: не создавать
`mt_wire_message.payload[1300]` или `raw[1328]` на стеке. Старый условный
stack bound6116 не переносится автоматически на интеграцию;8192 остаётся.
Текущие tx identity/nonce/index/sequence поля предполагаются повторно
использованными; модель не добавляет ещё одну identity в статическую SRAM.

TX layout при сборке:7байт запаса слева, raw header24, metadata20,
packed≤1280, CRC4. Raw занимает `[7,7+raw_length)`, конец максимум1335.
После CRC COBS идёт **вперёд на месте**, output с0, input с7. Максимальное
расширение до5 внутренних code-slots плюс первый code и delimiter укладывается
в7; запись не опережает ещё не прочитанный raw. Никакого memmove/full scratch.
После подготовки кадр занимает `[0,frame_length)`, frame_length≤1335.

State32: два uint32 rollingCRC; десять uint16 для count/rawlen/COBS
read/write/mark/code/phase/packedlen/TXoffset/framelength; uint32 prefix_seed.
CRC prefix по canonical u16le считается при collection в candidate; frameCRC
по header+metadata+packed — после поздней фиксации length/count. Только
финальный успешный commit публикует candidate prefixCRC и first+actualcount.

## Стадии и владение

1. EMPTY→COLLECT. Существующая identity фиксирует nonce/gen/config/first/seq.
   Collection quantum до512 отсчётов, соответствует DMA512 burst. Проверить
   ВСЕ исходные ADC12 и indices до копирования; canonical=(code>>2)<<2.
   Самостоятельный модуль не читает DMA и не снимает аппаратные guards.
2. Чистая prepare работает с копией32-byte state и свободной областью TX.
   До queue pop проверяются epoch/lifecycle/time/identity и ВСЕ borrowed views
   выбранного quantum. До мутаций validate-all, затем одна atomic ownership
   transaction: pop до4×128 и publish prepared state. Сразу освобождаются
   source slots; committed prefix пока прежний. Не ограничиваться128 за новый
   полный runtime loop: producer выдаёт512, такой scheduler мог бы отстать.
3. При1024 — SEAL. При Stop сначала hardware barrier/snapshot/tail/seal,
   затем собрать реально оставшийся prefix и SEAL фактическим count1..1023.
   Count0 не порождает DATA. Нет ожидания1024 после Stop, padding отсчётами,
   мостика через gap или скрытой паузы АЦП.
4. Поздние header length/count, frameCRC, in-place COBS. Каждый проход
   обрабатывает≤512 raw bytes; вызов не ждёт USB. В интеграции ADC/TIME service
   между bounded quanta обязательны. Число quanta/их scheduler ещё требует
   проверки: отдельный полный runtime loop на каждый мелкий этап может
   уничтожить ожидаемую экономию. Не объявлять WCET по счётчику bytes.
   Обязательных3CRC+3COBS полных runtime loop нет: модуль resumable;
   integration может объединять несколько quanta с последним collect только
   при отдельно подтверждённом ADC service interval<3413мкс. Scheduler TBD.
   COBS destructive: старый state не откатывает уже изменённый storage.
   После quantum публикуется монотонный cursor, либо при stale epoch/TIME
   весь in-flight frame уходит в abort/recovery; повторять старый cursor
   поверх изменённого raw запрещено. Work-copy транзакционность collection
   свободной области не переносится автоматически на CRC/COBS стадий.
5. READY/SEND: `min(frame_remaining,384)`. Для каждого фрагмента прежние
   whole-fit, known0, exact-positive/partial, epoch/TIME pre/post guards.
   Ready bytes immutable до known acceptance. SIZE_MAX/невозможный ответ или
   post-write TIME — fail-closed; committed prefix не угадывается.
6. Только после ВСЕХ известных accepted bytes, final TIME и identity check
   атомарно publish count/end/candidateCRC/sequence. Не пересчитывать2048
   canonical bytes под PRIMASK: кандидат подготовлен раньше; доказательство
   связи candidateCRC с immutable frame — отдельная часть нового контракта.

При USB loss/Abort/ошибке незавершённый COBS frame не становится host DATA.
Host публикует raw только после полного bounded frame/CRC/count/pad check.
Уже popped→staging, но не committed отсчёты не исчезают из учёта: это отдельный
in-flight диапазон, при невозможности доставить — incomplete/unknown tail.
На обычный Stop retained tail должен быть доставлен. Replacement HELLO
потребует явно решить: завершить старый неизменяемый кадр под старой identity,
либо barrier+delimiter с неполным старым сеансом; не достраивать его новыми
данными. Прототип не выдаётся за реализацию этих lifecycle ветвей.

## Почему сейчас без footer0.4

Early streaming header с ещё неизвестным count потребовал бы footer/0.4 и
новый decoder. Он может экономить SRAM, но расширяет согласование и recovery.
Здесь packed staging делает count известным до отправки, поэтому layout0.3
не меняется. Mode5/discovery/max_payload1300 должны быть отдельно объявлены;
mode4 и исторические файлы не переосмысливаются. Host proposal должен
обновить прежнюю рекомендацию0.4 для выбранного позднего header варианта.

## Ограниченный первый результат

Изолированный модуль `firmware/v2-stream/batch1024/`, один native runner/model
в `tests/v2-stream-firmware/batch1024*`: independent CRC/COBS oracle,
1024 и Stop-tail1/2/3/127/128/129/1023, bounded quanta/zero/partial/unknown,
неизменный внешний prefix до полного guarded commit, bad ADC до masking,
границы буфера/canaries и partial-frame не публикуется. Это API/serializer
proof, не actual runtime/ADC/epoch proof. Только после него — окончательный
контракт/критик, интеграция, exact ARM/map/stack и отдельный аппаратный план.

Исходники SD и сохранённые K2 результаты остаются неизменными.

## Сохранённый первый результат прототипа

`build/v6l-native-01/result.json` — PASS первым запуском; три адресные группы.
State32 подтверждён native/ARM `_Static_assert`; отдельный ARM object1208text,
data0/bss0. `.su` отдельных функций: collect36, begin24, step24, commit20,
piece16, accepted12; это не полный stack bound будущего runtime.
Worst1335, partial/zero/unknown, canaries, хвосты и independent CRC/COBS oracle
прошли. Критик до запуска выявил shared-byte speculative append: исправлено
сохранением только already-owned low bits; точный retry witness включён.
При destructive COBS stale-guard — abort, а не повтор старого cursor.

Fixture `batch1153-transcript.bin`: DATA1024seq4, tail129seq5, synthetic ENDseq6,
nonce503/gen3/mode5, prefix1153. Его native проверка не исполняет production
Stop/HELLO/epoch или queue pop; эти обязательные ветви пока не реализованы.
Точные hashes и известные ограничения — в prototype freeze после crossdecode.
