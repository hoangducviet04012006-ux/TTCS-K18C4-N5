/* S-28: dependency-free DAG view. Edges come exclusively from the API. */
(function () {
  "use strict";
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[c]));
  const quantity = (value, unit) => value == null ? "Chưa có dữ liệu" : new Intl.NumberFormat("vi-VN").format(Number(value)) + " " + (unit || "kg");
  const formatStatus = s => (typeof formatBatchStatus === "function" ? formatBatchStatus(s) : (window.formatBatchStatus ? window.formatBatchStatus(s) : (s || "Chưa có dữ liệu")));
  const formatRelation = t => (typeof formatRelationType === "function" ? formatRelationType(t) : (window.formatRelationType ? window.formatRelationType(t) : (t || "—")));
  function mount(container, data) {
    const nodes = new Map();
    const root = { ...data.target_batch, batch_id: data.target_batch.id, level: 0 };
    nodes.set(root.batch_id, root);
    Object.values(data.descendants_by_level || {}).flat().forEach(node => {
      if (!nodes.has(node.batch_id)) nodes.set(node.batch_id, node);
    });
    const edges = (data.edges || []).filter(e => nodes.has(e.parent_batch_id) && nodes.has(e.child_batch_id));
    const children = new Map(), parents = new Map();
    nodes.forEach((_, id) => { children.set(id, []); parents.set(id, []); });
    edges.forEach(e => { children.get(e.parent_batch_id).push(e.child_batch_id); parents.get(e.child_batch_id).push(e.parent_batch_id); });
    const collapsed = new Set();
    let selected = root.batch_id;
    container.innerHTML = '<div class="genealogy-toolbar"><button type="button" class="btn btn--sm btn--light" data-graph-expand>Mở tất cả</button><button type="button" class="btn btn--sm btn--light" data-graph-collapse>Thu gọn về lô gốc</button><span class="genealogy-count" role="status"></span></div>' +
      '<p class="genealogy-help">Chọn lô để xem thông tin. Mũi tên là quan hệ tách/gộp thật; lô gộp có thể có nhiều cha. Có thể cuộn sơ đồ theo hai chiều.</p>' +
      (data.target_batch.is_truncated ? '<p class="genealogy-warning" role="status">Kết quả đã giới hạn; sơ đồ chưa bao gồm toàn bộ hậu duệ.</p>' : '') +
      (nodes.size === 1 ? '<p class="genealogy-help">Lô này chưa có hậu duệ.</p>' : '') +
      (!data.edges ? '<p class="genealogy-warning">Chưa có thông tin quan hệ giữa các lô.</p>' : '') +
      '<div class="genealogy-scroll" tabindex="0" role="region" aria-label="Sơ đồ phả hệ nhiều cha"><div class="genealogy-stage"></div></div>' +
      '<section class="genealogy-detail" aria-label="Chi tiết lô được chọn" aria-live="polite"></section>';
    const stage = container.querySelector(".genealogy-stage");
    function showDetail() {
      const n = nodes.get(selected);
      if (!n) return;
      const incoming = edges.filter(e => e.child_batch_id === selected);
      container.querySelector(".genealogy-detail").innerHTML = '<h5>Chi tiết lô ' + esc(n.code || "#" + selected) + '</h5><dl>' +
        [["Loại lô", selected === root.batch_id ? "Lô gốc truy xuất" : incoming.length > 1 ? "Lô gộp nhiều cha" : "Lô hậu duệ"],
         ["Sản phẩm", n.product_name || "Chưa có dữ liệu"],
         ["Tổ chức đang giữ", n.current_org_name || (n.current_org_id ? "Tổ chức #" + n.current_org_id : "Chưa có dữ liệu")],
         ["Vị trí nguồn gốc", n.is_masked ? "Thông tin bị giới hạn theo quyền" : n.location || "Chưa có dữ liệu"],
         ["Vị trí hiện tại", n.current_location ? [n.current_location_name, n.current_location].filter(Boolean).join(" · ") : "Chưa có dữ liệu"],
         ["Khối lượng ban đầu", quantity(n.initial_quantity, n.unit)],
         ["Khối lượng còn lại", quantity(n.remaining_quantity, n.unit)],
         ["Trạng thái", formatStatus(n.status) || "Chưa có dữ liệu"],
         ["Ngày thu hoạch", n.harvest_date || "Chưa có dữ liệu"]]
        .map(([label, value]) => '<div><dt>' + esc(label) + '</dt><dd>' + esc(value) + '</dd></div>').join("") + '</dl>' +
        (incoming.length ? '<p><strong>Quan hệ cha được phép xem:</strong> ' + incoming.map(e => esc(nodes.get(e.parent_batch_id).code || "#" + e.parent_batch_id) + ' (' + esc(formatRelation(e.relation_type)) + ', ' + esc(quantity(e.transferred_quantity, n.unit)) + ')').join("; ") + '</p>' : '') +
        '<p class="genealogy-help">Thông tin hiển thị trong phạm vi tài khoản của bạn. Vị trí nguồn gốc là nơi thu hoạch.</p>';
    }
    function render(focusToggle) {
      // Nodes without authorized incoming edges remain separate; no invented
      // link joins a masked component to the root.
      const starts = [...nodes.keys()].filter(id => !parents.get(id).length);
      const visible = new Set(), queue = [...starts];
      for (let i = 0; i < queue.length; i++) {
        const id = queue[i];
        if (visible.has(id)) continue;
        visible.add(id);
        if (!collapsed.has(id)) queue.push(...children.get(id));
      }
      const indegree = new Map([...nodes.keys()].map(id => [id, parents.get(id).length]));
      const ranks = new Map(starts.map(id => [id, 0])), order = [...starts];
      for (let i = 0; i < order.length; i++) {
        const id = order[i];
        for (const child of children.get(id)) {
          ranks.set(child, Math.max(ranks.get(child) || 0, (ranks.get(id) || 0) + 1));
          indegree.set(child, indegree.get(child) - 1);
          if (indegree.get(child) === 0) order.push(child);
        }
      }
      const rows = new Map();
      visible.forEach(id => {
        const rank = ranks.get(id) || 0;
        if (!rows.has(rank)) rows.set(rank, []);
        rows.get(rank).push(id);
      });
      const positions = new Map();
      rows.forEach((ids, rank) => ids.forEach((id, col) => positions.set(id, { x: col * 210 + 16, y: rank * 145 + 16 })));
      const width = Math.max(250, ...[...rows.values()].map(ids => ids.length * 210 + 20));
      const height = Math.max(145, ...[...rows.keys()].map(rank => (rank + 1) * 145 + 16));
      stage.style.width = width + "px"; stage.style.height = height + "px";
      const visibleEdges = edges.filter(e => visible.has(e.parent_batch_id) && visible.has(e.child_batch_id) && !collapsed.has(e.parent_batch_id));
      stage.innerHTML = '<svg aria-hidden="true" width="' + width + '" height="' + height + '"><defs><marker id="genealogy-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto"><path d="M0,0 L0,6 L6,3 z" fill="#64748b"/></marker></defs>' +
        visibleEdges.map(e => { const a=positions.get(e.parent_batch_id), b=positions.get(e.child_batch_id); return '<path class="genealogy-edge" d="M' + (a.x+90) + ',' + (a.y+100) + ' C' + (a.x+90) + ',' + (a.y+125) + ' ' + (b.x+90) + ',' + (b.y-25) + ' ' + (b.x+90) + ',' + b.y + '" marker-end="url(#genealogy-arrow)"><title>' + esc(formatRelation(e.relation_type)) + '</title></path>'; }).join("") + '</svg>' +
        [...visible].map(id => {
          const n=nodes.get(id), p=positions.get(id), merge=parents.get(id).length>1;
          return '<article class="genealogy-node ' + (id===root.batch_id?'genealogy-node--root ':'') + (merge?'genealogy-node--merge ':'') + '" style="left:' + p.x + 'px;top:' + p.y + 'px" data-node-id="' + id + '">' +
            '<button type="button" class="genealogy-select" data-select="' + id + '" aria-pressed="' + (id===selected) + '" aria-label="Xem chi tiết lô ' + esc(n.code || "#"+id) + '"><strong>' + esc(n.code || "#"+id) + '</strong><span>' + (id===root.batch_id?'Lô gốc':merge?'Gộp · '+parents.get(id).length+' cha':n.relation_type==='MERGE'?'Lô gộp':'Lô hậu duệ') + '</span><span>' + esc(quantity(n.remaining_quantity,n.unit)) + '</span></button>' +
            (children.get(id).length ? '<button type="button" class="genealogy-toggle" data-toggle="' + id + '" aria-expanded="' + !collapsed.has(id) + '" aria-label="' + (collapsed.has(id)?'Mở nhánh ':'Thu nhánh ') + esc(n.code || "#"+id) + '">' + (collapsed.has(id)?'＋':'−') + '</button>' : '') + '</article>';
        }).join("");
      container.querySelector(".genealogy-count").textContent = visible.size + "/" + nodes.size + " lô · " + visibleEdges.length + " quan hệ hiển thị";
      if (!visible.has(selected)) selected = root.batch_id;
      showDetail();
      if (focusToggle != null) stage.querySelector('[data-toggle="' + focusToggle + '"]')?.focus();
    }
    container.onclick = event => {
      const button = event.target.closest("button");
      if (!button || !container.contains(button)) return;
      if (button.hasAttribute("data-select")) {
        selected=Number(button.dataset.select);
        stage.querySelectorAll("[data-select]").forEach(b => b.setAttribute("aria-pressed", String(Number(b.dataset.select)===selected)));
        showDetail();
      } else if (button.hasAttribute("data-toggle")) {
        const id=Number(button.dataset.toggle);
        if (collapsed.has(id)) collapsed.delete(id); else collapsed.add(id);
        render(id);
      } else if (button.hasAttribute("data-graph-expand")) { collapsed.clear(); render(); }
      else if (button.hasAttribute("data-graph-collapse")) { nodes.forEach((_,id)=>{if(children.get(id).length)collapsed.add(id);}); render(); }
    };
    render();
  }
  window.AgriLineage = { mount };
})();
