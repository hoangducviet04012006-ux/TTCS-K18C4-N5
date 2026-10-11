"""Recall APIs on a separately migrated SQLite test database."""
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import get_current_user
from app.services import recall
from app.services.recall_database import begin_read_snapshot, require_recall_database


def trial_database(db: Session = Depends(get_db)):
    # Must run before authentication, whose legacy password upgrade may commit.
    require_recall_database(db)


router = APIRouter(prefix="/recalls", tags=["Recalls"], dependencies=[Depends(trial_database)])


class RecallCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root_batch_id: int = Field(ge=1)
    reason: str = Field(min_length=20, max_length=5000)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class RecallAck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notes: str = Field(default="", max_length=5000)

    @field_validator("notes", mode="before")
    @classmethod
    def trim_notes(cls, value):
        return value.strip() if isinstance(value, str) else value


def idempotency_key(key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128)):
    from fastapi import HTTPException
    if not key.strip() or key != key.strip():
        raise HTTPException(422, "Idempotency-Key must be nonempty without surrounding whitespace")
    return key


@router.post("", status_code=201)
def create(payload: RecallCreate, key: str = Depends(idempotency_key),
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return recall.create_recall(db, user, payload.root_batch_id, payload.reason, key)


@router.get("")
def listing(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return recall.list_recalls(db, user)


# Static route precedes /{recall_id}.
@router.get("/my-alerts")
def alerts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return recall.list_recalls(db, user, alerts=True)


@router.get("/{recall_id}")
def retrieve(recall_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_recall_database(db)
    begin_read_snapshot(db)
    return recall.detail(db, recall.get_recall(db, recall_id), user)


@router.post("/{recall_id}/acknowledge")
def acknowledge(recall_id: int, payload: RecallAck, key: str = Depends(idempotency_key),
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return recall.acknowledge(db, user, recall_id, payload.notes, key)
