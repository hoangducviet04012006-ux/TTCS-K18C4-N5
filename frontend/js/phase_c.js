/* Phase C: stores/CSV use API permissions and explicit readiness. */
(function () {
  "use strict";
  let caps={}, places=[], editId=null;
  const el=id=>document.getElementById(id);
  const escape=escapeHtml;
  function reset() {
    caps={};places=[];editId=null;
    ["location-rows","csv-results","store-allocation-results"].forEach(id=>el(id)?.replaceChildren());
    el("locations-form")?.reset();el("csv-form")?.reset();el("store-form")?.reset();
    if(el("store-items")){el("store-items").replaceChildren();addRow();addRow();}
    if(el("location-code"))el("location-code").disabled=false;
  }
  function canOpen(key) {
    if(!session)return false;
    return key==="locations-card" ? !!(caps.locations_ready&&caps.location_manage) : !!(caps.product_import||caps.plot_import);
  }
  function eligible() {
    return batches.filter(b=>batchIsHeld(b)&&["ACTIVE","SPLIT"].includes(b.status)&&Number(b.remaining_quantity)>0&&!b.is_pending&&!b.pending_handover&&!b.pending_handover_id&&!b.has_pending_handover&&!batchIsRecalled(b));
  }
  function draw() {
    const select=el("store-batch");
    const keep=select.value;
    select.innerHTML='<option value="">Chọn lô trên trang hiện tại…</option>'+eligible().map(b=>'<option value="'+b.id+'">'+escape(b.code)+' · '+formatNumber(b.remaining_quantity)+' '+escape(b.unit||"kg")+'</option>').join("");
    select.value=keep;
    el("store-allocate").hidden=!hasUiAction("SPLIT");
    el("location-rows").innerHTML=places.map(p=>'<tr><td>'+escape(p.code)+'</td><td>'+escape(p.name)+'</td><td>'+escape(p.address)+'</td><td>'+(p.is_active?'Hoạt động':'Ngừng hoạt động')+'</td><td><button type="button" class="btn btn--sm btn--light" data-place-edit="'+p.id+'">Sửa</button> <button type="button" class="btn btn--sm btn--light" data-place-toggle="'+p.id+'">'+(p.is_active?'Ngừng hoạt động':'Mở lại')+'</button></td></tr>').join("")||'<tr><td colspan="5">Chưa có địa điểm. Hãy khai báo địa chỉ thực.</td></tr>';
    const options='<option value="">Chọn địa điểm…</option>'+places.filter(p=>p.is_active).map(p=>'<option value="'+p.id+'">'+escape(p.code+' · '+p.name)+'</option>').join("");
    document.querySelectorAll(".store-location").forEach(s=>{const value=s.value;s.innerHTML=options;s.value=value;});
    el("store-current-quantity").textContent=select.value ? 'Lượng còn lại: '+formatNumber(eligible().find(b=>b.id===Number(select.value))?.remaining_quantity)+' · Phân bổ phải dùng toàn bộ lượng này.' : 'Danh sách lô theo trang hiện tại; đổi trang trong màn hình lô để chọn lô khác.';
  }
  function drawTotals() {
    const batch=eligible().find(b=>b.id===Number(el("store-batch").value));
    if(!batch)return;
    const total=[...document.querySelectorAll(".store-quantity")].reduce((sum,input)=>sum+Math.round(Number(input.value||0)*100),0);
    const remaining=Math.round(Number(batch.remaining_quantity)*100);
    el("store-current-quantity").textContent="Lượng còn lại: "+formatNumber(remaining/100)+" "+(batch.unit||"kg")+" · Tổng phân bổ: "+formatNumber(total/100)+" · Chênh lệch: "+formatNumber((remaining-total)/100)+". Chuyển nguyên lô không cần nhập lượng.";
  }
  async function load() {
    const actor=session;
    if(!actor){reset();return;}
    const result=await apiRequest("/phase-c/capabilities");
    if(actor!==session)return;
    caps=result;
    places=caps.locations_ready&&caps.location_manage ? await apiRequest("/organizations/locations") : [];
    if(actor!==session)return;
    const options=[];
    if(caps.product_import)options.push('<option value="product">Sản phẩm</option>');
    if(caps.plot_import)options.push('<option value="plot">Thửa đất</option>');
    el("csv-entity").innerHTML=options.join("");
    draw();
    renderAppScreen(false);
  }
  async function busy(button,action) {
    button.disabled=true;
    try{await action();}
    catch(error){toast(error.message||"Thao tác thất bại.","error");}
    finally{button.disabled=false;}
  }
  function addRow() {
    const row=document.createElement("div");row.className="store-allocation-row";
    row.innerHTML='<label>Địa điểm<select class="store-location" required></select></label><label>Lượng<input class="store-quantity" type="number" min="0.01" step="0.01" required></label><button class="btn btn--light" type="button" data-remove-store>Xóa dòng</button>';
    el("store-items").append(row);draw();
  }
  document.addEventListener("DOMContentLoaded",()=>{
    el("locations-form").addEventListener("submit",event=>{
      event.preventDefault();
      busy(el("location-save"),async()=>{
        const body={name:el("location-name").value.trim(),address:el("location-address").value.trim()};
        if(editId==null)body.code=el("location-code").value.trim();
        await apiRequest("/organizations/locations"+(editId==null?"":"/"+editId),{method:editId==null?"POST":"PATCH",body});
        editId=null;el("locations-form").reset();el("location-code").disabled=false;
        await load();toast("Đã lưu địa điểm.","success");
      });
    });
    el("location-cancel").onclick=()=>{editId=null;el("locations-form").reset();el("location-code").disabled=false;};
    el("location-rows").onclick=event=>{
      const edit=event.target.closest("[data-place-edit]");
      if(edit){const p=places.find(p=>p.id===Number(edit.dataset.placeEdit));editId=p.id;el("location-code").value=p.code;el("location-code").disabled=true;el("location-name").value=p.name;el("location-address").value=p.address;el("location-name").focus();}
      const toggle=event.target.closest("[data-place-toggle]");
      if(toggle)busy(toggle,async()=>{const p=places.find(p=>p.id===Number(toggle.dataset.placeToggle));if(p.is_active&&!await confirmAction("Ngừng hoạt động địa điểm "+p.name+"?"))return;await apiRequest("/organizations/locations/"+p.id,{method:"PATCH",body:{is_active:!p.is_active}});await load();});
    };
    el("store-add-row").onclick=addRow;
    el("store-items").onclick=event=>{const remove=event.target.closest("[data-remove-store]");if(remove)remove.parentElement.remove();};
    el("store-batch").onchange=()=>{draw();drawTotals();};
    el("store-items").addEventListener("input",drawTotals);
    el("store-form").addEventListener("submit",event=>{
      event.preventDefault();
      const button=event.submitter;
      busy(button,async()=>{
        const batchId=Number(el("store-batch").value);
        if(!eligible().some(b=>b.id===batchId))throw Error("Chọn lô còn lượng khả dụng trên trang hiện tại.");
        const rows=[...el("store-items").children].map(row=>({location_id:Number(row.querySelector("select").value),quantity:row.querySelector("input").value}));
        if(rows.some(row=>!row.location_id))throw Error("Chọn địa điểm hợp lệ cho mỗi dòng.");
        const allocate=button.id==="store-allocate";
        if(allocate&&!hasUiAction("SPLIT"))throw Error("Tài khoản không có quyền tách/phân bổ.");
        if(!allocate&&rows.length!==1)throw Error("Chuyển nguyên lô cần đúng một dòng địa điểm. Xóa các dòng dư.");
        if(allocate&&rows.length<2)throw Error("Phân bổ cần ít nhất hai lô con.");
        if(allocate&&rows.reduce((sum,r)=>sum+Math.round(Number(r.quantity)*100),0)!==Math.round(Number(eligible().find(b=>b.id===batchId).remaining_quantity)*100))throw Error("Tổng phân bổ phải bằng toàn bộ lượng còn lại.");
        if(!await confirmAction(allocate?"Xác nhận tách toàn bộ lượng còn lại vào các cửa hàng?":"Xác nhận chuyển vị trí nội bộ của nguyên lô?"))return;
        const result=await apiRequest("/batches/"+batchId+(allocate?"/allocate-stores":"/transfer-location"),{method:"POST",body:allocate?{items:rows}:{location_id:rows[0].location_id}});
        el("store-allocation-results").textContent=allocate?(result.message+" Lô con: "+result.child_batches.map(c=>c.code).join(", ")):"Đã cập nhật vị trí hiện tại.";
        await loadBatches();await load();
        toast("Giao dịch thành công.","success");
      });
    });
    el("csv-template").onclick=async()=>{
      try {
        const type=el("csv-entity").value;
        const response=await fetch(API_BASE_URL+"/catalogs/template/"+type,{credentials:"include"});
        if(!response.ok)throw Error("Không tải được mẫu CSV.");
        const a=document.createElement("a");const url=URL.createObjectURL(await response.blob());a.href=url;a.download=type+"-template.csv";a.click();URL.revokeObjectURL(url);
      }catch(error){toast(error.message,"error");}
    };
    el("csv-form").addEventListener("submit",event=>{
      event.preventDefault();
      busy(el("csv-submit"),async()=>{
        const file=el("csv-file").files[0];if(!file)throw Error("Chọn file CSV.");
        if(file.size>2*1024*1024)throw Error("CSV vượt giới hạn 2 MB.");
        const form=new FormData();form.append("entity_type",el("csv-entity").value);form.append("file",file);
        try {
          const result=await apiRequest("/catalogs/import-csv",{method:"POST",body:form});
          el("csv-results").textContent="Đã tạo "+result.created_count+" dòng; bỏ qua "+result.skipped_count+" dòng trùng; lỗi "+result.error_count+".";
          await loadProducts();await loadFarms();renderStats();
        }catch(error){
          el("csv-results").textContent=error.message + (error.detail?.errors ? "\nĐã tạo 0 dòng; số dòng có lỗi: " + new Set(error.detail.errors.map(e=>e.row)).size + ".\n" + error.detail.errors.map(e=>"Dòng "+e.row+", cột "+e.column+": "+e.message).join("\n") : "");
          throw error;
        }
      });
    });
    addRow();addRow();
  });
  window.phaseCUi={load,reset,canOpen};
})();
