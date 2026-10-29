# V2-06U2 — физический результат одного 30-секундного опыта SN

29.10.2026. Независимый критик `stream200_critic`, не автор реализации и не аппаратный оператор. **PASS, 9,60/10** для точного опыта U2: один захват mode5 / nominal150000 Гц / DATA1024 с полным 30-секундным Record, нормальным END/ACK и сохранением принятого диапазона. **Критерий P1-M2-01 «один 30-секундный поток без зарегистрированного source fault/разрывов» выполнен в условиях этого опыта.** Общая повторяемость, более длительная работа, другие нагрузки и полнота неизвестного produced tail этим выводом не принимаются.

## Привязка и лично проверенные свидетельства

Product source `308406d8627fc2aedc6e8eb7abd833e1f229102f`, база SL `695efd95e7c4ba72bfa6fb5fb511b85186be6266`; точный план `392a2321858e9524b8b2760cad6454d65f9f0af7d08bdbd5057063119dd2f6c5`. Образ SN / `0x5632534e`: **49744 байта**, SHA `abc20c98a870c082fce3cb6fab8e0789aa7bd42e53c5bf342861d0c9d3c37714`. Сохранённый отдельный readback лично сопоставлен с BIN: каждый байт равен. Source/plan оценки остаются отдельными и не использованы вместо физического результата.

[Physical manifest](../verification/v2-collect-local/physical-01/manifest.json): `1738e007006568b48eb134233cd0d90cb4f2e465bae1bb17bea334c88966e039` — **62 пары / 15157786 байт**. [Installation manifest](../verification/v2-collect-local/installation-01/manifest.json): `c3607b5c8bb02a37121f375773c7e01836d883c5dd8e210a5d6e3c19f383b316` — **22 пары / 145950 байт**. Лично проверены все размеры, SHA и побайтное source/archive равенство; ошибок нет. Все 28 execution_inputs сохранились без drift, пять оригиналов из offline before/after перечня совпали. Проверены hashes результатов, пары банков, входы register report, новый reply/reset binding, CLI argv/logs/timestamps и сохранённые raw/wire/journal/companion свидетельства.

Работа критика ограничена чтением и hash/byte-проверками через PowerShell/Python; ни capture, ни анализатор/декодеры, ни модель/ARM/GUI, ни аппаратные команды повторно не запускались. Содержательная wire/CRC/fresh Open проверка — **сохранённый единственный offline прогон root**, его inputs/tool pins и результаты прочитаны и связаны с архивными оригиналами. Критик не выдаёт это за второе независимое декодирование потока.

## Идентичность и порядок действий

Установка 28.10: один program/verify → отдельный readback49744 → один Reset/Run в19:12:54.295176 UTC. CLI подтверждает probe `57005400120000393333574E`, успешную запись/чтение/запуск. Новое фактическое «готово» относится к вопросу `call_9aca0580ce424db2849764fe2011a090`, сохранено 29.10 в03:26:30.734754 UTC с hash именно SN reset.log; старый SL reply не использован. Root фиксирует требуемый cold cycle обоих USB. Fresh inventory03:26:30.3631215 UTC: ожидаемый COM6/PNP, code0, owners=[]. PA0 пуст по сообщению пользователя; это условие, не измеренный входной сигнал.

Один `run_trial`: **03:26:43.321390–03:27:16.723586 UTC**, whole command33,4022857с; ровно один START в сохранённом wire. Root дождался PASS/owners_closed, выполнил один offline анализ coherent terminal, затем читал память. Первый SWD Dump **03:28:22.931834 UTC**, после завершения процесса. Все десять сохранённых чтений успешны и относятся к ожидаемому probe; ADC range0x40012408/12 не включает ADC_DR. Root chronology `41b82ae64cc77718a17d7c3ed0e00ee03fa6d9371777d258a9b54f8fd95201ca` явно фиксирует отсутствие SWD/halt при активном COM, повторного START/Reset/Flash и отката. Это процедурные наблюдения root, поддержанные logs/timestamps, а не информация, выводимая из одних диагностических bytes. SN оставлена остановленной.

## Результат потока и сохранения

- Discovery nonce `6a6e4232ef19e2c9`; выбранный mode5 nonce **`a8b96272e4732ac4`**, generation3. Wire ACK/CAPS наблюдают SN,150000/1, sourceADC12/retained10, max1024 и encoding2.
- Record **30,0020047999с**, target_duration_met=true; грубый прирост полученных отсчётов **150005,98/с** в пределах прежнего90–110% критерия. Это host-наблюдение скорости приёма, не калибровка Fs.
- Получено **4505560** canonical-кодов: **4399 полных DATA1024 + один terminal tail984**; максимальный encoded frame1335B. Полный принятый префикс [0,4505560) непрерывен, wire decode errors/gaps/overlaps отсутствуют, trailing partial0. CRC32 **826594608 / 0x3144d530**, raw SHA `dfc4144005629075d077e66adda0a91fc9a7fdea6b2551ed665a40d81c8e3e0f`.
- Host STOP request4 предшествует **END sequence4404/reason0/flags3**, prefix4505560, last DATA4403; **ACK4405** подтверждает END4404 и тот же prefix/request. Callback/errors=[]; owners_closed=true.
- Сохранённый Record **[2048,4505560), 4503512 отсчётов**. Fresh Open/companion проверены, discarded journal bytes0/recovery issue null; selected wire/raw byte_equal=true, SHA обеих последовательностей `ea542458eec2ddee0232976811eec012b9d3e7ed8f38c3e96ca4696f30c34fd9`. Journal SHA `40e2961555d39472c14eace170be91d685b18091d33d8a2f0b51b71909cb0645`.

`produced_end=null`, loss_samples=null и `clean_stop_reported=false` сохранены намеренно: normal END reason0 означает штатный протокольный Stop, **не доказательство полного учёта всех произведённых АЦП отсчётов**. Low2 bits исходного ADC12 отбрасываются согласно mode5; целостность относится к переданным retained10/canonicalu16 данным. Probe сам не доказывает image identity; здесь она дополнена source/image/readback/порядком действий.

## Диагностика и остановка

Пары136/64/24 лично сравнены побайтно и со SHA отчётов, nonce/gen совпали с текущим сеансом; никаких декодеров критик не повторял.

- Legacy136 SHA `33f15ec0c6f2e027f16cc943438789ea7a58db35d2ef39f26119dfb0aecb9e29`: frozen, **flags0**, все first reason/error/fault0, normal_stop_record_shape=true; final ADC stopped/owned0/hardware_off1. Наблюдённые poll **2708мкс**, copy **196мкс**, оба<3413; queue high-water **8/8** означает достигнутую заполненность, а не зафиксированное переполнение. Это observed maxima, не WCET или запас устойчивости на будущие нагрузки.
- N64 SHA `0e203dac588388945487a5653ed944831010ddbafbafab6c38a34f29e2088244`: VALID_WITH_LIMITS, **close CAP**, primary0, elapsed18038026cycles ≈250,528139мс при условных72МГц. Snapshot q4/READY1024/TX768/1335/FIFO320; prepare6245153cycles/315, positive47493B/142, zero-space53/other0. Эти inclusive данные прекращаются около250мс, не покрывают остальные30с и не являются CPU share или числом доставленных кадров.
- G24 SHA `b487c40e9afe44b571534c652e6abf150a79d49b1cffe0d2dc64e86569007f44`: VALID_WITH_LIMITS/CAP, historical RESUMED serial154, total384/prequeued256, evaluated age358мкс/budget2, event180cycles до Nclose. APPLICABLE=false; same_episode_as_later64_proven=false. Не доказательство действовавшей причины/selector/handoff или состояния на конце записи.
- Stopped registers all_checks=true: TIM3 CEN0/PSC47/ARR9, ADC_CR2=0/SMP0=4, DMA EN0; RCC clocks/reset checks пройдены. Это состояние после закрытия owner, не внешняя калибровка периода/АЦП.

Косметический заголовок/schema `V2-06s` в generated physical-analysis сохранён как результат неизменного helper; SN build/source/image явно правильны в теле/JSON. Архив задним числом не переписывается.

## Область приёмки и оценка

Один заранее заданный физический30s критерий принят; прежние неудачные S2 и другие опыты остаются FAIL. Открытость этого критерия из старых отчётов не переносится вопреки новому положительному результату. Одновременно **не подтверждены** повторяемость и работа дольше30с, неизвестный produced tail/абсолютная losslessness,50/100 на SN, GUI под нагрузкой, аналоговая точность/калибровка, зажигание/автомобиль. Успех совместим с гипотезой экономии collect, но один опыт не выделяет её единственной причиной улучшения.

| Критерий | Вес | Балл | Основание |
|---|---:|---:|---|
| C1 | 0,30 | 9,7 | Full30s, exactSN/CAPS, normal terminal и соответствующий retained диапазон |
| C2 | 0,20 | 9,5 | Нет зарегистрированных faults/gaps, closed owner/остановка; queue8 и неизвестный хвост явно ограничивают вывод |
| C3 | 0,25 | 9,6 | Один фактический опыт, цельная identity/byte/хронологическая цепочка; CAP не подменяет полные30с |
| C4 | 0,15 | 9,4 | Ограничения разделены; сохранён косметический исторический заголовок helper |
| C5 | 0,10 | 9,8 | Exact plan/source/readback, полные originals/архивы и новый reply/argv/timestamps |

Итог **9,60**. Открытых P0/P1 **в ограниченном критерии одного U2 опыта** не выявлено. Приёмка диагностических банков — VALID_WITH_LIMITS с историческим CAP; общей аппаратной/аналоговой квалификации этот балл не даёт.
