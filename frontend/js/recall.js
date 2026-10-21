/* Recall 3B.2B & S-33: Đánh dấu lô có sự cố và mở lệnh thu hồi kèm lý do. */
"use strict";
(() => {
  let generation = 0, detailVersion = 0, activeRecall = null;
  let busyCreate = false, busyAck = false;
  let createStep = 0, reviewVersion = 0;
  const recalledBatchesMap = new Map(); // batch_id -> { recall_code, status, reason, is_root }
  const recalledBatchCodes = new Set();

  const identity = () => session ? `${API_BASE_URL}:${session.username}:${session.role}:${session.organization_id}` : "";
  const canOpen = () => !!session && ["inspector", "org_admin"].includes(session.role);
  const canSelect = b => session?.role === "inspector" || (session?.role === "org_admin" && session.organization_id != null && b.current_org_id === session.organization_id);
  const e = escapeHtml;
  const rootLabel = r => r.batch_code || r.affected_batches.find(b => b.batch_id === r.root_batch_id)?.code || `#${r.root_batch_id}`;
  const progress = r => `<span class="recall-progress"><progress max="${Math.max(1, r.progress.required)}" value="${r.progress.acknowledged}"></progress>${r.progress.acknowledged}/${r.progress.required}</span>`;
  const statusLabel = value => ({OPEN:"Đang xử lý",COMPLETED:"Đã đủ xác nhận",ACTIVE:"Đang hoạt động",SPLIT:"Đã tách",MERGED:"Đã gộp",CONSUMED:"Đã tiêu thụ"}[value] || "Chưa xác định");
  const anomaly = r => !r.anomaly ? "—" : r.anomaly.code === "NEW_DESCENDANTS_AFTER_COMPLETION" ? "Có lô con mới sau khi hoàn tất; tiếp tục cách ly" : "Quan hệ lô thay đổi sau xác nhận; tiếp tục cách ly";
  const storageKey = () => `agritrace.recall.commands:${identity()}`;

  function setCreateStep(step) {
    createStep = step;
    document.querySelectorAll('[data-recall-step]').forEach(panel => {
      panel.hidden = Number(panel.dataset.recallStep) !== step;
    });
    document.querySelectorAll('[data-recall-step-label]').forEach(label => {
      if (Number(label.dataset.recallStepLabel) === step) label.setAttribute('aria-current', 'step');
      else label.removeAttribute('aria-current');
    });
    $('recall-step-back').hidden = step === 0 || !!pending('/recalls');
    $('recall-step-next').hidden = step === 3;
    $('recall-create-submit').hidden = step !== 3;
    if (step === 0) $('recall-root').focus();
    if (step === 1) $('recall-reason').focus();
    if (step === 3) $('recall-create-confirm').focus();
  }

  async function nextCreateStep() {
    if (busyCreate || !canOpen()) return;
    const owner = identity(), version = ++reviewVersion;
    const errorBox = $('recall-create-error');
    errorBox.textContent = '';
    if (createStep === 0) {
      if (!$('recall-root').reportValidity()) return;
      setCreateStep(1); return;
    }
    if (createStep === 2) { setCreateStep(3); return; }
    if (createStep !== 1) return;
    const reason = $('recall-reason').value.trim();
    if (reason.length < 20) {
      errorBox.textContent = 'Vui lòng nhập lý do thu hồi từ 20 ký tự.';
      $('recall-reason').focus(); return;
    }
    const value = $('recall-root').value.trim();
    $('recall-step-next').disabled = true;
    try {
      let batch;
      if (/^[1-9]\d*$/.test(value)) batch = await apiRequest('/batches/' + Number(value));
      else {
        const rows = await apiRequest('/batches?search=' + encodeURIComponent(value) + '&limit=100');
        batch = rows.find(b => String(b.code).toUpperCase() === value.toUpperCase());
      }
      if (owner !== identity() || version !== reviewVersion) return;
      if (!batch || !canSelect(batch)) throw Error('Không tìm thấy lô được phép thu hồi. Kiểm tra lại mã lô.');
      if (isBatchRecalled(batch.id)) throw Error('Lô đã có yêu cầu thu hồi. Hãy xem yêu cầu hiện có.');
      $('recall-root').value = batch.code;
      $('recall-review').innerHTML = `<h4>Kiểm tra trước khi xác nhận</h4><dl class="recall-review-fields"><dt>Mã lô</dt><dd>${e(batch.code)}</dd><dt>Sản phẩm</dt><dd>${e(batch.product_name)}</dd><dt>Tổ chức đang giữ</dt><dd>${e(batch.current_org_name || 'Chưa có dữ liệu')}</dd><dt>Lượng còn lại của lô gốc</dt><dd>${e(formatNumber(batch.remaining_quantity))} ${e(batch.unit || 'kg')}</dd><dt>Lý do</dt><dd>${e(reason)}</dd></dl><p class="recall-warning">Lô gốc và các lô phát sinh bị ảnh hưởng sẽ bị cách ly. Các tổ chức liên quan cần xác nhận xử lý.</p>`;
      setCreateStep(2);
    } catch (error) {
      if (owner === identity() && version === reviewVersion) errorBox.textContent = error.message || 'Chưa kiểm tra được lô. Vui lòng thử lại.';
    } finally {
      if (owner === identity()) $('recall-step-next').disabled = false;
    }
  }

  function isBatchRecalled(idOrCode) {
    if (idOrCode == null) return false;
    if (recalledBatchesMap.has(Number(idOrCode))) return true;
    return recalledBatchCodes.has(String(idOrCode).trim());
  }

  function getBatchRecallInfo(idOrCode) {
    if (idOrCode == null) return null;
    const num = Number(idOrCode);
    if (!Number.isNaN(num) && recalledBatchesMap.has(num)) return recalledBatchesMap.get(num);
    const code = String(idOrCode).trim();
    for (const [id, info] of recalledBatchesMap.entries()) {
      const b = (typeof batches !== "undefined" && Array.isArray(batches)) ? batches.find(x => x.id === id) : null;
      if (b && b.code === code) return info;
    }
    return null;
  }

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
    const rootEl = $("recall-root"), reasonEl = $("recall-reason");
    if (rootEl) rootEl.readOnly = locked;
    if (reasonEl) reasonEl.readOnly = locked;
  }

  function updateReasonCounter() {
    const reasonEl = $("recall-reason");
    const countEl = $("recall-reason-count");
    if (!reasonEl || !countEl) return;
    const len = reasonEl.value.trim().length;
    countEl.textContent = `${len} / 20 ký tự tối thiểu`;
    countEl.style.color = len >= 20 ? "#22c55e" : (len > 0 ? "#f59e0b" : "#94a3b8");
  }

  function updateBatchPreview() {
    const previewEl = $("recall-batch-preview");
    const rootEl = $("recall-root");
    if (!previewEl || !rootEl) return;
    const val = rootEl.value.trim();
    if (!val) {
      previewEl.hidden = true;
      previewEl.innerHTML = "";
      return;
    }

    const candidate = (typeof batches !== "undefined" && Array.isArray(batches))
      ? batches.find(b => b.code === val || String(b.id) === val)
      : null;

    if (candidate) {
      const recalled = isBatchRecalled(candidate.id) || isBatchRecalled(candidate.code);
      const orgAllowed = canSelect(candidate);
      previewEl.hidden = false;
      previewEl.innerHTML = `
        <div style="background:#0f172a; border:1px solid ${recalled ? '#ef4444' : (orgAllowed ? '#277B52' : '#f59e0b')}; border-radius:6px; padding:8px 12px; margin-top:6px; font-size:0.85rem;">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span><strong>Mã lô:</strong> <code style="color:#25313d; font-size:0.95rem; font-weight:700;">${e(candidate.code || '#' + candidate.id)}</code></span>
            <span>${recalled ? '<span class="badge badge--danger" style="background:#dc2626; color:#fff;">Có sự cố / Đã thu hồi</span>' : '<span class="badge badge--ok">Hợp lệ</span>'}</span>
          </div>
          <div style="margin-top:4px; color:#cbd5e1;">
            <span><strong>Sản phẩm:</strong> ${e(candidate.product_name || "—")}</span> ·
            <span><strong>Tồn kho:</strong> ${formatNumber(candidate.remaining_quantity != null ? candidate.remaining_quantity : candidate.quantity)} ${e(candidate.unit || "kg")}</span> ·
            <span><strong>Tổ chức giữ:</strong> ${e(candidate.current_org_name || "—")}</span>
          </div>
          ${recalled ? '<div style="color:#f87171; font-weight:600; margin-top:4px;">Lô hàng này đã có lệnh thu hồi đang xử lý hoặc bị phong tỏa! Không thể tạo trùng.</div>' : ''}
          ${!orgAllowed ? '<div style="color:#fbbf24; font-weight:600; margin-top:4px;">Bạn không thuộc tổ chức đang nắm giữ lô hàng này.</div>' : ''}
        </div>
      `;
    } else {
      previewEl.hidden = false;
      previewEl.innerHTML = `
        <div style="background:#0f172a; border:1px solid #475569; border-radius:6px; padding:6px 12px; margin-top:6px; font-size:0.85rem; color:#94a3b8;">
          <span>Mã lô <strong>${e(val)}</strong> chưa có trong danh sách hiển thị hiện tại. Hệ thống sẽ kiểm tra tồn tại và quyền trên máy chủ.</span>
        </div>
      `;
    }
  }

  function reset() {
    reviewVersion++;
    generation++; detailVersion++; activeRecall = null;
    for (const id of ["modal-recall-create", "modal-recall-detail"]) {
      const el = $(id);
      if (el) el.hidden = true;
    }
    for (const id of ["recall-list", "recall-alerts", "recall-detail-body"]) {
      const el = $(id);
      if (el) el.replaceChildren();
    }
    recalledBatchesMap.clear();
    recalledBatchCodes.clear();
    const formC = $("recall-create-form"), formA = $("recall-ack-form");
    if (formC) formC.reset();
    if (formA) formA.reset();
    const statusEl = $("recall-status");
    if (statusEl) statusEl.textContent = "";
    if (formA) formA.hidden = true;
    busyCreate = busyAck = false;
  }

  function applySession() {
    const openBtn = $("recall-open");
    if (openBtn) openBtn.hidden = !canOpen();
    const quick = $("recall-quick-search-bar");
    if (quick) quick.hidden = !canOpen();
    if (!session) reset();
  }

  async function load() {
    if (!session) return;
    const version = ++generation, owner = identity();
    const statusEl = $("recall-status");
    if (statusEl) statusEl.textContent = "Đang tải danh sách lệnh thu hồi…";
    $("recall-list")?.replaceChildren();
    $("recall-alerts")?.replaceChildren();

    try {
      const [rows, alerts] = await Promise.all([apiRequest("/recalls"), apiRequest("/recalls/my-alerts")]);
      if (version !== generation || owner !== identity()) return;

      recalledBatchesMap.clear();
      recalledBatchCodes.clear();

      for (const r of rows) {
        for (const b of (r.affected_batches || [])) {
          recalledBatchesMap.set(b.batch_id, {
            recall_code: r.recall_code,
            status: r.status,
            reason: r.reason,
            is_root: b.batch_id === r.root_batch_id,
          });
          if (b.code) recalledBatchCodes.add(b.code);
        }
      }

      const listEl = $("recall-list");
      if (listEl) {
        listEl.innerHTML = rows.map(r => `
          <tr>
            <td><strong style="color:#25313d; font-family:monospace;">${e(r.recall_code)}</strong></td>
            <td><strong>${e(rootLabel(r))}</strong></td>
            <td style="max-width:280px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${e(r.reason)}">${e(r.reason)}</td>
            <td><span class="badge ${r.status === 'COMPLETED' ? 'badge--ok' : 'badge--danger'}" style="${r.status === 'OPEN' ? 'background:#dc2626; color:#fff;' : ''}">${e(statusLabel(r.status))}${r.quarantined ? ' · Phong tỏa' : ''}</span></td>
            <td>${e(formatDateTime(r.created_at))}</td>
            <td>${progress(r)}</td>
            <td>${e(anomaly(r))}</td>
            <td><button class="btn btn--light btn--sm" data-recall-id="${r.id}">Chi tiết</button></td>
          </tr>
        `).join("");
      }

      const alertsEl = $("recall-alerts");
      if (alertsEl) {
        alertsEl.innerHTML = alerts.map(r => `
          <div class="recall-warning" style="margin-bottom:8px; border-left:4px solid #dc2626; padding:8px 12px; background:rgba(220, 38, 38, 0.1);">
            <strong>CẢNH BÁO THU HỒI: ${e(r.recall_code)}</strong> · Trạng thái: <strong>${e(statusLabel(r.status))}</strong> · ${r.quarantined ? "Đang phong tỏa" : ""}<br>
            <span>Các lô trong phạm vi tổ chức bạn: <strong>${e(r.affected_batches.map(b => `${b.code}${b.status === "CONSUMED" ? " (đã tiêu thụ)" : ""}`).join(", "))}</strong></span>
            ${r.anomaly ? `<br><span style="color:#ef4444;">${e(anomaly(r))}</span>` : ""}
          </div>
        `).join("");
      }

      if (statusEl) {
        statusEl.textContent = rows.length
          ? `${rows.length} lệnh thu hồi trong phạm vi được cấp quyền.`
          : "Chưa có yêu cầu thu hồi trong phạm vi bạn được xem";
      }

      // Thông báo cho giao diện lô nông sản cập nhật lại badge trạng thái "Có sự cố"
      if (typeof renderBatches === "function") {
        renderBatches();
      }
      renderBatchIncident();
    } catch (error) {
      if (version !== generation || owner !== identity()) return;
      if (statusEl) statusEl.textContent = error.message;
      toast(error.message, "error");
    }
  }

  function renderBatchIncident() {
    const meta=$("detail-overview-meta");
    if(!meta || !currentDetailBatchId)return;
    $("batch-recall-notice")?.remove();
    const info=getBatchRecallInfo(currentDetailBatchId);
    if(info){const notice=document.createElement("p");notice.id="batch-recall-notice";notice.className="recall-warning";notice.textContent="Có sự cố · "+info.recall_code+" · "+info.status+" · Đang cách ly. Lý do: "+info.reason;meta.prepend(notice);}
  }

  function renderDetail(r) {
    activeRecall = r;
    const titleEl = $("recall-detail-title");
    if (titleEl) titleEl.textContent = `Chi tiết lệnh thu hồi ${r.recall_code}`;
    const opts=r.filter_options||{organizations:[],locations:[]}, f=r.filters||{};
    const levels = [...new Set((r.affected_batches || []).map(b => b.level))].sort((a,b) => a-b);
    const bodyEl = $("recall-detail-body");
    if (bodyEl) {
      bodyEl.innerHTML = `
        <div style="background:#f8fafb; color:#25313d; padding:12px 16px; border-radius:8px; margin-bottom:12px; border:1px solid #dce2e7;">
          <p><strong>Lô gốc sự cố:</strong> <span style="color:#25313d; font-family:monospace; font-weight:700;">${e(rootLabel(r))}</span> · Trạng thái lệnh: <strong>${e(statusLabel(r.status))}</strong> · Ngày tạo: ${e(formatDateTime(r.created_at))}</p>
          <p><strong>Lý do thu hồi:</strong> <em>${e(r.reason)}</em></p>
          <p class="recall-warning">${r.quarantined ? "Tất cả các lô bị ảnh hưởng đã bị phong tỏa (chặn bàn giao, tách, gộp, tiêu thụ)." : ""} ${r.anomaly ? e(anomaly(r)) : ""}</p>
          <div style="margin:8px 0;"><strong>Tiến độ xác nhận:</strong> ${progress(r)}</div>
          <p><strong>Hoàn tất lúc:</strong> ${r.completed_at ? e(formatDateTime(r.completed_at)) : "Chưa hoàn tất"}. Không có quyền bỏ cách ly thủ công.</p>
        </div>
        <form id="recall-filter-form" class="audit-toolbar">
          <label>Tổ chức<select name="organization_id"><option value="">Tất cả trong phạm vi</option>${opts.organizations.map(([id,name])=>`<option value="${id}" ${Number(f.organization_id)===id?"selected":""}>${e(name)}</option>`).join("")}</select></label>
          <label>Vị trí hiện tại<select name="location_id"><option value="">Tất cả</option><option value="unknown" ${f.unknown_location?"selected":""}>Chưa có dữ liệu</option>${opts.locations.map(([id,name])=>`<option value="${id}" ${Number(f.location_id)===id?"selected":""}>${e(name)}</option>`).join("")}</select></label>
          <label>Trạng thái<select name="batch_status"><option value="">Tất cả</option>${["ACTIVE","SPLIT","MERGED","CONSUMED"].map(s=>`<option value="${s}" ${f.batch_status===s?"selected":""}>${e(statusLabel(s))}</option>`).join("")}</select></label>
          <button class="btn btn--primary" type="submit">Lọc lô thu hồi</button><button class="btn" type="button" data-recall-filter-reset>Đặt lại</button>
        </form>
        <div id="recall-graph"></div>
        <p>${r.status === "COMPLETED" ? "Tất cả các tổ chức đã xác nhận. Tiếp tục cách ly lô." : `Theo dõi các tổ chức chưa xác nhận sau ${r.reminder?.escalation_after_hours||24} giờ. Thông báo hiển thị trong phần mềm; chưa gửi email hoặc SMS.`}</p>
        <p>Đang hiển thị ${r.filtered_batch_count ?? r.visible_batch_count} lô${r.total_affected_batch_count == null ? " theo phạm vi tổ chức" : ` / ${r.total_affected_batch_count} lô ảnh hưởng`}.</p>
        ${Object.entries(r.filtered_metrics_by_unit || r.metrics_by_unit || {}).map(([unit,m]) => `
          <p><strong>Khối lượng (${e(unit)}):</strong> Tồn kho có thể thu hồi: <strong>${e(formatNumber(m.reclaimable_quantity))}</strong>; Đã tiêu thụ có chứng cứ: <strong>${e(formatNumber(m.known_consumed_quantity))}</strong>; Tổng đã tiêu thụ: <strong>${m.consumed_quantity == null ? "chưa xác định" : e(formatNumber(m.consumed_quantity))}</strong>.${m.unknown_consumed_batch_ids?.length ? ` Chưa xác định: ${e(m.unknown_consumed_batch_ids.map(id => '#' + id).join(", "))}.` : ""}</p>
        `).join("")}
        ${levels.map(level => `
          <h4>Tầng ${level}${level === 0 ? " · Lô gốc sự cố" : " · Hậu duệ phát tán"}</h4>
          <div class="table-wrap"><table class="table"><thead><tr><th>Mã lô</th><th>Tổ chức đang giữ</th><th>Vị trí hiện tại</th><th>Trạng thái lô</th><th>Tồn kho</th><th>Đã tiêu thụ</th><th>Gộp nhiều nguồn</th></tr></thead><tbody>
          ${r.affected_batches.filter(b => b.level === level).map(b => `
            <tr>
              <td><strong style="color:#25313d; font-family:monospace;">${e(b.code)}</strong></td>
              <td>${e(b.organization_name || "Chưa xác định")}</td>
              <td>${e(b.current_location ? [b.current_location_name,b.current_location].filter(Boolean).join(" · ") : "Chưa có dữ liệu")}</td>
              <td><span class="badge ${b.status === 'CONSUMED' ? '' : 'badge--danger'}" style="${b.status !== 'CONSUMED' ? 'background:#dc2626; color:#fff;' : ''}">${e(statusLabel(b.status))}</span></td>
              <td>${e(formatNumber(b.remaining_quantity))} ${e(b.unit)}</td>
              <td>${b.consumed_quantity == null ? "Chưa xác định" : `${e(formatNumber(b.consumed_quantity))} ${e(b.unit)}`}</td>
              <td>${b.is_merged_cross_origin ? "Có" : "—"}</td>
            </tr>
          `).join("")}
          </tbody></table></div>
        `).join("")}
        <h4>Xác nhận xử lý của các tổ chức liên quan</h4>
        <ul>${(r.acknowledgments || []).map(a => `
          <li><strong>${e(a.organization_name || `#${a.organization_id}`)}:</strong> <span class="badge ${a.status === 'ACKNOWLEDGED' ? 'badge--ok' : 'badge--warning'}">${a.status === "ACKNOWLEDGED" ? "Đã xác nhận" : "Chờ xác nhận"}</span> ${a.acknowledged_at ? ` · ${e(formatDateTime(a.acknowledged_at))}` : ""} ${a.notes ? ` · Ghi chú: ${e(a.notes)}` : ""}</li>
        `).join("")}</ul>
      `;
    }

    window.RecallGraph?.mount($("recall-graph"),r);
    const own = (r.acknowledgments || []).find(a => a.organization_id === session?.organization_id);
    const ackForm = $("recall-ack-form");
    if (ackForm) {
      ackForm.hidden = !(session?.role === "org_admin" && r.status === "OPEN" && own?.status === "PENDING");
      const saved = pending(`/recalls/${r.id}/acknowledge`);
      const notesEl = $("recall-ack-notes");
      if (notesEl) {
        notesEl.value = saved?.body.notes || "";
        notesEl.readOnly = !!saved;
      }
      const confirmEl = $("recall-ack-confirm");
      if (confirmEl) confirmEl.checked = false;
      const errEl = $("recall-ack-error");
      if (errEl) errEl.textContent = saved ? "Thao tác đang chờ: gửi lại với cùng khóa và ghi chú." : "";
    }
  }

  async function openDetail(id, filters={}) {
    const version = ++detailVersion, owner = identity();
    activeRecall = null;
    const ackForm = $("recall-ack-form");
    if (ackForm) ackForm.hidden = true;
    const bodyEl = $("recall-detail-body");
    if (bodyEl) bodyEl.textContent = "Đang tải dữ liệu phả hệ lệnh thu hồi…";
    const modalDetail = $("modal-recall-detail");
    if (modalDetail) modalDetail.hidden = false;

    try {
      const query=new URLSearchParams(filters).toString();
      const r = await apiRequest(`/recalls/${id}${query ? "?"+query : ""}`);
      if (owner === identity() && version === detailVersion) renderDetail(r);
    } catch (error) {
      if (owner === identity() && version === detailVersion && bodyEl) bodyEl.textContent = error.message;
    }
  }

  function openCreate(prefillBatch) {
    if (!canOpen()) {
      toast("Bạn không có quyền mở lệnh thu hồi.", "warning");
      return;
    }

    const candidateList = (typeof batches !== "undefined" && Array.isArray(batches)) ? batches.filter(canSelect) : [];
    const optionsEl = $("recall-root-options");
    if (optionsEl) {
      optionsEl.innerHTML = candidateList.map(b => `<option value="${e(b.code)}">#${b.id} - ${e(b.product_name || "")} (${e(b.current_org_name || "")})</option>`).join("");
    }

    const saved = pending("/recalls");
    const formC = $("recall-create-form");
    if (formC) formC.reset();

    // Điền thông tin người thực hiện và thời gian
    const opName = $("recall-operator-name"), opRole = $("recall-operator-role"), opTime = $("recall-operator-time");
    if (opName) opName.textContent = session?.username || "—";
    if (opRole) opRole.textContent = (typeof ROLE_NAMES !== "undefined" && ROLE_NAMES[session?.role]) || session?.role || "—";
    if (opTime) opTime.textContent = formatDateTime(new Date().toISOString());

    const rootEl = $("recall-root");
    const reasonEl = $("recall-reason");
    const errEl = $("recall-create-error");

    if (saved) {
      if (rootEl) rootEl.value = String(saved.body.batch_code || saved.body.root_batch_id || "");
      if (reasonEl) reasonEl.value = saved.body.reason || "";
      createLocked(true);
      if (errEl) errEl.textContent = "Thao tác đang chờ: gửi lại với cùng khóa và nội dung.";
    } else {
      createLocked(false);
      if (errEl) errEl.textContent = "";
      if (prefillBatch && rootEl) {
        rootEl.value = String(prefillBatch);
      }
    }

    updateReasonCounter();
    updateBatchPreview();

    const modalCreate = $("modal-recall-create");
    if (modalCreate) modalCreate.hidden = false;
    reviewVersion++;
    $('recall-review').replaceChildren();
    setCreateStep(saved ? 3 : 0);
    if (rootEl) {
      if (!prefillBatch) rootEl.focus();
      else if (reasonEl) reasonEl.focus();
    }
  }

  async function submit(event, ack) {
    event.preventDefault();
    if (!ack && createStep !== 3) { await nextCreateStep(); return; }
    if (!session || (ack ? busyAck : busyCreate)) return;
    const owner = identity();
    const prefix = ack ? "recall-ack" : "recall-create";
    const button = $(`${prefix}-submit`), errorBox = $(`${prefix}-error`);
    let record;

    try {
      if (ack && (!activeRecall || session.role !== "org_admin" || activeRecall.status !== "OPEN")) {
        throw new Error("Không có quyền xác nhận xử lý cho tổ chức.");
      }
      if (!ack && !canOpen()) {
        throw new Error("Không có quyền mở lệnh thu hồi.");
      }
      if (!$(`${prefix}-confirm`).checked) {
        throw new Error("Cần xác nhận trước khi tiếp tục.");
      }

      const path = ack ? `/recalls/${activeRecall.id}/acknowledge` : "/recalls";
      const saved = pending(path);
      let body;

      if (saved) {
        body = saved.body;
      } else if (ack) {
        body = { notes: $("recall-ack-notes").value.trim() };
      } else {
        const value = $("recall-root").value.trim();
        if (!value) {
          throw new Error("Vui lòng nhập hoặc chọn mã lô hàng cần thu hồi.");
        }
        const candidate = (typeof batches !== "undefined" && Array.isArray(batches))
          ? batches.find(b => b.code === value || String(b.id) === value)
          : null;

        const reason = $("recall-reason").value.trim();
        if (!reason) {
          throw new Error("Bắt buộc phải nhập lý do thu hồi.");
        }
        if (reason.length < 20) {
          throw new Error("Lý do thu hồi quá ngắn, tối thiểu cần 20 ký tự (hiện tại: " + reason.length + " ký tự).");
        }
        if (reason.length > 5000) {
          throw new Error("Lý do thu hồi không được vượt quá 5000 ký tự.");
        }

        if (candidate) {
          if (!canSelect(candidate)) {
            throw new Error("Tổ chức bạn không nắm giữ lô hàng này.");
          }
          if (isBatchRecalled(candidate.id) || isBatchRecalled(candidate.code)) {
            const info = getBatchRecallInfo(candidate.id) || getBatchRecallInfo(candidate.code);
            throw new Error(`Lô hàng đã có lệnh thu hồi đang xử lý (${info?.recall_code || 'đang mở'}). Không thể tạo lệnh trùng.`);
          }
          body = { root_batch_id: candidate.id, reason };
        } else {
          // Người dùng nhập mã hoặc ID trực tiếp không có trong trang danh sách hiện tại
          const isNumericId = /^[1-9]\d*$/.test(value);
          body = isNumericId ? { root_batch_id: Number(value), reason } : { batch_code: value, reason };
        }
      }

      record = saved || intent(path, body);
      if (ack) {
        busyAck = true;
        $("recall-ack-notes").readOnly = true;
      } else {
        busyCreate = true;
        createLocked(true);
      }

      setButtonLoading(button, true, "Đang xử lý…", ack ? "Xác nhận xử lý" : "Xác nhận mở lệnh");
      if (errorBox) errorBox.textContent = "";

      const result = await apiRequest(path, {
        method: "POST",
        body: record.body,
        headers: { "Idempotency-Key": record.key },
      });

      if (owner !== identity()) return;
      remember(record, false);

      if (!ack) {
        const modalCreate = $("modal-recall-create");
        if (modalCreate) modalCreate.hidden = true;
      }

      toast(ack ? "Đã xác nhận xử lý phần của tổ chức." : `Đã mở lệnh thu hồi thành công [${result.recall_code}]. Lô hàng đã chuyển sang trạng thái "Có sự cố".`, "success");

      await load();
      if (result.id) await openDetail(result.id);
    } catch (error) {
      if (owner !== identity()) return;
      const ambiguous = !error.status || error.status >= 500;
      if (record && !ambiguous) remember(record, false);
      if (!ack) createLocked(!!record && ambiguous);
      else if ($("recall-ack-notes")) $("recall-ack-notes").readOnly = !!record && ambiguous;

      let msg = error.message || "Đã xảy ra lỗi khi thực hiện thao tác.";
      if (error.detail?.code === "ROOT_ALREADY_RECALLED") {
        msg = `Lô hàng đã có lệnh thu hồi đang xử lý [${error.detail.recall_code}]. Không cho phép tạo lệnh trùng lặp.`;
      } else if (error.detail?.code === "IDEMPOTENCY_CONFLICT") {
        msg = "Khóa thao tác đã được sử dụng với nội dung khác.";
      }
      if (errorBox) {
        errorBox.textContent = `${msg}${record && ambiguous ? " Gửi lại sẽ dùng cùng khóa; nội dung được giữ nguyên." : ""}`;
      }
      toast(msg, "error");
    } finally {
      if (owner === identity()) {
        if (ack) busyAck = false; else busyCreate = false;
        setButtonLoading(button, false, "Đang xử lý…", ack ? "Xác nhận xử lý" : "Xác nhận tạo yêu cầu");
      }
    }
  }

  window.recallUi = {
    applySession,
    reset,
    load,
    openCreate,
    isBatchRecalled,
    getBatchRecallInfo,
    renderBatchIncident,
  };

  document.addEventListener("DOMContentLoaded", () => {
    $('recall-step-next')?.addEventListener('click', nextCreateStep);
    $('recall-step-back')?.addEventListener('click', () => {
      if (!busyCreate) { reviewVersion++; $('recall-create-error').textContent = ''; setCreateStep(Math.max(0, createStep - 1)); }
    });
    $("recall-detail-body")?.addEventListener("submit", event=>{
      if(event.target.id!=="recall-filter-form")return;event.preventDefault();
      const fields=new FormData(event.target), filters={};
      for(const [key,value] of fields){if(value){if(key==="location_id"&&value==="unknown")filters.unknown_location="true";else filters[key]=value;}}
      if(activeRecall)openDetail(activeRecall.id,filters);
    });
    $("recall-detail-body")?.addEventListener("click",event=>{if(event.target.closest("[data-recall-filter-reset]")&&activeRecall)openDetail(activeRecall.id);});
    $("recall-refresh")?.addEventListener("click", load);
    $("recall-open")?.addEventListener("click", () => openCreate());
    $("btn-quick-recall")?.addEventListener("click", () => {
      const code = $("recall-search-code")?.value.trim();
      if (!code) {
        toast("Vui lòng nhập mã lô hàng cần báo sự cố / thu hồi.", "warning");
        $("recall-search-code")?.focus();
        return;
      }
      openCreate(code);
    });
    $("recall-search-code")?.addEventListener("keydown", event => {
      if (event.key === "Enter") {
        event.preventDefault();
        const code = $("recall-search-code")?.value.trim();
        if (code) openCreate(code);
      }
    });
    $("recall-list")?.addEventListener("click", event => {
      const b = event.target.closest("[data-recall-id]");
      if (b) openDetail(Number(b.dataset.recallId));
    });
    $("recall-create-form")?.addEventListener("submit", event => submit(event, false));
    $("recall-ack-form")?.addEventListener("submit", event => submit(event, true));

    $("recall-root")?.addEventListener("input", updateBatchPreview);
    $("recall-root")?.addEventListener("change", updateBatchPreview);
    $("recall-reason")?.addEventListener("input", updateReasonCounter);

    document.querySelectorAll("[data-recall-close]").forEach(b => {
      b.addEventListener("click", () => {
        if (busyCreate || busyAck) return;
        const target = $(b.dataset.recallClose);
        if (target) target.hidden = true;
        detailVersion++;
      });
    });

    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && !busyCreate && !busyAck) {
        const mc = $("modal-recall-create"), md = $("modal-recall-detail");
        if (mc) mc.hidden = true;
        if (md) md.hidden = true;
        detailVersion++;
      }
    });
  });
})();
