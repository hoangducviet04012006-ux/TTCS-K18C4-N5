
(function () {
  "use strict";

  const STYLE_ID = "s28-lineage-tree-style";

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    })[char]);
  }

  function getBatchId(node) {
    return node?.batch_id ?? node?.id ?? null;
  }

  function getBatchCode(node) {
    return node?.code ?? node?.batch_code ?? "Chưa có mã lô";
  }

  function addStyles() {
    if (document.getElementById(STYLE_ID)) return;

    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
      .s28-lineage-layout {
        display: grid;
        grid-template-columns: minmax(220px, 1fr)
          minmax(220px, 1fr) minmax(260px, 1.4fr);
        gap: 16px;
        align-items: start;
        min-width: 0;
      }
      .s28-lineage-panel {
        min-width: 0;
        border: 1px solid #dbe2ea;
        border-radius: 10px;
        padding: 12px;
        background: #fff;
      }
      .s28-lineage-heading {
        margin: 0 0 12px;
        font-size: 15px;
        font-weight: 700;
      }
      .s28-lineage-level {
        margin: 10px 0;
        padding: 8px;
        border-left: 2px solid #cbd5e1;
      }
      .s28-lineage-level-title {
        margin: 0 0 8px;
        color: #475569;
        font-size: 12px;
        font-weight: 700;
      }
      .s28-lineage-node {
        margin: 8px 0;
        padding: 10px;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        overflow-wrap: anywhere;
      }
      .s28-lineage-node-current {
        border: 2px solid #0284c7;
        background: #f0f9ff;
      }
      .s28-lineage-node button {
        max-width: 100%;
        overflow-wrap: anywhere;
      }
      .s28-lineage-code {
        padding: 0;
        border: 0;
        background: transparent;
        color: #075985;
        font-weight: 700;
        cursor: pointer;
        text-align: left;
      }
      .s28-lineage-toggle {
        margin-right: 6px;
        min-width: 26px;
        min-height: 26px;
        cursor: pointer;
      }
      .s28-lineage-meta {
        margin-top: 5px;
        color: #475569;
        font-size: 12px;
      }
      .s28-lineage-children {
        margin: 8px 0 0 10px;
        padding-left: 12px;
        border-left: 1px solid #cbd5e1;
      }
      .s28-lineage-children[hidden] {
        display: none;
      }
      .s28-lineage-empty {
        color: #64748b;
        font-size: 13px;
      }
      .s28-lineage-scroll {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

@media (max-width: 760px) {
  .s28-lineage-layout {
    min-width: 732px;
    grid-template-columns: 220px 220px 260px;
  }
}
    `;
    document.head.appendChild(style);
  }

  function renderNode(node, options = {}) {
    const id = getBatchId(node);
    const key = id == null ? "" : String(id);
    const children = node.children || [];
    const expandable = children.length > 0;
    const expanded = options.expanded === true;
    const includeChildren = options.includeChildren !== false;

    const childHtml = expandable && includeChildren
      ? `<div class="s28-lineage-children"
             data-s28-children="${escapeHtml(key)}"
             ${expanded ? "" : "hidden"}>
           ${children.map((child) => renderNode(child)).join("")}
         </div>`
      : "";

    return `
      <div class="s28-lineage-node ${options.current ? "s28-lineage-node-current" : ""}">
        ${expandable && includeChildren
          ? `<button type="button"
               class="s28-lineage-toggle"
               data-s28-toggle="${escapeHtml(key)}"
               aria-expanded="${expanded}">
               ${expanded ? "−" : "+"}
             </button>`
          : ""}
        <button type="button"
          class="s28-lineage-code"
          data-s28-open="${escapeHtml(key)}">
          ${escapeHtml(getBatchCode(node))}
        </button>
        <div class="s28-lineage-meta">
          ${options.current ? "Lô đang xem" :
            node.level ? `F${escapeHtml(node.level)}` : "Lô tổ tiên"}
          ${node.relation_type
            ? ` · ${escapeHtml(node.relation_type)}` : ""}
        </div>
        ${node.transferred_quantity != null
          ? `<div class="s28-lineage-meta">
               Số lượng chuyển: ${escapeHtml(node.transferred_quantity)}
             </div>`
          : ""}
        ${childHtml}
      </div>`;
  }

  function groupAncestors(data) {
    if (!data) return "";

    const levels = data.ancestors_by_level || {};
    const levelKeys = Object.keys(levels).sort(
      (a, b) => Number(a) - Number(b)
    );

    if (!levelKeys.length) {
      const roots = data.root_batches || [];
      if (!roots.length) {
        return '<p class="s28-lineage-empty">Không có dữ liệu lô tổ tiên.</p>';
      }
      return roots.map((node) => renderNode(node)).join("");
    }

    return levelKeys.map((level) => {
      const items = levels[level] || [];
      return `
        <section class="s28-lineage-level">
          <p class="s28-lineage-level-title">
            Cấp tổ tiên ${escapeHtml(level)}
          </p>
          ${items.map((node) => renderNode(node)).join("")}
        </section>`;
    }).join("");
  }

  function render(container, data, options = {}) {
    if (!container) {
      throw new Error("S-28: Không tìm thấy vùng hiển thị cây phả hệ.");
    }

    addStyles();

    const target = data?.target_batch;
    if (!target) {
      container.innerHTML =
        '<p class="s28-lineage-empty">API chưa trả về thông tin lô đang chọn.</p>';
      return;
    }

    const targetId = getBatchId(target);
    const levels = data.descendants_by_level || {};
    const nodes = Object.values(levels).flat();
    const nodeMap = new Map();

    nodes.forEach((node) => {
      const id = getBatchId(node);
      if (id != null) {
        nodeMap.set(String(id), { ...node, children: [] });
      }
    });

    const root = { ...target, children: [] };
    const orphans = [];

    nodes.forEach((node) => {
      const id = getBatchId(node);
      const key = id == null ? null : String(id);
      const item = key === null ? null : nodeMap.get(key);

      if (!item) return;

      const parentId = node.parent_batch_id;

      if (parentId != null && String(parentId) === String(targetId)) {
        root.children.push(item);
      } else if (parentId != null && nodeMap.has(String(parentId))) {
        nodeMap.get(String(parentId)).children.push(item);
      } else {
        orphans.push(item);
      }
    });

    const ancestorData = options.ancestorData || null;
    const ancestorHtml = groupAncestors(ancestorData);

    const descendantHtml = root.children.length
      ? root.children.map((node) => renderNode(node)).join("")
      : '<p class="s28-lineage-empty">Chưa có lô con.</p>';

    container.innerHTML = `
    <div class="s28-lineage-scroll">
      <div class="s28-lineage-layout">
        <section class="s28-lineage-panel">
          <h3 class="s28-lineage-heading">Lô cha / tổ tiên</h3>
          ${ancestorHtml ||
            '<p class="s28-lineage-empty">Chưa có dữ liệu truy xuất ngược. Cần tải API trace-back để hiển thị tổ tiên.</p>'}
        </section>

        <section class="s28-lineage-panel">
          <h3 class="s28-lineage-heading">Lô đang chọn</h3>
          ${renderNode(root, { current: true, includeChildren: false })}
          <p class="s28-lineage-empty">
            Tổng số lô con: ${escapeHtml(data.total_descendants ?? nodes.length)}
          </p>
        </section>

        <section class="s28-lineage-panel">
          <h3 class="s28-lineage-heading">Các thế hệ lô con</h3>
          ${descendantHtml}
        </section>
      </div>

      ${orphans.length
        ? `<p class="s28-lineage-empty">
             Có ${orphans.length} lô chưa xác định được lô cha trong dữ liệu API.
           </p>`
                : ""}
  </div>`;

    container.onclick = function (event) {
      const toggle = event.target.closest("[data-s28-toggle]");

      if (toggle) {
        const key = toggle.dataset.s28Toggle;
        const node = toggle.parentElement;
        const childList = node.querySelector(
          `[data-s28-children="${key}"]`
        );

        if (!childList) return;

        const expand = childList.hidden;
        childList.hidden = !expand;
        toggle.setAttribute("aria-expanded", String(expand));
        toggle.textContent = expand ? "−" : "+";
        return;
      }

      const codeButton = event.target.closest("[data-s28-open]");
      if (!codeButton) return;

      const batchId = codeButton.dataset.s28Open;
      if (!batchId) return;

      if (typeof options.onOpenBatch === "function") {
        options.onOpenBatch(batchId);
      } else if (typeof window.openBatchDetailsModal === "function") {
        window.openBatchDetailsModal(batchId);
      } else {
        console.warn("S-28: Chưa tích hợp hàm mở chi tiết lô.", batchId);
      }
    };
  }

  window.LineageTree = { render };
})();
