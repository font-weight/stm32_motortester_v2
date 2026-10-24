# V2-06k — DATA256 при непрерывном АЦП150k

Контракт редакции1, 24.10.2026. Требование: V2-STR16. База программы
`310d53b10c79a48ddc45357ff65d88c686aef883` / V2SC. Новый build назначен
**V2SD / 0x56325344**. Это ограниченное изменение передачи, не подтверждение
устойчивости150k или характеристик аналогового входа. Статус и свидетельства —
[progress](progress.md), независимая приёмка — [quality-gate](quality-gate.md).
Базовый контракт [I](streaming-selectable-profiles.md) сохраняется, кроме явно
перечисленных дополнений. Исходные предложения сохранены в
`verification/v2-batch256/analysis-01/`; незавершённая TIME-оптимизация J сюда
не входит и не внедряется одновременно с пакетами.

## Результат и неизменяемые границы

Непрерывный ADC150k наполняет прежние DMA1024/half512 и очередь8×128.
Два соседних блока объединяются в DATA256 без второго массива отсчётов.
Это уменьшает число DATA/с с1171,875 до585,9375. Время отсчёта остаётся
20/3мкс; приложение соединяет только непрерывные source indices. Паузы АЦП,
скрытое заполнение пропусков и увеличение очереди не входят.

Сохраняются TIME/epoch, bounded USB burst6/<500мкс, FIFO384, max write384,
staging544, ADC sample time, IRQ guard и правила Stop/fault. Переполнение
остаётся явным отказом с сохранённым префиксом. Неизвестный произведённый
хвост остаётся неизвестным. Диагностика136 — один attempt на boot.

| mode/config | Fs, отсчётов/с | ADC / сохранено | encoding | DATA max |
|---|---:|---:|---|---:|
|1|50000|12 / 12|1, u16le|128|
|2|100000|12 / 12|1, u16le|128|
|3, прежний|150000|12 / 10|2, u10packed_le|128|
|4, новый|150000|12 / 10|2, u10packed_le|256|

Mode3 сохраняется в firmware как явно выбираемый wire0.3 режим и в чтении
исторических данных; новый пользовательский выбор150k всегда требует mode4.
UI по-прежнему предлагает три частоты50/100/150 до подключения. Mode4 использует
тот же PSC47/ARR9, deadline3413мкс и CEN bracket5мкс, что mode3. Режимы1/2
сохраняют свои timer/deadline параметры. Физический АЦП всегда12-битный;
в обоих десятибитных режимах canonical code = `(ADC12 >> 2) << 2`, два LSB
отброшены. Полоса, ENOB и калибровка этим не устанавливаются.

## Согласование до START

Host начинает HELLO0.2 с payload8 fresh nonzero nonce, header nonce0,
sequence=request1. ACK0.2 `<BBBBHHII>` допускает только следующие пары:

| capabilities | global max_block | Значение |
|---:|---:|---|
|1|128|Старый fixed-Fs wire0.2|
|3|128|SC, selectable wire0.3 modes1/2/3|
|7|256|SD, selectable wire0.3 с mode4/DATA256|

Общие channels1, physical adc_bits12, max_payload512. Бит4 означает batch256;
биты1/2 прежние. Discovery не допускает START/ADC. Старый I-host отвергает7/256
до START; новый host на SC при выборе150k явно просит batch-прошивку,
не подменяет выбор mode3. SC50/100 и старые fixed-Fs проверки сохраняются.

После marker7 отправляется fresh **другая** nonce в HELLO0.3 `<QHH>`:
nonce, выбранный mode1/2/4, reserved0. ACK0.3 остаётся16байт/capabilities1,
но max_block объявляет **выбранный** режим:128 для1/2/3,256 для4.
Это отличается от глобального discovery max и проверяется явно.
GET_CAPS/request2 сохраняет24байт. Mode4 ожидает точный host tuple
`(4,4,0,12,150000,1,256,1,10,2)`:
config,mode,channel,adc,Fs_num,Fs_den,max_block,flags,retained,encoding.
Selected ACK, CAPS и запрос должны совпасть до START/request3/config4.
Нет timeout fallback и повторного START. Nonce, generation=request,
pending/current/tx mode/revision и envelope isolation остаются прежними.

## Размер и размещение DATA

Wire0.3 DATA152: metadata20 `<IIQHH>` + packed samples. В mode4 count1…256;
старые режимы строго1…128. Для256 samples:320 packed байт, payload340,
raw24+340+CRC4=368. Верхняя граница COBS вместе с delimiter:
`368 + floor(368/254) + 2 = 371`байт, что меньше384 на13байт.
Общие MAX_PAYLOAD512/MAX_DECODED540/MAX_FRAME544 не расширяются.

Whole-fit допускает кадр только целиком в свободную часть FIFO; остаток
предыдущего кадра может временно дать known0. Не заменять его частичной
подачей. Условная оценка ceil(371/64)=6 USB-пакетов против4 для DATA128
не является измеренной границей ISR/throughput: реальные transfer boundaries
зависят от FIFO/control/host. Worst DATA bytes/s —217382,8125 вместо246093,75.

CRC END по-прежнему считает canonical u16le, не packed payload.
Source index продвигается на actual count, sequence — на один DATA.
Padding последнего packed байта строго0, длина20+ceil(10N/8).
Один DATA256 даёт ровно512 canonical байт в host.

## Пара блоков и атомарное принятие

Добавить bounded peek второго слота `(head+1)%8`; оба view принадлежат
очереди. При STREAMING mode4 отправляет только256 из двух полных128;
ожидание второго слота не блокирует foreground ADC/TIME/USB/Stop.
Первый slot пары обязан быть128, второй1…128, indices смежные.
Первый128 упаковывается в160байт существующего payload, затем второй:
граница1280бит кратна8, промежуточного padding нет. Ingress и Stop-tail
берут discard bits из descriptor, не из единственной проверки `mode==3`.

Staging/ticket фиксируют число выбранных слотов1/2, aggregate count,
оба slot/count/first_index, queue head/used/next_index и прежние
nonce/generation/config/revision/epoch поля. Перед write сохраняются
повторные проверки lifecycle/TIME/ticket. Перед любой мутацией CRC/prefix/
queue проверяются **оба** view. CRC последовательно обрабатывает их u16le
без нового512-byte scratch. Один bounded pop-span заранее проверяет все
expected indices/counts и лишь затем меняет head/used. Недопустимо удалить
первый slot и после этого обнаружить несоответствие второго.

После fully accepted кадра commit продвигает prefix на aggregate count,
sequence на1. Known0, partial/unknown, post-write TIME failure и stale ticket
сохраняют прежние fail-closed правила и границу принятого префикса.
CRC/pop/final TIME остаются под прежним IRQ guard. Более длинный guarded CRC
и старение early-grant после упаковки — реальные риски новой реализации;
~1мс transaction bound не объявляется измеренным. Второй grant не добавляется.

Stop/fault сначала синхронно quiesce/сертифицирует tail/append/seal.
Только в DRAINING при sealed queue последний выбранный набор, исчерпывающий
очередь, может иметь1…255:128+tail→129…255; lone128→128; lone tail→1…127.
Пары128+128 остаются256; остаток257 выдаётся как256+1. После short DATA
только END/control, не DATA.
Нет дополнения нулями или ожидания несуществующего партнёра после Stop.
После queue fault поздний tail не соединяется через потерянный блок.

## Host, файлы и происхождение

Режимный max проверяется в codec, endpoint, short_seen, synthetic peer,
GUI fixture и offline verifier. Нельзя глобально заменить128 на256 и тем
самым расширить старые режимы. ACK должен сохранять advertised max для
проверки CAPS. Для150k выбор mode4 определяется capability, не первым
совпадением Fs в таблице. Raw byte cap256КиБ/item cap1024 не увеличиваются.

Mode4 использует intrinsic `protocol_revision="0.3-batch256-20261024"`,
acquisition_mode=config4, Fs150000, source_adc_bits12, retained_bits10,
discarded_lsb2, wire_sample_encoding=u10packed_le, normalization=left_shift_2,
quantization=truncate_lsb, stored u16le/adc12. Session id остаётся
`wire-0.3:<nonce>`. Эта точная пара revision+mode однозначно задаёт max256
в закрытом неизменяемом registry; не выводить его из build или companion.
Для modes1/2/3 остаётся `0.3-modes-20261024`.

Сохраняются17 intrinsic fields, direct magic3/attempt magic4/companion3:
расширяется enum, а не layout. Reject mode4 со старым marker, новый marker
с mode1/2/3, отсутствие/частичные quantization fields. Старые читатели
отвергают новый enum, новые читают старые файлы без перезаписи. Открытие без
companion сохраняет mode4/quantization/dt. Observed CAPS256 в companion
сверяются с intrinsic registry. Journal chunk8192 независим от wire max.
Canonical domain/хеши старых файлов не меняются. CSV колонка остаётся
`adc12_scale_code_retained10_truncate_lsb2`; metadata несут полный identity.
Пересчёт U_CH1=a*code+b, время index/Fs и смысл крайних корзин0/4092 прежние.

## Необходимые свидетельства и отдельная аппаратная граница

До аппаратуры: одна actual-core/queue/wire модель пары и wrap7→0, CRC,
worst371, хвосты1/2/3/127/128/129/255, stale второй view/ticket/mode,
known0/partial/unknown/TIME и отсутствие преждевременного pop. Нужны exact
ARM/static RAM+stack (SC имела лишь932байта сверх8192reserve) и сверка
неизменённых runtime/TIME/DCD/FIFO/guards. Не запускать весь старый suite.

Host: strict negotiation/mismatch доSTART,256/129/255 packed vectors и
padding, reject257/mode3 count129, старое128-чтение, fresh Open mode4 без
companion, canonical/dt, actual C DATA256+tail+END→Python. Один адресный
Windows GUI и frozen package Record→Stop→Open; пакет собирается отдельно
от принятого I, который сохраняется. Критик проверяет точный manifest.

Физический план фиксируется после software/package: backup текущего образа,
verify/readback нового, fresh boot+пользовательский USB-replug на каждый
диагностический сеанс, точный build/CAPS доSTART, один короткий50k и100k
и150k/30с. После отказа сохранить префикс/diagnostics и остановить план.
SWD только после подтверждённой остановки/закрытия COM; ADC_DR не читать.
Возврат старой прошивки лишь при конкретной необходимости запуска/связи/
остановки. Физическая передача/хранение и аналоговое измерение — разные уровни.
