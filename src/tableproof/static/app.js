"use strict";

const $ = (id) => document.getElementById(id);
const state = {xlsx: "", filename: "", revision: 0, preview: null, report: null,
  filter: "ALL", page: 0, selected: null, busy: false, tables: [], sheets: []};
const PAGE_SIZE = 50;
const labels = {PASS: "通过", FAIL: "差异", INDETERMINATE: "未知"};
let inspectTimer;

function text(element, value) { element.textContent = value == null ? "∅ 空值" : String(value); }
function display(value) { return $("hide-content").checked ? "[已隐藏]" : value == null ? "∅ 空值" : String(value); }
function error(message) { text($("error"), message); $("error").hidden = !message; }
function notice(message) { text($("notice"), message); $("notice").hidden = !message; }
function phase(message) { text($("phase"), message); }
function ready() { return state.xlsx && $("sheet").value && $("range").value.trim() && $("table-index").value !== ""; }
function controls() {
  $("preview-button").disabled = state.busy || !ready();
  $("audit-button").disabled = state.busy || !state.preview || !$("confirm").checked;
  $("demo").disabled = state.busy;
  $("empty-demo").disabled = state.busy;
  for (const id of ["export-json", "export-html"]) $(id).disabled = state.busy || !state.report;
  for (const id of ["xlsx-file", "markdown-file", "markdown", "range", "header", "confirm"]) $(id).disabled = state.busy;
  $("sheet").disabled = state.busy || !state.sheets.length;
  $("table-index").disabled = state.busy || !state.tables.length;
}
function invalidate() {
  state.revision++;
  state.preview = null;
  state.report = null;
  state.selected = null;
  $("preview-panel").hidden = true;
  $("report-panel").hidden = true;
  $("cell-detail").hidden = true;
  $("empty-state").hidden = false;
  $("confirm").checked = false;
  phase(state.xlsx ? "待预览映射" : "等待输入");
  error(""); controls();
}
function payload() {
  return {xlsx_base64: state.xlsx, markdown: $("markdown").value, sheet: $("sheet").value,
    range_ref: $("range").value.trim(), table_index: Number($("table-index").value), header: $("header").checked};
}
async function request(path, data) {
  const response = await fetch(path, data === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
  if (!response.ok) {
    let message = "本地服务未能完成请求，请检查文件后重试。";
    try { const result = await response.json(); if (typeof result.detail === "string") message = result.detail; } catch (_) { /* Preserve friendly fallback. */ }
    throw new Error(message);
  }
  return response;
}
async function task(message, action) {
  if (state.busy) return;
  state.busy = true; document.querySelector(".workspace").setAttribute("aria-busy", "true"); document.body.classList.add("busy"); error(""); phase(message); controls();
  try { await action(); }
  catch (exception) { error(exception.message || "无法连接本地服务，请确认服务仍在运行。"); phase("请检查输入"); }
  finally { state.busy = false; document.querySelector(".workspace").setAttribute("aria-busy", "false"); document.body.classList.remove("busy"); controls(); }
}
function option(select, value, label) {
  const item = document.createElement("option"); item.value = String(value); text(item, label); select.append(item);
}
async function inspect(preferred = null) {
  if (!state.xlsx) return;
  const revision = state.revision;
  const result = await (await request("/api/inspect", payload())).json();
  if (revision !== state.revision) return;
  state.sheets = result.sheets; state.tables = result.tables;
  const previousSheet = preferred?.sheet || $("sheet").value;
  const previousTable = preferred?.table_index ?? $("table-index").value;
  $("sheet").replaceChildren();
  for (const sheet of result.sheets) option($("sheet"), sheet.name, sheet.name + (sheet.hidden ? "（隐藏工作表）" : ""));
  if (result.sheets.some(sheet => sheet.name === previousSheet)) $("sheet").value = previousSheet;
  $("sheet").disabled = !result.sheets.length;
  const current = result.sheets.find(sheet => sheet.name === $("sheet").value);
  if (preferred?.range_ref) $("range").value = preferred.range_ref;
  else if (!$("range").value && current) $("range").value = current.range_ref;
  $("table-index").replaceChildren();
  for (const table of result.tables) option($("table-index"), table.index,
    `第 ${table.index + 1} 张表 · ${table.rows} 行数据 × ${table.columns} 列${table.issues.length ? " · 有限制" : ""}`);
  if (result.tables.some(table => String(table.index) === String(previousTable))) $("table-index").value = String(previousTable);
  if (!result.tables.length) option($("table-index"), "", "未检测到 Markdown 表格");
  $("table-index").disabled = !result.tables.length;
  phase(result.tables.length ? "待预览映射" : "等待 Markdown 表格");
  controls();
}
function cell(row, value, tag = "td") { const node = document.createElement(tag); text(node, value); row.append(node); return node; }
function showIssues(element, issues) {
  element.replaceChildren();
  for (const message of issues) { const line = document.createElement("div"); text(line, message); element.append(line); }
  element.hidden = !issues.length;
}
function headerHelp() {
  text($("header-help"), $("header").checked
    ? "源范围包含一行表头，对齐 Markdown 的标题行与数据行。"
    : "源范围仅包含数据，对齐 Markdown 数据行；忽略 Markdown 标题行。");
}
function showPreview(result) {
  state.preview = result;
  $("empty-state").hidden = true; $("preview-panel").hidden = false; $("report-panel").hidden = true;
  text($("dimension-badge"), result.dimensions_match ? "尺寸一致" : "尺寸不一致");
  text($("preview-scope"), `${result.sheet}!${result.range_ref} · 源 ${result.source_rows} × ${result.source_columns} → Markdown ${result.markdown_rows} × ${result.markdown_columns}`);
  text($("preview-header"), result.header ? "第一行对齐 Markdown 标题行；后续按位置逐行对应。" : "源范围只对齐 Markdown 数据行，不包含 Markdown 标题行。");
  showIssues($("preview-issues"), result.issues);
  $("preview-body").replaceChildren();
  const rowCount = Math.max(result.source_preview.length, result.markdown_preview.length);
  for (let r = 0; r < rowCount; r++) {
    const source = result.source_preview[r] || [], markdown = result.markdown_preview[r] || [];
    for (let c = 0; c < Math.max(source.length, markdown.length); c++) {
      const tr = document.createElement("tr");
      cell(tr, source[c]?.coordinate || "无对应源单元格");
      cell(tr, source[c] ? source[c].value : "— 缺少行列 —");
      cell(tr, "→"); cell(tr, c < markdown.length ? markdown[c] : "— 缺少行列 —");
      $("preview-body").append(tr);
    }
  }
  text($("preview-limit"), result.preview_limited
    ? "预览仅展示前 6 行、8 列；确认后仍会扫描与统计完整选定范围。" : "已展示选定范围的全部映射。请核对表头、行列顺序与范围。");
  $("confirm").checked = false; controls(); phase("请确认行列映射");
}
function renderTable() {
  const report = state.report; if (!report) return;
  const entries = report.cells.map((item, index) => ({item, index})).filter(entry => state.filter === "ALL" || entry.item.status === state.filter);
  const pages = Math.max(1, Math.ceil(entries.length / PAGE_SIZE));
  state.page = Math.min(state.page, pages - 1);
  $("results-body").replaceChildren();
  for (const {item, index} of entries.slice(state.page * PAGE_SIZE, (state.page + 1) * PAGE_SIZE)) {
    const tr = document.createElement("tr"); if (state.selected === index) tr.classList.add("selected");
    const coordinateCell = document.createElement("td"), button = document.createElement("button");
    button.className = "coordinate-button"; text(button, item.coordinate + " ↗");
    button.setAttribute("aria-label", `定位源单元格 ${item.coordinate}`);
    button.addEventListener("click", () => { selectCell(index); $("cell-detail").scrollIntoView({behavior: "smooth", block: "nearest"}); $("cell-detail").focus({preventScroll:true}); });
    coordinateCell.append(button); tr.append(coordinateCell);
    cell(tr, display(item.source_value)); cell(tr, display(item.markdown_value));
    const status = document.createElement("span"); status.className = "badge " + item.status; text(status, labels[item.status] || "未知");
    const statusCell = document.createElement("td"); statusCell.append(status); tr.append(statusCell);
    $("results-body").append(tr);
  }
  if (!entries.length) { const row = document.createElement("tr"), td = cell(row, report.cells.length ? "此筛选条件下没有单元格。" : "映射无法确定，未生成逐格归因。请查看结构提示。"); td.colSpan = 4; td.className = "empty-result"; $("results-body").append(row); }
  text($("result-count"), `共 ${entries.length} 条${entries.length > PAGE_SIZE ? ` · 每页 ${PAGE_SIZE} 条` : ""} · 统计覆盖完整范围`);
  text($("page-label"), `${state.page + 1} / ${pages}`);
  $("page-prev").disabled = state.page === 0; $("page-next").disabled = state.page === pages - 1;
}
function selectCell(index) {
  state.selected = index; const item = state.report.cells[index];
  if (!item) { $("cell-detail").hidden = true; return; }
  $("cell-detail").hidden = false;
  text($("detail-coordinate"), `${$("hide-content").checked ? "[已隐藏]" : state.report.scope.sheet}!${item.coordinate}`);
  $("detail-status").className = "badge " + item.status; text($("detail-status"), item.status);
  text($("detail-source"), display(item.source_value)); text($("detail-markdown"), display(item.markdown_value));
  $("detail-meta").replaceChildren();
  for (const [label, value] of [["源类型", item.source_kind], ["数字格式", display(item.number_format)], ["公式", $("hide-content").checked ? "[已隐藏]" : item.formula || "无公式"]]) {
    const term = document.createElement("dt"), definition = document.createElement("dd"); text(term, label); text(definition, value); $("detail-meta").append(term, definition);
  }
  text($("detail-rule"), item.rule);
  text($("detail-reason"), display(item.reason));
  text($("detail-notes"), $("hide-content").checked ? "[已隐藏]" : item.notes.join(" · "));
  renderTable();
}
function renderReport() {
  const report = state.report; if (!report) return;
  $("empty-state").hidden = true; $("preview-panel").hidden = true; $("report-panel").hidden = false;
  text($("verdict-title"), report.status === "FAIL" ? "发现可以确认的转换差异" : report.status === "PASS" ? "选定范围验证通过" : "仍有无法验证的内容");
  $("verdict").className = "verdict " + report.status; text($("verdict"), report.status);
  text($("report-scope"), `${$("hide-content").checked ? "[已隐藏]" : report.scope.sheet}!${report.scope.range_ref} · Markdown 表 ${report.scope.table_index + 1} · ${report.scope.header ? "含一行表头" : "仅数据行"}`);
  for (const key of ["total", "passed", "failed", "indeterminate"]) text($("count-" + key), report.summary[key]);
  showIssues($("report-issues"), $("hide-content").checked ? report.issues.map(() => "[提示内容已隐藏]") : report.issues);
  renderTable(); if (state.selected !== null) selectCell(state.selected);
  phase("验收已完成"); controls();
}
async function loadDemo() {
  await task("正在加载合成示例…", async () => {
    const data = await (await request("/api/demo")).json();
    state.xlsx = data.xlsx_base64; state.filename = data.filename;
    text($("xlsx-label"), data.filename); $("xlsx-file").value = ""; $("markdown-file").value = "";
    $("markdown").value = data.markdown; $("header").checked = data.header;
    invalidate(); headerHelp(); notice(data.notice);
    await inspect(data);
    const revision = state.revision;
    const preview = await (await request("/api/preview", payload())).json();
    if (revision === state.revision) showPreview(preview);
  });
}

$("xlsx-file").addEventListener("change", async event => {
  const file = event.target.files[0]; if (!file) return;
  invalidate(); notice(""); state.xlsx = ""; controls();
  if (file.size > 10 * 1024 * 1024) return error("XLSX 超过 10 MiB，请选择较小的工作簿。");
  if (!file.name.toLowerCase().endsWith(".xlsx")) return error("请选择 .xlsx 文件。");
  const revision = state.revision;
  await task("正在读取工作簿…", async () => {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let encoded = ""; for (let i = 0; i < bytes.length; i += 16384) encoded += String.fromCharCode(...bytes.subarray(i, i + 16384));
    if (revision !== state.revision) return;
    state.xlsx = btoa(encoded); state.filename = file.name; text($("xlsx-label"), file.name);
    $("range").value = ""; await inspect();
  });
});
$("markdown-file").addEventListener("change", async event => {
  const file = event.target.files[0]; if (!file) return;
  if (file.size > 2 * 1024 * 1024) return error("Markdown 超过 2 MiB，请缩小文件。");
  invalidate(); notice(""); const revision = state.revision;
  await task("正在读取 Markdown…", async () => {
    const value = await file.text(); if (revision !== state.revision) return;
    $("markdown").value = value; await inspect();
  });
});
$("markdown").addEventListener("input", () => {
  invalidate(); notice(""); clearTimeout(inspectTimer);
  inspectTimer = setTimeout(() => { if (!state.busy) task("正在识别表格…", inspect); }, 450);
});
$("sheet").addEventListener("change", () => { invalidate(); const sheet = state.sheets.find(item => item.name === $("sheet").value); if (sheet) $("range").value = sheet.range_ref; controls(); });
$("table-index").addEventListener("change", invalidate);
$("range").addEventListener("input", invalidate);
$("header").addEventListener("change", () => { invalidate(); headerHelp(); });
$("confirm").addEventListener("change", controls);
$("preview-button").addEventListener("click", () => task("正在预览映射…", async () => {
  const revision = state.revision; const result = await (await request("/api/preview", payload())).json();
  if (revision === state.revision) showPreview(result);
}));
$("audit-button").addEventListener("click", () => task("正在独立验收…", async () => {
  const revision = state.revision;
  const result = await (await request("/api/audit", {...payload(), confirmed: $("confirm").checked, mapping_token: state.preview.mapping_token})).json();
  if (revision !== state.revision) return;
  state.report = result; state.filter = "ALL"; state.page = 0; state.selected = null;
  document.querySelectorAll("[data-filter]").forEach(button => (button.classList.toggle("active", button.dataset.filter === "ALL"), button.setAttribute("aria-pressed", String(button.dataset.filter === "ALL"))));
  renderReport();
}));
document.querySelectorAll("[data-filter]").forEach(button => button.addEventListener("click", () => {
  state.filter = button.dataset.filter; state.page = 0;
  document.querySelectorAll("[data-filter]").forEach(item => {
    item.classList.toggle("active", item === button);
    item.setAttribute("aria-pressed", String(item === button));
  }); renderTable();
}));
$("page-prev").addEventListener("click", () => { state.page--; renderTable(); });
$("page-next").addEventListener("click", () => { state.page++; renderTable(); });
$("hide-content").addEventListener("change", renderReport);
for (const format of ["json", "html"]) $("export-" + format).addEventListener("click", () => task("正在导出报告…", async () => {
  const response = await request(`/api/export?format=${format}&redact=${$("hide-content").checked}`, {report: state.report});
  const url = URL.createObjectURL(await response.blob()), link = document.createElement("a");
  link.href = url; link.download = `tableproof-report${$("hide-content").checked ? "-redacted" : ""}.${format}`;
  document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); phase("报告已导出");
}));
$("demo").addEventListener("click", loadDemo); $("empty-demo").addEventListener("click", loadDemo);
headerHelp(); controls();
