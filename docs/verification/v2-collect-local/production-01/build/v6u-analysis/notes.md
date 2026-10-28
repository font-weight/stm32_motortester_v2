# U/SN: эквивалентная упаковка collect

28.10.2026. База — exact SL `build/v6s-fw-02`, source695efd9 и
`build/v6s-freeze.json`. T/preflush отклонён без нового образа. Кандидат
SN/`0x5632534e` получает общий ID из config/generated header. Это программная
оптимизация, не подтверждение устойчивых150k.

Единственная алгоритмическая дельта — `mt_batch1024_collect` production
serializer. `-Os`, остальные семь API, CRC/COBS step и общий протокол прежние.
CRC уже local в SL: новой экономии CRC этим фактом не приписывать.

## Контракт

- Сначала прежняя полная проверка arguments/phase/count/indices и всех ADC12
  codes. Invalid call не меняет state либо storage.
- Начальный count и byte cursor локальны. Для alignment до четырёх samples
  и хвоста — scalar shared-byte append: сохранить только owned low bits,
  заменить speculative high bits. Retry после rejected work-copy корректен.
- На byte-aligned группе четыре10-битных q дают пять bytes со сдвигами
  0/2/4/6. Никакого store в следующий byte; произвольные count1..512 и
  начальный count0..1023, total≤1024 остаются допустимыми.
- Canonical code=(ADC12>>2)<<2; prefixCRC идёт тем же u16le порядком.
  Весь state32 публикуется как раньше при возврате. State/input/storage
  disjoint по существующему header; нового restrict/alias assumption нет.
- Нет новых static данных, callback/IRQ guards, queue pop/commit или RX.
  Runtime/S handoff, driver, DCD6/<500, TIME, deadline3413, whole-fit384,
  staging1336/queue8, Stop/HELLO и ABI136/64/24 неизменны.

## Необходимое доказательство

Host author пишет только `collect_local_model.c`. Один новый runner
`check_collect_local.py`: actual frozen SL и candidate C под sl_/sn_ API,
return/state32/all1336 bytes/canaries после вызовов; alignments/tails,
invalid-before-write, rejected-work retry и полный seal/step/commit/frameCRC.
Без повторения прежнего большого step sweep или hardware/GUI suite.

Одна exact ARM сборка: unchanged patched sources/остальные function bodies,
остальные objects (кроме config-derived identity), 0static growth,
reserve8192 и stack bound. Сравнить горячий compiled collect с SL:
убраны per-sample count reload/индексная арифметика, для основной группы
вместо восьми byte stores — пять; зафиксировать реальный ARM результат.
Это instruction/work reduction, не WCET/CPU-share/измерениеFs.

Если material loop reduction не подтверждён, нового аппаратного опыта нет.
Иначе independent exact source review≥9,5 и отдельный root physical plan.
Build/tests не открывают COM/SWD. Неудачные результаты сохраняются.
Архив — дельта и ссылки/хеши frozen SL, без копии сотен baseline inputs.
