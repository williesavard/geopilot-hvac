/* GeoPilot control surface.
 *
 * Loaded only by the server, never by the static file, because a file has no
 * back channel and a button that cannot work is worse than no button.
 *
 * Two rules shape everything here:
 *
 * - **the displayed state comes from the equipment, not from us.** Every poll
 *   asks the bus. Nothing on this page remembers what it commanded and shows
 *   that back, because a controller that believes its own intentions cannot
 *   notice a contact that did not move;
 * - **nothing is sent without a reason and a confirmation.** The server rejects
 *   a command with no reason; asking here means the person is asked while they
 *   still remember why.
 */

(function () {
  "use strict";

  const token = window.GEOPILOT && window.GEOPILOT.controlToken;
  const root = document.getElementById("control");
  if (!token || !root) return;

  const POLL_MS = 5000;
  let inFlight = false;

  function text(node, value) {
    node.textContent = value;
    return node;
  }

  function element(name, className, value) {
    const node = document.createElement(name);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
  }

  async function call(path, options) {
    const response = await fetch(path, {
      ...options,
      headers: { "X-GeoPilot-Token": token, "Content-Type": "application/json" },
    });
    const body = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, body: body };
  }

  function stateWord(target) {
    if (target.state === true) return "closed";
    if (target.state === false) return "open";
    return target.detail || "unknown";
  }

  function stateClass(target) {
    if (target.state === null) return "warn";
    return target.state ? "good" : "";
  }

  function describe(record) {
    const when = record.decided_at.slice(11, 19);
    const verb = record.closed ? "close" : "open";
    return `${when} · ${verb} ${record.target_id} · ${record.status}${record.detail ? " · " + record.detail : ""}`;
  }

  async function send(target, closed) {
    const reason = window.prompt(
      `Why ${closed ? "close" : "open"} ${target.target_id}?\n\nThis is recorded with the command.`,
    );
    if (reason === null || !reason.trim()) return;

    const confirmed = window.confirm(
      `${closed ? "Close" : "Open"} ${target.target_id}?\n\nThis operates real equipment.`,
    );
    if (!confirmed) return;

    const result = await call("/api/command", {
      method: "POST",
      body: JSON.stringify({ target_id: target.target_id, closed: closed, reason: reason }),
    });

    // A refusal is an answer, not an error. Show it and re-read the bus either
    // way: what the relay is doing is a fact about the relay, not about us.
    if (result.body && result.body.error) window.alert(result.body.error);
    await refresh();
  }

  function drawTargets(state) {
    root.textContent = "";

    if (!state.enabled) {
      root.appendChild(
        element(
          "p",
          "caveat",
          "Control is disabled in the configuration. The states below are read " +
            "from the equipment; every command will be refused and recorded as refused.",
        ),
      );
    }

    if (state.targets.length === 0) {
      root.appendChild(element("p", "note", "no relays are whitelisted"));
      return;
    }

    const table = element("table");
    const head = element("thead");
    const headRow = element("tr");
    ["relay", "reads as", "", ""].forEach((label) => {
      headRow.appendChild(element("th", null, label));
    });
    head.appendChild(headRow);
    table.appendChild(head);

    const body = element("tbody");
    state.targets.forEach((target) => {
      const row = element("tr");

      const name = element("td");
      name.appendChild(element("strong", null, target.target_id));
      if (target.description) {
        name.appendChild(document.createElement("br"));
        name.appendChild(element("span", "subtitle", target.description));
      }
      row.appendChild(name);

      const reads = element("td");
      const dot = element("span", "status " + stateClass(target));
      reads.appendChild(dot);
      reads.appendChild(document.createTextNode(stateWord(target)));
      row.appendChild(reads);

      [
        ["close", true],
        ["open", false],
      ].forEach(([label, closed]) => {
        const cell = element("td");
        const button = element("button", null, label);
        button.type = "button";
        button.disabled = !state.enabled;
        button.addEventListener("click", () => send(target, closed));
        cell.appendChild(button);
        row.appendChild(cell);
      });

      body.appendChild(row);
    });

    table.appendChild(body);

    const scroller = element("div", "scroll");
    scroller.appendChild(table);
    root.appendChild(scroller);

    if (state.journal.length) {
      root.appendChild(element("h3", null, "Recent commands"));
      const list = element("div", "readout");
      state.journal
        .slice()
        .reverse()
        .forEach((record) => {
          list.appendChild(text(document.createElement("div"), describe(record)));
        });
      root.appendChild(list);
    }
  }

  async function refresh() {
    if (inFlight) return;
    inFlight = true;
    try {
      const result = await call("/api/state", { method: "GET" });
      if (result.ok) {
        drawTargets(result.body);
      } else {
        root.textContent = "";
        root.appendChild(
          element("p", "caveat", `cannot read the control state: ${result.body.error || result.status}`),
        );
      }
    } catch (error) {
      root.textContent = "";
      root.appendChild(element("p", "caveat", `the control server is not answering: ${error}`));
    } finally {
      inFlight = false;
    }
  }

  refresh();
  setInterval(refresh, POLL_MS);
})();
