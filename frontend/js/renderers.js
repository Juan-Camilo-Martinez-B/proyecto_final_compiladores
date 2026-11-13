// Una funcion por vista. Cada una recibe (container, data) y dibuja la fase.
// Seguridad: todo dato de la API se inserta con textContent / createElement (nunca innerHTML).

export const PHASES = [
  { key: "tokens", label: "Tokens" },
  { key: "ast", label: "AST" },
  { key: "symbols", label: "Símbolos" },
  { key: "memory", label: "Memoria" },
  { key: "ir", label: "TAC" },
  { key: "assembly", label: "ASM" },
  { key: "execution", label: "Consola" },
];

const STATUS_TEXT = {
  ok: "completada", error: "con errores", skipped: "omitida", not_implemented: "no implementada",
};

// ----------------------------------------------------------------------
// Utilidades de DOM
// ----------------------------------------------------------------------
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "className") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function clear(container) {
  container.replaceChildren();
}

function notRun(container) {
  clear(container);
  container.append(h("p", { className: "empty", text: "Esta fase no se ejecutó." }));
  return true;
}

function typeBadge(type) {
  if (!type) return null;
  return h("span", { className: `type ${type}`, text: type });
}

function table(headers, rows) {
  return h("table", {},
    h("thead", {}, h("tr", {}, headers.map((title) => h("th", { text: title })))),
    h("tbody", {}, rows));
}

function cell(value, className) {
  return h("td", { className, text: value ?? "—" });
}

function dash(value) {
  return value === null || value === undefined ? "—" : String(value);
}

// ----------------------------------------------------------------------
// Barra de pipeline
// ----------------------------------------------------------------------
export function renderPipelineBar(container, status, { active, onSelect } = {}) {
  clear(container);
  PHASES.forEach((phase, index) => {
    const state = status?.[phase.key] ?? "skipped";
    if (index > 0) container.append(h("span", { className: "stage-arrow", text: "→", "aria-hidden": "true" }));
    container.append(h("button", {
      type: "button",
      className: `stage ${state}${phase.key === active ? " active" : ""}`,
      title: `${phase.label}: ${STATUS_TEXT[state] ?? state}`,
      onclick: () => onSelect?.(phase.key),
    }, phase.label));
  });
}

// ----------------------------------------------------------------------
// Fase 1: tokens
// ----------------------------------------------------------------------
export function renderTokens(container, tokens) {
  if (!tokens) return notRun(container);
  clear(container);
  const rows = tokens.map((token, index) => h("tr", {
    dataset: { search: `${token.type} ${token.lexeme}`.toLowerCase() },
  },
  cell(index + 1, "num"), cell(token.type, "code"), cell(token.lexeme, "code"),
  cell(token.line, "num"), cell(token.column, "num")));

  const count = h("span", { className: "muted", text: `${tokens.length} tokens` });
  const filter = h("input", {
    className: "filter", type: "search", placeholder: "Filtrar por tipo o lexema…",
    "aria-label": "Filtrar tokens",
    oninput: (event) => {
      const query = event.target.value.trim().toLowerCase();
      let visible = 0;
      for (const row of rows) {
        const show = !query || row.dataset.search.includes(query);
        row.hidden = !show;
        if (show) visible += 1;
      }
      count.textContent = query ? `${visible} de ${tokens.length} tokens` : `${tokens.length} tokens`;
    },
  });
  container.append(
    h("div", { className: "view-toolbar" }, filter, count),
    table(["#", "Tipo", "Lexema", "Línea", "Col"], rows));
}

// ----------------------------------------------------------------------
// Fase 2: AST
// ----------------------------------------------------------------------
const AST_ATTRS = {
  // JSON pierde el ".0" de los float enteros (50.0 llega como 50): se recupera con type_name.
  Literal: (n) => (n.type_name === "float" && Number.isInteger(n.value)
    ? n.value.toFixed(1) : JSON.stringify(n.value)),
  Identifier: (n) => n.name,
  BinaryOp: (n) => `'${n.operator}'`,
  UnaryOp: (n) => `'${n.operator}'`,
  Call: (n) => `${n.callee}()`,
  VarDecl: (n) => `${n.type_name} ${n.name}`,
  Assign: (n) => n.name,
  Param: (n) => `${n.type_name} ${n.name}`,
  FuncDecl: (n) => `${n.name}(${(n.params ?? []).map((p) => `${p.type_name} ${p.name}`).join(", ")}) -> ${n.return_type}`,
};

function isNode(value) {
  return value && typeof value === "object" && typeof value.node === "string";
}

function astChildren(node) {
  const children = [];
  for (const [key, value] of Object.entries(node)) {
    if (node.node === "FuncDecl" && key === "params") continue; // ya estan en la etiqueta
    if (isNode(value)) children.push([key, value]);
    else if (Array.isArray(value)) value.filter(isNode).forEach((child) => children.push([key, child]));
  }
  return children;
}

const HIDDEN_ROLES = new Set(["statements", "arguments"]);

function astLabel(node, role) {
  const attr = AST_ATTRS[node.node]?.(node);
  return [
    role && !HIDDEN_ROLES.has(role) ? h("span", { className: "node-role", text: `${role}:` }) : null,
    h("span", { className: "node-name", text: node.node }),
    attr ? h("span", { className: "node-attr", text: attr }) : null,
    typeBadge(node.inferred_type),
    h("span", { className: "pos", text: `[${node.line}:${node.column}]` }),
  ];
}

function astNode(node, role) {
  const children = astChildren(node);
  if (children.length === 0) return h("div", { className: "leaf" }, astLabel(node, role));
  return h("details", { open: true },
    h("summary", {}, astLabel(node, role)),
    children.map(([childRole, child]) => astNode(child, childRole)));
}

export function renderAst(container, ast) {
  if (!ast) return notRun(container);
  clear(container);
  const tree = h("div", { className: "ast" }, astNode(ast, null));
  const toggle = (open) => tree.querySelectorAll("details").forEach((d) => { d.open = open; });
  container.append(
    h("div", { className: "view-toolbar" },
      h("button", { type: "button", className: "btn", onclick: () => toggle(true) }, "Expandir todo"),
      h("button", { type: "button", className: "btn", onclick: () => toggle(false) }, "Colapsar todo"),
      h("span", { className: "legend" }, "La insignia de color es el tipo inferido por el analizador semántico.")),
    tree);
}

// ----------------------------------------------------------------------
// Fase 3: tabla de simbolos, ambitos y traza
// ----------------------------------------------------------------------
const KIND_LABELS = { variable: "variable", parameter: "parámetro", function: "función" };

function scopeCard(scope) {
  const rows = scope.symbols.map((symbol) => h("tr", {},
    cell(symbol.name, "code"),
    h("td", {}, typeBadge(symbol.type)),
    cell(KIND_LABELS[symbol.kind] ?? symbol.kind),
    cell(symbol.line, "num"),
    cell(symbol.kind === "function"
      ? `(${(symbol.params ?? []).join(", ")}) -> ${symbol.return_type}` : "", "code")));
  return h("section", { className: `scope-card level-${Math.min(scope.level, 3)}` },
    h("div", { className: "scope-head" },
      h("h3", { text: scope.name }),
      h("span", { className: "muted", text: `nivel ${scope.level}` }),
      scope.parent ? h("span", { className: "muted", text: `· padre: ${scope.parent}` }) : null),
    rows.length
      ? table(["Símbolo", "Tipo", "Clase", "Línea", "Firma"], rows)
      : h("p", { className: "muted", text: "(sin símbolos)" }));
}

function traceText(event) {
  switch (event.action) {
    case "enter_scope": return `entra a '${event.scope}'`;
    case "exit_scope": return `sale de '${event.scope}'`;
    case "define": return `define '${event.name}' en '${event.scope}'`;
    default: return event.found_in
      ? `lookup '${event.name}' desde '${event.scope}' → encontrado en '${event.found_in}'`
      : `lookup '${event.name}' desde '${event.scope}' → NO encontrado`;
  }
}

export function renderSymbols(container, symbols) {
  if (!symbols) return notRun(container);
  clear(container);

  // Arbol de ambitos: cada ambito se anida dentro de la tarjeta de su padre.
  const cards = new Map();
  const roots = [];
  for (const scope of symbols.scopes ?? []) {
    const card = scopeCard(scope);
    const parent = scope.parent ? cards.get(scope.parent) : null;
    (parent ? parent.append(card) : roots.push(card));
    cards.set(scope.name, card);
  }

  const trace = symbols.trace ?? [];
  const items = trace.map((event) => h("li", {},
    h("span", { className: "muted", text: `${event.step}.` }),
    h("span", {
      className: `action ${event.action}${event.action === "lookup" && !event.found_in ? " miss" : ""}`,
      text: event.action,
    }),
    h("span", { text: traceText(event) }),
    h("span", { className: "muted", text: `línea ${event.line}` })));

  let timer = null;
  const playButton = h("button", { type: "button", className: "btn" }, "▶ Reproducir");
  const stop = () => {
    clearInterval(timer);
    timer = null;
    playButton.textContent = "▶ Reproducir";
    items.forEach((li) => li.classList.remove("current", "done"));
    cards.forEach((card) => card.classList.remove("flash"));
  };
  playButton.addEventListener("click", () => {
    if (timer) { stop(); return; }
    let step = 0;
    playButton.textContent = "■ Detener";
    timer = setInterval(() => {
      if (!container.isConnected || step >= items.length) { stop(); return; }
      items.forEach((li, i) => {
        li.classList.toggle("done", i < step);
        li.classList.toggle("current", i === step);
      });
      cards.forEach((card) => card.classList.remove("flash"));
      cards.get(trace[step].scope)?.classList.add("flash");
      items[step].scrollIntoView({ block: "nearest" });
      step += 1;
    }, 450);
  });

  container.append(
    h("div", { className: "view-toolbar" }, h("h3", { text: "Ámbitos anidados" }),
      h("span", { className: "muted", text: `${cards.size} ámbitos` })),
    ...roots,
    h("div", { className: "view-toolbar" },
      h("h3", { text: "Traza de la pila de ámbitos" }), playButton,
      h("span", { className: "legend" },
        h("span", { className: "action enter_scope", text: "enter_scope" }),
        h("span", { className: "action exit_scope", text: "exit_scope" }),
        h("span", { className: "action define", text: "define" }),
        h("span", { className: "action lookup", text: "lookup" }))),
    trace.length ? h("ol", { className: "trace" }, items) : h("p", { className: "muted", text: "(traza vacía)" }));
}

// ----------------------------------------------------------------------
// Fase 4: memoria
// ----------------------------------------------------------------------
function slotTable(slots) {
  const rows = slots.map((slot) => h("tr", { className: slot.kind === "control" ? "control" : "" },
    cell(`+${slot.offset}`, "num"),
    cell(slot.name, "code"),
    h("td", {}, slot.type ? typeBadge(slot.type) : h("span", { className: "muted", text: slot.kind })),
    cell(slot.size, "num"),
    h("td", {}, h("span", { className: "bytes", style: `width:${slot.size * 6}px` }))));
  return table(["Offset", "Nombre", "Tipo", "Bytes", ""], rows);
}

export function renderMemory(container, memory) {
  if (!memory) return notRun(container);
  clear(container);
  const globals = memory.globals ?? { size: 0, slots: [] };
  const frames = memory.frames ?? [];
  const heap = memory.heap ?? [];

  const globalBlock = h("div", { className: "memory-block" },
    h("h3", { text: `Segmento global (data) · ${globals.size} bytes` }),
    globals.slots.length ? slotTable(globals.slots) : h("p", { className: "muted", text: "(sin variables globales)" }));

  const stackBlock = h("div", { className: "memory-block" },
    h("h3", { text: "Pila (registros de activación)" }),
    frames.length
      ? h("div", { className: "stack" }, frames.map((frame) => h("div", { className: "frame" },
        h("div", { className: "frame-head" },
          h("strong", { text: `frame ${frame.function}` }), h("span", { text: `${frame.size} bytes` })),
        slotTable(frame.slots))))
      : h("p", { className: "muted", text: "(sin funciones)" }));

  const heapRows = heap.map((entry) => h("tr", {},
    cell(entry.address, "code"), cell(JSON.stringify(entry.value), "code"), cell(entry.size, "num")));
  const heapBlock = h("div", { className: "memory-block" },
    h("h3", { text: "Heap (cadenas)" }),
    heap.length ? table(["Dirección", "Valor", "Bytes"], heapRows) : h("p", { className: "muted", text: "(sin cadenas)" }));

  container.append(h("div", { className: "memory-grid" }, globalBlock, stackBlock, heapBlock));
}

// ----------------------------------------------------------------------
// Fase 5: codigo de tres direcciones
// ----------------------------------------------------------------------
export function renderIr(container, quads) {
  if (!quads) return notRun(container);
  clear(container);
  const rows = quads.map((quad) => h("tr", {
    className: quad.op === "label" ? "ir-label" : quad.op.startsWith("func_") ? "ir-func" : "",
  },
  cell(quad.index, "num"), h("td", { className: "op", text: quad.op }),
  cell(dash(quad.arg1), "code"), cell(dash(quad.arg2), "code"), cell(dash(quad.result), "code")));

  const listing = h("pre", { className: "tac-listing" }, quads.map((quad) => {
    const isLabel = quad.op === "label";
    return h("span", { className: isLabel ? "label" : "" }, `${isLabel ? "" : "    "}${quad.text}\n`);
  }));
  container.append(
    h("div", { className: "view-toolbar" }, h("h3", { text: "Cuádruplas (op, arg1, arg2, result)" }),
      h("span", { className: "muted", text: `${quads.length} instrucciones` })),
    h("div", { className: "ir-layout" },
      table(["#", "Op", "Arg1", "Arg2", "Result"], rows),
      h("div", {}, listing)));
}

// ----------------------------------------------------------------------
// Fase 6: pseudo-ensamblador y registros
// ----------------------------------------------------------------------
export function renderAssembly(container, assembly) {
  if (!assembly) return notRun(container);
  clear(container);
  const instructions = assembly.instructions ?? [];
  const trace = assembly.register_trace ?? [];
  const spills = assembly.spills ?? [];
  const spillLines = new Set(spills.map((spill) => spill.instruction));

  const bank = h("div", { className: "register-bank" });
  const caption = h("p", { className: "muted" });

  const showRegisters = (index) => {
    const snapshot = trace[index]?.registers ?? {};
    const previous = trace[index - 1]?.registers ?? {};
    bank.replaceChildren(...Object.entries(snapshot).map(([reg, value]) => h("div", {
      className: `register${value === null ? " free" : ""}${index > 0 && previous[reg] !== value ? " changed" : ""}`,
    },
    h("span", { className: "reg-name", text: reg }),
    h("span", { className: "reg-value", text: value ?? "libre" }))));
    caption.textContent = `Estado después de la instrucción ${index}: ${(instructions[index] ?? "").trim()}`;
  };

  let selected = null;
  const lines = instructions.map((text, index) => {
    const trimmed = text.trim();
    const kind = spillLines.has(index) ? "spill"
      : text.includes("; recarga") ? "reload"
        : !text.startsWith(" ") && !trimmed.startsWith("FUNC") && !trimmed.startsWith("ENDFUNC") ? "label" : "";
    const li = h("li", { className: kind, tabindex: "0" },
      h("span", { className: "ln", text: index }), h("span", { text }));
    const select = () => {
      selected?.classList.remove("selected");
      li.classList.add("selected");
      selected = li;
      showRegisters(index);
    };
    li.addEventListener("mouseenter", select);
    li.addEventListener("click", select);
    li.addEventListener("focus", select);
    return li;
  });

  const stats = h("div", { className: "stat-row" },
    h("div", { className: "stat" }, h("div", { className: "stat-value", text: assembly.register_count }),
      h("div", { className: "stat-label", text: "registros" })),
    h("div", { className: `stat${spills.length ? " alert" : ""}` },
      h("div", { className: "stat-value", text: spills.length }), h("div", { className: "stat-label", text: "spills" })),
    h("div", { className: "stat" }, h("div", { className: "stat-value", text: instructions.length }),
      h("div", { className: "stat-label", text: "instrucciones" })));

  const spillTable = spills.length
    ? table(["Temporal", "Slot", "Instrucción"], spills.map((spill) => h("tr", {},
      cell(spill.variable, "code"), cell(spill.slot, "code"), cell(spill.instruction, "num"))))
    : h("p", { className: "muted", text: "Sin spills: los registros alcanzaron." });

  container.append(h("div", { className: "asm-layout" },
    h("ol", { className: "asm-listing" }, lines),
    h("aside", { className: "registers" },
      stats,
      h("h3", { text: "Registros" }), bank, caption,
      h("span", { className: "legend" },
        h("span", { text: "Rojo: spill a la pila" }), h("span", { text: "Ámbar: recarga" })),
      h("h3", { text: "Spills" }), spillTable)));

  if (lines.length) {
    const first = lines.findIndex((li) => li.classList.contains("spill"));
    lines[Math.max(first, 0)].click();
  }
}

// ----------------------------------------------------------------------
// Ejecucion: terminal simulada con la salida de la maquina virtual de TAC
// ----------------------------------------------------------------------
export function renderExecution(container, execution) {
  if (!execution) {
    clear(container);
    container.append(h("p", { className: "empty",
      text: "El programa solo se ejecuta si compila sin errores." }));
    return;
  }
  clear(container);
  const output = execution.output ?? [];
  const lines = output.map((line) => h("div", { className: "console-line", text: line }));
  if (!output.length) {
    lines.push(h("div", { className: "console-line muted", text: "(el programa no imprimió nada)" }));
  }
  const error = execution.error;
  const footer = error
    ? h("div", { className: "console-status error" },
      h("strong", { text: "Error en tiempo de ejecución: " }), error.message,
      h("div", { className: "console-detail",
        text: `Instrucción TAC ${error.instruction}: ${error.text}` }))
    : h("div", { className: "console-status ok",
      text: `Programa terminado · ${execution.steps} instrucciones TAC ejecutadas` });

  container.append(
    h("p", { className: "muted",
      text: "La máquina virtual ejecuta las cuádruplas del código intermedio, una por una." }),
    h("div", { className: "console", role: "log", "aria-label": "Salida del programa" },
      h("div", { className: "console-prompt", text: "$ rpgscript run" }), lines, footer));
}

// ----------------------------------------------------------------------
// Diagnosticos
// ----------------------------------------------------------------------
export function renderDiagnostics(container, diagnostics, { onSelect } = {}) {
  clear(container);
  if (!diagnostics) return;
  if (diagnostics.length === 0) {
    container.append(h("li", { className: "success-row" }, h("span", { className: "success", text: "✓ Compilación exitosa: sin errores ni advertencias." })));
    return;
  }
  for (const diagnostic of diagnostics) {
    const clickable = diagnostic.line > 0;
    container.append(h("li", {
      className: `${diagnostic.severity}${clickable ? " clickable" : ""}`,
      title: clickable ? "Ir a la línea en el editor" : null,
      onclick: clickable ? () => onSelect?.(diagnostic) : null,
    },
    h("span", { className: "icon", text: diagnostic.severity === "error" ? "✕" : "!" }),
    h("span", { className: "phase", text: diagnostic.phase }),
    h("span", { className: "pos", text: clickable ? `${diagnostic.line}:${diagnostic.column}` : "—" }),
    h("span", { className: "msg", text: diagnostic.message })));
  }
}
