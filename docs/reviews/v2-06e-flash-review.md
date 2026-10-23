# V2-06e — допуск одного опыта V2S8 / 100 kS/s

23.10.2026. **PASS, 9,605/10 только для допуска точного образа к одному 10-секундному опыту.** Общий E остаётся BLOCKED_EVIDENCE до фактического результата. Предыдущие S5/S6/S7 не выдержали свои опыты; их REWORK и данные сохраняются. Допуск — возможность проверить конкретную гипотезу расписания, не обещание устойчивых 100 kS/s.

## Область и точные входы

Критик `stream200_critic` независим от автора firmware, host и аппаратного плана; COM/SWD/Flash не использовал. Действуют E в task/coordination и quality-gate. USB-питание прежней платы, отсутствие 3,3 В от ST-Link, пустой PA0 и закрытие приложения — ранее подтверждённые пользователем условия; независимого осмотра монтажа не было. После возврата S4 пользователь подтвердил переподключение, изменений соединений не заявлено.

| Вход | Значение / SHA256 |
|---|---|
| Source commit | `bab09184455a41ac9f552565c825ce83f029c40f` |
| База сохранённого D | `fb7a9c7a0c6f9dd1a64d1c68c610e50026b6570e` |
| S8 BIN, 36120 байт | `80a5ed8d064a2d0559f063d6650fb4edab078de4c233ea66ef2cb0e1ac62cf20` |
| ELF | `65d477b3cfae09d3bc9c05fe7a2fa2c498445b22dac9f79a2c89b1b0e5e6330e` |
| Свежий backup, 65536 байт | `95d3a11f8db843e362b2c59ed6fbf380dd630e067fa23f6ae5a9c7d2b11dff1e` |
| План `build/v6e-board-01/plan.json` | `0949fe65b3bfa8e01fa988b55ab7d954df50f91603fe18f90d76e4f21eb81b41` |
| Decoder | `731cc09150bc5d4a9d34d1872f7a777878773d5ae082f3decb35c2082d63e711` |
| ST-Link CLI | `7fb012b5e26abf45342caa05c6bc33936f8a379b67797cc55658ffb8bf15e95f` |
| Build / Fs / DATA | `0x56325338` / `100000/1` /128 |
| Probe | Единственный ID0; connect SN `57005400120000393333574E` |

Все 26 пар [software evidence](../verification/v2-100ksps-schedule/software-evidence.json), 981284 байта, сверены побайтно/SHA; manifest `a4210ffc549ea224b67cd92bbff59e0446f8783072cd4cde773a3fe6d4d8b210`. Все 8 пар [preflight evidence](../verification/v2-100ksps-schedule/preflight-evidence.json), 84788 байт, также совпали; manifest `18cc7b188f222eac79887658d49157b7bdfebe543f0c5310e3fe9e7c4871f524`.

## Что проверено лично

Тело `step` S8 побайтно равно S4. Удалены только два добавленных ADC checkpoints и их дополнительные TIME/loss пары. Whole-fit `live_write` и 46 остальных patched файлов S7 неизменны; 21 функция runtime совпадает с S4/S7. Действительные driver deadline5120, clock/gates/ownership/sticky DMA flags, unknown tail, Stop и USB guard сохранены. Реже выполняемое обслуживание требует нового физического наблюдения; прежний успех S4 на 50k не переносится автоматически.

Сверены 508 входов сборки, 112 dependencies, 32 analysis inputs, 30 objects, 3 образа, 66 freeze pins и 106 native inputs. Лично повторены `build/v6e-native-schedule-02/model.exe` и exact static analyzer в Python `-I -B`. Проверено, что generated model содержит точные извлечённые runtime bodies и actual epoch metadata. ADC/core/USB callbacks в этой модели логические: проверяется порядок, не физическое исполнение периферии. Пройдены одно ADC обслуживание, RX Stop перед TX, ADC fault вместе с pending Stop, epoch loss внутри ADC/task/TX/flush, failed Stop без cleanup receipt/CTR, шесть TIME barriers, known-zero whole-fit и сохранение принятых байтов. Неизменные driver/USB/host/Windows проверки повторно не запускались.

Промежуточный native-schedule-01 отказ сохранён: precheck ошибочно требовал неиспользуемый скопированный legacy header в compiler receipt; C тогда ещё не запускался. Последующая проверка разделяет совпадение источников и наличие в фактических зависимостях компилятора. Это не скрытый успешный запуск.

Exact static: text35992/data128/bss11212, stack bound5924/aligned5928 при резерве8192; весь RAM19532 из20480 байт. Граница условна и не является измерением high-water/WCET. BIN независимо восстановлен из ELF PT_LOAD: полное равенство. MSP0x20005000, Reset0x08008759, Flash end0x08008D18; diagnostics0x20002BC4/136.

Свежие 64 KiB лично равны проверенному возврату S4 из D; prefix35384 равен точному S4 BIN. Fresh dump сообщает прежний SN, ID0x410, 3,2 В. Список старого CLI показывает текстовую заглушку вместо SN; конкретный connect однозначен. Сообщённые инструментом 128 KiB не удостоверяют подлинность MCU и не расширяют проектные 64 KiB Flash/20 KiB RAM.

Decoder отличается от проверенного S7 только version/build/BIN/ELF константами; все 34 поля совпали с exact header, адрес и размер совпали с ELF. Проверены exact argv, диапазоны регистров без ADC_DR, отсутствие mass erase/option-byte команд, новый каталог опыта и закреплённый rollback helper. В первоначальном draft helper указывал на архивную копию с неверной для её нового расположения логикой ROOT; до исполнения план исправлен на исходный S4 helper с exact argv/env. Старый draft сохранён, production не менялся. Детали — [source](../verification/v2-100ksps-schedule/critic-source.json), [static](../verification/v2-100ksps-schedule/critic-static.json), [image/plan](../verification/v2-100ksps-schedule/critic-flash-image.json).

## Обязательные условия опыта

1. Сохранить прежние питание и пустой PA0. Приложение и прочие владельцы COM закрыты; probe ID0 с прежним SN. При смене соединений или неоднозначности остановить подготовку. Exact BIN и fresh backup не изменять.
2. Записать только указанный BIN по0x08000000 с verify. Отдельно прочитать0x8D18 байт и сравнить все байты/SHA до START. Затем Reset/Run и подтверждённое USB-переподключение; проверить фактический COM.
3. До единственного START принять build0x56325338, CAPS100000/1, CH1/12bit/DATA128. Выполнить exact argv плана с seconds10 и новым `build/v6e-board-01/run`. Wire build не заменяет readback. Скрытых повторов при отказе нет.
4. Успех требует полных10с Record без source/host fault, грубого темпа90000…110000 received/s, normal END reason0 и соответствующего ACK, fresh Open и побайтного совпадения всех выбранных raw с wire без gaps/overlap. Host monotonic не калибрует Fs; неизвестный produced/loss остаётся неизвестным.
5. Не использовать SWD во время записи. После Stop и закрытия COM прочитать два frozen record0x20002BC4/136: правильные build/nonce/generation, flags0, ошибки0, ADC stopped/owned0/hardware_off1, observed poll/copy строго<5120мкс. Диагностика после неподтверждённого Stop не доказывает нормальное завершение.
6. Прочитать полные блоки TIM3 0x40000400/48, ADC0x40012408/12, DMA0x40020008/16, RCC0x4002100C/20. Ожидаются CEN0/PSC71/ARR9, ADC_CR2=0/SMPR2=4, DMA EN0, нужные clocks enabled/reset released. ADC_DR не читать. Frozen shape отдельно не означает normal Stop.
7. При отказе сохранить traffic/raw/journal/логи/dumps, закрыть владельца и вернуть свежие64KiB S4 с verify/readback. READY без START выполнять exact S4 helper/argv/env плана. Дальше — измерение отдельных фаз и причин задержки USB, а не ещё один скрытый повтор или произвольное снижение Fs.

## Оценка допуска

| Критерий | Балл | Основание |
|---|---:|---|
| C1, 30% | 9,7 | Exact расписание, сохранённые guards, Fs/сроки/память и критерии одного опыта проверены. |
| C2, 20% | 9,6 | Fresh backup, verify/readback/rollback и fail-closed сохранены; успешное исполнение не предполагается. |
| C3, 25% | 9,5 | Личные source/native/static/hash/ELF проверки и fresh read; монтаж подтверждён пользователем, а модель имеет явные seams. |
| C4, 15% | 9,6 | Проверяется конкретная гипотеза, допуск отделён от аппаратного результата, новых аналоговых соединений нет. |
| C5, 10% | 9,6 | Точные план, образ, инструменты, копии и исправленный READY argv закреплены. |

`0,30×9,7 + 0,20×9,6 + 0,25×9,5 + 0,15×9,6 + 0,10×9,6 = 9,605`.

**PASS только допуска.** Приёмка общего E остаётся BLOCKED_EVIDENCE; прежние A/C/D не переоценены. Короткий транспортный опыт не доказывает GUI с физической платой, длительную устойчивость, точность времени/напряжения, аналоговую полосу или работу с зажиганием.
