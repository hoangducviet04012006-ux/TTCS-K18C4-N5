/* Recall graph: every arrow is an authorized database relation, no inferred links. */
(function(){
  function mount(container, r) {
    const esc=escapeHtml, nodes=r.affected_batches || [], ids=new Map(), columns=new Map();
    for (const n of nodes) {if(!columns.has(n.level)) columns.set(n.level,[]); columns.get(n.level).push(n);}
    const levels=[...columns.keys()].sort((a,b)=>a-b);
    const width=Math.max(300, levels.length*250), height=Math.max(120, ...[...columns.values()].map(ns=>ns.length*100+30));
    levels.forEach((level,col)=>columns.get(level).forEach((n,row)=>ids.set(n.batch_id,{x:col*250+15,y:row*100+15,node:n})));
    const arrows=(r.affected_edges||[]).filter(e=>ids.has(e.parent_batch_id)&&ids.has(e.child_batch_id)).map(e=>{
      const a=ids.get(e.parent_batch_id),b=ids.get(e.child_batch_id);
      return '<path d="M '+(a.x+210)+' '+(a.y+32)+' L '+b.x+' '+(b.y+32)+'" stroke="#477b60" fill="none" marker-end="url(#recall-arrow)"><title>'+esc(formatRelationType(e.relation_type)+' · '+e.transferred_quantity)+'</title></path>';
    }).join('');
    const boxes=[...ids.values()].map(({x,y,node:n})=>'<g transform="translate('+x+','+y+')"><rect width="210" height="70" rx="5" fill="white" stroke="#b45309"/><text x="8" y="20" font-weight="600">'+esc(n.code)+'</text><text x="8" y="40">Tầng '+n.level+' · '+esc(formatBatchStatus(n.status))+'</text><text x="8" y="58">'+esc(formatNumber(n.remaining_quantity)+' '+n.unit)+'</text><title>'+esc(n.organization_name+' · '+(n.current_location||'Chưa có vị trí hiện tại'))+'</title></g>').join('');
    container.innerHTML=nodes.length ? '<p>'+nodes.length+' lô · '+(r.affected_edges||[]).length+' cạnh trong phạm vi hiển thị. Không hiển thị cạnh tới lô ngoài quyền/bộ lọc.</p><div class="genealogy-scroll" tabindex="0" role="region" aria-label="Sơ đồ các lô bị ảnh hưởng"><svg role="img" aria-label="Các quan hệ tách gộp thực của lệnh thu hồi" width="'+width+'" height="'+height+'"><defs><marker id="recall-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="#477b60"/></marker></defs>'+arrows+boxes+'</svg></div>' : '<p>Không có lô khớp bộ lọc trong phạm vi của bạn.</p>';
  }
  window.RecallGraph={mount};
})();
