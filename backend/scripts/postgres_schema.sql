-- ==============================================================================
-- AGRITRACE: POSTGRESQL SCHEMA SPECIFICATION (PHASE 1B MIGRATION BLUEPRINT)
-- Chuẩn hóa 7 vai trò, Khóa ngoại, Bất biến S-11 và Bảo toàn Hash-chain
-- ==============================================================================

-- 1. ENUM VAI TRÒ HỆ THỐNG (7 VAI TRÒ CHÍNH THỨC + 1 LEGACY ALIAS)
CREATE TYPE user_role_enum AS ENUM (
    'system_admin',
    'org_admin',
    'farmer',
    'processor',
    'transporter',
    'distributor',
    'inspector',
    'admin'
);

-- 2. BẢNG TỔ CHỨC (ORGANIZATIONS)
CREATE TABLE organizations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    code VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 3. BẢNG NGƯỜI DÙNG (USERS)
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(255) UNIQUE,
    password VARCHAR(255) NOT NULL,
    role user_role_enum NOT NULL DEFAULT 'farmer',
    organization_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_locked BOOLEAN NOT NULL DEFAULT FALSE,
    failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 4. BẢNG SẢN PHẨM (PRODUCTS)
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    unit VARCHAR(50) NOT NULL DEFAULT 'kg',
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 5. BẢNG VÙNG TRỒNG (FARMS)
CREATE TABLE farms (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    location VARCHAR(255) NOT NULL,
    area NUMERIC(10, 2) NOT NULL CHECK (area > 0),
    owner VARCHAR(255) NOT NULL,
    coordinates VARCHAR(100),
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 6. BẢNG THỬA ĐẤT (PLOTS)
CREATE TABLE plots (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    name VARCHAR(255) NOT NULL,
    location VARCHAR(255) NOT NULL,
    area NUMERIC(10, 2) NOT NULL CHECK (area > 0),
    coordinates VARCHAR(255),
    owner VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 7. BẢNG LÔ NÔNG SẢN (BATCHES)
CREATE TABLE batches (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    plot_id INTEGER REFERENCES plots(id) ON DELETE SET NULL,
    farm_id INTEGER REFERENCES farms(id) ON DELETE SET NULL,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    product_name VARCHAR(255),
    harvest_date DATE NOT NULL,
    initial_quantity NUMERIC(14, 2) NOT NULL CHECK (initial_quantity > 0),
    remaining_quantity NUMERIC(14, 2) NOT NULL CHECK (remaining_quantity >= 0),
    quantity DOUBLE PRECISION,
    current_org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    status VARCHAR(50) NOT NULL DEFAULT 'ACTIVE',
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    is_reconstructed BOOLEAN NOT NULL DEFAULT FALSE,
    reconstruction_notes TEXT,
    unverified_fields JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 8. BẢNG SỰ KIỆN LÔ BẤT BIẾN (BATCH_EVENTS - APPEND ONLY)
CREATE TABLE batch_events (
    id SERIAL PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE RESTRICT,
    event_type VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    event_data TEXT,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    user_id INTEGER,
    prev_hash VARCHAR(64) NOT NULL,
    current_hash VARCHAR(64) NOT NULL,
    record_hash VARCHAR(64),
    from_org_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    to_org_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    notes TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- TRIGGER S-11 POSTGRESQL: BẢO VỆ TÍNH BẤT BIẾN CỦA BATCH_EVENTS (CẤM UPDATE / DELETE)
CREATE OR REPLACE FUNCTION prevent_batch_event_tampering()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'S-11: Deletions from batch_events table are strictly prohibited (append-only log).';
    ELSIF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'S-11: Updates to batch_events table are strictly prohibited (append-only log).';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_batch_events_immutable
BEFORE UPDATE OR DELETE ON batch_events
FOR EACH ROW EXECUTE FUNCTION prevent_batch_event_tampering();

-- 9. BẢNG BÀN GIAO (HANDOVERS)
CREATE TABLE handovers (
    id SERIAL PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE RESTRICT,
    from_org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    to_org_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE RESTRICT,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    reject_reason TEXT,
    is_overdue BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 10. BẢNG QUAN HỆ PHẢ HỆ TÁCH/GỘP (BATCH_RELATIONS)
CREATE TABLE batch_relations (
    id SERIAL PRIMARY KEY,
    parent_batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE RESTRICT,
    child_batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE RESTRICT,
    relation_type VARCHAR(50) NOT NULL,
    transferred_quantity NUMERIC(14, 2) NOT NULL CHECK (transferred_quantity > 0),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 11. BẢNG NHẬT KÝ KIỂM TOÁN (AUDIT_LOGS)
CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(50) NOT NULL,
    entity VARCHAR(50) NOT NULL,
    entity_id INTEGER,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 12. CHỈ MỤC TỐI ƯU TRUY VẤN
CREATE INDEX idx_batches_current_org ON batches(current_org_id);
CREATE INDEX idx_batches_code ON batches(code);
CREATE INDEX idx_batch_events_batch_id ON batch_events(batch_id);
CREATE INDEX idx_batch_events_timestamp ON batch_events(timestamp);
CREATE INDEX idx_handovers_batch_id ON handovers(batch_id);
CREATE INDEX idx_handovers_status_to_org ON handovers(status, to_org_id);
CREATE INDEX idx_batch_relations_parent ON batch_relations(parent_batch_id);
CREATE INDEX idx_batch_relations_child ON batch_relations(child_batch_id);
