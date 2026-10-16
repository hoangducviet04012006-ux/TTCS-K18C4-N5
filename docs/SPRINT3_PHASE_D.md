# Sprint 3 — Giai đoạn D (S-31 và audit.where S-29)

AC đọc trực tiếp SCRUM-68 ngày 13/10/2026: key actions; actor/action/time/source IP khi có; query/filter theo lot/user. Không triển khai E/F, không lấy code nhánh thành viên.

## Hợp đồng tương thích

Giữ các fields AuditLog cũ. Thêm nullable source_ip, operation, organization_id, location_id/name/address và batch_ids (JSON trên DB, array trong response). Các properties ORM không yêu cầu cột mới khi đọc/ghi DB cũ. Không auto migration/backfill; audit cũ trả metadata null/array rỗng.

IP lấy request.client.host hợp lệ IPv4/IPv6 qua ContextVar, không tin X-Forwarded-For client tự gửi. Service ngoài request ghi null. operation phân biệt split/merge/handover_init/accept/reject/sell_out/allocate_store/transfer_location/recall/confirm/recall_complete, giữ action cũ để tương thích. Audit ghi cùng transaction, không tự commit.

Consume lưu snapshot Location thật trong AuditLog mới; không có vị trí thì null. Không tham chiếu động địa chỉ sau đổi tên/sửa địa điểm. Merge/allocation ghi ID lô liên quan thực để lọc cả cha/con. Recall/ACK ghi root_batch_id; không mở thêm chức năng Recall.

GET /audit-logs giữ list response; thêm batch_id và offset; filters kết hợp entity/user_id/batch_id trước limit/offset. entity mở rộng handover/recall/location/product/organization/batch_event; limit1..500, default100. Không có API sửa/xóa audit.

RBAC giữ nguyên: SystemAdmin/Inspector đọc toàn bộ, OrgAdmin chỉ scope của tổ chức tại thao tác mới. Audit cũ không có snapshot dùng guard cũ actor+target đang thuộc org (fail closed). Không suy snapshot cho lịch sử cũ. Hành động quản trị trên target org khác không lộ qua actor org. 5 tài khoản thường không đọc audit. IP và vị trí được bảo vệ cùng scope audit.

## Migration

Chỉ QA mới có backup: .sprint123-trial/qa_sprint3_d.db. Backup trước migration nằm trong thư mục báo cáo D ngoài repo. Script từ backend:

~~~powershell
python -m scripts.migrate_phase_d_qa --db ../.sprint123-trial/qa_sprint3_d.db --apply
~~~

CLI chỉ nhận qa_*.db đã tồn tại trong .sprint123-trial, từ chối ttcs.db/demo chính thức/hardlink. ALTER nullable additive, index organization_id/id, không sửa 6 fields audit cũ hay events. Startup không tự migration D. Database chưa migration vẫn giữ logging cũ, chưa có metadata D; không coi official đã triển khai S-31 mới.

UI có filters lot/user/entity, paging100, actor/time/action/target/lot/IP/snapshot location, bảng cuộn ngang trên mobile; logout xóa dữ liệu và bộ lọc. Không sửa Farmer/Packing hoặc graph B.

Kết quả cuối và giới hạn browser xem báo cáo nghiệm thu D ngoài repo.
