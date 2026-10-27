# SF: срок DMA соблюдён, но очередь всё равно заполнена

27.10.2026, higher_fs_review. Только чтение сохранённого SF-опыта и exact
исходников `build/v6m-fw-01`. Новых сборок, тестов, COM/SWD/Reset, изменений
production или канонических документов не выполнялось.

## Наблюдение

`build/v6m-board-02/150000/physical-analysis.json`: build0x56325346,
nonce89f044908e44e09b/gen3, mode5,150000/10retained/maxDATA1024.
Три полных DATA =3072 Preview-кода, END reason1/flags3 до host STOP,
неизвестный произведённый хвост. Записан диапазон[1024,3072),2048кодов;
его raw/CRC/fresh Open совпали с wire. Короткие0,0163207с Record и host
timestamps не являются устойчивым темпом150k. Источник остановлен, SF
остаётся на плате. Проверка сохранённых байтов PASS не отменяет physical FAIL.

`diagnostics-decoded.json`: queue8/8, first_acquisition_reason1,
ADCfault0/localerror0, copy7, poll41, step91, TX91; maxpoll2834мкс,
copy112мкс, maxstep203716cycles, guardedTX14317cycles. Это замороженная
legacy136; она не сохраняет состояние FIFO/staging в момент первого отказа
или active-only количества successful/zero writes. Итоговые state/регистры
после Stop/drain не восстанавливают такое состояние задним числом.

## Почему2834<3413 не предотвращает queue-full

Это две независимые задачи обслуживания.

**DMA:** при150k half512 обновляется через512/150000 =3,413333мс.
`adc_timer_dma.c:542–610` проверяет poll deadline `<3413мкс`, события DMA,
положение CNDTR, безопасную половину до/после копирования и переносит512кодов
в отдельный snapshot. ADCfault0 означает только отсутствие зарегистрированного
driver fault; измеренного WCET или доказательства всех преобразований нет.

**Transport queue:** `app/mt_live_adc.c:95–119` после валидной копии предлагает
четыре queue128 подряд. Они должны целиком найти место в queue8. Затем уже
выполняются grant, RX, prepare и guarded write. `mt_live_device_offer:757–762`
при отказе push вызывает terminate(reason1), хотя сама DMA-копия была вовремя.

В установившемся режиме очередь должна в среднем освобождать512 отсчётов
за3,413333мс. Её1024кода — только6,826667мс производства. Из состояния8/8
не помещается даже первый chunk128 очередной половины; из состояния5/8
не помещается её четвёртый chunk. Частые успешные poll не освобождают очередь.
Счётчик copy7 — число наблюдённых копирований snapshot, а не семь принятых
полупакетов: последующая передача в transport может отказать.

Наличие отдельного staging1024 позволяет пережить часть backlog, но это
не вторая очередь для следующего кадра. `build_tx:465` возвращает cached TX
сразу при `tx_length!=0`, до `batch_prepare:383`. Пока готовый/частично
принятый DATA отправляется, следующий queue→staging collect не выполняется.
В самой COLLECT-фазе за проход забираются максимум4×128=512.

Полный frame≤1335 требует минимум четырёх positive whole-fit предложений:
384+384+384+183. Все они выполняются в разных runtime-проходах: `step_tx:718`
предлагает не более384 один раз; `live_write:110` возвращает known-zero при
недостатке FIFO-space, даже если часть места свободна. При cached TX такой
zero-проход также не собирает очередь. Два collect-прохода плюс три оставшихся
write-прохода дают минимум пять проходов на полный кадр, даже без zero/EMPTY
poll; последний collect совмещён с первой write.

Для150k надо завершать≈146,484кадра/с, в среднем один1024-frame за6,826667мс.
Это не менее≈732,422прохода/с только по этой нижней структурной оценке.
Реальных проходов может быть существенно больше из-за ожидания новой half,
free-space, TinyUSB task/final-IN и lifecycle. Каждый несёт сохранённые
TIME/epoch/ADC/RX/guard проверки; максимум poll ограничивает один интервал,
а не суммарный backlog или возраст текущего TX.

## USB: что известно по коду и чего не измерено

`app/mt_live_runtime.c:207–300`: одна grant opportunity после ADC и свежей
TIME/stable проверки, до RX/prepare; поздний второй бюджет запрещён.
`dcd_stm32_fsdev.c:180–195,613–626`:6пакетов и<500мкс разрешают продолжение
лишь одной уже опубликованной IN-передачи≤384, с прежними проверками.
Final-IN ставит task event и остаётся held до следующего foreground.
Следующий `tud_task_ext` может опубликовать transfer, а его IRQ вновь ждёт grant.

Поэтому1логический DATA1024 не означает1USB-transfer или1IRQ opportunity.
Обычная отдельная packetization трёх384фрагментов и183хвоста —6+6+6+3=21
IN-packet; реальная FIFO/control/partial packetization может отличаться.
Worst wire bytes≈1335×150000/1024=195556,64байт/с. Это меньше номинального
12Mb/s физического USB, но номинальная line rate не гарантирует темп такой
foreground/FIFO/final-completion схемы. В текущем логе нет IN/NAK timestamps.
Host service-gap29мс не равен паузе USB на плате и не доказывает host stall.

Шесть внутренних quanta CRC/COBS всё ещё выполняются в одном prepare.
SF убирает state LDR/STR из горячих циклов, но не устраняет эту единичную
нагрузку, четыре submit на кадр или fixed TIME-затраты на каждый проход.
Нельзя называть единственной причиной ни encoder, ни USB, ни TIME.

## Сравнение с SE L2

| Сохранённое наблюдение | SE L2 | SF |
|---|---:|---:|
| Принятые полные DATA1024 |8 |3 |
| Получено Preview-кодов |8192 |3072 |
| Выбранная запись |failed_unbound |2048кодов,[1024,3072) |
| Maxpoll,мкс |3337 |2834 |
| Maxstep,cycles |239935 |203716 |
| GuardedTX,cycles,безprepare |14950 |14317 |
| Queuehigh-water / ADCfault |8/8 /0 |8/8 /0 |
| Copy / poll / step |17 /65 /91 |7 /41 /91 |

Меньшие SF maxima согласуются с возможным сокращением одного длинного
прохода, но эти два разных коротких опыта не измеряют выигрыш encoder и
не доказывают регрессию из-за3вместо8DATA. Время USB host scheduling,
момент queue-full и drain различались. Особенно нельзя вычитать guardedTX
из отдельного maxstep или считать step91/длительность host записи CPU-темпом.
Оба результата остаются FAIL; delivered prefix включает drain после отказа.

## Один наиболее полезный следующий шаг

**Сначала компактный active-only first-fault trace очереди/TX progress,
без очередной функциональной оптимизации.** Legacy136 уже не отвечает,
где в цикле задержан следующий collect. Повторение прежнего опыта с той же
диагностикой даст ещё один конечный prefix, но не различит эти причины.

Ограничить отдельный диагностический draft одним64B foreground-owned bank,
сохраняя нынешние136байт и полностью прежнюю работу transport. Пример
достаточного набора16слов: magic/version; phase/close/validity/saturation flags;
generation; nonce2; beginDWT; freezeDWT; prepare-inclusive sum; DATApositivebytes;
attempts; zero-space counts; lastpositiveDWT; maxno-positivegap; firstfault
stage/count; firstfault TXoffset/length; firstfault queue/FIFO-space/held/task-ready
flags. Packed поля ограничены размерами state/count≤1024, TX≤1335 иFIFO≤384.
Build проверяется отдельно по неизменным136байтам той же nonce/generation и
exact image pin, а не угадывается из такого compact bank. Это скелет измерения,
не принятый ABI или текущая реализация.

Hook границы: begin только после успешного START; прямые DWT reads вокруг
существующего prepare; DATA write-result после известного return без новых
TIME/MMIO health loops; **first-close при наблюдённом queue-full до terminate,
quiesce и drain**. Freeze должен запрещать поздние эпилоги/записи. Снимок
FIFO/task/held согласовать одним коротким guard, не dispatch task и не читать
ADC_DR. Никакой печати/добавления traffic в CDC. Нормальный Stop/другой fault/
cap наблюдения явно различать.250мс — checkpoint cap только наблюдения, с
actual end/overshoot, не остановка ADC или объявление долгого опыта.

Расчёт памяти:20388+64=20452/20480 с сохранённым8192резервом,28байт остатка.
Это допускает компактный bank без второго frozen/scratch массива; точные
layout/stack/link и observer overhead требуют отдельного software scope и
review. Нового образа/аппаратного допуска этим предложением нет.

Замер ответит, сколько DATA-byte прогресса было ДО первого отказа, были ли
known-zero из-за FIFO, как долго не было положительного write и в какой
staging/TX фазе накопились8slots. Большой inclusive prepare sum укажет на
направление работы, но включает IRQ и не равен доле CPU; малый prepare при
zero-space/held backlog сузит проблему до publication/completion path, ещё
не отделяя host NAK от device gating. По этим данным выбирается ровно одно
следующее исправление scheduler/подготовки, сохраняя deadline, guards, Fs,
пакет1024 и явный отказ. Ни размер очереди, ни rollback сейчас менять не нужно.
