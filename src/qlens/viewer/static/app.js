// Placeholder frontend: exercises every API endpoint (health, stream,
// circuit, state) so the server contract is proven end-to-end. The
// designed UI replaces this file and styles.css; the API stays.

const runList = document.getElementById("run-list");
const circuitJson = document.getElementById("circuit-json");
const stateJson = document.getElementById("state-json");
const health = document.getElementById("health");
const runs = new Map();

async function loadHealth() {
  const res = await fetch("/api/health");
  const data = await res.json();
  health.textContent = `v${data.version} · ${data.source}`;
}

function renderRuns() {
  runList.replaceChildren(
    ...[...runs.values()].map((run) => {
      const li = document.createElement("li");
      li.className = run.in_flight ? "running" : run.status;
      const failed = run.assertions_failed > 0 ? ` · ${run.assertions_failed} failed` : "";
      li.textContent =
        `${run.trace_id} · ${run.backend ?? "?"} · ${run.num_qubits ?? "?"}q · ` +
        `${run.gate_count ?? "?"} gates · ${run.status}${failed}`;
      li.addEventListener("click", () => openRun(run.trace_id));
      return li;
    }),
  );
}

async function openRun(traceId) {
  const circuit = await (await fetch(`/api/circuit?trace_id=${traceId}`)).json();
  circuitJson.textContent = JSON.stringify(circuit, null, 2);
  const state = await (await fetch(`/api/state?trace_id=${traceId}&position=-1`)).json();
  stateJson.textContent = JSON.stringify(state, null, 2);
}

function listen() {
  const source = new EventSource("/api/stream");
  source.onmessage = (event) => {
    const run = JSON.parse(event.data);
    runs.set(run.trace_id, run);
    renderRuns();
  };
  source.onerror = () => {
    source.close();
    setTimeout(listen, 2000);
  };
}

loadHealth();
listen();
