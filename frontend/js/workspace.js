/* Local table tools and accessible field feedback; no API or permission overrides. */
(function () {
  'use strict';
  const normalized = text => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/g,'d').toLowerCase();
  function limitStats() {
    const role=session?.role;
    const ids=role==='system_admin'||role==='admin' ? ['users','products','orgs','audit'] : role==='org_admin' ? ['farms','users','eligible','audit'] : role==='inspector' ? ['farms','batches','yield','audit'] : role==='transporter' ? ['batches','yield','pending','outgoing'] : role==='farmer' ? ['farms','batches','yield','pending'] : ['batches','yield','pending','eligible'];
    document.querySelectorAll('#overview>article[id]').forEach(card => {
      if(!ids.some(id=>card.id==='stat-'+id+'-card'))card.hidden=true;
    });
  }
  window.workspaceUi={limitStats};
  document.addEventListener('DOMContentLoaded', () => {
    const practiceHelp=document.querySelector('.login-practice-helpers');
    if(practiceHelp && window.AGRITRACE_CONFIG?.practiceMode) {
      practiceHelp.hidden=false;
    }
    document.addEventListener('toggle',event=>{
      const details=event.target;
      if(details.id==='batch-entry' && details.open)document.getElementById('batch-cancel').hidden=false;
      if(details.id==='farm-entry' && details.open)document.getElementById('farm-cancel').hidden=false;
      if(!details.matches?.('.action-dropdown') || !details.open)return;
      document.querySelectorAll('.action-dropdown[open]').forEach(other=>{if(other!==details)other.open=false;});
      const rect=details.querySelector('summary').getBoundingClientRect();
      const menu=details.querySelector('.action-dropdown__menu');
      const width=Math.min(220,window.innerWidth-24);
      menu.style.width=width+'px';
      const height=Math.min(menu.scrollHeight,window.innerHeight-24);
      const top=rect.bottom+height+6<=window.innerHeight ? rect.bottom+4 : Math.max(12,rect.top-height-4);
      menu.style.setProperty('--menu-top',top+'px');
      menu.style.setProperty('--menu-left',Math.max(12,Math.min(rect.right-width,window.innerWidth-width-12))+'px');
    },true);
    document.addEventListener('scroll',event=>{
      if(event.target.closest?.('.action-dropdown__menu'))return;
      document.querySelectorAll('.action-dropdown[open]').forEach(details=>{details.open=false;});
    },true);
    document.addEventListener('keydown',event=>{
      if(event.key==='Escape')document.querySelectorAll('.action-dropdown[open]').forEach(details=>{details.open=false;details.querySelector('summary').focus();});
    });
    limitStats();
    const auditPager=document.getElementById('audit-prev')?.closest('.pagination');
    const auditTable=document.getElementById('audit-table-body')?.closest('.table-wrap');
    if(auditPager && auditTable)auditTable.after(auditPager);
    for (const id of ['farm-table-body','products-table-body','location-rows','recall-list','pending-handovers-table-body']) {
      const body=document.getElementById(id);
      if (!body) continue;
      const wrap=body.closest('.table-wrap');
      if (!wrap) continue;
      const toolbar=document.createElement('div'); toolbar.className='table-controls';
      toolbar.id=id+'-controls';
      const label=document.createElement('label'); label.textContent='Tìm trong danh sách';
      const search=document.createElement('input'); search.type='search'; search.placeholder='Nhập từ khóa…'; search.setAttribute('aria-label','Tìm trong danh sách');
      label.append(search);
      const stateFilter=document.createElement('select');
      const states=id==='recall-list'?['Đang xử lý','Đã đủ xác nhận']:id==='location-rows'?['Hoạt động','Ngừng hoạt động']:[];
      stateFilter.setAttribute('aria-label','Lọc trạng thái');
      for(const text of ['Tất cả trạng thái',...states])stateFilter.add(new Option(text,text==='Tất cả trạng thái'?'':text));
      const pager=document.createElement('div'); pager.className='pagination';
      pager.id=id+'-pager';
      const prev=document.createElement('button'); const next=document.createElement('button');
      prev.type=next.type='button'; prev.className=next.className='btn btn--light'; prev.textContent='Trước'; next.textContent='Sau';
      const info=document.createElement('span'); info.setAttribute('aria-live','polite');
      pager.append(prev,info,next);toolbar.append(label);
      if(states.length)toolbar.append(stateFilter);
      wrap.before(toolbar);wrap.after(pager);
      let page=1;
      function draw() {
        const rows=[...body.children];
        const matches=rows.filter(row=>normalized(row.textContent).includes(normalized(search.value.trim())) && (!stateFilter.value || row.cells?.[3]?.textContent.trim().startsWith(stateFilter.value)));
        const pages=Math.max(1,Math.ceil(matches.length/10)); page=Math.min(page,pages);
        const selected=new Set(matches.slice((page-1)*10,page*10));
        for(const row of rows)row.hidden=!selected.has(row);
        info.textContent=matches.length?`${matches.length} dòng · Trang ${page}/${pages}`:'Không có kết quả';
        prev.disabled=page<=1; next.disabled=page>=pages;
      }
      search.addEventListener('input',()=>{page=1;draw();});
      stateFilter.addEventListener('change',()=>{page=1;draw();});
      prev.onclick=()=>{page--;draw();}; next.onclick=()=>{page++;draw();};
      new MutationObserver(()=>{page=1;draw();}).observe(body,{childList:true});
      document.getElementById('btn-logout')?.addEventListener('click',()=>{search.value='';stateFilter.value='';page=1;draw();});
      draw();
    }
    for (const form of document.querySelectorAll('form')) {
      form.addEventListener('invalid',event=>{
        const input=event.target;
        input.setAttribute('aria-invalid','true');
        let error=input.parentElement.querySelector('.field-error');
        if(!error){error=document.createElement('span');error.className='field-error';error.setAttribute('role','alert');input.after(error);}
        error.textContent=input.validity.valueMissing?'Vui lòng nhập thông tin này.':input.validity.rangeUnderflow?'Giá trị nhỏ hơn mức cho phép.':input.validity.rangeOverflow?'Giá trị vượt mức cho phép.':input.validity.stepMismatch?'Vui lòng kiểm tra số chữ số thập phân.':'Thông tin chưa đúng định dạng.';
      },true);
      form.addEventListener('input',event=>{
        event.target.removeAttribute('aria-invalid');
        event.target.parentElement.querySelector('.field-error')?.remove();
      });
      form.addEventListener('reset',()=>{
        form.querySelectorAll('.field-error').forEach(e=>e.remove());
        form.querySelectorAll('[aria-invalid]').forEach(e=>e.removeAttribute('aria-invalid'));
      });
    }
    document.addEventListener('click', event => {
      const btn = event.target.closest('[data-fill-account]');
      if (!btn) return;
      const username = btn.dataset.fillAccount;
      const password = btn.dataset.fillPass;
      const userInput = document.getElementById('login-username');
      const passInput = document.getElementById('login-password');
      const form = document.getElementById('login-form');
      if (userInput && passInput) {
        userInput.value = username;
        passInput.value = password;
        userInput.dispatchEvent(new Event('input', { bubbles: true }));
        passInput.dispatchEvent(new Event('input', { bubbles: true }));
        if (form) form.requestSubmit();
      }
    });
  });
})();
