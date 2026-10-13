/* Recall 3B.2B: render only the server's authorized projection. */
"use strict";
(() => {
  let generation = 0, detailVersion = 0, activeRecall = null;
  let busyCreate = false, busyAck = false;
  const identity = () => session ? `${API_BASE_URL}:${session.username}:${session.role}:${session.organization_id}` : "";
  const canOpen = () => !!session && ["inspector", "org_admin"].includes(session.role);
  const canSelect = b => session?.role === "inspector" || (session?.role === "org_admin" && session.organization_id != null && b.current_org_id === session.organization_id);
  const e = escapeHtml;
  const rootLabel = r => r.affected_batches.find(b => b.batch_id === r.root_batch_id)?.code || `#${r.root_batch_id}`;
  const progress = r => `<span class="recall-progress"><progress max="${Math.max(1, r.progress.required)}" value="${r.progress.acknowledged}"></progress>${r.progress.acknowledged}/${r.progress.required}</span>`;
  const anomaly = r => !r.anomaly ? "—" : r.anomaly.code === "NEW_DESCENDANTS_AFTER_COMPLETION" ? "Hậu duệ mới sau COMPLETED; tiếp tục phong tỏa" : "Đồ thị thay đổi sau ACK; tiếp tục phong tỏa";
  const storageKey = () => `agritrace.recall.commands:${identity()}`;
  // Store payload + key before dispatch. Retain successful keys too: a repeated
  // identical intent can never be silently assigned a new key after a timeout.
  function intent(path, body) {
    const signature = JSON.stringify([path, body]);
    const records = JSON.parse(sessionStorage.getItem(storageKey()) || "{}");
    if (!records[signature]) {
      records[signature] = { key: crypto.randomUUID(), path, body, pending: true };
      sessionStorage.setItem(storageKey(), JSON.stringify(records));
    }
    return records[signature];
  }
  function remember(record, pending) {
    const records = JSON.parse(sessionStorage.getItem(storageKey()) || "{}");
    records[JSON.stringify([record.path, record.body])] = { ...record, pending };
    sessionStorage.setItem(storageKey(), JSON.stringify(records));
  }
  function pending(path) {
    return Object.values(JSON.parse(sessionStorage.getItem(storageKey()) || "{}")).find(r => r.path === path && r.pending);
  }
  function createLocked(locked) {
    $("recall-root").readOnly = locked;
    $("recall-reason").readOnly = locked;
  }
  function reset() {
    generation++; detailVersion++; activeRecall = null;
    for (const id of ["modal-recall-create", "modal-recall-detail"]) $(id).hidden = true;
    for (const id of ["recall-list", "recall-alerts", "recall-detail-body"]) $(id).replaceChildren();
    $("recall-create-form").reset(); $("recall-ack-form").reset();
    $("recall-status").textContent = "";
    $("recall-ack-form").hidden = true;
    busyCreate = busyAck = false;
  }
  function applySession() {
    $("recall-open").hidden = !canOpen();
    if (!session) reset();
  }
  async function load() {
    if (!session) return;
    const version = ++generation, owner = identity();
    $("recall-status").textContent = "Đang tải Recall…";
    // Clear old sensitive rows before every new read, including permission failures.
    $("recall-list").replaceChildren(); $("recall-alerts").replaceChildren();
    try {
      const [rows, alerts] = await Promise.all([apiRequest("/recalls"), apiRequest("/recalls/my-alerts")]);
      if (version !== generation || owner !== identity()) return;
      $("recall-list").innerHTML = rows.map(r => `<tr><td>${e(r.recall_code)}</td><td>${e(rootLabel(r))}</td><td>${e(r.reason)}</td><td>${e(r.status)}${r.quarantined ? " · Phong tỏa" : ""}</td><td>${e(formatDateTime(r.created_at))}</td><td>${progress(r)}</td><td>${e(anomaly(r))}</td><td><button class="btn btn--light" data-recall-id="${r.id}">Chi tiết</button></td></tr>`).join("");
      $("recall-alerts").innerHTML = alerts.map(r => `<p class="recall-warning">${e(r.recall_code)} · ${e(r.status)} · ${r.quarantined ? "Tiếp tục phong tỏa" : ""}<br>Lô trong phạm vi: ${e(r.affected_batches.map(b => `${b.code}${b.status === "CONSUMED" ? " (CONSUMED — đã tiêu thụ)" : ""}`).join(", "))}${r.anomaly ? `<br>${e(anomaly(r))}` : ""}</p>`).join("");
      $("recall-status").textContent = rows.length ? `${rows.length} lệnh trong phạm vi được cấp quyền.` : "Chưa có lệnh Recall trong phạm vi của bạn.";
    } catch (error) {
      if (version !== generation || owner !== identity()) return;
      $("recall-status").textContent = error.message;
      toast(error.message, "error");
    }
  }
  function renderDetail(r) {
    activeRecall = r;
    $("recall-detail-title").textContent = `Chi tiết ${r.recall_code}`;
    const levels = [...new Set(r.affected_batches.map(b => b.level))].sort((a,b) => a-b);
    $("recall-detail-body").innerHTML = `<p><strong>Lô gốc:</strong> ${e(rootLabel(r))} · ${e(r.status)} · ${e(formatDateTime(r.created_at))}</p><p>${e(r.reason)}</p><p class="recall-warning">${r.quarantined ? "Các lô vẫn bị phong tỏa, kể cả khi COMPLETED." : ""} ${r.anomaly ? e(anomaly(r)) : ""}</p>${progress(r)}<p>Đang hiển thị ${r.visible_batch_count} lô${r.total_affected_batch_count == null ? " theo phạm vi tổ chức" : ` / ${r.total_affected_batch_count} lô ảnh hưởng`}. Tổng khối lượng dưới đây chỉ thuộc các lô đang hiển thị.</p>
      ${Object.entries(r.metrics_by_unit).map(([unit,m]) => `<p><strong>${e(unit)}:</strong> Tồn có thể thu hồi ${e(m.reclaimable_quantity)}; đã tiêu thụ có chứng cứ ${e(m.known_consumed_quantity)}; tổng đã tiêu thụ ${m.consumed_quantity == null ? "chưa xác định" : e(m.consumed_quantity)}.${m.unknown_consumed_batch_ids.length ? ` Chưa xác định: ${e(m.unknown_consumed_batch_ids.map(id => `#${id}`).join(", "))}.` : ""}</p>`).join("")}
      ${levels.map(level => `<h4>Tầng ${level}${level === 0 ? " · Lô gốc" : " · Hậu duệ"}</h4><div class="table-wrap"><table class="table"><thead><tr><th>Lô</th><th>Tổ chức</th><th>Trạng thái</th><th>Tồn</th><th>Tiêu thụ có chứng cứ</th><th>Gộp khác nguồn</th></tr></thead><tbody>${r.affected_batches.filter(b => b.level === level).map(b => `<tr><td>${e(b.code)}</td><td>${e(b.organization_name || "Chưa xác định")}</td><td>${e(b.status)}</td><td>${e(b.remaining_quantity)} ${e(b.unit)}</td><td>${b.consumed_quantity == null ? "Chưa xác định" : `${e(b.consumed_quantity)} ${e(b.unit)}`}</td><td>${b.is_merged_cross_origin ? "Có" : "—"}</td></tr>`).join("")}</tbody></table></div>`).join("")}
      <h4>Xác nhận của tổ chức trong phạm vi</h4><ul>${r.acknowledgments.map(a => `<li>${e(a.organization_name || `#${a.organization_id}`)}: ${e(a.status)} · ${e(formatDateTime(a.acknowledged_at))}${a.notes ? ` · ${e(a.notes)}` : ""}</li>`).join("")}</ul>`;
    const own = r.acknowledgments.find(a => a.organization_id === session?.organization_id);
    $("recall-ack-form").hidden = !(session?.role === "org_admin" && r.status === "OPEN" && own?.status === "PENDING");
    const saved = pending(`/recalls/${r.id}/acknowledge`);
    $("recall-ack-notes").value = saved?.body.notes || "";
    $("recall-ack-notes").readOnly = !!saved;
    $("recall-ack-confirm").checked = false;
    $("recall-ack-error").textContent = saved ? "Thao tác đang chờ: gửi lại với cùng khóa và ghi chú." : "";
  }
  async function openDetail(id) {
    const version = ++detailVersion, owner = identity();
    activeRecall = null; $("recall-ack-form").hidden = true;
    $("recall-detail-body").textContent = "Đang tải…";
    $("modal-recall-detail").hidden = false;
    try {
      const r = await apiRequest(`/recalls/${id}`);
      if (owner === identity() && version === detailVersion) renderDetail(r);
    } catch (error) {
      if (owner === identity() && version === detailVersion) $("recall-detail-body").textContent = error.message;
    }
  }
  function openCreate() {
    if (!canOpen()) return;
    const candidates = batches.filter(canSelect);
    $("recall-root-options").innerHTML = candidates.map(b => `<option value="${e(b.code)}">#${b.id}</option>`).join("");
    const saved = pending("/recalls");
    $("recall-create-form").reset();
    $("recall-root").value = saved ? String(saved.body.root_batch_id) : "";
    $("recall-reason").value = saved?.body.reason || "";
    createLocked(!!saved);
    $("recall-create-error").textContent = saved ? "Thao tác đang chờ: gửi lại với cùng khóa và nội dung." : "";
    $("modal-recall-create").hidden = false;
    $("recall-root").focus();
  }
  async function submit(event, ack) {
    event.preventDefault();
    if (!session || (ack ? busyAck : busyCreate)) return;
    const owner = identity();
    const prefix = ack ? "recall-ack" : "recall-create";
    const button = $(`${prefix}-submit`), errorBox = $(`${prefix}-error`);
    let record;
    try {
      if (ack && (!activeRecall || session.role !== "org_admin" || activeRecall.status !== "OPEN")) throw new Error("Không có quyền xác nhận.");
      if (!ack && !canOpen()) throw new Error("Không có quyền mở Recall.");
      if (!$(`${prefix}-confirm`).checked) throw new Error("Cần xác nhận thao tác trước khi gửi.");
      const path = ack ? `/recalls/${activeRecall.id}/acknowledge` : "/recalls";
      const saved = pending(path);
      let body;
      if (saved) body = saved.body;
      else if (ack) body = { notes: $("recall-ack-notes").value.trim() };
      else {
        const value = $("recall-root").value.trim();
        const candidate = batches.find(b => b.code === value);
        const root = candidate?.id || (/^[1-9]\d*$/.test(value) ? Number(value) : NaN);
        const reason = $("recall-reason").value.trim();
        if (!Number.isSafeInteger(root) || reason.length < 20 || reason.length > 5000) throw new Error("Chọn mã lô hợp lệ hoặc ID nguyên dương và lý do ít nhất 20 ký tự.");
        if (candidate && !canSelect(candidate)) throw new Error("Tổ chức bạn không đang nắm giữ lô này.");
        body = { root_batch_id: root, reason };
      }
      record = saved || intent(path, body);
      if (ack) { busyAck = true; $("recall-ack-notes").readOnly = true; } else { busyCreate = true; createLocked(true); }
      setButtonLoading(button, true, "Đang gửi…", "Gửi"); errorBox.textContent = "";
      const result = await apiRequest(path, { method: "POST", body: record.body, headers: { "Idempotency-Key": record.key } });
      if (owner !== identity()) return;
      remember(record, false);
      if (!ack) $("modal-recall-create").hidden = true;
      toast(ack ? "Đã xác nhận xử lý của tổ chức." : "Đã mở lệnh thu hồi.", "success");
      await load(); await openDetail(result.id); // GET fresh state after an idempotent replay.
    } catch (error) {
      if (owner !== identity()) return;
      const ambiguous = !error.status || error.status >= 500;
      if (record && !ambiguous) remember(record, false);
      if (!ack) createLocked(!!record && ambiguous);
      else $("recall-ack-notes").readOnly = !!record && ambiguous;
      errorBox.textContent = `${error.message}${record && ambiguous ? " Gửi lại sẽ dùng cùng khóa; nội dung được giữ nguyên." : ""}`;
      toast(error.message, "error");
    } finally {
      if (owner === identity()) {
        if (ack) busyAck = false; else busyCreate = false;
        setButtonLoading(button, false, "Đang gửi…", ack ? "Xác nhận xử lý" : "Xác nhận mở Recall");
      }
    }
  }
  window.recallUi = { applySession, reset, load };
  document.addEventListener("DOMContentLoaded", () => {
    $("recall-refresh").addEventListener("click", load);
    $("recall-open").addEventListener("click", openCreate);
    $("recall-list").addEventListener("click", event => { const b = event.target.closest("[data-recall-id]"); if (b) openDetail(Number(b.dataset.recallId)); });
    $("recall-create-form").addEventListener("submit", event => submit(event, false));
    $("recall-ack-form").addEventListener("submit", event => submit(event, true));
    document.querySelectorAll("[data-recall-close]").forEach(b => b.addEventListener("click", () => { if (busyCreate || busyAck) return; $(b.dataset.recallClose).hidden = true; detailVersion++; }));
    document.addEventListener("keydown", event => { if (event.key === "Escape" && !busyCreate && !busyAck) { $("modal-recall-create").hidden = true; $("modal-recall-detail").hidden = true; detailVersion++; } });
  });
})();
