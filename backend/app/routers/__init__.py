"""Nhóm các router (endpoint) của API theo từng nghiệp vụ.

Quy ước: mỗi file trong package này là một `APIRouter` cho một nhóm chức năng
(`health.py`, `farms.py`, `batches.py`, `auth.py`, `users.py`, `audit.py`,
sau này là `cold_chain.py`...). Tất cả router được đăng ký tập trung tại
`app/main.py`.
"""

from app.routers import audit, auth, batches, cold_chain, events, farms, handovers, health, products, users

__all__ = ["audit", "auth", "batches", "cold_chain", "events", "farms", "handovers", "health", "products", "users"]
