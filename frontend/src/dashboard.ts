/**
 * Ambient edge readouts + full dashboard overlay.
 * Populates the corner HUD around the orb and a one-place dashboard that opens
 * on demand, wired to the live backend endpoints.
 */

function $(id: string): HTMLElement | null {
  return document.getElementById(id);
}
function setText(id: string, text: string) {
  const el = $(id);
  if (el) el.textContent = text;
}

async function getJSON<T>(url: string): Promise<T | null> {
  try {
    const r = await fetch(url);
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  }
}

const DAY = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const p2 = (n: number) => (n < 10 ? "0" : "") + n;

function tickClock() {
  const d = new Date();
  const time = `${p2(d.getHours())}:${p2(d.getMinutes())}:${p2(d.getSeconds())}`;
  setText("hud-time", time);
  setText("hud-date", `${DAY[d.getDay()]} ${p2(d.getDate())} ${MON[d.getMonth()]} ${d.getFullYear()}`);
  setText("dash-clock", time);
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function esc(s: any): string {
  return String(s ?? "").replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c] || c));
}

interface Ctx {
  weather?: string; calendar?: string; mail?: string;
  events?: Array<{ title?: string; time?: string; start?: string; location?: string }>;
  next_event?: { title?: string; time?: string } | null;
  unread_count?: number;
  tasks?: Array<{ title?: string; priority?: string; due_date?: string }>;
}
interface Status {
  memory_count?: number; task_count?: number; uptime_seconds?: number;
  claude_code_installed?: boolean; calendar_accessible?: boolean; mail_accessible?: boolean;
  env_keys_set?: { llm_provider?: string; voice_engine?: string };
}
interface Usage { today?: { cost_usd?: number; api_calls?: number; tts_calls?: number } }
interface Projects { projects?: Array<{ name?: string; branch?: string }> }

function fmtUptime(s?: number): string {
  if (!s) return "—";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

async function refresh() {
  const [ctx, status, usage, projects] = await Promise.all([
    getJSON<Ctx>("/api/context"),
    getJSON<Status>("/api/settings/status"),
    getJSON<Usage>("/api/usage"),
    getJSON<Projects>("/api/projects"),
  ]);

  // ---- edge readouts ----
  if (status?.env_keys_set) {
    setText("prov-label", status.env_keys_set.llm_provider || "—");
    setText("voice-label", status.env_keys_set.voice_engine || "—");
  }
  if (status) {
    setText("m-tasks", String(status.task_count ?? 0));
    setText("m-mem", String(status.memory_count ?? 0));
  }
  if (ctx) {
    setText("m-mail", String(ctx.unread_count ?? 0));
    // weather string is like "Clear, 31°F ..." — show first clause
    const w = (ctx.weather || "").split(".")[0].trim();
    setText("hud-weather", w || "—");
    const ne = ctx.next_event;
    setText("hud-next", ne?.title ? `NEXT · ${esc(ne.time || "")} ${esc(ne.title)}`.trim() : "no events today");
  }

  // ---- dashboard cards ----
  // Schedule
  if (ctx) {
    const ev = ctx.events || [];
    setText("dash-sched-count", ev.length ? `${ev.length}` : "");
    const sched = $("dash-schedule");
    if (sched) {
      sched.innerHTML = ev.length
        ? ev.map((e) => `<div class="row"><span class="t">${esc(e.time || e.start || "")}</span><span>${esc(e.title || "Untitled")}${e.location ? ` <span class="muted">· ${esc(e.location)}</span>` : ""}</span></div>`).join("")
        : `<span class="muted">Nothing scheduled today.</span>`;
    }
    // Mail
    setText("dash-mail-count", ctx.unread_count != null ? `${ctx.unread_count} unread` : "");
    const mail = $("dash-mail");
    if (mail) mail.innerHTML = `<div class="big">${ctx.unread_count ?? 0}</div><div class="muted">${esc((ctx.mail || "").split("\n")[0] || "unread messages")}</div>`;
    // Tasks
    const tk = ctx.tasks || [];
    setText("dash-task-count", tk.length ? `${tk.length} open` : "");
    const tasks = $("dash-tasks");
    if (tasks) {
      tasks.innerHTML = tk.length
        ? tk.slice(0, 12).map((t) => `<div class="row"><span class="t">${esc((t.priority || "").slice(0, 3).toUpperCase() || "·")}</span><span>${esc(t.title || "")}${t.due_date ? ` <span class="muted">· ${esc(t.due_date)}</span>` : ""}</span></div>`).join("")
        : `<span class="muted">No open tasks.</span>`;
    }
    // Weather
    const wx = $("dash-weather");
    if (wx) wx.innerHTML = ctx.weather ? esc(ctx.weather) : `<span class="muted">Unavailable.</span>`;
  }
  // Projects
  if (projects) {
    const pr = projects.projects || [];
    setText("dash-proj-count", pr.length ? `${pr.length}` : "");
    const el = $("dash-projects");
    if (el) el.innerHTML = pr.length
      ? pr.map((p) => `<div class="row"><span>${esc(p.name)}</span><span class="muted">${esc(p.branch || "")}</span></div>`).join("")
      : `<span class="muted">No projects found.</span>`;
  }
  // System
  const sys = $("dash-system");
  if (sys && status) {
    const cost = usage?.today?.cost_usd ?? 0;
    sys.innerHTML = [
      `<div class="row"><span>Brain</span><span class="muted">${esc(status.env_keys_set?.llm_provider || "—")}</span></div>`,
      `<div class="row"><span>Voice</span><span class="muted">${esc(status.env_keys_set?.voice_engine || "—")}</span></div>`,
      `<div class="row"><span>Claude Code</span><span class="muted">${status.claude_code_installed ? "ready" : "off"}</span></div>`,
      `<div class="row"><span>Calendar / Mail</span><span class="muted">${status.calendar_accessible ? "✓" : "✕"} / ${status.mail_accessible ? "✓" : "✕"}</span></div>`,
      `<div class="row"><span>Memory records</span><span class="muted">${status.memory_count ?? 0}</span></div>`,
      `<div class="row"><span>Uptime</span><span class="muted">${fmtUptime(status.uptime_seconds)}</span></div>`,
      `<div class="row"><span>Cost today</span><span class="muted">$${cost.toFixed(4)}</span></div>`,
    ].join("");
  }
}

export function setConnState(connected: boolean, label?: string) {
  const dot = $("dot-conn");
  if (dot) dot.classList.toggle("off", !connected);
  setText("conn-label", label || (connected ? "online" : "offline"));
}

export function initDashboard() {
  tickClock();
  setInterval(tickClock, 1000);
  refresh();
  setInterval(refresh, 30000);

  const dash = $("dashboard");
  const open = () => { dash?.classList.remove("dash-hidden"); refresh(); };
  const close = () => dash?.classList.add("dash-hidden");
  $("btn-dashboard")?.addEventListener("click", open);
  $("btn-dash-close")?.addEventListener("click", close);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
}
