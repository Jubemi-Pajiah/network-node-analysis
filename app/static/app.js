"use strict";

let solvedOnce = false;

// ---- table rendering -------------------------------------------------------
function nodeRow(n) {
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input value="${n.id ?? ""}" data-f="id" aria-label="node id"></td>
    <td><select data-f="type" aria-label="node type">
      <option value="junction"${n.type === "junction" ? " selected" : ""}>junction</option>
      <option value="reservoir"${n.type === "reservoir" ? " selected" : ""}>reservoir</option>
    </select></td>
    <td><input value="${n.elevation ?? 0}" data-f="elevation" inputmode="decimal" aria-label="elevation"></td>
    <td><input value="${n.demand ?? 0}" data-f="demand" inputmode="decimal" aria-label="demand"></td>
    <td><input value="${n.fixed_head ?? ""}" data-f="fixed_head" inputmode="decimal" aria-label="fixed head"></td>
    <td><button class="row-del" type="button" aria-label="delete node">&times;</button></td>`;
  tr.dataset.coords = n.coords ? JSON.stringify(n.coords) : "";
  tr.querySelector(".row-del").onclick = () => tr.remove();
  return tr;
}

function pipeRow(p) {
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input value="${p.id ?? ""}" data-f="id" aria-label="pipe id"></td>
    <td><input value="${p.from ?? ""}" data-f="from" aria-label="from node"></td>
    <td><input value="${p.to ?? ""}" data-f="to" aria-label="to node"></td>
    <td><input value="${p.length ?? ""}" data-f="length" inputmode="decimal" aria-label="length"></td>
    <td><input value="${p.diameter ?? ""}" data-f="diameter" inputmode="decimal" aria-label="diameter"></td>
    <td><input value="${p.roughness ?? ""}" data-f="roughness" inputmode="decimal" aria-label="roughness"></td>
    <td><button class="row-del" type="button" aria-label="delete pipe">&times;</button></td>`;
  tr.querySelector(".row-del").onclick = () => tr.remove();
  return tr;
}

function loadNetwork(net) {
  const nb = document.querySelector("#nodes tbody");
  const pb = document.querySelector("#pipes tbody");
  nb.innerHTML = ""; pb.innerHTML = "";
  net.nodes.forEach(n => nb.appendChild(nodeRow(n)));
  net.pipes.forEach(p => pb.appendChild(pipeRow(p)));
}

// ---- collect edited network -----------------------------------------------
function collect() {
  const nodes = [...document.querySelectorAll("#nodes tbody tr")].map(tr => {
    const get = f => tr.querySelector(`[data-f="${f}"]`).value;
    const o = { id: get("id"), type: get("type"), elevation: get("elevation"),
                demand: get("demand"), fixed_head: get("fixed_head") };
    if (tr.dataset.coords) { try { o.coords = JSON.parse(tr.dataset.coords); } catch (e) {} }
    return o;
  });
  const pipes = [...document.querySelectorAll("#pipes tbody tr")].map(tr => {
    const get = f => tr.querySelector(`[data-f="${f}"]`).value;
    return { id: get("id"), from: get("from"), to: get("to"), length: get("length"),
             diameter: get("diameter"), roughness: get("roughness") };
  });
  return {
    nodes, pipes,
    model: document.getElementById("model").value,
    tol: document.getElementById("tol").value,
    max_iter: document.getElementById("maxiter").value,
  };
}

// ---- helpers ---------------------------------------------------------------
function fmt(x, d = 3) { return (typeof x === "number") ? x.toFixed(d) : x; }
function setKpi(id, value, cls) {
  const el = document.getElementById(id);
  el.textContent = value;
  el.className = "kpi-value" + (cls ? " " + cls : "");
}

function updateKpis(data) {
  setKpi("kpi-status", data.converged ? "Converged" : "No converge",
         data.converged ? "is-good" : "is-alert");
  setKpi("kpi-iter", data.iterations);
  setKpi("kpi-res", data.max_residual.toExponential(1));
  const t = data.solve_time_ms;
  setKpi("kpi-time", t < 1000 ? t.toFixed(1) + " ms" : (t / 1000).toFixed(2) + " s");

  const junc = data.nodes.filter(n => n.type === "junction");
  if (junc.length) {
    const pmin = Math.min(...junc.map(n => n.pressure_head));
    setKpi("kpi-pmin", pmin.toFixed(1),
           pmin < 0 ? "is-alert" : (pmin < 15 ? "is-warn" : "is-good"));
  } else { setKpi("kpi-pmin", "—"); }

  if (data.pipes.length) {
    const vmax = Math.max(...data.pipes.map(p => p.velocity));
    setKpi("kpi-vmax", vmax.toFixed(2), vmax > 2 ? "is-warn" : "is-good");
  } else { setKpi("kpi-vmax", "—"); }
}

// ---- solving ---------------------------------------------------------------
async function solve() {
  const status = document.getElementById("status");
  const btn = document.getElementById("solve");
  btn.classList.add("loading"); btn.disabled = true;
  status.textContent = "Solving..."; status.className = "";

  let data;
  try {
    const resp = await fetch("/solve", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collect()),
    });
    data = await resp.json();
  } catch (e) {
    status.textContent = "Request error: " + e; status.className = "error";
    btn.classList.remove("loading"); btn.disabled = false;
    return;
  }
  btn.classList.remove("loading"); btn.disabled = false;

  if (!data.ok) {
    status.textContent = "Error: " + data.error;
    status.className = "error";
    if (!solvedOnce) {
      document.getElementById("results").classList.add("hidden");
      document.getElementById("results-empty").classList.remove("hidden");
    }
    return;
  }

  solvedOnce = true;
  document.getElementById("results-empty").classList.add("hidden");
  document.getElementById("results").classList.remove("hidden");

  status.textContent = data.converged
    ? `Converged in ${data.iterations} iterations (${data.solve_time_ms.toFixed(1)} ms).`
    : (data.warning || "Did not converge.");
  status.className = data.converged ? "ok" : "error";

  updateKpis(data);

  if (data.diagram_png)
    document.getElementById("diagram").src = "data:image/png;base64," + data.diagram_png;
  if (data.convergence_png)
    document.getElementById("convergence").src = "data:image/png;base64," + data.convergence_png;

  // result tables
  const nb = document.querySelector("#node-results tbody");
  nb.innerHTML = "";
  data.nodes.forEach(n => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${n.id}</td><td>${fmt(n.head, 3)}</td><td>${fmt(n.pressure_head, 3)}</td>`;
    nb.appendChild(tr);
  });
  const pb = document.querySelector("#pipe-results tbody");
  pb.innerHTML = "";
  data.pipes.forEach(p => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${p.id}</td><td>${fmt(p.flow * 1000, 2)}</td>`
      + `<td>${fmt(p.velocity, 3)}</td><td>${fmt(p.head_loss, 4)}</td>`;
    pb.appendChild(tr);
  });

  // interpretation
  const interpList = document.getElementById("interp-list");
  interpList.innerHTML = "";
  (data.interpretation || []).forEach(f => {
    const li = document.createElement("li");
    li.className = "interp-item lvl-" + f.level;
    li.innerHTML = `<span class="interp-title">${f.title}</span>`
      + `<span class="interp-detail">${f.detail}</span>`;
    interpList.appendChild(li);
  });
}

// ---- tab switching ---------------------------------------------------------
function showTab(name) {
  document.querySelectorAll(".tab").forEach(t =>
    t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach(p =>
    p.classList.toggle("active", p.id === "tab-" + name));
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ---- wiring ----------------------------------------------------------------
document.querySelectorAll("button.add").forEach(btn => {
  btn.onclick = () => {
    if (btn.dataset.target === "nodes")
      document.querySelector("#nodes tbody").appendChild(nodeRow({ type: "junction" }));
    else
      document.querySelector("#pipes tbody").appendChild(pipeRow({}));
  };
});
document.getElementById("preset").onchange = async (e) => {
  const model = document.getElementById("model").value;
  const r = await fetch("/preset/" + e.target.value + "?model=" + encodeURIComponent(model));
  const d = await r.json();
  if (d.ok) loadNetwork(d.network);
};
document.getElementById("solve").onclick = solve;
document.querySelectorAll(".tab").forEach(t => { t.onclick = () => showTab(t.dataset.tab); });
document.querySelectorAll(".goto-solver").forEach(el =>
  el.addEventListener("click", () => showTab("solver")));

// initial load + auto-solve
loadNetwork(window.INITIAL_NETWORK);
solve();
