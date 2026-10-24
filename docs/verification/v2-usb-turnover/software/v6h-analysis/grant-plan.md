# H: одна ранняя CTR opportunity после ADC

Draft V2SB/build0x56325342;100k, wire/ADC/DMA512half/queue8/FIFO384/MPS64/burst6/<500мкс/TIME/prepare-commit SA неизменны. Profile512 off, legacy136 остаётся. Никакого COM/SWD/Flash.

## API и владение

`static void grant_irq(mt_live_runtime *r)` содержит точное прежнее wrapper grant body: clock_fault/healthy → lock → epoch snapshot → pending/fault/exhaustion/soft/cleaned/task_event gating → mt_usb_fsdev_irq_grant → unlock. DCD grant/continuation не изменяется.

`static mt_live_runtime_result step(mt_live_runtime *r, unsigned *grant_attempted)` получает caller-owned local flag, начально0. После существующих ADC service → live_time → stable/loss → invalid-argument(-2) checks устанавливает1 и вызывает grant_irq. Затем новый fresh live_time и stable/loss барьер перед любым RX. В обычном пути scope ещё entered, actor=current epoch: ISR только обслуживает/публикует события, core callbacks/reentrant task не выполняются. При RESET/epoch/TIME loss после IRQ scope оставляется, прежний time_fault/synchronize_loss обрабатывает отказ до RX/TX. Knownzero/partial/unknown write и prepare ticket не меняются.

Wrapper вызывает step и выполняет `if(!grant_attempted)grant_irq(r)`. Таким образом максимум одна попытка за runtime step; normal и fallback не складываются в12пакетов/два500мкс reset. Flag устанавливается до helper, даже если helper не может открыть IRQ. На аргументном return до начала step прежний wrapper также ничего не делает. Никакого static flag/буфера не добавляется.

## События и границы

| Когда final IN | BUSY/новый transfer | IRQ и следующий CTR |
|---|---|---|
| До tud_task этого прохода | task снимает BUSY; callback может публиковать next | после ADC/TIME ранний grant открывает CTR; RX/prepare больше не обязательная задержка |
| После task, до ранней точки | событие остаётся ready, BUSY не снят | normal grant deny по прежнему event_ready; следующая итерация task→ADC→grant; второго grant в этом проходе нет |
| После раннего grant | ISR final ставит событие и удерживает IRQ | wrapper не делает второй reset; следующий проход task→ADC→grant |
| Return до ранней точки (not-ready/stable/loss/ADC argument) | прежние состояния/cleanup | wrapper fallback ровно как раньше, включая lifecycle без CTR |
| TIME fault после раннего IRQ | stale RX/write запрещены, time_fault/Stop | второй grant не выполняется; clock fault не маскируется |

Возможный lifecycle, появившийся после единственной ранней opportunity, обслуживается на следующем bounded runtime step/fallback, а не вторым burst текущего. ISR/foreground прежних checks не удалять. Это изменение порядка grant, не доказательство WCET или физической100k. Отдельная модель должна проверить event_ready/actor/epoch/TIME/ADC first-cause, early-return fallback и максимум один вызов grant; exact ARM/static затем независимое ревью.

Ограничение производительности: если task ещё не опубликовал transfer, ранний6/<500мкс quantum стартует доRX/encode/TX. К моменту нового publish часть окна может пройти. H не обновляет его второй раз и не гарантирует ускорение первого transfer/startup; steady queued transfer — отдельный сценарий. Это сохраняемая цена одной попытки, а не основание для удвоения grant.
