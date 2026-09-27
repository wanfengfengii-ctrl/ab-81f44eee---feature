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

function renderEditors(n, values) {
  const points = values || defaultPoints(n);
  segCountEl.innerHTML = "";
  points.forEach((pts, i) => segCountEl.appendChild(makeSegmentEditor(i, pts)));
  segCountEl.querySelectorAll("input").forEach((el) =>
    el.addEventListener("input", () => {
      drawPreview();
      invalidateCoating("控制点已修改");
    }));
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
  return { segments, max_curvature: Number($("kmax").value) };
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
  return null;
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

// ---------- anti-corrosion travel review ------------------------------------

const coatingPanel = $("coatingPanel");
const coatingEnabled = $("coatingEnabled");
const coatingForm = $("coatingForm");
const segmentTimesEl = $("segmentTimes");
const vminEl = $("vmin");
const vmaxEl = $("vmax");
let auditSignature = "";

function draftSignature(payload) {
  return JSON.stringify({ s: payload.segments, k: payload.max_curvature });
}

function buildTimeInputs(n) {
  segmentTimesEl.innerHTML = "";
  for (let i = 0; i < n; i++) {
    const cell = document.createElement("label");
    cell.className = "time-cell";
    cell.innerHTML =
      `<span>第 ${i + 1} 段</span>` +
      `<input type="number" step="1" min="1" value="1" data-seg="${i}" ` +
      `aria-label="第 ${i + 1} 段喷涂时长">`;
    segmentTimesEl.appendChild(cell);
  }
  segmentTimesEl.querySelectorAll("input").forEach((el) =>
    el.addEventListener("input", () => invalidateCoating("走行参数已修改")));
}

function invalidateCoating(reason) {
  const old = $("coatingResult");
  if (old && old.children.length > 0) {
    old.innerHTML =
      `<div class="banner warn">⚠ ${reason}，上一条防腐走行复核结论已撤销，` +
      `请重新发起审计并运行复核。</div>`;
  }
}

function resetCoatingUI() {
  auditSignature = "";
  coatingEnabled.checked = false;
  coatingPanel.classList.add("hidden");
  coatingForm.classList.add("hidden");
  const old = $("coatingResult");
  if (old) old.innerHTML = "";
}

function validateReviewParams() {
  const vmin = Number(vminEl.value);
  const vmax = Number(vmaxEl.value);
  if (!Number.isFinite(vmin) || !Number.isFinite(vmax) || vmin <= 0 || vmax <= 0) {
    return "最小、最大允许喷涂速度必须为有限正数。";
  }
  if (vmin > vmax) return "最小允许喷涂速度不得大于最大允许喷涂速度。";
  const times = [];
  for (const el of segmentTimesEl.querySelectorAll("input")) {
    const t = Number(el.value);
    if (!Number.isInteger(t) || t <= 0) {
      return `第 ${Number(el.dataset.seg) + 1} 段喷涂时长必须为正整数。`;
    }
    times.push(t);
  }
  return null;
}

function statusLabel(status) {
  return {
    certified: ["✓ 认证通过", "ok"],
    too_fast: ["✗ 过快", "bad"],
    too_slow: ["✗ 过慢", "bad"],
    insufficient_margin: ["⚠ 余量不足", "warn"],
    not_converged: ["⚠ 未收敛", "warn"],
  }[status] || [status, "warn"];
}

function renderCoating(cr) {
  const rows = cr.segments.map((s) => {
    const [label, cls] = statusLabel(s.status);
    return `
    <tr>
      <td>第 ${s.index + 1} 段</td>
      <td class="num">${s.time}</td>
      <td class="num">[${fmt(s.arc_length.lower, 9)}, ${fmt(s.arc_length.upper, 9)}]
        <span class="sub">误差 ≤ ${fmt(s.arc_length.error, 3)}</span></td>
      <td class="num">[${fmt(s.speed.lower, 9)}, ${fmt(s.speed.upper, 9)}]</td>
      <td class="st-${cls}">${label}</td>
    </tr>`;
  }).join("");

  let banner;
  if (cr.certified) {
    banner = `<div class="banner pass">✓ 防腐走行复核认证通过：各段推导出的整个速度区间均位于闭区间 ` +
      `[${fmt(cr.min_speed)}, ${fmt(cr.max_speed)}] 内。</div>`;
  } else {
    const e = cr.error;
    const name = {
      TOO_FAST: "走行过快", TOO_SLOW: "走行过慢",
      INSUFFICIENT_MARGIN: "安全余量不足",
      NOT_CONVERGED: "弧长包围未收敛",
    }[e.code] || e.code;
    banner = `<div class="banner fail">✗ 不予认证 · 首个问题为第 ${e.segment + 1} 段（${name}）：${e.message || ""}</div>
      <div class="detail">
        <div class="row"><span class="k">原因代码</span><code>${e.code}</code></div>
        <div class="row"><span class="k">速度证据</span><code>[${fmt(e.speed_lower, 9)}, ${fmt(e.speed_upper, 9)}]</code></div>
        <div class="row"><span class="k">允许闭区间</span><code>[${fmt(e.min_speed)}, ${fmt(e.max_speed)}]</code></div>
        <div class="row"><span class="k">弧长范围</span><code>[${fmt(e.arc_length_lower, 9)}, ${fmt(e.arc_length_upper, 9)}]</code></div>
        <div class="row"><span class="k">建议时长窗</span><code>${
          e.time_window_feasible
            ? `[${fmt(e.time_window_lower, 6)}, ${fmt(e.time_window_upper, 6)}]（整数时长落入此窗可使整段速度处于限值内）`
            : "当前弧长不确定度下无整段可行的整数时长窗，须先增加安全余量"}</code></div>
      </div>`;
  }

  return `
    <div id="coatingResult" class="coating-result">
      ${banner}
      <table>
        <thead><tr>
          <th>段落</th><th>喷涂时长</th><th>真实弧长范围（长度）</th>
          <th>实际走行速度范围（长度/时间）</th><th>结论</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="total-line">总喷涂时长：<b>${cr.total_time}</b> 个时间单位
        （最小/最大允许速度：${fmt(cr.min_speed)} / ${fmt(cr.max_speed)}）</div>
      <p class="hint">弧长由服务端按三次贝塞尔连续真实弧长给出可收敛的严格上下界，
        未使用控制多边形、屏幕绘制或固定参数采样。</p>
    </div>`;
}

async function runCoatingReview() {
  const payload = readPayload();
  const localError = validateDraft(payload) || validateReviewParams();
  if (localError) {
    $("coatingResult").outerHTML =
      `<div id="coatingResult"><div class="banner fail">✗ ${localError}</div></div>`;
    return;
  }
  if (draftSignature(payload) !== auditSignature) {
    $("coatingResult").outerHTML =
      `<div id="coatingResult"><div class="banner fail">✗ 控制点或最大曲率自上次审计后已修改，请先重新“发起审计”。</div></div>`;
    return;
  }
  payload.coating_review = {
    enabled: true,
    segment_times: [...segmentTimesEl.querySelectorAll("input")].map((el) => Number(el.value)),
    min_speed: Number(vminEl.value),
    max_speed: Number(vmaxEl.value),
  };
  const box = $("coatingResult");
  box.innerHTML = `<div class="banner" style="color:var(--muted);border-color:var(--border);background:var(--panel-2)">正在计算各段真实弧长的严格上下界…</div>`;
  try {
    const res = await fetch("/api/audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json();
    if (!body.ok) {
      box.innerHTML = `<div class="banner fail">✗ 审计已不再通过，请重新发起审计后再复核。</div>`;
      resetCoatingUI();
      return;
    }
    box.outerHTML = renderCoating(body.coating_review);
  } catch (err) {
    box.innerHTML = `<div class="banner fail">✗ 无法连接审计服务：${err.message}</div>`;
  }
}

coatingEnabled.addEventListener("change", () => {
  coatingForm.classList.toggle("hidden", !coatingEnabled.checked);
  const box = $("coatingResult");
  if (box) box.innerHTML = "";
});
[vminEl, vmaxEl].forEach((el) =>
  el.addEventListener("input", () => invalidateCoating("走行参数已修改")));
$("reviewBtn").addEventListener("click", runCoatingReview);

async function runAudit() {
  const payload = readPayload();
  const localError = validateDraft(payload);
  const box = $("result");
  box.classList.remove("hidden");
  if (localError) {
    box.innerHTML = `<div class="banner fail">✗ ${localError}</div>`;
    resetCoatingUI();
    return;
  }
  resetCoatingUI();
  box.innerHTML = `<div class="banner" style="color:var(--muted);border-color:var(--border);background:var(--panel-2)">正在进行精确根隔离审计…</div>`;
  try {
    const res = await fetch("/api/audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await res.json();
    box.innerHTML = body.ok ? renderPass(body) : renderFail(body.error);
    if (body.ok) {
      // Only a passing audit unlocks the anti-corrosion travel review.
      auditSignature = draftSignature(payload);
      coatingPanel.classList.remove("hidden");
      buildTimeInputs(body.segments.length);
    } else {
      coatingPanel.classList.add("hidden");
    }
  } catch (err) {
    box.innerHTML = `<div class="banner fail">✗ 无法连接审计服务：${err.message}</div>`;
    resetCoatingUI();
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
  drawPreview();
  resetCoatingUI();
});
$("kmax").addEventListener("input", () => invalidateCoating("走行参数已修改"));
$("segCount").addEventListener("change", (e) => {
  let n = Math.max(2, Math.min(5, Number(e.target.value) || 2));
  e.target.value = n;
  renderEditors(n);
  drawPreview();
  resetCoatingUI();
});

resetCoatingUI();
renderEditors(2, SAMPLE.segments.map((s) => s.points));
$("kmax").value = SAMPLE.max_curvature;
drawPreview();
checkHealth();
setInterval(checkHealth, 10000);
