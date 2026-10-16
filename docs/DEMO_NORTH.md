# Hướng dẫn Demo AgriTrace — Bối cảnh Miền Bắc (Tân Cương – Hà Nội – Bắc Ninh)

Tài liệu này hướng dẫn chạy và kiểm thử bộ dữ liệu demo **miền Bắc** được xây dựng biệt lập tại:
`.sprint123-trial/demo_sprint123_north.db`

---

## 1. Tổng quan Bộ Dữ liệu Miền Bắc

| Thông tin | Chi tiết |
|---|---|
| **Cơ sở dữ liệu** | `.sprint123-trial/demo_sprint123_north.db` (biệt lập, không ảnh hưởng DB cũ) |
| **Sản phẩm chính** | **Chè búp tươi Tân Cương** (đơn vị: `kg`, chuẩn VietGAP) |
| **Sản phẩm bổ sung** | **Rau an toàn Gia Lâm** (đơn vị: `kg`) |
| **Org 1 (id=1)** | **HTX Nông nghiệp Tân Cương – Thái Nguyên** (`HTX-TC`) — Trồng trọt, thu hoạch, sơ chế |
| **Org 2 (id=2)** | **Công ty Chế biến & Logistics Hà Nội** (`LOG-HN`) — Tiếp nhận, chế biến sâu, vận tải chuỗi lạnh |
| **Org 3 (id=3)** | **Trung tâm Phân phối Nông sản Bắc Ninh** (`NPP-BN`) — Phân phối, siêu thị, bán lẻ tiêu dùng |

---

## 2. Vùng trồng & Đồi Chè (Org 1: HTX-TC)

1. **Đồi Chè Tân Cương 1** (ID: 1): Xã Tân Cương, TP. Thái Nguyên (4.5 ha, Chủ hộ: Nguyễn Văn An, Tọa độ: `21.5583, 105.7725`)
2. **Đồi Chè Phúc Trìu** (ID: 2): Xã Phúc Trìu, TP. Thái Nguyên (3.8 ha, Chủ hộ: Trần Thị Bình, Tọa độ: `21.5712, 105.7481`)
3. **Đồi Chè Phúc Xuân** (ID: 3): Xã Phúc Xuân, TP. Thái Nguyên (5.2 ha, Chủ hộ: Lê Văn Cường, Tọa độ: `21.5945, 105.7234`)

---

## 3. Cấu trúc Phả hệ Lô hàng (16 lô hàng)

### Tầng 0: 3 Lô thu hoạch gốc (Đã băm SHA-256 từ Genesis)
- `CHE-TC-01`: 1.000 kg chè búp tươi tại Đồi Chè Tân Cương 1 (SPLIT -> LO-A1, LO-B1)
- `CHE-PT-02`: 1.000 kg chè búp tươi tại Đồi Chè Phúc Trìu (SPLIT -> LO-A2, LO-B2)
- `CHE-PX-03`: 1.000 kg chè búp tươi tại Đồi Chè Phúc Xuân (SPLIT -> LO-A3, LO-B3)

### Tầng 1: 6 Lô sau phân loại phẩm cấp (Tách)
- `CHE-LO-A1` (400 kg, MERGED) & `CHE-LO-B1` (600 kg, MERGED)
- `CHE-LO-A2` (500 kg, MERGED) & `CHE-LO-B2` (500 kg, MERGED)
- `CHE-LO-A3` (300 kg, MERGED) & `CHE-LO-B3` (700 kg, MERGED)

### Tầng 2: 3 Lô gộp theo tiêu chuẩn đóng gói & chế biến
- `CHE-GOP-HN01` (900 kg, SPLIT): Gộp từ `CHE-LO-A1` (400 kg) + `CHE-LO-A2` (500 kg)
- `CHE-GOP-ND02` (900 kg, ACTIVE tại Org 1): Gộp từ `CHE-LO-B1` (600 kg) + `CHE-LO-A3` (300 kg)
- `CHE-GOP-CB03` (1.200 kg, ACTIVE tại Org 1): Gộp từ `CHE-LO-B2` (500 kg) + `CHE-LO-B3` (700 kg)

### Tầng 3: 2 Lô thành phẩm bàn giao từ Lô gộp CHE-GOP-HN01
- `CHE-TP-HN01` (500 kg, ACTIVE tại Org 2 `LOG-HN`): Bàn giao Org 1 -> Org 2 (ACCEPTED)
- `CHE-TP-BN02` (400 kg, ACTIVE tại Org 3 `NPP-BN`): Bàn giao Org 1 -> Org 3 (ACCEPTED)

### Lô Demo Nghiệp vụ Bổ sung
- `CHE-CHO-TIEP-NHAN` (250 kg, ACTIVE tại Org 1): Bàn giao Org 1 -> Org 2 (PENDING — sẵn sàng demo thao tác tiếp nhận cho `s123_receiver`)
- `CHE-TIEU-THU-HET` (200 kg, CONSUMED tại Org 3 `NPP-BN`): Đã bán lẻ hết ra thị trường

---

## 4. Danh sách 8 Tài khoản Demo

Mật khẩu được lưu trong file bí mật `.sprint123-trial/credentials.local` (không đưa vào tài liệu công khai):

| STT | Username / Email | Vai trò | Tổ chức | Đơn vị đại diện |
|---|---|---|---|---|
| 1 | `s123_farm@demo.local` | `farmer` | Org 1 | HTX Nông nghiệp Tân Cương – Thái Nguyên |
| 2 | `s123_packing@demo.local` | `processor` | Org 1 | HTX Nông nghiệp Tân Cương – Thái Nguyên |
| 3 | `s123_receiver@demo.local` | `processor` | Org 2 | Công ty Chế biến & Logistics Hà Nội |
| 4 | `s123_transport@demo.local` | `transporter` | Org 2 | Công ty Chế biến & Logistics Hà Nội |
| 5 | `s123_distribution@demo.local` | `distributor` | Org 3 | Trung tâm Phân phối Nông sản Bắc Ninh |
| 6 | `s123_inspector@demo.local` | `inspector` | None | Thanh tra toàn cảnh nghiệp vụ |
| 7 | `s123_admin@demo.local` | `system_admin` | Org 1 | Quản trị hệ thống AgriTrace |
| 8 | `s123_org_admin@demo.local` | `org_admin` | Org 1 | Quản trị HTX Tân Cương |

---

## 5. Hướng dẫn Khởi chạy & Kiểm thử

### Cách 1: Khởi chạy trực tiếp backend bằng script demo
```powershell
backend\.venv\Scripts\python.exe -m scripts.run_sprint123_demo --db .sprint123-trial/demo_sprint123_north.db --port 8769
```

### Cách 2: Kiểm tra toàn diện tính toàn vẹn (Integrity, Foreign Keys, Hash-chains)
```powershell
backend\.venv\Scripts\python.exe backend/scripts/verify_realistic_db_north.py
```
