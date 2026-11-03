(function () {
  "use strict";
  const data = JSON.parse(document.getElementById("travel-data").textContent);
  const $ = id => document.getElementById(id);
  const places = new Map(data.places.map(p => [p.id, p]));
  const activities = new Map(data.activities.map(a => [a.id, a]));
  const routes = new Map(data.routes.map(r => [r.id, r]));
  const mapRoutes = new Map(data.map.routes.map(r => [r.id, r]));
  const days = [...data.days].sort((a,b) => a.date.localeCompare(b.date));
  const colors = ["#426951", "#af6340", "#376c9e", "#8a5c9d", "#9d7a21"];
  const modes = {rail:"铁路",drive:"驾车",walk:"步行",taxi:"打车",bus:"公交",shuttle:"景区接驳",cable_car:"索道",elevator:"景区电梯",boat:"游船"};
  const format = value => value === null ? "待核实" : new Intl.NumberFormat("zh-CN", {style:"currency",currency:data.currency}).format(value / 100);
  const time = value => value ? new Intl.DateTimeFormat("zh-CN", {hour:"2-digit",minute:"2-digit",timeZone:data.timezone,hour12:false}).format(new Date(value)) : "时间待定";
  function node(tag, text, className) { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; }
  function safeUrl(value) { try { const u = new URL(value); return ["https:","http:"].includes(u.protocol) && !u.username && !u.password ? u.href : null; } catch (_) { return null; } }
  function link(label, url) { const address = safeUrl(url); if (!address) return node("span", label + "（入口待核实）"); const el = node("a",label); el.href=address; el.target="_blank"; el.rel="noopener noreferrer"; return el; }
  function selectedDays() { return days.filter(d => $("day-filter").value === "all" || d.id === $("day-filter").value); }
  function pointOrder(day) {
    const result = [], seen = new Set();
    function add(id) { if (!seen.has(id)) { seen.add(id); result.push(id); } }
    add(day.start_place_id);
    const events = [...day.route_ids.map(id => ({...routes.get(id), route:true})), ...day.activity_ids.map(id => activities.get(id))];
    events.sort((a,b) => new Date(a.depart_at || a.start_at) - new Date(b.depart_at || b.start_at));
    events.forEach(e => { if (e.route) { add(e.from_place_id); add(e.to_place_id); } else add(e.place_id); });
    add(day.end_place_id); return result;
  }
  document.title = data.title;
  $("trip-title").textContent = data.title;
  $("trip-meta").textContent = `修订 ${data.revision} · ${days[0]?.date || ""} — ${days.at(-1)?.date || ""} · ${data.timezone}`;
  $("footer-version").textContent = `生成于 ${data.generated_at} · 修订 ${data.revision} · ${data.data_mode === "mock" ? "模拟数据，仅用于功能测试" : "以各项证据状态为准，出发前复核"}`;
  [data.data_mode === "mock" ? "模拟旅行 · 非真实报价" : "已确认计划", `预算目标 ${format(data.total_minor)}`, `报价已知小计 ${format(data.budget.known_subtotal_minor)}`, `待核实 ${data.pending.length} 项`].forEach(text => $("summary").append(node("span",text)));
  document.body.dataset.theme = data.theme;
  $("theme").value = data.theme;
  $("theme").addEventListener("change", () => { document.body.dataset.theme = $("theme").value; if (map) map.resize(); });
  const all = node("option", "整趟旅行"); all.value = "all"; $("day-filter").append(all);
  days.forEach((day,i) => { const option=node("option",`第 ${i+1} 天 · ${day.date}`); option.value=day.id; $("day-filter").append(option); });
  function renderDays() {
    $("days").replaceChildren(); $("map-points").replaceChildren();
    selectedDays().forEach(day => {
      const di=days.indexOf(day), block=node("article",undefined,"day");
      block.append(node("h3",`第 ${di+1} 天 · ${day.date}`));
      block.append(node("p",`步行 ${day.walking_km === null ? "待核实" : day.walking_km+" km"} · 驾驶 ${day.driving_minutes === null ? "待核实" : day.driving_minutes+" 分钟"}`));
      const events=[...day.activity_ids.map(id => ({...activities.get(id),kind:"activity"})),...day.route_ids.map(id => ({...routes.get(id),kind:"route"}))];
      events.sort((a,b) => new Date(a.start_at || a.depart_at) - new Date(b.start_at || b.depart_at));
      events.forEach(event => {
        const card=node("div",undefined,"stop");
        if (event.kind === "activity") {
          const p=places.get(event.place_id);
          card.append(node("div",`${time(event.start_at)} — ${time(event.end_at)}`,"time"),node("h4",event.label));
          if(p.recommendation_reason) card.append(node("p",p.recommendation_reason));
          (event.notes || []).forEach(text => card.append(node("p",text)));
          if(p.introduction_url) card.append(link("景点介绍",p.introduction_url));
          if(p.photo && safeUrl(p.photo.url)) {
            const img=node("img"); img.className="photo"; img.alt=p.photo.caption; img.loading="lazy"; img.src=safeUrl(p.photo.url);
            img.addEventListener("error",() => { img.replaceWith(node("p","实景照片暂不可用，请打开介绍或图片来源。")); },{once:true});
            card.append(img,link("图片来源 · "+p.photo.caption,p.photo.source_url));
          }
        } else {
          card.append(node("div",`${time(event.depart_at)} · ${modes[event.mode] || event.mode}`,"time"));
          card.append(node("h4",`${places.get(event.from_place_id).name} → ${places.get(event.to_place_id).name}`));
          const buffer=event.buffers.reduce((sum,b) => sum+b.minutes,0);
          card.append(node("p",`路段 ${event.duration_minutes === null ? "耗时待核实" : event.duration_minutes+" 分钟"}，另留缓冲 ${buffer} 分钟 · ${event.evidence === "verified" ? "有耗时证据" : "耗时待复核"}`));
          if(event.navigation_url) card.append(link("打开导航",event.navigation_url));
          if(event.operating_window?.last_departure_at) card.append(node("p",`末班限制 ${time(event.operating_window.last_departure_at)}`));
          event.buffers.forEach(b => card.append(node("p",`${b.label}：${b.minutes} 分钟；${b.reason}`)));
        }
        block.append(card);
      });
      data.scenic_visits.filter(v => v.day_id === day.id).forEach(visit => {
        const group=node("div",undefined,"scenic");
        group.append(node("h4",places.get(visit.scenic_place_id).name+" · 园内路线"));
        group.append(node("p",`入口：${places.get(visit.entry_place_id).name}；出口：${places.get(visit.exit_place_id).name}`));
        const sequence=node("ol"); visit.route_ids.forEach(id => {const r=routes.get(id);sequence.append(node("li",`${places.get(r.from_place_id).name} → ${places.get(r.to_place_id).name} · ${modes[r.mode] || r.mode}`));});group.append(sequence);
        visit.notes.forEach(text => group.append(node("p",text)));
        if(visit.alternatives.length) group.append(node("p","缩短／替代安排："+visit.alternatives.join("；")));
        block.append(group);
      });
      (day.rest_notes || []).forEach(text => block.append(node("p",text)));
      $("days").append(block);
      const points=node("div",undefined,"map-day"); points.style.borderLeftColor=colors[di%colors.length];
      points.append(node("h3",`第 ${di+1} 天 · ${day.date}`));
      pointOrder(day).forEach((id,i) => {const p=places.get(id);const label=node("span",`${di+1}.${i+1} ${p.name}${data.map.points[id] ? "" : "（坐标待核实）"}`,"map-point");points.append(label);});
      $("map-points").append(points);
    });
    if (map) drawMap();
  }
  let map=null, mapLoading=false;
  function drawMap() {
    map.clearMap(); let drawn=0;
    selectedDays().forEach(day => {
      const di=days.indexOf(day), color=colors[di%colors.length];
      pointOrder(day).forEach((id,i) => {
        const pos=data.map.points[id]; if(!pos) return;
        const badge=node("div",`${di+1}.${i+1}`,"map-marker");badge.style.backgroundColor=color;
        const marker=new AMap.Marker({position:pos,title:places.get(id).name,content:badge,anchor:"bottom-center"});
        marker.on("click",()=>{
          const content=node("div");content.append(node("strong",places.get(id).name));
          const p=places.get(id);if(p.recommendation_reason)content.append(node("p",p.recommendation_reason));
          day.activity_ids.map(aid=>activities.get(aid)).filter(a=>a.place_id===id).forEach(a=>content.append(node("p",`${time(a.start_at)} — ${time(a.end_at)} · ${a.label}`)));
          day.route_ids.map(rid=>routes.get(rid)).filter(r=>r.from_place_id===id || r.to_place_id===id).forEach(r=>{
            content.append(node("p",`${time(r.depart_at)} · ${modes[r.mode] || r.mode} · ${places.get(r.from_place_id).name} → ${places.get(r.to_place_id).name}`));
            if(r.navigation_url)content.append(link("打开该段导航",r.navigation_url));
          });
          if(p.introduction_url)content.append(link("景点介绍",p.introduction_url));
          new AMap.InfoWindow({content,offset:new AMap.Pixel(0,-32)}).open(map,pos);
        });map.add(marker);drawn++;
      });
      day.route_ids.forEach(id => {const r=mapRoutes.get(id);if(!r?.coordinates)return;map.add(new AMap.Polyline({path:r.coordinates,strokeColor:color,strokeWeight:4,strokeOpacity:.85,strokeStyle:r.kind === "actual" ? "solid" : "dashed",showDir:r.kind === "actual"}));});
    });
    if(drawn)map.setFitView();
    $("map-status").textContent=drawn ? `已显示 ${drawn} 个地点标记。请结合虚线说明与精度缺口使用。` : "当前日期缺少已确认坐标，地图暂不能标点；请查看地点列表。";
  }
  $("map-status").textContent=data.map_config ? "地图按需联网加载；行程与预算无需加载地图即可使用。" : "尚未配置网页地图接入，互动地图未完成；下方保留地点顺序和导航入口。";
  $("load-map").disabled=!data.map_config;
  $("load-map").addEventListener("click",()=>{
    if(map || mapLoading)return;mapLoading=true;$("load-map").disabled=true;
    $("map-status").textContent="正在加载地图…";
    window._AMapSecurityConfig={serviceHost:data.map_config.service_host};
    const script=node("script");script.src="https://webapi.amap.com/maps?v=2.0&key="+encodeURIComponent(data.map_config.amap_key);
    let done=false;
    const failed=()=>{if(done)return;done=true;clearTimeout(timer);if(map){map.destroy();map=null;}script.remove();mapLoading=false;$("load-map").disabled=false;$("map-status").textContent="地图加载失败，互动地图尚未完成；可检查接入配置或网络后重试，或继续使用地点列表与导航。";$("map-status").className="error";};
    const timer=setTimeout(failed,15000);script.onerror=failed;
    script.onload=()=>{if(done)return;try{if(!window.AMap)throw new Error("SDK unavailable");$("map-canvas").style.display="block";map=new AMap.Map("map-canvas",{viewMode:"2D",zoom:10});map.on("complete",()=>{if(done)return;done=true;clearTimeout(timer);drawMap();});}catch(_){failed();}};
    document.head.append(script);
  });
  $("day-filter").addEventListener("change",renderDays);
  renderDays();
  data.map.pending.forEach(text=>$("map-pending").append(node("li",text)));
  if(!data.map.pending.length)$("map-pending").append(node("li","数据中未发现路径或位置缺口；仍需完成真实地图加载与路线验收。"));
  data.pending.forEach(item=>$("pending").append(node("li",`${item.target_id}：${item.message}`)));
  if(!data.pending.length)$("pending").append(node("li","暂无已记录事项；出发前仍需复核价格、开放与交通。"));
  data.sources.forEach(source=>{const li=node("li");li.append(link(source.provider,source.url),node("span",` · 查询于 ${source.queried_at || "待核实"}`));$("sources").append(li);});

  let budgetItems=structuredClone(data.budget_plan.items), rowControls=[];
  const amountText=value=>value===null ? "" : (value/100).toFixed(2);
  function amountInput(value,label,disabled=false) { const input=node("input");input.type="number";input.min="0";input.max="10000000000";input.step="0.01";input.value=amountText(value);input.disabled=disabled;input.setAttribute("aria-label",label);return input; }
  function parseAmount(input, nullable=false) { if(input.value==="" && nullable)return null;if(!input.validity.valid || !/^\d+(\.\d{1,2})?$/.test(input.value))throw new Error("金额请填写非负数字，最多两位小数");const parts=input.value.split(".");const value=Number(parts[0])*100+Number((parts[1]||"").padEnd(2,"0"));if(!Number.isSafeInteger(value)||value>1000000000000)throw new Error("金额超出支持范围");return value; }
  $("total").value=amountText(data.total_minor);$("reserve").value=amountText(data.budget_plan.reserve_minor);
  function buildBudgetRows() {
    $("budget-rows").replaceChildren();rowControls=[];
    budgetItems.forEach((item,index)=>{
      const tr=node("tr"), label=node("input");label.type="text";label.value=item.label;label.disabled=item.protected;label.setAttribute("aria-label","支出项目名称");
      const amount=amountInput(item.amount_minor,item.label+"已知金额",item.protected), low=amountInput(item.minimum_minor,item.label+"最低额度",item.protected), high=amountInput(item.maximum_minor,item.label+"最高额度",item.protected);
      const weight=node("input");weight.type="number";weight.min="1";weight.max="1000";weight.step="1";weight.value=item.weight;weight.disabled=item.protected;weight.setAttribute("aria-label",item.label+"分配权重");
      const locked=node("input");locked.type="checkbox";locked.checked=item.locked;locked.disabled=item.protected;locked.setAttribute("aria-label",item.label+"保持不变");
      const result=node("td");
      [label,amount,low,high,weight,locked].forEach(control=>{const td=node("td");td.append(control);tr.append(td);});tr.append(result);
      if(item.protected)tr.firstChild.append(node("span","已锁定／已付","badge"));
      if(!item.quote_id && !item.automatic) {const remove=node("button","删除","secondary");remove.type="button";remove.addEventListener("click",()=>{budgetItems.splice(index,1);buildBudgetRows();});tr.firstChild.append(remove);}
      rowControls.push({label,amount,low,high,weight,locked,result,item});$("budget-rows").append(tr);
    });calculate();
  }
  function currentBudget() {
    const total=parseAmount($("total"),true),reserve=parseAmount($("reserve"));
    const items=rowControls.map(c=>{if(!c.label.value.trim())throw new Error("请填写项目名称");if(!c.weight.validity.valid || !/^\d+$/.test(c.weight.value))throw new Error("权重须为 1–1000 的整数");return {...c.item,label:c.label.value.trim(),amount_minor:parseAmount(c.amount,true),minimum_minor:parseAmount(c.low),maximum_minor:parseAmount(c.high,true),weight:Number(c.weight.value),locked:c.locked.checked};});
    return {total,reserve,items};
  }
  function calculate() {
    try {
      const current=currentBudget(), result=TravelBudget.allocate(current.total,current.reserve,current.items);budgetItems=current.items;
      result.rows.forEach((row,i)=>{rowControls[i].result.textContent=format(row.allocated_minor);});
      const status={allocated:`额度已分配；未分配余额 ${format(result.unallocated_minor)}。实际候选与待核实费用仍需检查。`,over_budget:`必要支出已超预算，至少还差 ${format(result.shortfall_minor)}，请提高预算或调整允许变动的项目。`,incomplete:`有 ${result.unknown_item_ids.length} 项固定费用未知，暂不能判断是否符合预算。`,unknown_budget:"请填写双人总预算；当前仅列出费用与最低额度。"};
      $("budget-result").textContent=status[result.status];$("budget-result").className=result.fits_target ? "success" : "error";$("export-budget").disabled=false;return current;
    } catch(error) {$("budget-result").textContent=error.message;$("budget-result").className="error";$("export-budget").disabled=true;rowControls.forEach(c=>{c.result.textContent="—";});return null;}
  }
  $("budget-rows").addEventListener("input",calculate);$("total").addEventListener("input",calculate);$("reserve").addEventListener("input",calculate);
  $("add-item").addEventListener("click",()=>{if(!calculate())return;if(budgetItems.length>=200)return;let i=1;while(budgetItems.some(row=>row.id===`custom-${i}`))i++;budgetItems.push({id:`custom-${i}`,label:"新增可调支出",quote_id:null,amount_minor:null,minimum_minor:0,maximum_minor:null,weight:1,locked:false,protected:false,automatic:false});buildBudgetRows();});
  $("reset-budget").addEventListener("click",()=>{budgetItems=structuredClone(data.budget_plan.items);$("total").value=amountText(data.total_minor);$("reserve").value=amountText(data.budget_plan.reserve_minor);buildBudgetRows();});
  $("export-budget").addEventListener("click",()=>{
    const current=calculate();if(!current)return;
    const draft=TravelBudget.makeDraft(data,current.total,current.reserve,current.items);
    const url=URL.createObjectURL(new Blob([JSON.stringify(draft,null,2)],{type:"application/json"}));
    const a=node("a");a.href=url;a.download=`${data.trip_id}-budget-draft.json`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  buildBudgetRows();
})();
