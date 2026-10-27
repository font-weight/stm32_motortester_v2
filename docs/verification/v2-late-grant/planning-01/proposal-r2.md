# N2: очередь DMA и окно обслуживания USB — 27.10.2026

Статус: offline-предложение одного следующего изменения, **не исправление и не
приёмка150k**. Прочитаны сохранённые N2 и exact SG из `build/v6n-fw-01`.
Новые сборки, тесты, COM/SWD/Reset/START и production-изменения не выполнялись.
На плате остаётся SG; завершённый N2 не даёт разрешения на новый опыт.

## Наблюдение и пределы

Входы: `build/v6n-board-01/150000/{progress-decoded,diagnostics-decoded,
physical-analysis}.json`; одинаковые пары64/136, nonce`1ee629e5d97127e3`,
generation3, build`0x56325347`. Первая причина QUEUE/1 зафиксирована **внутри
ADC service до terminate/drain и до grant текущего прохода**.

| До первого close | Значение | Что это означает |
|---|---:|---|
| ACTIVE interval | 1758937cycles ≈24,430мс | Номинальные72МГц; wall с IRQ/измерителем |
| Завершённые prepare | 41 / 474368cycles ≈6,588мс | Включают cached/EMPTY/control; не доля CPU и не только encode |
| Положительный DATA FIFO-приём | 6 / 2103байта | Known acceptance в CDC FIFO; не USB delivery/accepted prefix |
| Zero-space / zero-other | 19 / 0 | Реальный отказ available<offer; не неизвестная запись |
| TX / batch / queue | 768/1335; READY1024; 8/8 | Второй готовый кадр принят FIFO частично; очередь заполнена |
| FIFO free / IRQ / task | 0; held+deferred; ready=false | Нет свободного места; источник hold не записан |
| Max no-positive gap | 689131cycles ≈9,571мс | Включает ожидание первого DATA1024; нельзя целиком назвать USB stall |
| Legacy ADC fault / max poll / copy | 0 / 2828мкс / 133мкс | Deadline fault не обнаружен; это не доказательство достаточного drain |

Нет флагов unknown/partial write, open prepare, saturation или DWT-invalid.
Арифметика2103=1335+768 и6=4+2 согласуется с первым полным кадром
384+384+384+183 и двумя384-приёмами следующего кадра. Поля N не позволяют
определить, сколько из этого уже ушло в USB до close. Финальные3DATA/3072кода
и ENDprefix3072 включают последующий drain; не переносить их в active snapshot.

ADC half512 приходит каждые512/150000≈3,413333мс. Queue8×128=1024кода —
ещё≈6,826667мс ёмкости, а не гарантированная задержка. Poll<3413мкс показывает
своевременность наблюдавшегося обслуживания DMA, но не освобождение queue:
подготовленный/cached TX не собирает следующий batch, пока старый кадр не принят.
Кадру1335 нужны как минимум4 положительных вызова write≤384. Вместе с двумя
collect≤512 это обычно не менее5 foreground-проходов на1024кода; отдельные
нулевые записи увеличивают число проходов. При150k это минимум≈732,4прохода/с,
не измеренная производительность. Характеристики SE/SF из иных попыток не являются
контролируемым сравнением; меньший max poll или число полученных кадров не рейтинг.

## Конкретная зависимость в exact source

Все ссылки ниже — строки файлов `build/v6n-fw-01`, без обращения к аппаратуре.

1. `patched/v2/app/mt_live_runtime.c:237,255,262,295`: `tud_task_ext` выполняется
   в начале прохода, затем ADC service, **единственный grant**, RX и полный
   `prepare_tx`, затем guarded submit. Core собирает до512код и при достижении
   полного batch завершает CRC/COBS в том же prepare
   (`patched/v2/protocol/mt_live_device.c:399–444`). Cached TX возвращается
   раньше batch collection (`:478–485`).
2. `patched/dcd_stm32_fsdev.c:180–196`: grant сбрасывает счётчик6 и сохраняет
   TIM2 tick. `:156–161,616–623`: continuation промежуточного IN разрешается,
   только если от **этого grant** прошло<500мкс и остальные lifecycle/owner/
   endpoint/budget проверки прошли. Время RX/prepare между grant и первым IN
   уже расходует это окно. Даже при истёкшем окне первый разрешённый CTR может
   обслужиться; запрещается дальнейшее continuation, это не500мкс busy-wait.
3. `patched/dcd_stm32_fsdev.c:355–382`: промежуточный CTR загружает следующий
   пакет; final CTR публикует completion. `:610–623`: final и небезопасные
   ветви остаются held. Только разрешённый промежуточный CDC IN может продолжить
   тот же transfer, максимум384байта/6×64, без app callbacks.
4. `patched/usbd.c:842–860`: task разбирает completion, снимает BUSY/CLAIMED
   и вызывает CDC callback. `source/firmware/third_party/usb/vendor/tinyusb/src/
   class/cdc/cdc_device.c:516–523` пытается запустить следующий FIFO transfer.
   Соответствующие `tusb.c:401–437` требуют endpoint claim; FIFO384 освобождается
   по мере помещения≤64байт в PMA (`patched/dcd_stm32_fsdev.c:894`), не только
   при final callback. Поэтому FIFO occupancy не равно числу ещё не доставленных
   host байтов и pending completion не равно свободному FIFO.
5. `patched/v2/app/mt_live_runtime.c:111`: whole-fit384/остаток отклоняется
   при недостатке свободного FIFO. Возвращается known0; индексы/CRC не
   продвигаются. Если final появился после task, его software completion
   обслужится только в следующем проходе. Если остановилось промежуточное IN,
   нужен следующий grant. В обоих случаях перед ним опять стоит ADC service.

Снимок held/deferred/!task_ready **не различает** исчерпанное время, бюджет,
остановку промежуточного IN и историю уже обработанного final. Например,
возможна загрузка последнего PMA-пакета старого transfer, заполнение освободившегося
FIFO следующим write и удержание дальнейшего CTR; это лишь согласованный путь,
не установленная причина именно N2. Данных о каждом grant/endpoint состоянии нет.
Подтверждена зависимость времени grant от последующего prepare, но её вклад
в19zero-space и достаточность её устранения пока не измерены.

## Одно следующее изменение: сохранить grant свежим для нового mode5 DATA

Предлагается **перенести ту же единственную grant-попытку за тяжёлую подготовку
нового полного DATA1024**. Cached TX, обычные collect/EMPTY и control, modes1–4
должны сохранять прежнюю H post-ADC точку. Не менять6/<500, FIFO/queue/ADC,
TIME checks, wire, принятие индексов/CRC и Stop.

Поскольку actual PREPARED ticket появляется только после prepare, `tx_length==0`
недостаточен для выбора точки заранее. Узкий scheduling hint до обычного grant:

- Только mode5 и STREAMING; нет cached TX, pending control/error/start и перехода
  сессии. Batch EMPTY либо COLLECT; его identity/count и очередь допустимы.
- Только проход, способный заполнить batch в текущем collect≤512:
  `staged_count + 128*min(queue_used,4) >=1024`; STREAMING блоки должны быть128.
  Если этот hint не выполнен — прежний early grant без изменений.
- Для hint-прохода пропустить early grant, выполнить прежние RX/подготовку.
  После неё проверить реальный результат PREPARED/DATA/mode5, offset0,
  READY/count1024, length/count==ticket и актуальность сессии. Hint не является
  разрешением записи или новым состоянием accepted prefix.

После prepare **до deferred grant** обязательны свежий `live_time`, затем
`synchronize_loss/stable`: сохранённый `mt_timebase_healthy` внутри grant сам
не перечитывает MMIO. Изменение TIME/epoch/lifecycle во время долгого prepare
должно остановить путь до допуска IRQ. Затем заново войти в app scope/actor,
проверить его актуальность и выполнить существующий grant с неизменным gating.
Отказ app_enter не допускает DATA; он завершает выбранную попытку без второго
обычного grant/reset в wrapper. Actor восстанавливается на любом выходе.

После новой IRQ-границы опять обязательны fresh TIME и stable/synchronize-loss,
а **под исходным guard непосредственно перед write — повторная prepared
epoch/soft-serial/ticket проверка**. При потере актуальности — прежняя
recovery/cleanup, без stale RX/TX или публикации префикса. Pre/post проверки
обязательны и для отменённого scheduling hint, если достигается late точка.

RX может успеть принять Stop/HELLO и отменить scheduling hint, либо prepare
вернёт EMPTY/ERROR. Тогда не выдавать DATA по старому hint: использовать одну
late/fallback lifecycle возможность и прежнюю guarded обработку результата.
Это явно небольшое изменение расписания отменённого candidate; оно не называется
строго actual-only переносом. Обычный control, не выбранный hint, остаётся ранним.
Разделять prepare на новый intent/finalize API ради идеальной классификации
сейчас не предлагается.

Attempt marker выставляется **до вызова**, включая grant=false/FRES; wrapper
не может выдать вторую обычную попытку/reset6/500. Ранний return до выбранной
точки сохраняет ровно исходный fallback. Не разрешать дополнительный burst
после final/task, не увеличивать время окна, не обходить task-ready gating.

Цена/риск: прежний in-flight transfer в таком редком new-frame проходе тоже
получит grant позже, а ADC service всё ещё precedes grant и способен первым
обнаружить full queue. Предложение не устраняет конечную сериализацию
completion→task→grant и не доказывает средний темп150k. Надо сохранить ADC
deadline3413мкс: отложенное окно плюс prepare не объявляются WCET по расчёту.
Нет нового frame buffer/постоянного bank; целевой дополнительный static RAM0.
Существующие28байт запаса сверх8192 stack reserve не тратить на телеметрию;
фактический stack/layout и новые local spills проверяются exact ARM.

После отдельного разрешения достаточно одной адресной actual-runtime модели
выбора early/deferred/fallback и единственности grant, ISR epoch/TIME потери
на новой границе и отсутствия stale submit; unchanged-source proof остальных
узлов и одного ARM/resource audit. Новые широкие suite или диагностические
поля не нужны. Только после независимого source/plan review — **одна** отдельная
150k аппаратная попытка с сохранением отрицательного результата при отказе.
Критерий физической готовности остаётся успешный непрерывный захват с проверкой
raw/индексов/CRC/Stop/Open; этот документ его не закрывает.
