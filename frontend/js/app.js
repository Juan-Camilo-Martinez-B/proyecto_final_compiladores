// Estado, eventos y pestanas: conecta la API con los renderers.
import { compileSource, fetchExamples, mockMode } from "./api.js";
import {
  PHASES, h, renderAssembly, renderAst, renderDiagnostics, renderExecution, renderIr,
  renderMemory, renderPipelineBar, renderSymbols, renderTokens,
} from "./renderers.js";

const RENDERERS = {
  tokens: renderTokens, ast: renderAst, symbols: renderSymbols,
  memory: renderMemory, ir: renderIr, assembly: renderAssembly, execution: renderExecution,
};
const DEFAULT_EXAMPLE = "batalla_ok.rpg";
const MOCK_EXAMPLES = { ok: "batalla_ok.rpg", errors: "estres_semantico.rpg" };
const LINE_HEIGHT = 20;

const $ = (id) => document.getElementById(id);
const ui = {
  source: $("source"), gutter: $("gutter"), examples: $("examples"), registers: $("registers"),
  compile: $("compile"), pipeline: $("pipeline"), tabs: $("tabs"), views: $("views"),
  diagnostics: $("diagnostics"), diagnosticsCount: $("diagnostics-count"), summary: $("summary"),
};

// La pestana inicial puede venir en la URL (#ast, #asm...), util para la demo.
const hashTab = window.location.hash.slice(1);
const state = {
  result: null,
  active: PHASES.some((phase) => phase.key === hashTab) ? hashTab : "tokens",
  examples: [],
  busy: false,
};
const tabButtons = new Map();
const views = new Map();

// ----------------------------------------------------------------------
// Pestanas
// ----------------------------------------------------------------------
function buildTabs() {
  for (const phase of PHASES) {
    const dot = h("span", { className: "dot" });
    const button = h("button", {
      type: "button", className: "tab", role: "tab", id: `tab-${phase.key}`,
      "aria-controls": `view-${phase.key}`, onclick: () => selectTab(phase.key),
    }, dot, phase.label);
    const view = h("div", { className: "view", role: "tabpanel", id: `view-${phase.key}`,
      "aria-labelledby": `tab-${phase.key}` },
    h("p", { className: "empty waiting", text: "Compila un programa para ver esta fase." }));
    tabButtons.set(phase.key, { button, dot });
    views.set(phase.key, view);
    ui.tabs.append(button);
    ui.views.append(view);
  }
  selectTab(state.active);
}

function selectTab(key) {
  state.active = key;
  for (const [phaseKey, { button }] of tabButtons) {
    const selected = phaseKey === key;
    button.setAttribute("aria-selected", String(selected));
    views.get(phaseKey).hidden = !selected;
  }
  renderPipelineBar(ui.pipeline, state.result?.status, { active: key, onSelect: selectTab });
}

// ----------------------------------------------------------------------
// Editor con numeros de linea
// ----------------------------------------------------------------------
function updateGutter() {
  const total = ui.source.value.split("\n").length;
  const marks = new Map();
  for (const d of state.result?.diagnostics ?? []) {
    if (d.line > 0 && marks.get(d.line) !== "error") marks.set(d.line, d.severity);
  }
  const lines = [];
  for (let line = 1; line <= total; line += 1) {
    const severity = marks.get(line);
    lines.push(h("span", { className: severity ? `has-${severity}` : "", text: line }));
  }
  ui.gutter.replaceChildren(...lines);
  ui.gutter.scrollTop = ui.source.scrollTop;
}

function selectLine(line, column = 1) {
  const lines = ui.source.value.split("\n");
  if (line < 1 || line > lines.length) return;
  let start = 0;
  for (let i = 0; i < line - 1; i += 1) start += lines[i].length + 1;
  const end = start + lines[line - 1].length;
  ui.source.focus();
  ui.source.setSelectionRange(Math.min(start + Math.max(column - 1, 0), end), end);
  ui.source.scrollTop = Math.max(0, (line - 1) * LINE_HEIGHT - ui.source.clientHeight / 3);
  ui.gutter.scrollTop = ui.source.scrollTop;
}

function handleEditorKeys(event) {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    compile();
  } else if (event.key === "Tab" && !event.shiftKey && !event.ctrlKey && !event.metaKey) {
    event.preventDefault();
    const { selectionStart, selectionEnd, value } = ui.source;
    ui.source.value = `${value.slice(0, selectionStart)}    ${value.slice(selectionEnd)}`;
    ui.source.setSelectionRange(selectionStart + 4, selectionStart + 4);
    updateGutter();
  }
}

// ----------------------------------------------------------------------
// Compilacion
// ----------------------------------------------------------------------
async function compile() {
  if (state.busy) return;
  state.busy = true;
  ui.compile.disabled = true;
  ui.compile.textContent = "Compilando…";
  try {
    const result = await compileSource(ui.source.value, Number(ui.registers.value));
    showResult(result);
  } catch (error) {
    showFailure(error);
  } finally {
    state.busy = false;
    ui.compile.disabled = false;
    ui.compile.textContent = "Compilar";
  }
}

function showResult(result) {
  state.result = result;
  for (const phase of PHASES) {
    const status = result.status?.[phase.key] ?? "skipped";
    tabButtons.get(phase.key).dot.className = `dot ${status}`;
    RENDERERS[phase.key](views.get(phase.key), result.phases?.[phase.key] ?? null);
  }
  renderDiagnostics(ui.diagnostics, result.diagnostics ?? [],
    { onSelect: (d) => selectLine(d.line, d.column) });

  const diagnostics = result.diagnostics ?? [];
  const errors = diagnostics.filter((d) => d.severity === "error").length;
  const warnings = diagnostics.length - errors;
  ui.diagnosticsCount.textContent = `${errors} error(es) · ${warnings} advertencia(s)`;
  ui.summary.textContent = result.success
    ? "Compilación exitosa"
    : `${errors} error(es), ${warnings} advertencia(s)`;
  ui.summary.className = `summary ${result.success ? "ok" : "error"}`;

  // Si la fase visible no se ejecuto, se muestra la ultima que si produjo datos.
  if (!result.phases?.[state.active]) {
    const lastRun = [...PHASES].reverse().find((phase) => result.phases?.[phase.key]);
    if (lastRun) state.active = lastRun.key;
  }
  selectTab(state.active);
  updateGutter();
}

function showFailure(error) {
  ui.summary.textContent = "No se pudo compilar";
  ui.summary.className = "summary error";
  ui.diagnosticsCount.textContent = "";
  ui.diagnostics.replaceChildren(h("li", { className: "error" },
    h("span", { className: "icon", text: "✕" }),
    h("span", { className: "phase", text: "conexión" }),
    h("span", { className: "pos", text: "—" }),
    h("span", { className: "msg",
      text: `${error.message} ¿Está corriendo el servidor? (python server.py en backend/)` })));
}

// ----------------------------------------------------------------------
// Ejemplos y registros
// ----------------------------------------------------------------------
async function loadExamples() {
  try {
    state.examples = await fetchExamples();
  } catch {
    state.examples = [];
  }
  const options = state.examples.map((example) => h("option", { value: example.name, text: example.name }));
  ui.examples.replaceChildren(
    h("option", { value: "", text: state.examples.length ? "(editor libre)" : "(sin servidor)" }),
    ...options);

  // En modo mock el editor muestra el programa que produjo ese JSON.
  const wanted = MOCK_EXAMPLES[mockMode()] ?? DEFAULT_EXAMPLE;
  const initial = state.examples.find((example) => example.name === wanted) ?? state.examples[0];
  if (initial) {
    ui.examples.value = initial.name;
    ui.source.value = initial.source;
  }
  updateGutter();
}

function fillRegisters() {
  for (let count = 2; count <= 8; count += 1) {
    ui.registers.append(h("option", { value: count, text: `${count} (R0..R${count - 1})` }));
  }
  ui.registers.value = "4";
}

// ----------------------------------------------------------------------
// Arranque
// ----------------------------------------------------------------------
async function init() {
  buildTabs();
  fillRegisters();
  renderPipelineBar(ui.pipeline, null, { active: state.active, onSelect: selectTab });

  ui.source.addEventListener("input", updateGutter);
  ui.source.addEventListener("scroll", () => { ui.gutter.scrollTop = ui.source.scrollTop; });
  ui.source.addEventListener("keydown", handleEditorKeys);
  ui.compile.addEventListener("click", compile);
  ui.registers.addEventListener("change", () => { if (state.result) compile(); });
  ui.examples.addEventListener("change", () => {
    const example = state.examples.find((item) => item.name === ui.examples.value);
    if (!example) return;
    ui.source.value = example.source;
    ui.source.scrollTop = 0;
    updateGutter();
    compile();
  });

  await loadExamples();
  if (mockMode() || ui.source.value) compile();
}

init();
