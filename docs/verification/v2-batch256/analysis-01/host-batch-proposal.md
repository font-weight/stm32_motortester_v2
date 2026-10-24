# V2-06k: предложение host-контракта DATA256 для150k

Статус: **DRAFT / предложение, не разрешение реализации или физического опыта**.
24.10.2026. Пользователь выбрал попробовать передачу более крупными пакетами.
Обсуждение TIME-оптимизации J приостановлено; её файлы и исходные отрицательные
результаты сохраняются. Здесь только контракт host/wire/files, production не менялся.

База: source `310d53b10c79a48ddc45357ff65d88c686aef883`, SC
`0x56325343`, BIN `a36f72a772c03c5cbfd85767e5f07f0abc3ad2f2ffd7d1ee1c43143d20ca1c90`.
Существующий SC уже передаёт DATA-пакеты по128 отсчётов. Предлагаемая дельта —
256 отсчётов для150k/10 сохранённых бит;50/100k остаются по128.
Это не паузы захвата и не сбор всей записи в RAM.

## Рекомендуемый вариант: новый mode4 при wire0.3

| Wire | mode/config | Fs | ADC/retained | encoding | max_block |
|---|---:|---:|---:|---|---:|
|0.2 legacy|1|объявленная fixed-Fs50/100/200k|12/12|u16le|128|
|0.3|1|50000|12/12|u16le|128|
|0.3|2|100000|12/12|u16le|128|
|0.3|3 — прежнее значение|150000|12/10|u10packed_le|128|
|0.3|4 — новое значение|150000|12/10|u10packed_le|256|

Имена mode1/2/3 и их прежний смысл не меняются. Это закрытая таблица,
а не произвольный max_block, присланный устройством. В новом UI по-прежнему
три частоты50/100/150 до Connect;150 выбирает mode4 при явной поддержке.
Декодирование прежнего mode3 остаётся для старых файлов/свидетельств.
Mode4 не включает прежнюю physical-приёмку100k автоматически.

Альтернатива wire0.4 могла бы определить mode3=150k/max256 именно внутри
новой версии, оставив mode3 wire0.3 прежним. Это корректно, но расширяет
перечень поддерживаемых revisions во всех envelope, session-id, provenance,
file/connection и offline-verifier ветках без изменения layout DATA.
Для одной фиксированной новой группы достаточно mode4 с отдельным marker.
Простое изменение max_block у существующего0.3/mode3 отвергается:
оно молча изменило бы опубликованный режим и смысл старого журнала.

## Обнаружение и подтверждение до START

Все числа ниже — предлагаемые точные значения, предварительно согласованные
с firmware author `higher_fs_review`; независимый contract gate ещё требуется.

1. Host начинает прежним HELLO0.2, header nonce0, sequence=request1,
   payload8 fresh nonzero nonce.
2. HELLO_ACK0.2 имеет прежний layout `<BBBBHHII>`; strict combinations:
   - capability1 / max_block128: прежняя fixed-Fs прошивка;
   - capability3 / max_block128: SC с выбранными режимами1/2/3;
   - **capability7 / global max_block256**: новая batch-прошивка.
   Во всех трёх: channels1, physical adc_bits12, max_payload512.
   Бит4 означает поддержку нового mode4, биты1/2 сохраняют прежнее значение.
   Не принимать другие mask/block combinations «на всякий случай».
3. Для marker7 новый host отправляет HELLO0.3 с другой fresh nonce,
   sequence=request1, payload12 `<QHH>`, selected mode1/2/4, reserved0.
   Discovery не запускает ADC, а замена проходит прежнюю isolation/commit
   границу. Нет timeout downgrade или повторного START.
4. HELLO_ACK0.3 сохраняет payload16. Его max_block — **выбранный**128 для
   mode1/2/3 либо256 дляmode4, capabilities1. Discovery global256 и
   selected128 не противоречат друг другу: это разные стадии согласования.
5. GET_CAPS/request2 возвращает прежний24-байтный layout. Для mode4
   observed tuple строго:
   `(4,4,0,12,150000,1,256,1,10,2)`
   в host-порядке config,mode,channel,adc,Fs_num,Fs_den,max_block,flags,
   retained_bits,encoding. ACK max_block, выбранный mode и CAPS должны
   совпасть до допуска START.
6. START/request3 payload `<I>`=config4, START_ACK config4, generation3,
   first_index0. Приём, Stop, END и ACK остаются привязаны к той же
   nonce/config/generation; mode не меняется в активном сеансе.
7. CRC/header-валидный кадр другой nonce не влияет на текущий контракт.
   Wrong revision текущей nonce и неправильные length/count/padding —
   fail-closed по прежнему правилу. Ограниченные framing/CRC/header проверки
   сохраняются до игнорирования чужой nonce.

Прежний app I отвергнет marker7/max256 ещё до START; нельзя скрывать
новую batch-прошивку под marker3. Новый app на старой SC при выборе150
сообщает, что необходима прошивка с пакетами256; он **не выбирает mode3
молча**. На SC выбор50/100 продолжает прежнюю marker3→mode1/2 ветку.
Legacy fixed-Fs сохраняет явную проверку выбранной частоты и запрещает
подмену. Номер build остаётся наблюдаемым фактом, не механизмом согласования
и не подтверждением прошитого SHA.

## DATA256, границы, короткий хвост

Envelope0.3, DATA152, metadata20 `<IIQHH>` и правила canonical ADC12
остаются прежними. Только mode4 допускает count1…256; прочие режимы —
count1…128. Приёмник проверяет максимальный count по negotiated CAPS и
закрытой mode-таблице, а не заменяет общую128 на256 для всех источников.

Для256 кодов10бит packed payload320байт, вместе сmetadata340байт.
Header24+payload340+CRC4 =368 decoded bytes. Общая безопасная граница
COBS с delimiter — **371байт**, а не безусловно370. Это меньше FIFO384
и прежних глобальных MAX_PAYLOAD512 / MAX_DECODED540 / MAX_FRAME544.
Увеличивать framing/read allocation или FIFO ради такого кадра не требуется.
Один принятый DATA256 разворачивается ровно в512 canonical raw-байт;
это меньше прежнего StreamBlock/journal предела8192 кодов. Индекс конца
вычисляется как first_index+count с прежним uint64 overflow guard до
публикации. Время, префикс и CRC считают256 отсчётов/512 canonical bytes,
а не320 packed bytes и не два независимых wire-кадра.

- Порядок q10-битов, `canonical=(ADC12>>2)<<2`, floor/truncation и
  padding0 последнего байта неизменны. Length точно `20+ceil(10N/8)`.
- Канонические code12 остаются0…4092, кратные4. END CRC32 считается
  по canonical u16le в порядке отсчётов, не по packed wire или headers.
- В STREAMING нужны полные DATA256. Единственный оставшийся128-slot
  ждёт партнёра; foreground продолжает ADC/TIME/USB/Stop, а не блокируется.
  Нельзя отправить128 как «короткий обычный пакет», а затем продолжить DATA:
  прежний конечный short-frame контракт это запрещает.
- После seal/Stop/fault DRAINING допустим последний count1…255 без
  заполнения нулями. Например остаток одного128-slot даёт short DATA128;
 128+частичный tail1…127 даёт129…255. После short DATA следует только END/
  управляющее завершение, не очередной DATA.
- START/END/STOP_ACK номера и layout не меняются. Последний DATA sequence
  отражает число переданных wire-кадров; prefix_end всегда считает
  отсчёты, независимо от объединения. Потери/produced_end неизвестны
  по прежним правилам, batching не превращает хвост в подтверждённый.

Группа256 должна объединять два существующих128-slot без нового sample
буфера и без увеличения queue8. Атомарность обоих head/count/CRC/pop после
полного принятия, partial/unknown acceptance, ticket, эпоха и deferred errors
относятся к firmware-контракту автора. Host не должен считать принятие
первой половины успешной публикацией всего256-кадра.

Расчёт, не измерение: при150k нужно585,9375 DATA256/с вместо1171,875
DATA128/с. Интервал полных wire-кадров1,706667мс; ADC по-прежнему получает
отсчёт каждые20/3мкс. Worst-case371×585,9375 ≈217382,813 wire-байт/с.
Больше задержка первого полного кадра и другая USB-разбивка; это не
гарантия устойчивости150k. До physical проверки ничего не обещать.

## Intrinsic metadata и старые записи

Предлагается сохранить17 полей StreamIdentity и существующие magic:
direct `MTSTRM\x03\x00`, attempt `MTSTRM\x04\x00`, companion version3.
Для mode4:
- `protocol_revision="0.3-batch256-20261024"`;
- `acquisition_mode=4, config_id=4, nominal_fs_hz=150000`;
- physical/source_adc_bits12, retained_bits10, discarded_lsb2;
- wire_sample_encoding `u10packed_le`, normalization `left_shift_2`,
  quantization `truncate_lsb`, stored `u16le` / `adc12`;
- session_id по реальному wire-envelope: `wire-0.3:<nonce>`.

Пара нового intrinsic revision+mode4 **однозначно задаёт max_block256**
в неизменяемой закрытой таблице. Это не догадка по firmware build или
companion. Для mode1/2/3 прежний marker `0.3-modes-20261024` сохраняется.
Валидация запрещает mode4 со старым marker, новый marker с mode1/2/3,
и отсутствие/частичную quantization metadata. Старые читатели отказывают
на неизвестной revision/mode4, а не отображают его как прежний raw12.

Структура metadata и домен raw не меняются, поэтому добавлять новое
необязательное поле или новый magic ради одного enum не требуется.
Если независимое ревью потребует буквальное поле `wire_max_block_samples`
в header вместо определения из version/mode, это уже отдельная строгая
версия identity/magic/companion, а не необязательный default256/128.

Journal chunks до8192 кодов независимы от wire-batch: writer уже агрегирует
StreamBlock, поэтому B/checkpoint/hash-chain layout не меняется. Кодовая
проверка канонических10бит должна применяться к обоим mode3/4. Открытие
без companion сохраняет режим, квантизацию и время. Companion3 хранит
observed_caps max256 и сравнивает его с intrinsic registry; mismatch
отклоняется. Все старые magic1/2/3/4 и companion1/2/3 читаются как прежде,
не переписываются и не переобозначаются.

CSV остаётся с колонкой `adc12_scale_code_retained10_truncate_lsb2`;
JSON/CSV metadata несут полный новый identity и выбранные CAPS при наличии
соединения. Derived wire_max_block256 допустимо отображать/экспортировать
отдельно, но не заменять им intrinsic marker. Оси, dt=index/Fs,
калибровка U_CH1=a*code12+b и предупреждение об крайних корзинах0/4092
не меняются. 10retained не становится точностью10ENOB.

## Минимальные затронутые host-пути при будущем разрешении

- `stream_wire.py`: конечная mode/max-table; ACK должен возвращать
  объявленный max_block (сейчас HelloAck сохраняет лишь build/capabilities);
  strict marker pairs, DATA/per-mode count, pack/unpack bound256.
- `stream_endpoint.py`: preferred mode по discovery capability, без
  поиска первого совпадения Fs (mode3 и4 имеют одну Fs); ACK/CAPS binding;
  short-frame predicate по selected max_block, а не общему128.
- `stream_bridge.py`, `stream_provenance.py`, `stream_model.py`:
  точная mode4 identity/revision, origin остаётся device/synthetic;
  calibrated/raw domain прежний. Не использовать `mode==3` как единственный
  признак10бит, если contract допускает также4.
- `v2/stream_device.py` и UI: связь max_block/identity, явная ошибка SC150,
  публичный выбор50/100/150 и блокировка после Connect сохраняются.
- `verify_stream_trial.py` и future physical helper: count/short по CAPS,
  оба intrinsic revisions для session wire0.3; max256 exacttuple. Старые
  SC/0.2 records и evidence должны оставаться читаемыми.
- Synthetic peer/GUI fixtures также берут negotiated max_block: в mode4
  обычный128-блок нельзя выдавать за полный DATA перед следующим DATA.
  Тот же short-tail predicate применяется в codec/endpoint, synthetic
  проверке и offline physical verifier; journal8192 не является wire max.
- `stream_recording.py`/export: только admission нового точного enum,
  без изменения raw layout/хеширования старых файлов. RAM/disk лимиты
  не увеличивать: raw byte cap256КиБ на wire256 ограничивает очередь
  не более512 полных512-byte blocks, даже при item cap1024. Число
  канонических кодов в этом byte cap не изменяется.

Предлагаемые будущие минимальные доказательства, **сейчас не запускались**:
одна группа strict handshake/mode4 плюс SC150 mismatch before START;
независимые packed vectors на границе256 и коротких129/255 с padding,
отказы257 и mode3 count129; existing old128 read; intrinsic mode4 fresh
Open без companion, canonical equality и dt20/3мкс; один actual C→Python
DATA256+tail+END vector и один Windows GUI/package Record→Stop→Open.
Firmware pair-pop/partial/ticket/TIME проверяет отдельная узкая actual-core
модель автора. Это перечень для согласования, не приглашение к full suite.

## Основания и незакрытая граница

Читались только исходники SC: `host/motortester/stream_wire.py`,
`stream_endpoint.py`, `stream_model.py`, `stream_provenance.py`,
`stream_recording.py`, `stream_bridge.py`, `v2/stream_device.py`,
`host/docs/stream-modes.md` и прежний `build/v6i-analysis/firmware-contract.md`.
Точные исходные pins — source310d53b и I software evidence. Общий K wire
draft должен закрепить перечисленные числа/строки, build нового образа
назначает root. До независимого contract gate реализация и новые аппаратные
действия этим предложением не разрешены.

