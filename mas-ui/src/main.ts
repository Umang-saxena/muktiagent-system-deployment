import "./style.css";
import { API_URL, listTasks, startRun, type Task, type TaskStatus } from "./api";

const POLL_MS = 3000;
const SESSION_KEY = "mas-session-started-at";
const STATUSES: TaskStatus[] = ["PENDING", "PROCESSING", "COMPLETED", "FAILED"];

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const runsEl = $<HTMLUListElement>("runs");
const emptyEl = $("empty");
const errorEl = $("error");
const summaryEl = $("summary");
const sessionLabel = $("session-label");
const showAll = $<HTMLInputElement>("show-all");
const form = $<HTMLFormElement>("trigger");
const topicInput = $<HTMLInputElement>("topic");
const triggerBtn = $<HTMLButtonElement>("trigger-btn");

interface Row {
  el: HTMLLIElement;
  status: HTMLSpanElement;
  age: HTMLSpanElement;
  body: HTMLDivElement;
  renderedResult: string | null | undefined;
  task: Task;
}

const rows = new Map<string, Row>();
const expanded = new Set<string>();
let timer: number | undefined;

function sessionStart(): string {
  let started = sessionStorage.getItem(SESSION_KEY);
  if (!started) {
    started = new Date().toISOString();
    sessionStorage.setItem(SESSION_KEY, started);
  }
  return started;
}

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatDuration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  return m ? `${m}m ${s % 60}s` : `${s}s`;
}

function ageText(task: Task): string {
  const created = new Date(task.created_at);
  const time = created.toLocaleTimeString();
  if (task.status === "PENDING" || task.status === "PROCESSING") {
    return `${time} · ${formatDuration(Date.now() - created.getTime())} so far`;
  }
  return time;
}

function splitResult(result: string): { article: string; imageUrl: string | null } {
  const match = result.match(/Image URL:\s*(\S+)/i);
  if (!match) return { article: result.trim(), imageUrl: null };
  const imageUrl = match[1].replace(/[)\].,'"`]+$/, "");
  return { article: result.replace(match[0], "").trim(), imageUrl };
}

function renderBody(row: Row): void {
  const { task, body } = row;
  body.replaceChildren();

  const meta = el("p", "meta");
  meta.append(el("span", "muted", "Task id "), el("code", undefined, task.task_id));
  body.append(meta);

  if (!task.result) {
    body.append(el("p", "muted", task.status === "PENDING" ? "Waiting for a worker…" : "Agents are working…"));
    return;
  }

  if (task.status === "FAILED") {
    body.append(el("pre", "failure", task.result));
    return;
  }

  const { article, imageUrl } = splitResult(task.result);
  if (imageUrl) {
    const link = el("a");
    link.href = imageUrl;
    link.target = "_blank";
    link.rel = "noreferrer";
    const img = el("img", "hero");
    img.src = imageUrl;
    img.alt = `Featured image for ${task.topic}`;
    img.loading = "lazy";
    link.append(img);
    body.append(link);
  }
  body.append(el("div", "article", article));
}

function createRow(task: Task): Row {
  const li = el("li", "run");
  const head = el("button", "run-head");
  head.type = "button";
  const status = el("span", "badge");
  const topic = el("span", "topic", task.topic);
  const age = el("span", "age muted");
  head.append(status, topic, age);
  const body = el("div", "run-body");
  li.append(head, body);

  const row: Row = { el: li, status, age, body, renderedResult: undefined, task };
  head.addEventListener("click", () => {
    if (expanded.has(task.task_id)) expanded.delete(task.task_id);
    else expanded.add(task.task_id);
    updateRow(row, row.task);
  });
  return row;
}

function updateRow(row: Row, task: Task): void {
  row.task = task;
  row.status.textContent = task.status;
  row.status.dataset.status = task.status;
  row.el.dataset.status = task.status;
  row.age.textContent = ageText(task);

  const open = expanded.has(task.task_id);
  row.el.classList.toggle("open", open);
  row.body.hidden = !open;
  const key = open ? `${task.status}:${task.result}` : undefined;
  if (open && key !== row.renderedResult) {
    renderBody(row);
    row.renderedResult = key;
  }
}

function renderSummary(tasks: Task[]): void {
  summaryEl.replaceChildren(
    ...STATUSES.map((s) => {
      const chip = el("span", "chip");
      chip.dataset.status = s;
      chip.append(el("strong", undefined, String(tasks.filter((t) => t.status === s).length)), ` ${s.toLowerCase()}`);
      return chip;
    }),
  );
}

function render(tasks: Task[]): void {
  const seen = new Set<string>();
  tasks.forEach((task, i) => {
    seen.add(task.task_id);
    let row = rows.get(task.task_id);
    if (!row) {
      row = createRow(task);
      rows.set(task.task_id, row);
    }
    updateRow(row, task);
    if (runsEl.children[i] !== row.el) runsEl.insertBefore(row.el, runsEl.children[i] ?? null);
  });
  for (const [id, row] of rows) {
    if (!seen.has(id)) {
      row.el.remove();
      rows.delete(id);
    }
  }
  renderSummary(tasks);
  emptyEl.hidden = tasks.length > 0;
  emptyEl.textContent = showAll.checked ? "No runs yet." : "No runs in this session yet.";
}

function showError(message: string | null): void {
  errorEl.hidden = !message;
  errorEl.textContent = message ?? "";
}

async function refresh(): Promise<void> {
  try {
    const tasks = await listTasks(showAll.checked ? null : sessionStart());
    render(tasks);
    showError(null);
  } catch (err) {
    showError(`Cannot reach the API at ${API_URL}. Is the stack running? (${(err as Error).message})`);
  }
}

function schedule(): void {
  window.clearTimeout(timer);
  if (document.hidden) return;
  timer = window.setTimeout(async () => {
    await refresh();
    schedule();
  }, POLL_MS);
}

function updateSessionLabel(): void {
  sessionLabel.textContent = `Session started ${new Date(sessionStart()).toLocaleString()} · API ${API_URL}`;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const topic = topicInput.value.trim();
  if (!topic) return;
  triggerBtn.disabled = true;
  try {
    const { task_id } = await startRun(topic);
    expanded.add(task_id);
    topicInput.value = "";
    await refresh();
  } catch (err) {
    showError(`Could not start the run: ${(err as Error).message}`);
  } finally {
    triggerBtn.disabled = false;
  }
});

showAll.addEventListener("change", () => void refresh());

$("new-session").addEventListener("click", () => {
  sessionStorage.setItem(SESSION_KEY, new Date().toISOString());
  expanded.clear();
  updateSessionLabel();
  void refresh();
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) void refresh();
  schedule();
});

updateSessionLabel();
void refresh().then(schedule);
