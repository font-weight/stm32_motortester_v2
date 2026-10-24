# K: непрерывная передача256 отсчётов в одном DATA для150k/10MSB

24.10.2026, higher_fs_review. **Только проект, без реализации/аппаратных действий.**
Пользователь попросил передачу пакетами. Работа J над direct TIME остановлена
до изменений production; сохранены только её read-only proposals/findings.
SC `a36f72a7…ca1c90` и результаты I2/I3 остаются неизменными.

## Цель и обоснование

ADC/TIM3/DMA продолжают непрерывно работать150k с прежним sample time и
DMA1024/half512. Меняется только объединение **двух очередных queue128**
в один wire DATA256. Паузы захвата/оконный Stop→transfer→restart не вводятся.
Source indices и время1/150000с сохраняются; приложение соединяет реальные
непрерывные индексы. Потеря очереди остаётся отказом, не скрытой паузой.

Сегодня150k mode3 передаёт27×210B в I3 и завершается queue-full;100k работает.
Укрупнение уменьшает число foreground TX admissions и final-IN/task turnover
на256 отсчётов с двух до одного. Это одна проверяемая гипотеза, не доказательство
доминирования CPU/USB и не обещание устойчивых150k. Буферы не увеличиваются.

## Новый режим, старые форматы не переопределяются

С host_200k согласуется новый **mode4/config4**:150000/1, ADC12, retained10,
discarded_lsb2, encoding2/u10packed_le, canonical c12=(ADC12>>2)<<2,
**max_block256**. Modes1/2/3 сохраняют свои значения и DATA<=128;
mode3 остаётся прежним историческим150k10/128 и его файлы читаются по старому контракту.
Пользовательский выбор всё ещё50/100/150, а не четыре технических mode.

Discovery HELLO0.2 остаётся8-byte nonce. Новый образ отвечает HELLO_ACK0.2
со строгой парой **capability_mask7/global_max_block256**: STREAM_BASE1,
REQUIRES_MODE_HELLO_0_3=2, BATCH256=4. Это только discovery, ADC/START запрещены.
Старый app отвергнет7/256 доSTART. Новый host знает строгие discovery пары:
legacy1/128, SC3/128, batch7/256. Для requested150 он выбирает mode4 только при7;
при старомSC3 явно сообщает о необходимости новой прошивки, без fallback mode3.
50/100 наSC3 могут остаться доступны как modes1/2.

Затем fresh nonce HELLO0.3(`<QHH>` mode4/reserved0), как вSC. Полный ACK0.3
объявляет **selected** max_block256 дляmode4,128 для1/2/3; CAPS24 содержит
такой же max_block. Global discovery256 и selected128 для50/100 не противоречат:
это явно разные области объявления. START остаётсяu32 config_id, generation=request.
Pending/current/tx mode+revision, checked envelope, nonce/epoch/ticket guards сохраняются.
DATA152 остаётся `<IIQHH>` +packed samples, count1…256 только приmode4;
generation/config/index/reserved0 и END/STOP_ACK layout не меняются.

Новый identity marker дляmode4 — `0.3-batch256-20261024`; quantum/calibration
домен какmode3. Existing acquisition_mode/config4 однозначно закрепляютmax256
через immutable registry. По предложениюhost новые17intrinsic fields и journal
magic3/4 сохраняются: старыйreader отвергает неизвестныйmode/revision доraw,
новыйreader знает старые0.2 и modes1/2/3. Host обязан отдельно принятьblock512
canonical bytes и строго ограничивать их по выбранной identity, не расширять
все старыеwire/file режимы до256 молча. Companion/CSV/JSON сохраняют mode4 и
прежнюю явную потерю2LSB; packet aggregation не является новой разрядностью ADC.

## Точный размер кадра и FIFO

256×10бит =320sample-байт. DATA payload20+320=340; raw envelope24+340+CRC4=368.
COBS worst incl delimiter:368+floor(368/254)+2=**371байт**, не370.
Например320ненулевыхsample-байт уже требуют дополнительныйCOBS code.
371<=FIFO384, запас13байт; existing max write offer384 и staging544 достаточны.
ACK/другие ещё не ушедшие байты могут уменьшить free space: whole-fit возвращает
known0 до появления371байта, не делает частичный новый кадр. Задача не увеличиваетFIFO.

| Условная оценка полногоDATA отдельнымUSB transfer |128 |256 |
|---|---:|---:|
| Fs/число отсчётов, кадров/с |1171,875 |585,9375 |
| Wire worst B/frame |210 |371 |
| Wire worst B/s |246093,75 |217382,8125 |
| ceil(frame/64), INпакетов/кадр |4 |6 |
| Условных INпакетов/с |4687,5 |3515,625 |

Это не абсолютный максимум реальныхIN/ISR: FIFO коалесцируетcontrol/data и
меняетtransfer boundaries. Бюджет6пакетов/<500мкс не увеличивается; один371B
transfer укладывается в6пакетов, но actual elapsed/USB host scheduling требуют
проверки. Не обещать throughput только из расчётаbytes/s.

## Подготовка двухqueue view без второго массива

Queue остаётся8×128=1024sample capacity, с прежними indices/counts/seal/fault.
Добавить bounded peek второго блока (head+1 mod8), не копировать samples в
новыйuint16[256]. Вmode4 при STREAMING строить кадр только при двух blocks;
при DRAINING разрешать остаток из одного. Первый при паре обязанcount128,
второй1…128, next first_index=first+128. Short first не объединяется.
**STREAMING mode4 выдаёт толькоcount256.** Short count1…255 допустим лишь
вDRAINING после синхронного terminate/quiesce/tailappend и queue.sealed,
когда выбранные слоты исчерпывают retained queue. После него толькоEND/ACK,
не другойDATA: это сохраняет host short_seen. Повторного append послеseal нет.

Existing packer может отдельно упаковать первый128 в160B существующего
`m.payload+20`, затем второй в следующий участок.1280бит кратны8, поэтому
промежуточного padding нет; только final unused high bits строго0. Headercount
равен реальной сумме, не всегда256. Дополнять отсутствующие samples нулями нельзя.
Mode4 canonical ingress и Stop-tail берут discard2 из descriptor; нельзя оставить
старую проверку `mode==3` и случайно передать mode4 полныеADC12.

TX staging хранит nblocks1/2 и aggregatecount, first_index. Ticket фиксирует
решениеcombine, оба slot/count/first_index, generation/nonce/config/revision,
queue head/used/next_index и прежние поля. Borrowed views остаются queue-owned,
их нельзя менять/публиковать другим foreground во время prepare→submit.
ISR по-прежнему может менять только transport epoch; actual submit повторно
проверяет ticket/epoch/lifecycle/TIME до write.

## Commit и хвост

Перед commit проверить **оба выбранных блока** до любой мутации CRC/prefix/queue.
CRC вычисляется по canonical c12 u16le первого и второго в исходном порядке,
без промежуточного512-byte scratch. END CRC должен совпасть с прежним побайтовым
CRC того же массива независимо от разбиения DATA.
После fully accepted frame применять один bounded atomic pop-span1/2:
проверить все expected indices/counts перед изменениемhead/used, затем продвинуть
prefix на действительный aggregatecount и last_data_sequence один раз на кадр.
Не допустить pop первого при неподтверждённом/устаревшем втором. Partial/unknown,
known0 и post-write TIME failures сохраняют прежние fail-closed/accepted-prefix правила.
Completed CRC/pop и final TIME остаются под прежним IRQ guard; больший guarded
CRC может увеличить transaction time, поэтому1ms остаётся неподтверждённым bound.
Pure prepare остаётся после earlygrant: более длинная упаковка может сильнее
состарить прежнее6/<500мкс окно до first/new transfer. Второйgrant не добавляется.

Stop/fault сначала выполняет прежний quiesce и сертификацию tail. В DRAINING:
пары128+128→256;128+short→129…255; lone128→128; lone short→1…127.
После последнего одиночного блока должен выйтиEND, без ожидания новой пары.
При queue fault поздний tail не мостит dropped block; только сохранённый prefix.
Sequence увеличивается на кадр, sample index — на фактическое количество.
ПаузаPreview по-прежнему не останавливает acquisition/Record.

## Ограниченный следующий scope после согласования

Таблица descriptor max_block/новыйmode4; discovery/selected CAPS; bounded queue
peek/pop-span и pair-aware prepare ticket/completed.50/100/старыйmode3 не менять.
TIME J specialization не входит. Runtime H/USB/DMA/deadline/legacy136 остаются;
новый sample/frame buffer и увеличение очереди запрещены. Дополнительные metadata/
borrowed view занимают лишь небольшие scalars/stack, но exactRAM/stack нельзя
принимать по SC: сейчасзапас932байта сверх8192reserve, нужен итоговыйARM/static.

Одна адресная actual-core/queue/wire модель: two-head wrap7→0; DATA256 worst371B;
canonical CRC и Stop tails1/2/3/127/128/129/255; stale второгоhead/count/mode,
known0/partial/unknown/TIME и отсутствиеpop доfully accepted. Source guards
сравнить сSC; old H/USB suite не повторять без причины. Host — одинcrosscheck
actualCpacked256fixture +сохранение/открытие/режимныеbounds, отдельныйnativeGUI
при изменённомData-size path. Независимыйsoftwarecritic и отдельныйphysicalplan
обязательны. Fresh boot на каждый диагностируемый сеанс; legacy136 всё ещё
one-attempt-per-boot. Новый150k по-прежнему требует фактической приёмки.
