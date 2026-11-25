"use strict";
let credentials = null;
let sessionId = null;
const $ = (selector) => document.querySelector(selector);
const notice = (text) => { $("#notice").textContent = text; };
const node = (tag, text, cls) => { const el = document.createElement(tag); el.textContent = text; if (cls) el.className = cls; return el; };

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (credentials) headers.set("Authorization", `Basic ${credentials}`);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { message = (await response.json()).message || message; } catch (_) { /* non-JSON response */ }
    throw new Error(message);
  }
  return response.status === 204 ? null : response.json();
}
function guarded(fn) { return async (...args) => { try { notice(""); await fn(...args); } catch (e) { notice(e.message); } }; }

async function loadMenu() {
  const params = new URLSearchParams(new FormData($("#filters")));
  for (const [k, v] of [...params]) if (!v) params.delete(k);
  const items = await api(`/api/menu_items?${params}`);
  const target = $("#menu"); target.replaceChildren();
  for (const item of items) {
    const card = node("article", "", "card");
    card.append(node("strong", item.title), node("p", `${item.category} · ${item.vegetarian ? "Vegetarian" : "Non-vegetarian"}`),
      node("p", `₹${item.price} · ${item.capacity} portions available`));
    const qty = document.createElement("input"); qty.type = "number"; qty.min = "1"; qty.max = "10"; qty.value = "1";
    qty.setAttribute("aria-label", `Quantity for ${item.title}`);
    const buy = node("button", "Order");
    buy.addEventListener("click", guarded(async () => {
      if (!credentials) throw new Error("Sign in to place an order");
      if (!qty.reportValidity()) return;
      const order = await api("/api/orders", {method:"POST", headers:{"Idempotency-Key":crypto.randomUUID()},
        body: JSON.stringify({lines:[{item_id:item.id, quantity:Number(qty.value)}]})});
      notice(`Order #${order.id} created.`); await loadMenu(); await loadOrders();
    }));
    card.append(qty, buy); target.append(card);
  }
}
async function loadOrders() {
  if (!credentials) throw new Error("Sign in to view orders");
  const orders = await api("/api/orders"); const target = $("#orders"); target.replaceChildren();
  for (const order of orders) {
    const row = node("div", `Order #${order.id} · ${order.status} · ₹${order.total} `, "card");
    row.append(node("p", order.lines.map(l => `Item #${l.item_id}: ${l.quantity} × ₹${l.unit_price}`).join(", ")));
    if (order.status === "CONFIRMED") {
      const cancel = node("button", "Cancel order");
      cancel.addEventListener("click", guarded(async () => {
        if (!window.confirm(`Cancel order #${order.id}?`)) return;
        await api(`/api/orders/${order.id}/cancel`, {method:"POST"}); await loadOrders(); await loadMenu();
      }));
      row.append(cancel);
    }
    target.append(row);
  }
}
async function loadSessions(selected = sessionId) {
  const sessions = await api("/api/chat/sessions"); const select = $("#sessions"); select.replaceChildren();
  for (const s of sessions) { const opt = node("option", `${s.title} (#${s.id})`); opt.value = s.id; select.append(opt); }
  sessionId = sessions.some(s => s.id === selected) ? selected : sessions[0]?.id || null;
  select.value = sessionId || "";
  if (sessionId) await loadMessages(); else { $("#messages").replaceChildren(); $("#actions").replaceChildren(); }
}
async function loadMessages() {
  let after = 0, result, all = [];
  do {
    result = await api(`/api/chat/sessions/${sessionId}/messages?limit=100&after=${after}`);
    all.push(...result.messages);
    if (result.messages.length) after = result.messages[result.messages.length - 1].seq_no;
  } while (result.messages.length === 100);
  const target = $("#messages"); target.replaceChildren();
  for (const m of all) {
    const entry = node("div", `${m.role === "user" ? "You" : "Assistant"}${m.details.mode ? ` (${m.details.mode})` : ""}: ${m.content}`, `message ${m.role}`);
    for (const c of m.details.citations || []) entry.append(node("div", `Source: ${c.filename}, ${c.page}, chunk ${c.chunk_id}`, "source"));
    target.append(entry);
  }
  const actions = $("#actions"); actions.replaceChildren();
  for (const action of result.actions.filter(a => a.status === "PENDING")) {
    const box = node("div", `Pending ${action.action.toLowerCase()} #${action.id} (expires ${action.expires_at} UTC): ${JSON.stringify(action.payload)}`, "action");
    for (const [label, confirm] of [["Confirm", true], ["Reject", false]]) {
      const button = node("button", label);
      button.addEventListener("click", guarded(async () => {
        await api(`/api/chat/actions/${action.id}/confirm`, {method:"POST", body:JSON.stringify({confirm})});
        await loadMessages(); await loadMenu(); await loadOrders();
      }));
      box.append(button);
    }
    actions.append(box);
  }
}
$("#filters").addEventListener("submit", guarded(async e => { e.preventDefault(); await loadMenu(); }));
$("#login").addEventListener("submit", guarded(async e => {
  e.preventDefault(); const f = new FormData(e.target);
  credentials = btoa(`${f.get("username")}:${f.get("password")}`);
  try { await loadOrders(); await loadSessions(); } catch (err) { credentials = null; throw err; }
  e.target.elements.password.value = ""; notice("Signed in. Credentials are kept in memory only.");
}));
$("#logout").addEventListener("click", () => { credentials = null; sessionId = null; $("#orders").replaceChildren(); $("#messages").replaceChildren(); $("#actions").replaceChildren(); $("#sessions").replaceChildren(); notice("Signed out."); });
$("#refresh-orders").addEventListener("click", guarded(loadOrders));
$("#new-chat").addEventListener("click", guarded(async () => {
  if (!credentials) throw new Error("Sign in to start a chat");
  const s = await api("/api/chat/sessions", {method:"POST", body:JSON.stringify({title:"Food assistant"})}); await loadSessions(s.id);
}));
$("#sessions").addEventListener("change", guarded(async e => { sessionId = Number(e.target.value); await loadMessages(); }));
$("#chat-form").addEventListener("submit", guarded(async e => {
  e.preventDefault(); if (!sessionId) throw new Error("Start a chat first");
  const button = e.target.querySelector("button"); button.disabled = true; button.textContent = "Thinking…";
  try { await api(`/api/chat/sessions/${sessionId}/messages`, {method:"POST", body:JSON.stringify({message:$("#chat-input").value})}); $("#chat-input").value = ""; }
  finally { button.disabled = false; button.textContent = "Send"; await loadMessages(); }
}));
$("#item-form").addEventListener("submit", guarded(async e => {
  e.preventDefault(); const f = new FormData(e.target), id = f.get("id");
  await api(`/api/menu_items${id ? `/${id}` : ""}`, {method:id ? "PUT" : "POST", body:JSON.stringify({
    title:f.get("title"), category:f.get("category"), price:f.get("price"), capacity:Number(f.get("capacity")),
    vegetarian:f.has("vegetarian"), active:f.has("active")})}); notice("Menu item saved."); await loadMenu();
}));
$("#status-form").addEventListener("submit", guarded(async e => {
  e.preventDefault(); const f = new FormData(e.target);
  await api(`/api/admin/orders/${f.get("id")}/status`, {method:"PATCH", body:JSON.stringify({status:f.get("status")})}); notice("Order status updated.");
}));
$("#upload-form").addEventListener("submit", guarded(async e => {
  e.preventDefault(); const result = await api("/api/documents", {method:"POST", body:new FormData(e.target)}); notice(`Indexed ${result.filename}, ${result.chunks} chunks.`);
}));
loadMenu().catch(e => notice(e.message));
