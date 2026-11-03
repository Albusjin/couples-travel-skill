/* Same integer allocation contract as travel_planner/allocation.py. No dependencies. */
(function (root) {
  "use strict";
  const limit = 1000000000000;
  function money(value, nullable) {
    if (nullable && value === null) return;
    if (!Number.isSafeInteger(value) || value < 0 || value > limit) throw new Error("金额须为非负整数分，且不超过支持范围");
  }
  function allocate(total, reserve, items) {
    money(total, true); money(reserve, false);
    if (!Array.isArray(items) || items.length > 200) throw new Error("支出项目不能超过 200 个");
    let fixed = 0, minimum = 0;
    const unknown = [], seen = new Set();
    const rows = items.map(item => {
      if (!item || !/^[A-Za-z0-9_-]{1,80}$/.test(item.id) || seen.has(item.id) || typeof item.label !== "string" || !item.label || typeof item.locked !== "boolean") throw new Error("支出项目无效或 ID 重复");
      seen.add(item.id);
      money(item.amount_minor, true); money(item.minimum_minor, false); money(item.maximum_minor, true);
      if (!Number.isSafeInteger(item.weight) || item.weight < 1 || item.weight > 1000) throw new Error("权重须为 1–1000 的整数");
      if (item.maximum_minor !== null && item.maximum_minor < item.minimum_minor) throw new Error("项目上限不能小于下限");
      const value = item.locked ? item.amount_minor : item.minimum_minor;
      if (item.locked) { if (value === null) unknown.push(item.id); else fixed += value; }
      else minimum += item.minimum_minor;
      return {...item, allocated_minor: value};
    });
    const required = fixed + minimum + reserve;
    let remaining = total === null ? null : Math.max(0, total - required);
    const shortfall = total === null ? null : Math.max(0, required - total);
    if (total !== null && !shortfall && !unknown.length) {
      let eligible = rows.map((_, i) => i).filter(i => !rows[i].locked && (rows[i].maximum_minor === null || rows[i].allocated_minor < rows[i].maximum_minor));
      while (remaining && eligible.length) {
        const weights = eligible.reduce((sum, i) => sum + rows[i].weight, 0), pool = remaining;
        const shares = new Map(eligible.map(i => [i, Math.floor(pool * rows[i].weight / weights)]));
        const residue = pool - [...shares.values()].reduce((a,b) => a+b, 0);
        const order = [...eligible].sort((a,b) => (pool * rows[b].weight % weights) - (pool * rows[a].weight % weights) || a-b);
        order.slice(0, residue).forEach(i => shares.set(i, shares.get(i) + 1));
        eligible.forEach(i => {
          const cap = rows[i].maximum_minor;
          const take = cap === null ? shares.get(i) : Math.min(shares.get(i), cap - rows[i].allocated_minor);
          rows[i].allocated_minor += take; remaining -= take;
        });
        eligible = eligible.filter(i => rows[i].maximum_minor === null || rows[i].allocated_minor < rows[i].maximum_minor);
      }
    }
    const status = total === null ? "unknown_budget" : shortfall ? "over_budget" : unknown.length ? "incomplete" : "allocated";
    return {status, total_minor:total, reserve_minor:reserve, fixed_minor:fixed, minimum_required_minor:required,
      shortfall_minor:shortfall, unallocated_minor:remaining, unknown_item_ids:unknown, rows,
      fits_target:status === "allocated", note:"仅为支出额度试算；不修改实际报价，不代表候选可订或全部费用已核实"};
  }
  function makeDraft(snapshot, total, reserve, items) {
    allocate(total, reserve, items);
    const fields=["id","label","quote_id","amount_minor","minimum_minor","maximum_minor","weight","locked"];
    return {format:"travel-budget-draft/1",trip_id:snapshot.trip_id,base_revision:snapshot.revision,
      base_hash:snapshot.base_hash,currency:snapshot.currency,total_minor:total,
      plan:{reserve_minor:reserve,items:items.filter(row=>!row.automatic)
        .map(row=>Object.fromEntries(fields.map(key=>[key,row[key]])))}};
  }
  root.TravelBudget = {allocate,makeDraft};
})(globalThis);
