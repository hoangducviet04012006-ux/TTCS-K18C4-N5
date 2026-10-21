/* Sprint 4 uses the existing authenticated API/session and UI helpers. */
"use strict";

async function loadTripTelemetry(tripId) {
  const panel = document.getElementById("trip-telemetry");
  if (!panel) return;
  const actor = session;
  panel.dataset.tripId = String(tripId);
  panel.textContent = "Đang tải số đo và đánh giá nhiệt độ…";
  try {
    const [readings, violations, evaluations] = await Promise.all([
      apiRequest(`/trips/${tripId}/readings?limit=1000`),
      apiRequest(`/trips/${tripId}/violations`),
      apiRequest(`/trips/${tripId}/evaluation`)
    ]);
    if (session !== actor || panel.dataset.tripId !== String(tripId)) return;
    panel.innerHTML = `<h4>Nhiệt độ chuyến #${Number(tripId)}</h4>
      <button type="button" class="btn btn--light" id="refresh-trip-telemetry">Làm mới nhiệt độ</button>
      <ul>${evaluations.map(e => `<li>${escapeHtml(e.batch_code)}: ${escapeHtml(e.message)}</li>`).join("")}</ul>
      <p class="${violations.length ? "error" : "muted"}">${violations.length ?
        `CẢNH BÁO: ${violations.length} vi phạm nhiệt độ` : "Chưa ghi nhận vi phạm; không đồng nghĩa sản phẩm an toàn"}</p>
      <ul>${violations.map(v => `<li>${escapeHtml(typeof formatViolationType === "function" ? formatViolationType(v.violation_type) : v.violation_type)} · Lô ${escapeHtml((v.affected_batch_ids || []).join(", "))} ·
        ${escapeHtml(formatDateTime(v.start_time))} · ${escapeHtml(v.duration_minutes)} phút ·
        ${escapeHtml(v.peak_temperature)} °C (ngưỡng ${escapeHtml(v.threshold_temperature)} °C)</li>`).join("")}</ul>
      <div style="max-height:250px;overflow:auto"><table><thead><tr><th>Thời điểm</th><th>Thùng lạnh</th><th>Nhiệt độ °C</th></tr></thead>
      <tbody>${readings.map(r => `<tr><td>${escapeHtml(formatDateTime(/[Zz]|[+-]\d\d:\d\d$/.test(r.recorded_at) ? r.recorded_at : r.recorded_at + "Z"))}</td>
        <td>${escapeHtml(r.container_code)}</td><td>${escapeHtml(r.temperature)}</td></tr>`).join("")}</tbody></table></div>
      ${readings.length ? "" : "Chưa có số đo"}`;
    document.getElementById("refresh-trip-telemetry").onclick = () => loadTripTelemetry(tripId);
  } catch (error) {
    if (session === actor && panel.dataset.tripId === String(tripId)) {
      panel.textContent = "Không thể đánh giá nhiệt độ: " + error.message;
    }
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const dialog = document.createElement("dialog");
  dialog.id = "temperature-policy-dialog";
  dialog.setAttribute("aria-labelledby", "temperature-policy-title");
  dialog.innerHTML = `<form id="temperature-policy-form"><h3 id="temperature-policy-title">Ngưỡng nhiệt độ theo sản phẩm</h3>
    <p id="temperature-policy-status" role="status"></p>
    <label>Ngưỡng min (°C)<input id="temperature-policy-min" type="number" step="any" min="-100" max="100" required></label>
    <label>Ngưỡng max (°C)<input id="temperature-policy-max" type="number" step="any" min="-100" max="100" required></label>
    <label>Độ trễ (phút, ít nhất 30)<input id="temperature-policy-delay" type="number" step="any" min="30" max="1440" required></label>
    <p>Vi phạm chỉ ghi nhận khi vượt ngưỡng liên tục lâu hơn độ trễ; từng lô được đánh giá độc lập.</p>
    <button id="temperature-policy-save" class="btn btn--primary" type="submit">Lưu cấu hình</button>
    <button id="temperature-policy-close" class="btn btn--ghost" type="button">Đóng</button></form>`;
  document.body.append(dialog);
  document.getElementById("temperature-policy-close").onclick = () => dialog.close();
  let productId = null;
  let policyActor = null;
  document.addEventListener("click", async event => {
    const cancel = event.target.closest("[data-cancel-trip]");
    if (cancel) {
      const id = Number(cancel.dataset.cancelTrip);
      if (!await confirmAction("Hủy chuyến xe và giải phóng các lô?")) return;
      try {
        await apiRequest(`/trips/${id}/cancel`, {method: "POST", body: {notes: "Hủy qua giao diện"}});
        toast("Đã hủy chuyến xe", "success");
        await loadColdTrips();
        await loadBatches();
      } catch (error) { toast(error.message, "error"); }
    }
    const button = event.target.closest("[data-temperature-product]");
    if (!button) return;
    productId = Number(button.dataset.temperatureProduct);
    document.getElementById("temperature-policy-title").textContent = "Ngưỡng nhiệt độ — " +
      (products.find(p => p.id === productId)?.name || `Sản phẩm #${productId}`);
    policyActor = session;
    document.getElementById("temperature-policy-form").reset();
    const editable = isSystemAdmin();
    for (const name of ["min", "max", "delay"]) document.getElementById("temperature-policy-" + name).disabled = !editable;
    document.getElementById("temperature-policy-save").hidden = !editable;
    document.getElementById("temperature-policy-status").textContent = "Đang tải…";
    dialog.showModal();
    try {
      const data = await apiRequest(`/products/${productId}/temperature-policy`);
      if (session !== policyActor || data.product_id !== productId) return;
      document.getElementById("temperature-policy-status").textContent = data.message;
      if (data.policy) {
        document.getElementById("temperature-policy-min").value = data.policy.min_temperature;
        document.getElementById("temperature-policy-max").value = data.policy.max_temperature;
        document.getElementById("temperature-policy-delay").value = data.policy.delay_minutes;
      }
    } catch (error) { document.getElementById("temperature-policy-status").textContent = error.message; }
  });
  document.getElementById("temperature-policy-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (!isSystemAdmin() || session !== policyActor) return;
    const payload = {min_temperature: Number(document.getElementById("temperature-policy-min").value),
      max_temperature: Number(document.getElementById("temperature-policy-max").value),
      delay_minutes: Number(document.getElementById("temperature-policy-delay").value)};
    try {
      await apiRequest(`/products/${productId}/temperature-policy`, {method: "PUT", body: payload});
      document.getElementById("temperature-policy-status").textContent = "Đã lưu cấu hình";
    } catch (error) { document.getElementById("temperature-policy-status").textContent = error.message; }
  });
});
