"use strict";

const SAMPLE = {
  max_curvature: 2,
  segments: [
    { points: [[-3, 0], [-2, 1], [-1, 0], [0, 0]] },
    { points: [[0, 0], [1, 0], [2, 1], [3, 0]] },
  ],
};

const $ = (id) => document.getElementById(id);
const segCountEl = $("segments");

function makeSegmentEditor(idx, points) {
  const wrap = document.createElement("div");
  wrap.className = "segment";
  wrap.dataset.idx = idx;
  let grid = '<div class="pt-grid">';
  for (let i = 0; i < 4; i++) {
    grid += `
      <div class="pt">
        <span>P${i}</span>
        <input type="number" step="1" data-pt="${i}" data-axis="x" value="${points[i][0]}" aria-label="第${idx +1}段 P${i} x">
        <input type="number" step="1" data-pt="${i}" data-axis="y" value="${points[i][1]}" aria-label="第${idx +1}段 P${i} y">
      </div>`;
  }
  grid += "</div>";
  wrap.innerHTML = `<h3>第 ${idx + 1} 段</h3>${grid}`;
  return wrap;
}

function defaultPoints(n) {
  // Continuous, tangent-continuous straight pieces as a safe starting draft.
  const segs = [];
  for (let i = 0; i < n; i++) {
    const x0 = 3 * i;
    segs.push([[x0, 0], [x0 + 1, 0], [x0 + 2, 0], [x0 + 3, 0]]);
  }
  return segs;
}

function renderDurationRows(n) {
  const box = $("durationRows");
  box.innerHTML = "";
  for (let i = 0; i < n; i++) {
    const row = document.createElement("div");
    row.className = "dur-row";
    row.innerHTML =
      `<span>第 ${i + 1} 段喷涂时长</span>` +
      `<input type="number" step="1" min="1" data-seg="${i}"` +
      ` placeholder="正整数" aria-label="第${i + 1}段喷涂时长" />`;
    box.appendChild(row);
  }
  box.querySelectorAll("input").forEach((el) =>
    el.addEventListener("input", invalidateCoating));
}

function renderEditors(n, values) {
  const points = values || defaultPoints(n);
  segCountEl.innerHTML = "";
  points.forEach((pts, i) => segCountEl.appendChild(makeSegmentEditor(i, pts)));
  segCountEl.querySelectorAll("input").forEach((el) =>
    el.addEventListener("input", onGeometryEdit));
  renderDurationRows(n);
}

function readPayload() {
  const segments = [...segCountEl.querySelectorAll(".segment")].map((wrap) => {
    const pts = [[], [], [], []];
    wrap.querySelectorAll("input").forEach((input) => {
      pts[Number(input.dataset.pt)][input.dataset.axis === "x" ? 0 : 1] =
        Number(input.value);
    });
    return { points: pts };
  });
  const payload = { segments, max_curvature: Number($("kmax").value) };
  if ($("coatingEnabled").checked) {
    payload.coating = {
      enabled: true,
      spray_durations: [...$("durationRows").querySelectorAll("input")]
        .map((el) => Number(el.value)),
      min_speed: Number($("vmin").value),
      max_speed: Number($("vmax").value),
    };
  }
  return payload;
}

function isValidInteger(v) {
  return Number.isFinite(v) && Math.trunc(v) === v;
}

function validateDraft(payload) {
  if (!Number.isFinite(payload.max_curvature) || payload.max_curvature <= 0) {
    return "最大曲率必须是有限正数。";
  }
  for (const seg of payload.segments) {
    for (const pt of seg.points) {
      if (pt.length !== 2 || !isValidInteger(pt[0]) || !isValidInteger(pt[1])) {
        return "所有控制点必须填写整数 x、y 坐标。";
      }
    }
  }
  if (payload.coating) {
    const c = payload.coating;
    if (c.spray_durations.length !== payload.segments.length ||
        c.spray_durations.some((d) => !isValidInteger(d) || d <= 0)) {
      return "每段喷涂时长必须填写正整数。";
    }
    if (!Number.isFinite(c.min_speed) || !Number.isFinite(c.max_speed) ||
        c.min_speed <= 0 || c.max_speed <= 0 ||
        c.min_speed > c.max_speed) {
      return "请填写 0 < 最小速度 ≤ 最大速度 的有限正数。";
    }
  }
  return null;
}

// ---------- conclusion invalidation ----------------------------------------

function invalidateAudit(msg) {
  const toggle = $("coatingEnabled");
  toggle.checked = false;
  toggle.disabled = true;
  $("coatingFields").classList.add("hidden");
  // A geometry edit also voids every displayed conclusion.
  invalidateCoating();
  const box = $("result");
  if (msg && !box.classList.contains("hidden")) {
    box.innerHTML = `<div class="banner fail">✗ ${msg}</div>`;
  }
}

function invalidateCoating() {
  const existing = $("coatingResult");
  if (existing) existing.remove();
}

function onGeometryEdit() {
  invalidateAudit("草稿已修改：曲率审计与防腐走行复核结论均已撤销，请重新发起审计。");
  drawPreview();
}

function onTravelParamEdit() {
  // Only the coating conclusion is voided; the curvature audit stands.
  invalidateCoating();
}

// ---------- SVG preview (display only; never used for audit decisions) ----

function bezPoint(p, t) {
  const u = 1 - t;
  const b = [u ** 3, 3 * u * u * t, 3 * u * t * t, t ** 3];
  return [0, 1].map((ax) => b.reduce((s, w, i) => s + w * p[i][ax], 0));
}

function drawPreview() {
  const svg = $("preview");
  svg.innerHTML = "";
  let payload;
  try { payload = readPayload(); } catch { return; }
  const all = payload.segments.flatMap((s) => s.points);
  if (!all.length) return;
  const xs = all.map((p) => p[0]), ys = all.map((p) => p[1]);
  let minX = Math.min(...xs), maxX = Math.max(...xs);
  let minY = Math.min(...ys), maxY = Math.max(...ys);
  if (maxX - minX < 1) { minX -= 1; maxX += 1; }
  if (maxY - minY < 1) { minY -= 1; maxY += 1; }
  const W = 640, H = 420, pad = 30;
  const sx = (x) => pad + ((x - minX) / (maxX - minX)) * (W - 2 * pad);
  const sy = (y) => H - pad - ((y - minY) / (maxY - minY)) * (H - 2 * pad);
  const NS = "http://www.w3.org/2000/svg";

  const path = document.createElementNS(NS, "path");
  let d = "";
  payload.segments.forEach((seg, si) => {
    const p = seg.points;
    for (let i = 0; i <= 80; i++) {
      const [x, y] = bezPoint(p, i / 80);
      d += (i === 0 && si === 0 ? "M" : "L") + sx(x).toFixed(2) + "," + sy(y).toFixed(2);
    }
  });
  path.setAttribute("d", d);
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "#4da3ff");
  path.setAttribute("stroke-width", "2.5");
  svg.appendChild(path);

  payload.segments.forEach((seg) => {
    const poly = document.createElementNS(NS, "polyline");
    poly.setAttribute("points",
      seg.points.map((p) => sx(p[0]).toFixed(1) + "," + sy(p[1]).toFixed(1)).join(" "));
    poly.setAttribute("fill", "none");
    poly.setAttribute("stroke", "#5a7299");
    poly.setAttribute("stroke-dasharray", "4 4");
    poly.setAttribute("stroke-width", "1");
    svg.appendChild(poly);
    seg.points.forEach((p, i) => {
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", sx(p[0])); c.setAttribute("cy", sy(p[1]));
      c.setAttribute("r", 3.5);
      c.setAttribute("fill", i === 0 || i === 3 ? "#ffb84d" : "#93a6c4");
      svg.appendChild(c);
    });
  });
}

// ---------- result rendering ------------------------------------------------

function fmt(v, digits = 6) {
  return Number.isFinite(v) ? Number(v).toFixed(digits).replace(/\.?0+$/, "") : String(v);
}

function renderPass(result) {
  const rows = result.segments.map((s) => `
    <tr>
      <td>第 ${s.index + 1} 段</td>
      <td class="num">${fmt(s.max_curvature)}</td>
      <td class="num">t = ${fmt(s.location.t)}</td>
      <td class="num">(${fmt(s.location.x)}, ${fmt(s.location.y)})</td>
    </tr>`).join("");
  return `
    <div class="banner pass">✓ 审计通过：各段拼接连续，曲率均未超过 κ<sub>max</sub> = ${fmt(result.max_curvature)}</div>
    <table>
      <thead><tr><th>段落</th><th>段内最大曲率</th><th>对应参数</th><th>坐标</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderCoating(c) {
  const bannerClass = c.certified ? "pass" : "fail";
  const title = c.certified
    ? `✓ 防腐走行复核已认证：各段速度区间均落入闭区间 [${fmt(c.min_speed)}, ${fmt(c.max_speed)}]`
    : `✗ 防腐走行复核未认证（首个问题段）：${c.error.message}`;
  const rows = c.segments.map((s) => {
    const L = s.arc_length;
    const status = s.certified
      ? '<span class="tag ok">已认证</span>'
      : '<span class="tag bad">未认证</span>';
    return `
    <tr class="${s.certified ? "" : "badrow"}">
      <td>第 ${s.index + 1} 段 ${status}</td>
      <td class="num">${fmt(s.duration)}</td>
      <td class="num">[${fmt(L.lower, 9)}, ${fmt(L.upper, 9)}]<br/>
        <span class="sub">误差 ≤ ${fmt(L.error, 3)}</span></td>
      <td class="num">[${fmt(s.speed.lower, 9)}, ${fmt(s.speed.upper, 9)}]</td>
    </tr>`;
  }).join("");
  const ev = c.error ? `
    <div class="detail">
      <div class="row"><span class="k">原因代码</span><code>${c.error.code}</code></div>
      <div class="row"><span class="k">问题段</span><code>第 ${c.error.segment + 1} 段</code></div>
      <div class="row"><span class="k">速度证据</span><code>[${fmt(c.error.speed_lower, 9)}, ${fmt(c.error.speed_upper, 9)}]</code></div>
      <div class="row"><span class="k">真实弧长</span><code>[${fmt(c.error.arc_length_lower, 9)}, ${fmt(c.error.arc_length_upper, 9)}]（误差 ≤ ${fmt(c.error.arc_length_error, 3)}）</code></div>
      <div class="row"><span class="k">喷涂时长</span><code>${c.error.duration}</code></div>
      <div class="row"><span class="k">允许闭区间</span><code>[${fmt(c.error.min_speed)}, ${fmt(c.error.max_speed)}]</code></div>
    </div>` : "";
  return `
    <div id="coatingResult" class="coating-result">
      <div class="banner ${bannerClass}">${title}</div>
      <table>
        <thead><tr>
          <th>段落</th><th>喷涂时长</th><th>真实弧长上下界</th><th>实际走行速度区间</th>
        </tr></thead>
        <tbody>${rows}</tbody>
        <tfoot><tr>
          <td><b>总喷涂时长</b></td>
          <td class="num"><b>${fmt(c.total_duration)}</b></td>
          <td colspan="2" class="sub">速度统一限值闭区间 [${fmt(c.min_speed)}, ${fmt(c.max_speed)}]</td>
        </tr></tfoot>
      </table>
      ${ev}
    </div>`;
}

function renderFail(error) {
  const rows = [];
  const push = (k, v) => rows.push(
    `<div class="row"><span class="k">${k}</span><code>${v}</code></div>`);
  if (error.segment !== null) push("问题段", `第 ${error.segment + 1} 段`);
  if (error.parameter !== null) push("曲线参数 t", fmt(error.parameter, 9));
  if (error.point) push("坐标", `(${fmt(error.point[0], 6)}, ${fmt(error.point[1], 6)})`);
  if (error.curvature !== undefined) push("实际曲率", fmt(error.curvature));
  if (error.max_curvature !== undefined) push("最大曲率", fmt(error.max_curvature));
  if (error.curvature_end !== undefined) {
    push("前段端曲率", fmt(error.curvature_end));
    push("后段端曲率", fmt(error.curvature_start));
  }
  if (error.tangent_end) {
    push("前段端切向量", `(${error.tangent_end.join(", ")})`);
    push("后段端切向量", `(${error.tangent_start.join(", ")})`);
  }
  if (error.point_end) {
    push("前段终点", `(${error.point_end.join(", ")})`);
    push("后段起点", `(${error.point_next.join(", ")})`);
  }
  return `
    <div class="banner fail">✗ 审计不通过（最早问题）：${error.message}</div>
    <div class="detail">
      <div class="row"><span class="k">原因代码</span><code>${error.code}</code></div>
      ${rows.join("")}
    </div>`;
}

async function runAudit() {
  const payload = readPayload();
  const localError = validateDraft(payload);
  const box = $("result");
  box.classList.remove("hidden");
  if (localError) {
    box.innerHTML = `<div class="banner fail">✗ ${localError}</div>`;
    return;
  }
  box.innerHTML = `<div class="banner" style="color:var(--muted);border-color:var(--border);background:var(--panel-2)">正在进行精确根隔离审计${payload.coating ? "与防腐走行复核（真实弧长收敛）" : ""}…</div>`;
  try {
    const res = await fetch("/api/audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json();
    if (!body.ok) {
      invalidateAudit();
      box.innerHTML = renderFail(body.error);
      return;
    }
    state.auditOk = true;
    const toggle = $("coatingEnabled");
    toggle.disabled = false;
    box.innerHTML = renderPass(body);
    if (body.coating) {
      box.insertAdjacentHTML("beforeend", renderCoating(body.coating));
    }
  } catch (err) {
    box.innerHTML = `<div class="banner fail">✗ 无法连接审计服务：${err.message}</div>`;
  }
}

async function checkHealth() {
  const dot = $("healthDot"), text = $("healthText");
  try {
    const res = await fetch("/api/health");
    const body = await res.json();
    dot.className = "dot ok";
    text.textContent = body.status === "ok" ? "审计服务在线" : "服务状态异常";
  } catch {
    dot.className = "dot bad";
    text.textContent = "审计服务不可达";
  }
}

$("auditBtn").addEventListener("click", runAudit);
$("sampleBtn").addEventListener("click", () => {
  $("kmax").value = SAMPLE.max_curvature;
  $("segCount").value = SAMPLE.segments.length;
  renderEditors(SAMPLE.segments.length, SAMPLE.segments.map((s) => s.points));
  invalidateAudit();
  drawPreview();
});
$("segCount").addEventListener("change", (e) => {
  let n = Math.max(2, Math.min(5, Number(e.target.value) || 2));
  e.target.value = n;
  renderEditors(n);
  invalidateAudit();
  drawPreview();
});
$("kmax").addEventListener("input", () =>
  invalidateAudit("最大曲率已修改：审计与复核结论均已撤销，请重新发起审计。"));

$("coatingEnabled").addEventListener("change", (e) => {
  const fields = $("coatingFields");
  fields.classList.toggle("hidden", !e.target.checked);
  // Switching the feature on/off withdraws any displayed verdict until a
  // fresh request certifies it.
  invalidateCoating();
});
$("vmin").addEventListener("input", onTravelParamEdit);
$("vmax").addEventListener("input", onTravelParamEdit);

renderEditors(2, SAMPLE.segments.map((s) => s.points));
$("kmax").value = SAMPLE.max_curvature;
drawPreview();
checkHealth();
setInterval(checkHealth, 10000);
