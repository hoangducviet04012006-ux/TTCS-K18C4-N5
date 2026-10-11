# Cấu trúc bàn giao AgriTrace

Bộ code duy nhất: `D:\TTCS_K23C_N5\TTCS-K18C4-N5`. Điểm khởi động dành cho người dùng ở gốc: **`start_demo.bat`**. Xem [hướng dẫn demo](DEMO.md).

```text
TTCS-K18C4-N5/
├── start_demo.bat                 # Nhấp đúp để mở demo Sprint 1–3
├── scripts/                      # Script hỗ trợ, không phải ứng dụng mới
│   ├── start_demo.ps1
│   ├── start_recall_demo.ps1      # Công cụ thử nghiệm cũ
│   ├── seed_demo.bat             # Công cụ cũ, không chạy cho demo này
│   └── README.md
├── backend/                      # Code API duy nhất
│   ├── app/
│   ├── scripts/                  # Python runner và công cụ kiểm tra
│   ├── tests/
│   ├── backups/                  # Backup database hiện hữu, giữ nguyên
│   └── ttcs.db                   # Database gốc được bảo vệ
├── frontend/                     # Giao diện duy nhất
├── .sprint123-trial/              # Database demo và các DB kiểm thử hiện hữu
├── .recall-trial/                 # Dữ liệu thử nghiệm Recall hiện hữu
├── .demo-logs/                    # Log launcher
├── tools/backups/                # Backup script/cấu hình trước tổ chức lại
├── docs/qa/                      # Bằng chứng kiểm thử, ảnh chụp
├── .git/ và .github/              # Git và CI, giữ nguyên
└── cấu hình Docker, pytest, nginx # Giữ nguyên để phát triển/bàn giao
```

Các thư mục trial chỉ chứa dữ liệu/công cụ kiểm thử, không chứa bản sao Backend hoặc Frontend. Giữ nguyên vị trí database, log và backup để tránh phá tham chiếu, đường dẫn an toàn và cấu hình local. Không cần gom tất cả vào một thư mục mới.

Launcher gọi `scripts/start_demo.ps1`, chạy Python trong `backend/.venv` với thư mục làm việc `backend`, phục vụ chính `frontend/` hiện có. Database duy nhất được launcher này chấp nhận là `.sprint123-trial/demo_sprint123.db`, phải tồn tại sẵn. Cổng mặc định 8765; nếu bận, launcher in PID và thử cổng tiếp theo, không dùng lại hoặc dừng server khác. URL thực tế được in trên màn hình và tự mở trong trình duyệt.

Database, file `*.local`, log và `**/backups/` được Git ignore. Bản sao script/config có manifest SHA-256 để kiểm tra; không sao chép database hoặc thông tin đăng nhập local vào backup này. Các launcher phát triển bên trong Backend/Frontend vẫn được lưu giữ cho người phát triển, không phải cách chạy demo dành cho người dùng.

Phạm vi bàn giao dừng tại Sprint 1–3. Code Recall và cấu hình migration cũ được giữ nguyên, không chạy thêm.
