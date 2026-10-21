"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

// Giả lập môi trường trình duyệt tối thiểu cho app.js
global.document = {
  readyState: "loading",
  addEventListener() {},
  getElementById() {
    return {
      hidden: false,
      className: "",
      textContent: "",
      addEventListener() {},
      replaceChildren() {},
      appendChild() {},
      querySelector() { return null; },
      querySelectorAll() { return []; },
    };
  },
  activeElement: null,
};
global.window = {
  location: { href: "http://127.0.0.1:8765/", origin: "http://127.0.0.1:8765" },
  AGRITRACE_CONFIG: { apiBase: "http://127.0.0.1:8765" },
  setTimeout,
  clearTimeout,
};

const {
  renderTimelineBody,
  renderTimelineItemHtml,
  formatEventType,
  formatViolationType,
  TIMELINE_PAYLOAD_LABELS,
  TL_PAYLOAD_LABELS,
} = require("../js/app.js");

test("TL_PAYLOAD_LABELS is defined and aliases TIMELINE_PAYLOAD_LABELS", () => {
  assert.ok(TL_PAYLOAD_LABELS, "TL_PAYLOAD_LABELS must be defined");
  assert.equal(TL_PAYLOAD_LABELS, TIMELINE_PAYLOAD_LABELS);
  assert.equal(typeof TL_PAYLOAD_LABELS.violation_type, "string");
  assert.equal(typeof TL_PAYLOAD_LABELS.peak_temperature, "string");
  assert.equal(typeof TL_PAYLOAD_LABELS.threshold_temperature, "string");
  assert.equal(typeof TL_PAYLOAD_LABELS.duration_minutes, "string");
  assert.equal(typeof TL_PAYLOAD_LABELS.trip_code, "string");
  assert.equal(typeof TL_PAYLOAD_LABELS.container_code, "string");
});

test("formatViolationType translates standard cold chain codes", () => {
  assert.equal(formatViolationType("PROLONGED_HEAT"), "Nhiệt độ vượt ngưỡng kéo dài");
  assert.equal(formatViolationType("FREEZING_RISK"), "Nguy cơ đông lạnh");
  assert.equal(formatViolationType("TEMPERATURE_EXCEEDED"), "Vượt ngưỡng nhiệt độ");
  assert.equal(formatViolationType("UNKNOWN_TYPE"), "UNKNOWN_TYPE");
  assert.equal(formatViolationType(null), "Vi phạm nhiệt độ");
});

test("formatEventType recognizes TEMPERATURE_VIOLATION and cold chain events", () => {
  assert.equal(formatEventType("TEMPERATURE_VIOLATION"), "Cảnh báo vi phạm nhiệt độ");
  assert.equal(formatEventType("TRIP_DISPATCH"), "Khởi hành chuyến lạnh (lên xe)");
  assert.equal(formatEventType("TRIP_DELIVER"), "Hoàn thành chuyến lạnh (xuống xe)");
  assert.equal(formatEventType("HARVEST"), "Thu hoạch ban đầu");
  assert.equal(formatEventType("SPLIT"), "Tách lô");
  assert.equal(formatEventType("MERGE"), "Gộp lô");
});

test("renderTimelineItemHtml renders TEMPERATURE_VIOLATION with full payload (S4-DEMO-LOT-HEAT-VEG)", () => {
  const evt = {
    event_type: "TEMPERATURE_VIOLATION",
    timestamp: "2026-10-20T14:59:07.755010",
    current_hash: "a".repeat(64),
    actor: "Nguyễn Văn Tài (Đội xe 01)",
    organization_name: "Đội xe 01",
    payload: {
      violation_id: 1,
      trip_id: 2,
      trip_code: "S4-DEMO-TRIP-HEAT-01",
      container_code: "S4-DEMO-CONT-HEAT-01",
      start_time: "2026-10-20T14:59:07.755010",
      end_time: null,
      duration_minutes: 35.0,
      peak_temperature: 18.2,
      threshold_temperature: 8.0,
      min_threshold: 2.0,
      max_threshold: 8.0,
      violation_type: "PROLONGED_HEAT",
      severity: "CRITICAL",
      status: "ACTIVE",
      description: "Cảnh báo vi phạm nhiệt độ: Đỉnh 18.2°C (ngưỡng 8.0°C), kéo dài 35.0 phút trên chuyến S4-DEMO-TRIP-HEAT-01",
    },
  };

  // S-45 Regression: Không được ném lỗi ReferenceError "TL_PAYLOAD_LABELS is not defined"
  assert.doesNotThrow(() => {
    const html = renderTimelineItemHtml(evt);
    assert.ok(html.includes("timeline-item--temperature-violation"), "Must include temperature-violation class");
    assert.ok(html.includes("timeline-item__dot--temperature-violation"), "Must include dot class");
    assert.ok(html.includes("Cảnh báo vi phạm nhiệt độ"), "Must show event type header");
    assert.ok(html.includes("Nhiệt độ vượt ngưỡng kéo dài"), "Must display violation type");
    assert.ok(html.includes("18,2°C") || html.includes("18.2°C"), "Must display peak temperature");
    assert.ok(html.includes("2°C – 8°C"), "Must display threshold range");
    assert.ok(html.includes("35 phút"), "Must display duration");
    assert.ok(html.includes("S4-DEMO-TRIP-HEAT-01"), "Must display trip code");
    assert.ok(html.includes("S4-DEMO-CONT-HEAT-01"), "Must display container code");
    assert.ok(html.includes("Cảnh báo vi phạm nhiệt độ: Đỉnh 18.2°C"), "Must display description note");
  });
});

test("renderTimelineItemHtml handles TEMPERATURE_VIOLATION when trip details are not provided", () => {
  const evt = {
    event_type: "TEMPERATURE_VIOLATION",
    timestamp: "2026-10-20T14:59:07.755010",
    current_hash: "b".repeat(64),
    payload: {
      violation_type: "FREEZING_RISK",
      peak_temperature: -2.5,
      threshold_temperature: 0.0,
      duration_minutes: 40,
    },
  };

  assert.doesNotThrow(() => {
    const html = renderTimelineItemHtml(evt);
    assert.ok(html.includes("Nguy cơ đông lạnh"));
    assert.ok(html.includes("-2,5°C") || html.includes("-2.5°C"));
    assert.ok(html.includes("0°C"));
    assert.ok(html.includes("40 phút"));
    // Không hiển thị rỗng cho chuyến xe nếu không có dữ liệu
    assert.ok(!html.includes("Mã chuyến xe"));
  });
});

test("renderTimelineItemHtml renders fallback events with payload labels without crashing", () => {
  const genericEvt = {
    event_type: "CUSTOM_INSPECTION",
    timestamp: "2026-10-20T10:00:00",
    current_hash: "c".repeat(64),
    payload: {
      temperature: 4.5,
      note: "Kiểm tra định kỳ bình thường",
      batch_code: "DEMO-BATCH-01",
    },
  };

  assert.doesNotThrow(() => {
    const html = renderTimelineItemHtml(genericEvt);
    assert.ok(html.includes("Nhiệt độ (°C)"));
    assert.ok(html.includes("4,5") || html.includes("4.5"));
    assert.ok(html.includes("Ghi chú"));
    assert.ok(html.includes("Kiểm tra định kỳ bình thường"));
  });
});

test("Sprint 1–3 events render without regression", () => {
  // Harvest (Sprint 1)
  const harvestHtml = renderTimelineItemHtml({
    event_type: "HARVEST",
    timestamp: "2026-10-19T08:00:00",
    current_hash: "d".repeat(64),
    payload: { product_name: "Chè Búp Tươi", initial_quantity: 500, unit: "kg", batch_code: "LOT-01" },
  });
  assert.ok(harvestHtml.includes("Chè Búp Tươi"));
  assert.ok(harvestHtml.includes("Khối lượng thu hoạch"));

  // Handover (Sprint 2)
  const handoverHtml = renderTimelineItemHtml({
    event_type: "HANDOVER_ACCEPT",
    timestamp: "2026-10-19T10:00:00",
    current_hash: "e".repeat(64),
    payload: { from_org: "HTX A", to_org: "Công ty B", note: "Tiếp nhận đủ số lượng" },
  });
  assert.ok(handoverHtml.includes("HTX A"));
  assert.ok(handoverHtml.includes("Công ty B"));

  // Split / Merge (Sprint 3)
  const splitHtml = renderTimelineItemHtml({
    event_type: "SPLIT",
    timestamp: "2026-10-19T11:00:00",
    current_hash: "f".repeat(64),
    payload: { total_split_quantity: 200, unit: "kg", child_batch_codes: ["CHILD-1", "CHILD-2"], child_quantities: [100, 100] },
  });
  assert.ok(splitHtml.includes("Khối lượng tách"));
  assert.ok(splitHtml.includes("CHILD-1"));

  // Trip Dispatch (Sprint 4)
  const dispatchHtml = renderTimelineItemHtml({
    event_type: "TRIP_DISPATCH",
    timestamp: "2026-10-20T08:00:00",
    current_hash: "1".repeat(64),
    payload: { trip_code: "TRIP-01", container_code: "CONT-01" },
  });
  assert.ok(dispatchHtml.includes("TRIP-01"));
  assert.ok(dispatchHtml.includes("CONT-01"));
});
