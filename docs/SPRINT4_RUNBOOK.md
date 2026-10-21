# AgriTrace Sprint 4 — Chạy và kiểm tra trên database cách ly

Nhánh làm việc: `fix/sprint4-system-completion`, nền `144f703`. Chưa commit/push/merge. Không dùng database chính để chạy các bước nâng schema.

## Chạy bản demo đã chuẩn bị

Tại thư mục dự án, PowerShell:

```powershell
.\scripts\start_app.ps1 -DatabasePath "$PWD\.sprint123-trial\sprint4-completion\final\demo-final.db" -Port 8896
```

Database này là bản sao kiểm thử, có ba sản phẩm/lô E2E, Recall và dữ liệu cảm biến mô phỏng. Dùng tám mục đăng nhập nhanh hiện có. Các mật khẩu dùng trong kiểm thử chỉ được thay trên bản sao; file `sensor-credentials.local` trong cùng thư mục chứa thông tin thử nghiệm, bị Git bỏ qua, không đưa vào báo cáo công khai hoặc commit.

URL công khai của runner tự dùng host/port đã chọn. Khi triển khai qua domain/LAN/reverse proxy, đặt `PUBLIC_TRACE_BASE_URL` thành URL HTTP(S) thật của `trace.html` trước khi khởi chạy; không dùng địa chỉ loopback cho điện thoại ngoài máy chủ. `frontend/config.json` giữ same-origin, không đổi ứng dụng chính sang database test.

## Tạo một bản sao khác

Dùng SQLite backup API, mở nguồn `mode=ro`, từ chối ghi đè đích đã tồn tại. Ví dụ chạy bằng Python của `backend/.venv`:

```python
from pathlib import Path
import sqlite3

root = Path.cwd()
source = root / 'data/agritrace.db'
target = root / '.sprint123-trial/sprint4-new-demo.db'
if target.exists():
    raise RuntimeError('Đích đã tồn tại; hãy chọn tên mới')
target.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as src:
    with sqlite3.connect(target) as dst:
        src.backup(dst)
```

Sau đó chỉ nâng bản sao:

```powershell
.\scripts\start_app.ps1 -DatabasePath "$PWD\.sprint123-trial\sprint4-new-demo.db" -UpgradeSchema -Port 8896
```

`-UpgradeSchema` bị từ chối với đường dẫn chính `data/agritrace.db`, `backend/ttcs.db` và alias/hardlink cùng file. Mặc định chỉ kiểm schema. Schema thiếu thì startup dừng với danh sách cụ thể; không tự seed/reset/chạy lại migration Sprint 1–3.

## Chính sách nhiệt độ đã được trưởng nhóm xác nhận

- Quản trị hệ thống vào Danh mục sản phẩm → Ngưỡng nhiệt độ; cấu hình min/max và độ trễ từ 30 phút trở lên.
- Mỗi lô được đánh giá bằng cấu hình sản phẩm riêng, không áp một ngưỡng tùy ý lên cả chuyến.
- Chỉ phát hiện khi thời gian vượt ngưỡng liên tục **lớn hơn** độ trễ. Độ trễ 30: đúng 30 chưa vi phạm, 31 vi phạm.
- Số đo trong ngưỡng hoặc đổi từ vượt cao sang vượt thấp kết thúc chuỗi vượt trước đó. Không gộp hai đợt vượt qua một số đo bình thường.
- Chưa có cấu hình: vẫn lưu số đo, hiện “Chưa cấu hình — Không thể đánh giá”; không mặc định an toàn.
- Cấu hình mới/sửa chỉ đánh giá các số đo nhận từ lúc lưu cấu hình; không phán xét lại số đo trước đó. Sự kiện phát hiện là bằng chứng tại thời điểm phát hiện, không sửa lại payload/hash khi có số đo tiếp.
- Vi phạm tự động dùng khóa duy nhất của lô/thời điểm bắt đầu và `source_trip_id` riêng; không làm mất cơ chế unique/idempotency của API ghi vi phạm thủ công.

## Chạy simulator với API thật

Mở một chuyến, ghi lại mã thùng. Dùng thông tin tài khoản vận chuyển của bản sao; ví dụ với bản demo chuẩn bị sẵn:

```powershell
$s4DemoAuth = Get-Content .sprint123-trial\sprint4-completion\final\sensor-credentials.local -Raw | ConvertFrom-Json
$env:AGRITRACE_SENSOR_PASSWORD = $s4DemoAuth.password
.\backend\.venv\Scripts\python.exe scripts\sensor_simulator.py --username $s4DemoAuth.username --url "http://127.0.0.1:8896/trips/active-container/MA_THUNG/readings" --count 10
Remove-Item Env:AGRITRACE_SENSOR_PASSWORD
```

Có thể đặt `AGRITRACE_SENSOR_USERNAME` và dùng URL mặc định cổng 8765 với `--container MA_THUNG`. Nếu không đặt mật khẩu qua biến môi trường, CLI hỏi bằng getpass, không đưa mật khẩu lên command line/log. Không gửi Basic Auth qua Internet không có HTTPS.

`--replay path.json` nhận danh sách `[{"temperature":15,"recorded_at":"2026-10-20T00:00:00Z"}, ...]`. Đây là dữ liệu thời gian mô phỏng để nghiệm thu, không phải chờ đồng hồ thật 31 phút. Simulator thông thường gửi UTC thực, mặc định mỗi 5 giây. Xem lịch sử/đánh giá trong chi tiết chuyến và dùng nút Làm mới nhiệt độ.

## Kiểm tra trước/sau nâng

1. Ghi SHA-256 nguồn, số hàng/fingerprint các bảng hiện có; integrity_check, foreign_key_check, hash-chain từng lô, DDL indexes/triggers.
2. Giữ nguyên marker Sprint 1–3, không sửa payload/hash/Recall/bàn giao. Nâng tạo năm bảng S4 (bao gồm bảng cấu hình sản phẩm), hai cột batches và `source_trip_id` nếu đang dùng schema S4 cũ.
3. Bộ nâng tự khóa ghi, tạo backup SQLite tên mới, chạy DDL trong transaction, so fingerprint trên các cột cũ và so indexes/triggers cũ trước commit. Không nuốt lỗi drift/unique/FK.
4. Sau nâng, kiểm readiness, số hàng/fingerprint/hash-chain/FK, constraints/partial unique. Chạy lần hai phải no-op. Sau đó mới chạy smoke có ghi dữ liệu trên một bản sao thử nghiệm.

## Rollback

- Lỗi trước commit: transaction rollback; ứng dụng không serve schema dở. Giữ backup và log.
- Lỗi sau commit, chưa có dữ liệu nghiệp vụ mới: dừng mọi process dùng DB; khôi phục backup `.backup.db` sang **tên mới**, kiểm integrity/FK/fingerprint/hash-chain rồi chọn tệp phục hồi qua `-DatabasePath`. Không ghi đè hoặc xóa database lỗi.
- Đã có nghiệp vụ sau nâng: bảo toàn cả DB/backup, dừng ghi và đối soát; không restore mù làm mất giao dịch mới.
- Không DROP bảng/cột cũ hoặc reset Git để rollback. Không tự nâng/restore database chính; việc đó cần phê duyệt riêng.

## Kiểm thử tái lập

```powershell
$env:DATABASE_URL = 'sqlite:///:memory:'
.\backend\.venv\Scripts\python.exe -m pytest backend/tests scripts/test_sensor_simulator.py -q
.\backend\.venv\Scripts\python.exe -m flake8 backend/app backend/scripts/run_agritrace.py scripts/sensor_simulator.py
node --test frontend/tests/trace-url.test.cjs frontend/tests/trace-integrity.test.cjs
```

Test file SQLite dùng đường dẫn tạm riêng. Bằng chứng phiên triển khai nằm ở `.sprint123-trial/sprint4-completion/` (Git ignored). Không đưa database, credentials hay 21 tệp untracked được bảo vệ vào commit.
