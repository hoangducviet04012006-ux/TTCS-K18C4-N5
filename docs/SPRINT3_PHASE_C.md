# Sprint 3 — Giai đoạn C
Phạm vi: S-29, S-30, S-32, current_location của S-27. Không thực hiện D/E/F, không sử dụng PR #10.

## API và schema
- LOCATION_MANAGE: distributor/org_admin, đúng tổ chức; allocation còn cần SPLIT nên OrgAdmin không được phân bổ.
- POST/GET /organizations/locations; PATCH /organizations/locations/{id}. Mã bất biến/unique trong org; ngừng hoạt động bị chặn nếu còn tồn kho.
- POST /batches/{id}/allocate-stores: tối thiểu2child, tổng bằng toàn remaining, đúng holder/state/pending/Recall và active store ownorg, transaction nguyên tử.
- POST /batches/{id}/transfer-location: chuyển nguyên lô nội bộ, không đổi org/không tạo Handover, ghi INTERNAL_TRANSFER.
- GET /phase-c/capabilities: quyền và readiness. Location chưa migration thì menu Location ẩn/API503, startup không tự tạo schema.
- GET/POST batch giữ fields cũ, thêm nullable location_id/current_location/current_location_name; location cũ trong trace vẫn là nguồn gốc.
- Current location lấy địa chỉ Location thực, không fallback Plot/Farm. Metadata/edges mới theo quyền từng batch; mask không mutate cache.
- Generic split kế thừa Location; merge chỉ giữ nếu mọi parent cùng Location; accepted handover clear vị trí cũ. Giữ generic partial split và các quyền cũ.
- Consume chặn remaining<=0/unknown, serialize trước đọc state, tránh2event khi double-submit/race. Ghi snapshot Location vào event CONSUMED mới; AuditLog hiện hữu vẫn actor/time/entity.
- POST /catalogs/import-csv, multipart entity_type=product|plot/file. CSV UTF-8/BOM,<=2MB/5000dòng; row errors/rollback toàn file; trùng tương đương skip, khác nội dung báo lỗi; không upsert cũ.
- Product CSV theo PRODUCT_CREATE (SystemAdmin/admin); Plot CSV theo FARM_MANAGE (Farmer/OrgAdmin) ownorg. Không nhận organization_id/id từ CSV.
- Plot import tạo cặp Farm/Plot mới cùngID không đụng IDs cả2bảng. Nếu mirror cũ thiếu/mâu thuẫn thì báo lỗi, không tự chữa.
- GET /catalogs/template/{product|plot}: mẫu CSV có đánh dấu QA.

## Migration QA
Chạy module script từ thư mục backend hoặc đặt PYTHONPATH=backend:
```powershell
python -m scripts.migrate_phase_c_qa --db ../.sprint123-trial/qa_sprint3_c.db --apply
```
CLI chỉ nhận file qa_*.db có sẵn trong .sprint123-trial; hàm migration từ chối backend/ttcs.db và demo_sprint123_north.db/hardlink. Không startup auto-migration. Thêm locations, batches.location_id nullableFK/index, không backfill. Cột batch lưu bằng SQL helper thay đổi có kiểm tra schema; tránh ORM SELECT/INSERT yêu cầu cột mới trên DB cũ.

Snapshot/backups, full tests và browser evidence nằm trong báo cáo C ngoài repository. Chưa migration chính thức. Dataset QA là dữ liệu thử, không sao chép ngược vào DB chính thức.

## Nghiệm thu
Full pytest và lint theo CI phải PASS trên bản cuối; tests mới cover allocation mass/hash/rollback, consume zero/race, store permissions, CSV/mirror, summary3queries, handover clearing, masking và merge vị trí.
S-29 audit.where trực tiếp trong AuditLog vẫn cần đánh giá khi làm S-31; vị trí đã lưu trong hash event nhưng không có cột riêng AuditLog. Không tự tuyên bố Sprint3 hoàn tất.
