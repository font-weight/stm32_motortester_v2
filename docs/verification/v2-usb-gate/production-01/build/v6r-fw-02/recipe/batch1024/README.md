# Serializer DATA1024

Модуль кодирует mode5/wire0.3 по [контракту](../../../docs/streaming-batch1024.md).
Production recipe подключает `production/mt_batch1024.c` и общий API
`production/mt_batch1024.h`. Прежний `mt_batch1024.c/.h` в этой папке —
сохранённый исходник прототипа и SE для воспроизводимого сравнения.
Оптимизация локальных CRC/cursors описана в [контракте M](../../../docs/streaming-serializer-local.md).
Фактическая готовность и выполненные проверки — только в progress/review.

State —32байта, caller-owned TX —1336; state/storage/input не пересекаются.
Raw начинается с7, COBS output с0; второй большой массив не нужен.
Collection валидирует ADC12 до masking и считает canonical u16le prefixCRC.
Wire frame≤1335, immutable fragments≤384 относятся к одному кадру с одним
delimiter. Принятый prefix публикуется только после полного известного
acceptance и внешних final guards. Epoch/TIME/queue/USB admission реализует core.

Collection допускает work-state и retry-safe shared-byte append. CRC/COBS —
destructive monotonic этапы: invalidation требует abort всего in-flight frame;
откат cursor не восстанавливает изменённое storage. Один step обрабатывает
до512 input bytes, сохраняя state перед каждым возвратом. Ограниченный объём
работы сам по себе не доказывает ADC service deadline или физический темп.

Сборка production без COM/SWD/Flash:

```powershell
.\.venv\Scripts\python.exe -I -B firmware\v2-stream\build_windows.py --output build\v6m-fw-NEW
```

Адресная проверка нового serializer и его подключения к actual core:

```powershell
.\.venv\Scripts\python.exe -I -B tests\v2-stream-firmware\batch1024_local_check.py --image build\v6m-fw-NEW --baseline build\v6l-fw-04 --zig build\v5-native-toolchain\zig-x86_64-windows-0.15.2\zig.exe --output build\v6m-native-NEW
```

Runner сравнивает serializer с frozen SE, исполняет actual-core модель,
сохраняет input pins/выходы и fixture. Он не открывает аппаратные интерфейсы.
Исторический `batch1024_check.py` отдельно воспроизводит изолированный
прототип; его успешная проверка не заменяет production ownership/Stop/HELLO.
