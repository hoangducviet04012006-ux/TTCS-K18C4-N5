-- Extracted from the actual migrated synthetic test database.
-- Review only; never execute against backend/ttcs.db.
-- Base tables batches/users/organizations/batch_events must already exist.
CREATE TABLE idempotency_records (
        key VARCHAR(128) NOT NULL CHECK (length(key) BETWEEN 1 AND 128),
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        endpoint VARCHAR(100) NOT NULL,
        request_hash VARCHAR(64) NOT NULL,
        response_code INTEGER NOT NULL,
        response_body TEXT NOT NULL,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, endpoint, key)
    );

CREATE TABLE recall_acknowledgments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recall_id INTEGER NOT NULL,
        organization_id INTEGER NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','ACKNOWLEDGED')),
        acknowledged_by_user_id INTEGER NULL,
        acknowledged_at DATETIME NULL,
        notes TEXT NULL,
        CHECK ((status='PENDING' AND acknowledged_by_user_id IS NULL AND acknowledged_at IS NULL) OR (status='ACKNOWLEDGED' AND acknowledged_by_user_id IS NOT NULL AND acknowledged_at IS NOT NULL)),
        CONSTRAINT fk_ack_recall FOREIGN KEY (recall_id) REFERENCES recalls(id) ON DELETE RESTRICT,
        CONSTRAINT fk_ack_org FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE RESTRICT,
        CONSTRAINT fk_ack_user FOREIGN KEY (acknowledged_by_user_id) REFERENCES users(id) ON DELETE RESTRICT,
        CONSTRAINT uq_recall_org_ack UNIQUE (recall_id, organization_id)
    );

CREATE TABLE recalls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recall_code VARCHAR(50) NOT NULL UNIQUE,
        root_batch_id INTEGER NOT NULL,
        reason TEXT NOT NULL,
        created_by_user_id INTEGER NOT NULL,
        created_by_org_id INTEGER NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','COMPLETED')),
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME NULL,
        CHECK ((status='OPEN' AND completed_at IS NULL) OR (status='COMPLETED' AND completed_at IS NOT NULL)),
        CONSTRAINT fk_recall_root_batch FOREIGN KEY (root_batch_id) REFERENCES batches(id) ON DELETE RESTRICT,
        CONSTRAINT fk_recall_user FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE RESTRICT,
        CONSTRAINT fk_recall_org FOREIGN KEY (created_by_org_id) REFERENCES organizations(id) ON DELETE RESTRICT,
        CONSTRAINT check_recall_reason_len CHECK (LENGTH(TRIM(reason)) >= 20)
    );

CREATE INDEX ix_ack_org_id ON recall_acknowledgments(organization_id);

CREATE INDEX ix_ack_recall_id ON recall_acknowledgments(recall_id);

CREATE INDEX ix_idempotency_created_at ON idempotency_records(created_at);

CREATE INDEX ix_recalls_recall_code ON recalls(recall_code);

CREATE INDEX ix_recalls_root_batch_id ON recalls(root_batch_id);

CREATE INDEX ix_recalls_status ON recalls(status);

CREATE UNIQUE INDEX uq_recall_event_evidence ON batch_events (event_type, batch_id, json_extract(payload, '$.recall_id'), coalesce(json_extract(payload, '$.organization_id'), -1)) WHERE event_type IN ('RECALL_INIT', 'RECALL_AFFECTED', 'RECALL_ACKNOWLEDGED', 'RECALL_COMPLETED');

CREATE UNIQUE INDEX uq_recall_open_per_root_batch 
    ON recalls(root_batch_id) 
    WHERE status = 'OPEN';

CREATE UNIQUE INDEX uq_recall_root_lifetime ON recalls(root_batch_id);
