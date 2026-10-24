# V2-06i — проект трёх выбираемых профилей приёма

Статус: **DRAFT, только контракт; реализация и аппаратные действия не разрешены этим файлом**.
24.10.2026, автор higher_fs_review; согласованная рабочая гипотеза с host_200k.
Пользователь подтвердил выбор 50/100/150 тысяч отсчётов/с в приложении до начала приёма.
Это профили захвата, отдельные от UI-профилей «Осциллограф» / «Зажигание».

## 1. Основание и сохраняемая база

V2SB/build0x56325342 остаётся неизменным: `build/v6h-fw-01`, BIN SHA256
`e7f6f07fc6a43e6b109af6e5c652db1322a0e5023e328007b2c50d303f12536e`.
Root сообщил результат одного 30-секундного H2: 3 003 339 полученных raw,
queue high-water6/8, flags0, poll1384мкс, copy134мкс и остановленные регистры.
Это не доказывает бессрочную устойчивость, калибровку времени или аналогового входа.
Новый многорежимный образ не наследует физическую приёмку SB автоматически.

Основа нового образа — расписание SB, TX prepare/ticket, ранний единственный USB grant,
FIFO384, MPS64, burst6/<500мкс, DATA128, DMA1024/half512, queue8, legacy136 и profile512 off.
Проверки TIME/epoch/lifecycle/Stop, whole-fit, partial/unknown write, CRC/pop и неизвестный
хвост сохраняются. Очередь, DMA и USB FIFO не увеличиваются. Нового буфера samples нет.
Старые отрицательные образы/свидетельства не изменяются. Новый образ —
V2SC/build0x56325343 по назначению root.

## 2. Три профиля и физическая разрядность

| wire0.3 mode/config_id | Fs_num/Fs_den, отсчётов/с | ADC / сохраняемые биты | DATA encoding | Канонический код |
|---|---|---|---|---|
| 1 | 50000/1 | 12 / 12 | 1, u16le | исходный code12, 0…4095 |
| 2 | 100000/1 | 12 / 12 | 1, u16le | исходный code12, 0…4095 |
| 3 | 150000/1 | 12 / 10 старших | 2, u10packed-le | `(code12 >> 2) << 2`, 0…4092 |

STM32F103C8T6 имеет 12-битный ADC; режим150k не переключает ADC на10бит.
Он необратимо отбрасывает два младших бита при подготовке данных после безопасной
копии DMA. Физический шаг ADC остаётся прежним; передаваемый квант — четыре кода12.
Для10бит применён truncation/floor без округления или добавления середины интервала.
Потерянные два бита не восстанавливаются и не выдаются за исходный полный ADC raw.

Шкала `U_CH1=a*code12+b` сохраняет прежний кодовый домен. Профиль150k требует
явных метаданных adc_bits12, retained_bits10, discarded_lsb2, truncation и encoding.
Имя/профиль UI и выбор Fs не меняют физическую калибровку. Вход без настройки
остаётся unconfigured. Квантование не является калибровкой или улучшением точности.
Крайний q10=1023 объединяет исходные4092…4095, q10=0 —0…3: точное достижение
4095/0 по такому коду неизвестно. Saturation/threshold логика обязана учитывать эту
неопределённость; нельзя считать4092 точным отсчётом аппаратного насыщения4095.

Вариант хранить q10 как raw0…1023 отклонён для этого узла: он меняет домен
калибровки (потребовал бы gain4a), диапазоны и downstream-интерпретацию. Канонический
c12 с нулевыми LSB проще для совместимости, но маркировка потери точности обязательна.

## 3. Обнаружение версии без timeout downgrade

1. Новый host всем устройствам посылает прежний **HELLO wire0.2**: session0,
   sequence=request1, payload8=`<Q>` fresh nonzero nonce.
2. Старый firmware отвечает прежним HELLO_ACK0.2/capability_mask1. Host продолжает
   существующий wire0.2 fixed-Fs путь и проверяет реальные CAPS. Доступен только
   режим, который объявила старая прошивка; выбранную другую Fs не подменять молча.
3. Новый firmware принимает этот HELLO только как discovery. Он выполняет прежний
   quiesce/isolate/deadline барьер и возвращает HELLO_ACK **envelope0.2**, payload16:
   `<BBBBHHII>` = `(0,2,1,12,512,128,firmware_build,3)`.
   mask3 означает STREAM_BASE|REQUIRES_MODE_HELLO_0_3. Никакой START/ADC в discovery.
4. Старый app уже требует mask1 и отвергнет mask3 до START. Новый host после этого
   явного marker отправляет **HELLO0.3 с другим fresh nonce**, session0,
   sequence=request1, payload12=`<QHH>`: nonce, mode1/2/3, reserved0.
5. Только после принятого ACK0.3 и selected CAPS разрешён START. Timeout, malformed
   marker и неизвестная версия не дают автоматического повтора в другой версии.

Discovery допускает замену только новым корректным HELLO; CAPS/START/STOP0.2 не
исполняются, ERROR0.2 unsupported разрешён без аппаратных эффектов. Неподдержанный
mode/reserved не получает successful ACK и не запускает ADC. Сохраняются прежние
правила новой nonce, delimiter при частичном старом кадре, writer isolation,
переносимого deadline и known/unknown acceptance. Версия и выбранный mode имеют
pending/current поля: current identity публикуется только при completed HELLO_ACK,
а не при parse/prepare/частичном write. Старый cached ACK не может закоммитить
новый mode. Ticket получает эти поля и проверяет их fieldwise до write/commit.
TX metadata хранит tx_revision/tx_mode отдельно: HELLO_ACK commit требует их
равенства pending revision/mode и nonce. CRC-valid non-HELLO с иной session nonce
игнорируется до active revision check; wrong revision текущего nonce — fail-closed.
HELLO freshness сохраняет прежнюю проверку current/attempted nonce, а не журнал
всех исторических nonce. Отложенный не-HELLO старого сеанса не выбирает режим.
Checked envelope decode публикует revision+message лишь после COBS/length/CRC/
reserved validation; прежний strict decode API сохраняет unchanged-on-failure.

Новый firmware может также принимать прямой корректный HELLO0.3, но host для
обычного автоматического обнаружения использует описанную одну discovery ветвь.
Не добавляются SET_PROFILE, горячая смена Fs, перечисление произвольных режимов
или частичное обслуживание старого wire0.2 потока новым образом.

## 4. Полный wire0.3 сеанс

Envelope/COBS/CRC32, header24, размер512payload и номера сообщений сохраняются;
номер версии0.3 обязателен на всех кадрах полного сеанса. Нельзя менять DATA0.2.

HELLO_ACK0.3 payload16=`<BBBBHHII>`: `(0,3,1,12,512,128,build,1)`.
CAPS request2 пустой. CAPS_REPLY130 payload24:

| offset | поле |
|---|---|
| 0 | u32 config_id = выбранный mode1/2/3 |
| 4 | u16 acquisition_mode = тот же mode |
| 6 | u8 channel =0 (CH1) |
| 7 | u8 adc_bits =12 |
| 8 | u32 Fs_num |
| 12 | u32 Fs_den =1 |
| 16 | u16 max_block =128 |
| 18 | u8 retained_bits =12 либо10 |
| 19 | u8 encoding =1 либо2 |
| 20 | u32 flags =1, согласованное прежнее значение |

Host принимает только три точных согласованных tuples, остальные отвергает.
START8 payload4=`<I>` config_id, generation=request. START_ACK136 payload16
как прежде: u32 generation, u32 config_id, u64 first_index0. START допускается
лишь STOPPED после CAPS; повторные CAP/START, config mismatch и устаревшая epoch
не перенастраивают периферию. Выбор связан с nonce/CAPS/generation на весь сеанс,
включая Preview, Record, Stop-tail и drain. Для смены режима — штатный Stop,
закрытие сеанса/порта, новое подключение с новым HELLO и отдельный START.

DATA152 payload: прежний `<IIQHH>` = generation, config_id, first_index,
count1…128, reserved0; затем samples выбранного encoding. Все индексы относятся
к непрерывному физическому acquisition, не к USB-пакетам или моменту их прихода.
END153/STOP_ACK133 сохраняют layout/флаги/reason, но END.config_id — выбранный.
STOP5 payload4 generation без изменений. Другие типы/неизвестные комбинации
отвергаются; reserved поля не используются как скрытый формат.

## 5. Упаковка, CRC и единственная точка потери LSB

DMA/driver stable snapshot остаются uint16 исходных ADC12. Проверить диапазон
0…4095 до преобразования. В единственной общей функции приёма в transport queue
выполнять mode3 `c12=code12 & 0x0ffc`, mode1/2 копировать без изменения.
Этим же путём обрабатываются проверенные Stop-tail blocks; хвост не получает
иного преобразования. Нельзя мутировать DMA ring, borrowed snapshot или ранее
сохранённые данные. Existing queue storage становится владельцем canonical c12;
`offer`/tail push должны иметь явный единый домен, без скрытого двойного callback.

encoding2 передаёт q10=c12>>2, little-endian bitstream, младший бит q0 первым:
поток бит `q0 | q1<<10 | q2<<20 | q3<<30` занимает5байт. Для N отсчётов длина
ровно ceil(10N/8); неиспользуемые старшие биты последнего байта строго0.
Нет выравнивания каждого отсчёта до16бит. DATA128 содержит160sample-байт.
encoding1 содержит2Nsample-байт u16le. Host проверяет длину/padding до публикации.

Frame CRC32 защищает фактически переданный packed/unpacked кадр. END rolling
prefix CRC32 считается по **canonical c12 u16le** в порядке индексов, как после
host unpack+q10<<2. В150k это не CRC исходных отброшенных12бит. Commit CRC/pop/seq
по-прежнему только после полного подтверждённого write под guard; partial/unknown,
stale ticket, zero-space и post-write TIME не дают ложного committed prefix.

Файл может сохранить прежний2байта/sample raw payload canonical c12. Новый
versioned provenance/context обязателен и хранит wire0.3/config/mode/Fs rational,
adc12/retained10/discarded2/encoding/truncation. Имя поля raw не отменяет потери
LSB: это исходные полученные данные, а не исходные полные ADC12. Файлы0.2 и
их хеши не переписываются; loader различает revision/кодовый домен явно.

## 6. TIM3, время, DMA и Start

При проверенных TIM3 input72MHz / ADC12MHz предлагаются точные константы:

| mode | PSC / ARR | период trigger, мкс | half512, мкс | reject delta_us>= |
|---|---|---|---|---|
| 1 | 71 /19 |20/1 |10240 |10240 |
| 2 | 71 /9 |10/1 |5120 |5120 |
| 3 | 47 /9 |20/3 |10240/3 =3413⅓ |3413 |

Formula Fs=72000000/((PSC+1)*(ARR+1)). TIM2/TIME остаётся1MHz; не менять его
clock backend или checks. При integer-microsecond наблюдениях mode3 threshold
3413 консервативен: разрешённый delta<=3412 даёт фактический интервал<3413мкс
при исправном номинальном1MHz источнике, что меньше3413⅓. Не округлять deadline
вверх до3414. Все copy/progress/Stop-tail/service проверки используют один
выбранный descriptor и сохраняют wrap semantics. DMA ring1024 не меняется.

First-trigger-offset задаётся рационально20/1,10/1,20/3мкс; внутренний metadata
не может содержать ложное целое6 или7мкс для150k. Первый update следует за одним
номинальным периодом после TIM3 CEN, CNT0/UG/trigger gating как вSB. Относительное
время графика/CSV: t(i)=(i-i0)*Fs_den/Fs_num, без накопления округлённых6/7мкс.
Absolute CEN bracket остаётся отдельной неопределённостью; ADC aperture/latency
не измерены. Для узкой observed CEN bracket предлагается bound20/10/5 TIM2ticks
с прежним readback и pre/post full validation. Новая граница150k допускает5ticks
(физический интервал<6мкс при исправном номинальном1MHz TIME), отвергает6ticks;
это консервативнее периода20/3мкс. Граница — не точное время апертуры. На реализацию
выделить константу start_bracket_max_us отдельно от rational sample period.

ADC sample41.5+conversion12.5cycles/12MHz =4.5мкс плюс trigger latency;
это расчёт совместимости периода150k, не подтверждение установления аналогового
входа/точности. Все профили используют тот же sample time и ADC12.

## 7. Бюджет передачи и границы ожиданий

| режим | DATA128 wire max | frames/s | wire B/s без редких control | IN packets/s max |
|---|---|---|---|---|
| 50k12u16 |307 |390.625 |119921.875 |1953.125 |
| 100k12u16 |307 |781.25 |239843.75 |3906.25 |
| 150k10packed |210 |1171.875 |246093.75 |4687.5 |

Дляpacked: raw frame24+20+160+4=208байт, COBS+delimiter максимум210;
4USBпакета вместо5. Полезный wire темп лишь на2.606% выше100k12, но число
DATA/encode/commit операций на50% выше, IN packet events на20% выше и deadline
на⅓ короче. Поэтому150k не обещается по успешному100k или снижениюpayload.
128×q10 вuint16 не экономитUSB: обязательна плотная упаковка.

USB framing уже пакетный, приложение уже соединяет блоки по source indices.
Здесь ADC/TIM3/DMA не останавливаются между пакетами. Если будущий оконный
Stop→transfer→restart вариант понадобится отдельно, паузы показывать как gap
с неизвестной длительностью, не склеивать их в якобы непрерывную искру.

## 8. Ограниченный объём реализации и необходимые свидетельства

После принятия контракта: один const descriptor table профилей; небольшая
HELLO revision/mode state branch и ticket pins; выбранный config вwire;
packer/unpacker + canonical queue ingress/CRC; параметризация driver ready/start/
service/metadata; host selector доConnect/START и versioned provenance/loaders.
Очереди/USB task/fairness/runtime order/ADC sample не переписываются.
Ожидается несколько связанных модулей, не отдельные прошивки/новый runtime.
RAM вSB оставалась948байт сверх stack reserve8192; exactARM/static обязателен,
добавление второго staging/samplebuffer не входит в объём.

Адресные проверки: wire0.2 unchanged/0.3 discovery selection и stale identity;
packing full/short/pad/CRC и canonical prefix; descriptor50/100/150 timer/deadline/
rational metadata/Start bound; сохранённые epoch/TIME/partial/Stop boundaries.
Одна небольшая native-модель изменённого core/driver path и несколько host fixtures,
source equality неизменённых guards, один итоговый ARM/static + независимый critic.
Не повторять всюUSB/GUI/унаследованную suite. Аппаратный опыт каждой Fs отдельно,
по точному плану root после допуска; обновлённый100k также нужно подтвердить.
Выбор150k пока лишь доступная software-конфигурация, не принятая характеристика.

## Основания и оставшиеся решения

Exact host file API: `host/docs/stream-modes.md`, согласованная редакция
SHA256 `0e98abc0d0fa7df79dc77ffe8b56c47f83f00063d5001f369db950af5f577da5`.
Новые magic3/direct и4/attempt, companion3; strict migration старых1/2 без
изменения файлов. StreamIdentity intrinsic поля: acquisition_mode,
source_adc_bits, retained_bits, discarded_lsb, wire_sample_encoding,
normalization, quantization, stored_sample_encoding, stored_code_domain.
Mode3: `(3,12,10,2,u10packed_le,left_shift_2,truncate_lsb,u16le,adc12)`;
mode1/2: `(1|2,12,12,0,u16le,identity,none,u16le,adc12)`. Revision0.3-modes-20261024
явно различает config namespace. Canonical10 проверяется и без companion.
Legacy CAPS Fs mismatch запрещает Connect/START до нового явного выбора.

Локальные факты: `build/v6h-fw-01/patched/v2/protocol/mt_live_device.c/.h`,
`platform/adc_timer_dma.c/.h`, `app/mt_live_adc.c`, `app/mt_live_runtime.c`;
`host/motortester/stream_wire.py`, `stream_provenance.py`, `stream_recording.py`.
DS5319 Rev20, ADC12 и tconv=tsample+12.5: [официальный ST datasheet](https://www.st.com/resource/en/datasheet/stm32f103c8.pdf).
RM0008/ES096 основания clock/TRGO/DMA — существующие `docs/sources.md`;
максимум datasheet не характеристика готовой платы.

Root разрешил обратимый черновик параллельно с независимым review контракта;
приёмка требует согласованных wire numbers/marker/selected tuples, canonical
raw/provenance и rational timing. Точный file schema/API фиксируется с host
до записи новых файлов. Неизменённая SB доступна отдельно; Flash не разрешён.
