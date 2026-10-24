# H: ограничение turnover USB после F2/G2

## Подтверждённые факты

S4 работает50k, S8/S9 и SA пробовались100k. G2/SA вновь queue-full8 после4992wire samples, source END reason1 до Stop; ADCfault0 означает только отсутствие зарегистрированного ADC fault. Полнота ADC и устойчивые100k не подтверждены. Legacy poll1375мкс и copy202мкс меньше5120, но поздние метрики включают drain. SA TXmax276,5мкс исключает prepare; это не сравнение с полным TX S8/S9.

F2 first-close31,176806мс:41foreground passes,15DATA128 committed и14ZERO_SPACE; grants denied15, hold_final16, hold_time1, hold_budget0. TIME572updates/sum557758циклов, ISR91/sum179189циклов; они вложены в wall-фазы и не суммируются как независимые доли CPU. S9 observer оказывает неизвестное полное влияние; raw-read heuristic1,6044% не его граница.

## Конкретная serial dependency

Точные пути далее относительно `build/v6g-fw-02`:

- `patched/usbd.c:907` исполняет максимум один task event; XFER_COMPLETE освобождает BUSY/CLAIMED в `:842..857` и вызывает CDC callback. Callback может публиковать следующий FIFO transfer.
- `patched/dcd_stm32_fsdev.c:485` удерживает IRQ при входе. Только промежуточный IN может продолжить серию в `:602..626`; финальный IN остаётся held и ставит событие.
- `patched/v2/app/mt_live_runtime.c:212` task находится до ADC. Единственный grant — только в конце wrapper `:278..291`; при `tud_task_event_ready()` обычный CTR запрещён.
- Поэтому final IN после task → held+event → end grant(false) → следующий task clears BUSY/может публиковать следующий transfer → **CTRM ещё0 через целый ADC/RX/prepare/TX/TIME проход до следующего end grant**. Чистый prepare SA находится до PRIMASK, но это не снимает уже held USB IRQ/CTRM.

Путь определён исходниками; F2 counts с ним согласуются. Профиль не сохраняет порядок каждого final/event/grant, поэтому нельзя утверждать, что каждый DATA прошёл именно этот путь или приписывать ему точную длительность. Max IN gap5,449мс мог включать первые5,12мс заполнения DMAhalf и не доказывает host stall.

## Бюджет и сравнение

| Свойство | S4 | S8 | SA |
|---|---:|---:|---:|
| Fs, тыс.отсчётов/с |50|100|100|
| DATA samples |128|128|128|
| DMA half |128|512|512|
| core offer cap, байт |64|384|384|
| TIME updates healthy DATA/empty DMA pass |14|14|14|
| grant point |wrapper end|wrapper end|wrapper end|
| pure prepare before guard |нет|нет|да|

DATA128 при100k должен уходить каждые1280мкс, бюджет92160циклов при72МГц. Фактический frame307байт даёт239843,75wirebytes/s и5IN packets (4×64+51). FIFO configuration384 не означает transfer384: `tusb.c:401..416` при ep_buf=NULL берёт фактический FIFO count. F2 это подтверждает:4651байт=46START_ACK+15×307,76пакетов=1+15×5. Значит final turnover происходит приблизительно на каждом DATA, хотя его длительность не измерена. Политика short packets сама по себе в H не меняется.

F2 средний полный STEP740,553мкс; два таких средних прохода1481,107мкс превышают1280мкс (арифметические86,4k raw/s). Это иллюстрация масштаба возможной serial зависимости, **не измеренный устойчивый предел или WCET**: середина/начало захвата, ADCfull и ZERO смешаны. Часы номинальные.

TIME source в S4/S8/SA побайтно одинаков (SHA в JSON): один update27MMIOreads,14updates→378reads на healthy pass. F2 mean13,543мкс/update,7,7466мс вложенных TIME в31,1768мс observation. Удаление проверок недопустимо; direct-MMIO specialization мог бы убрать callback overhead, но это другое изменение и экономия не измерена. Ticket SA —160байт ARM, fixed32logical field comparisons,2matches перед write, без MMIO/ожидания;153static instruction rows не являются циклами. Нет свидетельства, что именно ticket доминирует. Frame build обнуляет544байта и использует bytewise memcpy/CRC/COBS; G перенёс его, не устранил CPU стоимость. Увеличение буфера не исправляет средний дефицит.

## Одна выбранная H-гипотеза

Сделать **единственную обычную CTR opportunity после ADC+fresh TIME/stable/loss и до RX/prepare**, чтобы transfer, опубликованный task, не ждал всего дорогого прохода. Старый wrapper действует только как fallback для return до этой точки. Одна попытка за runtime step, без второго reset6/<500мкс; прежние lifecycle/OUT/SETUP/TIME/error и post-write guards сохраняются. После возможного раннего IRQ заново проверить TIME/epoch/lifecycle до RX/write, не публикуя stale bytes.

Реализация требует отдельного компактного контракта actor/app scope, early returns и моделей порядка/единственного grant. Это одна schedule-оптимизация, не packetization/TIME/queue/Fs rewrite. Достаточность для100k проверяется физически отдельно;200k не объявлены невозможными. Этот документ получен offline, без тестов, COM или SWD.
