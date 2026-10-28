# R2 / SK: фактический аппаратный опыт 28.10.2026

Root — единственный оператор COM/SWD. Пользователь ответил «готово» на
call_2bb73a17ab2045fe8b6f8c0c91e97507: новый холодный перезапуск обоих USB
после установки SK. Длительность ручного отключения независимо не измерялась.
В 03:50:58 UTC Windows показала ожидаемый COM6/code0 и owners=[].
Установленный образ ранее сверён полностью (46820 байт); аппаратных
перепрошивок/Reset между этим подтверждением и опытом root не выполнял.

Ровно один START по принятому плану: команда 03:51:17.400011–03:51:18.591850 UTC,
wall 1.1918345 с. Требуемые 30 с не достигнуты: FAIL/device_1/queue-full.
Получены 21 DATA1024 = 21504 кодов. Record [2048,21504) = 19456 кодов;
Record host wall 0.1324486998 с. Это не измеренная частота АЦП.
Nonce 7266eaaa454327da, generation3, build SK/0x5632534b, mode5.
END seq25/reason1/flags3/prefix21504/CRC2237768949 пришёл до host STOPreq4;
matching ACKseq26. Offline wire/индексы/CRC/raw/freshOpen прошли для полученного
префикса. Хвост и число потерянных измерений неизвестны. Полных 30 с нет.

До окончания команды, cleanup_finished и phase=closed SWD/halt не применялись.
После offline-проверки согласованных END/STOP/ACK прочитаны дважды 136/64/24,
затем stopped TIM3/ADC/DMA/RCC. ADC_DR не читался. Все stopped checks true.
Legacy: queue8, firstreason1, ADCfault0, maxpoll2907мкс, copy166мкс.
Снимок64: queue8, READY1024, TX1152/1335, FIFO free64, held/deferred=true,
task_ready=false. First close 10580665 nominal cycles (~146.95мс), prepare
4203334 cycles/158, positive26517B/79, zero-space45/other0. FIFO acceptance
не означает USB delivery; prepare включает прерывания, это не CPU share.

Новый24B: flags15, serial82, decisionPUBLISHED, total384/queued64,
ACTIVE=true, APPLICABLE=false, evaluated TIME/budget неизвестны. Публикация
помечена за18497 nominal cycles (~256.9мкс) до N CLOSING. Декодер валиден с
предупреждением historical_not_applicable. Не наблюдается применимая причина
HOLD_TIME/BUDGET/FINAL; поздний HELD64 не связывает её с этой публикацией.
64/24 не одновременные снимки. Поэтому результат сужает следующий offline
разбор к пути публикации/первого IN, но сам по себе не устанавливает причину
переполнения или достаточную пропускную способность. Observer влияет на время.

Все парные байты совпадают и identity64/136/CAPS/readback согласованы.
physical-analysis.md сохранил унаследованную подпись «SJ» перед правильным
build0x5632534b; это известная косметическая ошибка pinned helper. Фактически
проверена SK, исходный вывод не исправлялся задним числом.

После опыта START/Flash/Reset/50/100k/отката не было. SK оставлена остановленной.
Новые hardware действия в этом плане не допускаются; дальнейший offline разбор
можно вести по сохранённым данным. Устойчивые150k остаются незакрытой целью.
