# Изолированный прототип DATA1024

Модуль не подключён в production recipe. Установленная SD и её runtime,
RX/previous544, USB/DMA/queue и сохранённые результаты K2 не изменены.
Назначение — проверить размещение1024 packed10 в TX1336 с late header count,
ограниченные этапы CRC/COBS и раздельные staged/committed prefix.

`mt_batch1024_state` —32байта, caller-owned TX —1336. Raw начинается с7,
COBS output с0: in-place кодировщик не требует второго большого массива.
Collection принимает исходный ADC12, проверяет значения до masking и считает
canonical prefixCRC по u16le. Wire frame максимум1335; фрагменты≤384 относятся
к одному кадру с одним delimiter. Кандидат prefix публикуется только после
всех известных accepted bytes и переданного внешнего final-guards predicate.
Это API seam; модуль не реализует сам epoch/TIME/USB/queue admission.

Collection рассчитан на work-state и свободную область, включая retry-safe
shared-byte append. CRC/COBS этапы destructive/monotonic: после invalidation
нужен abort всего in-flight frame, старый state не откатывает storage.
Перед production обязательно отдельное доказательство queue→staging ownership,
Stop/HELLO/Abort/fault, ADC service schedule и exact linked SRAM/stack.

Один необходимый проверяющий проход:

```powershell
.\.venv\Scripts\python.exe -I -B tests\v2-stream-firmware\batch1024_check.py --output build\v6l-native-NEW
```

Runner компилирует native модель, запускает её один раз и компилирует только
ARM object для размера state/локальных `.su`, без ARM image/link/Flash.
Сохраняет stdout/stderr/inputs и synthetic1153-code fixture для host crossdecode.
Он не открывает COM/SWD. Фактические проверки — в progress/review; кодирование
не подтверждает stable150k, аналоговую точность или зажигание.
