/* 참가자 진행 페이지 (정적 버전). 서버 없이 동작한다.
   - 진행 상태는 이 브라우저의 localStorage 에 번호별로 저장된다 (새로고침해도 이어진다).
   - 마지막 단계에서 기록 전체를 JSON 파일로 내려받아 연구자에게 보낸다.
   - 설정, 단원 구조, 연습 세트, 시험 문항, 입력 텍스트는 data.js 에서 읽는다 (tools/build_docs_data.py 로 생성). */
(function () {
  "use strict";
  const D = window.FRAME_DATA;
  const CFG = D.config;
  const STAGES = ["pre", "s1_source", "s1_warning", "s1_practice", "s1_judge", "s1_test",
                  "s2_source", "s2_warning", "s2_practice", "s2_judge", "s2_test", "post", "done"];
  const FORMATS = ["개념 확인", "자료 해석", "계산", "서술형", "탐구 설계"];
  const CIRC = "①②③④⑤";
  const app = document.getElementById("app");
  let timer = null;

  // ---------- 작은 도구 ----------
  const now = () => { const d = new Date(), p = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; };
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  function mulberry32(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  function assignment(pid) {
    // P001.. 번호에서 집단과 순서를 결정한다. 4명 블록마다 네 칸을 섞으므로 균형 배정이다.
    const m = /^P(\d{3})$/.exec(pid); if (!m) return null;
    const n = parseInt(m[1], 10); if (n < 1 || n > (CFG.max_participants || 200)) return null;
    const cells = [["warn","ai_first"],["warn","exam_first"],["ctrl","ai_first"],["ctrl","exam_first"]];
    const block = Math.floor((n - 1) / 4), rng = mulberry32((CFG.seed || 1) + block * 7919);
    for (let i = cells.length - 1; i > 0; i--) { const j = Math.floor(rng() * (i + 1)); [cells[i], cells[j]] = [cells[j], cells[i]]; }
    const [group, order] = cells[(n - 1) % 4];
    return { group, order };
  }
  const key = pid => "frame:" + pid;
  function loadRec(pid) { try { const s = localStorage.getItem(key(pid)); return s ? JSON.parse(s) : null; } catch (e) { return null; } }
  function saveRec(rec) { rec.updated = now(); try { localStorage.setItem(key(rec.id), JSON.stringify(rec)); } catch (e) { alert("이 브라우저에 저장할 수 없습니다. 연구자에게 알려 주세요."); } remoteSave(rec); }
  // 연구자 노트북의 로컬 서버(local_server.py)가 있으면 기록을 그쪽에도 저장한다. 없으면(예: GitHub Pages) 조용히 넘어간다.
  const remote = { ok: null };
  function remoteSave(rec) { try { return fetch("save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(rec) })
    .then(r => { remote.ok = r.ok; return r.ok; }).catch(() => { remote.ok = false; return false; }); } catch (e) { remote.ok = false; return Promise.resolve(false); } }
  function advance(rec, to) { rec.events.push({ ts: now(), from: rec.stage, to }); rec.stage = to; saveRec(rec); render(); }
  const sessionKey = st => st.startsWith("s1") ? "A" : "B";
  const sessionSource = (rec, k) => { const first = rec.order === "ai_first" ? "ai" : "exam"; return k === "A" ? first : (first === "ai" ? "exam" : "ai"); };
  const unitOf = k => CFG.units[k];
  const shortName = u => u.includes(" ") ? u.split(" ").slice(1).join(" ") : u;
  const pagesOf = u => { const x = D.units[u]; return x ? `${x.start}~${x.end}` : ""; };
  const promptFor = u => CFG.prompt_template.replace("{unit}", shortName(u)).replace("{pages}", pagesOf(u));
  function download(name, text) { const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], { type: "application/json" })); a.download = name; document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500); }

  // ---------- 지표 (파이썬 metrics.py 와 같은 규칙) ----------
  const PUNCT = /[\s\.,;:!?\(\)\[\]{}「」『』“”‘’"'·…ㆍ\-–—\/\\|~^*_=+<>①②③④⑤]/g;
  const normalize = s => String(s || "").replace(PUNCT, "");
  function ngrams(s, n) { s = normalize(s); const out = new Set(); if (s.length < n) { if (s) out.add(s); return out; } for (let i = 0; i <= s.length - n; i++) out.add(s.slice(i, i + n)); return out; }
  function containment(text, unitSet, n) { const g = ngrams(text, n || 4); if (!g.size) return 0; let hit = 0; g.forEach(x => { if (unitSet.has(x)) hit++; }); return hit / g.size; }
  const UNIT_WORDS = /\d+(\.\d+)?\s*(g|kg|mg|mL|L|J|kJ|W|kW|kWh|%|℃|°C|mol|M|N|m|cm|km|s|초|분|년|배|개|ppm|V|A)(?![A-Za-z])/;
  const CALC_WORDS = ["구하시오","계산","몇 ","얼마","비율은","효율은","농도는","질량은","부피는","에너지는 몇"];
  const DATA_WORDS = ["표","그래프","그림","자료","다음은","다음과 같이","실험 결과","(가)","(나)","A~","ㄱ.","보기"];
  const DESIGN_WORDS = ["설계","실험 방법","탐구 과정","가설을","변인"];
  function classifyFormat(stem, type, optionsText) { const s = stem || "", both = s + " " + (optionsText || "");
    if (DESIGN_WORDS.some(w => s.includes(w))) return "탐구 설계";
    if (type === "서술형" || ["서술하시오","설명하시오","서술하","설명하"].some(w => s.includes(w))) return DATA_WORDS.some(w => s.includes(w)) ? "자료 해석" : "서술형";
    if (UNIT_WORDS.test(both) || CALC_WORDS.some(w => s.includes(w))) return "계산";
    if (DATA_WORDS.some(w => s.includes(w))) return "자료 해석";
    return "개념 확인"; }
  function distribution(labels) { const c = {}; labels.forEach(l => c[l] = (c[l] || 0) + 1); const t = Math.max(1, labels.length); const out = {}; FORMATS.forEach(k => out[k] = (c[k] || 0) / t); return out; }
  function tvDistance(p, q) { let s = 0; FORMATS.forEach(k => s += Math.abs((p[k] || 0) - (q[k] || 0))); return s / 2; }
  function localMetrics(items, unitText, objectives, pastFormats) {
    const idx = ngrams(unitText || "", 4);
    const rows = items.map(it => { const txt = it.stem + " " + (it.options || []).join(" ");
      return { id: it.id, type: it.type, format: classifyFormat(it.stem, it.type, (it.options || []).join(" ")), overlap4: +containment(txt, idx, 4).toFixed(3), mentions_textbook: it.stem.includes("교과서") ? 1 : 0, has_answer: it.answer ? 1 : 0 }; });
    const fdist = distribution(rows.map(r => r.format));
    const out = { n_items: items.length, n_mc: rows.filter(r => r.type === "객관식").length, n_sa: rows.filter(r => r.type === "서술형").length,
      mean_overlap4: +(rows.reduce((a, r) => a + r.overlap4, 0) / Math.max(1, rows.length)).toFixed(3),
      high_overlap_ratio: +(rows.filter(r => r.overlap4 > 0.6).length / Math.max(1, rows.length)).toFixed(3),
      textbook_mentions: rows.filter(r => r.mentions_textbook).map(r => r.id), missing_answers: rows.filter(r => !r.has_answer).map(r => r.id), format_dist: fdist, rows };
    if (pastFormats && pastFormats.length) { const pf = distribution(pastFormats); out.past_format_dist = pf; out.format_tv_vs_past = +tvDistance(fdist, pf).toFixed(3); out.format_short = FORMATS.filter(k => (fdist[k] || 0) - (pf[k] || 0) < -0.1); }
    if (objectives && objectives.length) { const og = objectives.map(o => [o.id, ngrams(o.text, 3)]); const tags = {};
      items.forEach(it => { const g = ngrams(it.stem + " " + (it.options || []).join(" "), 3); let best = "none", bs = 0;
        og.forEach(([oid, s]) => { if (!s.size) return; let hit = 0; g.forEach(x => { if (s.has(x)) hit++; }); const sc = hit / s.size; if (sc > bs) { bs = sc; best = oid; } });
        tags[it.id] = bs >= 0.10 ? best : "none"; });
      const covered = new Set(Object.values(tags).filter(x => x !== "none"));
      out.objective_tags = tags; out.coverage_ratio = +(covered.size / objectives.length).toFixed(3); out.missing_objectives = objectives.filter(o => !covered.has(o.id)); }
    return out; }

  // ---------- 챗 앱 출력 파서 (파이썬 local_tools.parse_ai_output 과 같은 규칙) ----------
  const NUM = /^\s*(?:\*\*)?(?:#+\s*)?(?:문제|문항|Q|q)?\s*(\d{1,2})\s*(?:[\.\)\]번:：]|\*\*)\s*(.*)$/;
  const OPT = /^\s*(?:\*\*)?(?:[\(\[]?([1-5])[\)\]\.]|([①②③④⑤]))\s*(?:\*\*)?\s*(.+)$/;
  const ANS = /^\s*(?:\*\*)?(?:정답|답)\s*(?:\*\*)?\s*[:：]?\s*(?:\*\*)?\s*(.*)$/;
  const ANS_NUM = /[\(\[]?([1-5])[\)\]]?\s*번?|([①②③④⑤])/;
  const EXPL = /^\s*(?:\*\*)?(?:해설|풀이|설명|근거)\s*(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*(.*)$/;
  const MODEL = /^\s*(?:\*\*)?(?:모범\s*답안|예시\s*답안|모범답)\s*(?:\*\*)?\s*[:：]?\s*(?:\*\*)?\s*(.*)$/;
  const SECTION = /^\s*(?:#+\s*|\*\*|\[|【)?\s*(객관식|서술형|선택형|주관식)/i;
  const META = /^\s*(?:난이도|유형|출제\s*의도|관련\s*단원|사고\s*수준)\s*[:：]/;
  const INLINE = /(?:(?<=\s)|^)(?:[\(\[]([1-5])[\)\]]|([①②③④⑤]))\s*/g;
  const clean = s => String(s || "").replace(/\*\*|__|`/g, "").trim();
  function explode(text) { const out = [];
    for (const raw of text.replace(/\r/g, "").split("\n")) { const line = raw.replace(/\s+$/, "");
      if (/(정답|답)\s*[:：]/.test(line) && line.includes("해설")) { const i = line.search(/해설\s*[:：]/); if (i > 0) { out.push(line.slice(0, i).replace(/\s+$/, "")); out.push(line.slice(i)); continue; } }
      const marks = [...line.matchAll(INLINE)];
      if (marks.length >= 3) { const head = line.slice(0, marks[0].index).replace(/\s+$/, ""); if (head) out.push(head);
        marks.forEach((m, i) => { const end = i + 1 < marks.length ? marks[i + 1].index : line.length; const label = m[1] || m[2];
          out.push(m[1] ? `${label}) ${line.slice(m.index + m[0].length, end).trim()}` : `${label} ${line.slice(m.index + m[0].length, end).trim()}`); });
        continue; }
      out.push(line); }
    return out; }
  function parseAI(text) { const items = []; let cur = null;
    for (const line of explode(text)) { if (!line.trim()) continue;
      if (SECTION.test(line) && clean(line).length < 25) continue;
      if (META.test(line)) continue;
      const mn = NUM.exec(line), mo = OPT.exec(line);
      if (mn) { const n = parseInt(mn[1], 10);
        const isOpt = cur && mo && !cur.answer && n <= 5 && n === cur.options.length + 1 && (cur.options.length > 0 || n === 1);
        if (!isOpt && (!cur || n > cur.id || n === 1)) { cur = { id: n, type: "객관식", stem: clean(mn[2]), options: [], answer: "", explanation: "" }; items.push(cur); continue; } }
      if (!cur) continue;
      const ma = ANS.exec(line);
      if (ma) { const a = clean(ma[1]); const m = ANS_NUM.exec(a); if (cur.options.length && m) cur.answer = m[1] || String(CIRC.indexOf(m[2]) + 1); else cur.answer = a; continue; }
      const mm = MODEL.exec(line); if (mm) { cur.answer = clean(mm[1]); cur.type = "서술형"; continue; }
      const me = EXPL.exec(line); if (me) { cur.explanation = (cur.explanation + " " + clean(me[1])).trim(); continue; }
      if (mo && !cur.answer && cur.options.length < 5) { cur.options.push(clean(mo[3])); continue; }
      if (cur.explanation) cur.explanation += " " + clean(line);
      else if (cur.answer && cur.type === "서술형") cur.answer += " " + clean(line);
      else if (cur.options.length) cur.options[cur.options.length - 1] += " " + clean(line);
      else cur.stem = (cur.stem + " " + clean(line)).trim(); }
    items.forEach((it, i) => { it.id = i + 1;
      if (it.options.length >= 2) { it.type = "객관식"; if (it.answer && !"12345".includes(it.answer)) { const m = ANS_NUM.exec(it.answer); it.answer = m ? (m[1] || String(CIRC.indexOf(m[2]) + 1)) : ""; } }
      else { it.type = "서술형"; it.options = []; } });
    return items.filter(it => it.stem); }

  // ---------- 화면 ----------
  function shell(inner, rec) { const idx = rec ? STAGES.indexOf(rec.stage) : -1;
    const head = rec ? `<p class="muted">참가자 ${esc(rec.id)} · 진행 ${idx + 1}/${STAGES.length}</p><div class="progress"><div style="width:${((idx + 1) / STAGES.length * 100).toFixed(0)}%"></div></div>` : "";
    app.innerHTML = head + inner + `<p class="foot">기록은 이 브라우저에만 저장되고, 마지막에 JSON 파일로 내려받아 연구자에게 보냅니다. <a href="researcher.html">연구자용</a></p>`; }
  function sliderRow(id, label, min, max, val, step) { return `<label for="${id}">${label} <span class="slider-val" id="${id}_v">${val}</span></label><input type="range" id="${id}" min="${min}" max="${max}" step="${step || 1}" value="${val}" oninput="document.getElementById('${id}_v').textContent=this.value">`; }
  const val = id => document.getElementById(id).value;

  function pageLogin() { shell(`<h1>${esc(CFG.title)}</h1><p>연구자가 알려 준 참가자 번호를 입력하고 시작을 누르세요. 중간에 창이 닫혀도 같은 번호로 다시 들어오면 이어서 할 수 있습니다.</p>
    <div class="card"><label for="pid">참가자 번호 (예: P001)</label><input type="text" id="pid" autocomplete="off"><p class="err" id="login_err"></p><div class="row" style="margin-top:10px"><button class="primary" id="login_btn">시작</button></div></div>`);
    const go = () => { const pid = val("pid").trim().toUpperCase(); const a = assignment(pid);
      if (!a) { document.getElementById("login_err").textContent = "등록되지 않은 번호입니다. 연구자에게 번호를 다시 확인해 주세요."; return; }
      let rec = loadRec(pid); if (!rec) { rec = { id: pid, group: a.group, order: a.order, stage: "pre", created: now(), pre_survey: {}, sessions: { A: {}, B: {} }, post_survey: {}, events: [] }; saveRec(rec); }
      sessionStorage.setItem("frame:pid", pid); render(); };
    document.getElementById("login_btn").onclick = go; document.getElementById("pid").addEventListener("keydown", e => { if (e.key === "Enter") go(); }); }

  function pagePre(rec) { const opts = CFG.ai_options.map(o => `<label class="opt"><input type="checkbox" name="apps" value="${esc(o)}">${esc(o)}</label>`).join("");
    const sel = CFG.ai_options.map(o => `<option>${esc(o)}</option>`).join("");
    shell(`<h2>시작 전 짧은 설문</h2><div class="card"><label>평소 공부할 때 쓰는 AI (모두 고르세요)</label>${opts}
      <label for="pre_other">'기타'를 골랐다면 이름</label><input type="text" id="pre_other">
      <label for="pre_main">가장 자주 쓰는 AI</label><select id="pre_main">${sel}</select>
      <label for="pre_freq">AI를 공부에 쓰는 빈도</label><select id="pre_freq"><option>거의 안 씀</option><option>한 달에 몇 번</option><option selected>일주일에 몇 번</option><option>거의 매일</option></select>
      ${sliderRow("pre_trust", "AI가 알려 주는 공부 내용을 믿는 편이다 (1 전혀 아니다 ~ 7 매우 그렇다)", 1, 7, 4)}
      ${sliderRow("pre_verify", "AI 답을 교과서나 다른 자료로 확인하는 편이다", 1, 7, 4)}
      ${sliderRow("pre_conf", "이 과목에 자신이 있다", 1, 7, 4)}
      <div class="row" style="margin-top:14px"><button class="primary" id="go">저장하고 다음</button></div></div>`, rec);
    document.getElementById("go").onclick = () => { rec.pre_survey = { apps: [...document.querySelectorAll('input[name=apps]:checked')].map(x => x.value), other: val("pre_other"), main_app: val("pre_main"), freq: val("pre_freq"), trust: +val("pre_trust"), verify: +val("pre_verify"), confidence: +val("pre_conf"), ts: now() }; advance(rec, "s1_source"); }; }

  function pageSource(rec) { const k = sessionKey(rec.stage), unit = unitOf(k), src = sessionSource(rec, k), n = k === "A" ? 1 : 2;
    if (src === "ai") { const sel = CFG.ai_options.map(o => `<option>${esc(o)}</option>`).join("");
      shell(`<h2>${n}번째 공부: ${esc(shortName(unit))} 단원</h2><div class="card"><ol><li>평소 쓰는 AI 앱을 열고 <b>새 대화</b>를 시작하세요.</li><li>아래 문장을 그대로 복사해서 보내세요.</li><li>AI가 준 답 <b>전체</b>를 복사해서 아래 칸에 붙여 넣으세요. 답이 중간에 끊기면 '이어서 보여줘'라고 한 뒤 이어 붙이세요.</li></ol>
        <pre class="prompt" id="prompt">${esc(promptFor(unit))}</pre><div class="row"><button id="copy">문장 복사</button><span class="muted" id="copied"></span></div>
        <label for="app">어떤 AI를 썼나요?</label><select id="app">${sel}</select>
        <label for="app_other">'기타'이면 이름</label><input type="text" id="app_other">
        <label for="model">모델 이름 (화면에 보이면 적어 주세요. 몰라도 됩니다)</label><input type="text" id="model">
        <label for="raw">AI가 준 답 전체 붙여넣기</label><textarea id="raw"></textarea>
        <label class="opt" style="display:block"><input type="checkbox" id="force">문항 수가 부족해도 그대로 진행 (연구자 확인 후에만 체크)</label>
        <p class="err" id="src_err"></p><div class="row"><button class="primary" id="go">저장하고 다음</button></div></div>`, rec);
      document.getElementById("copy").onclick = () => { navigator.clipboard.writeText(promptFor(unit)).then(() => document.getElementById("copied").textContent = "복사됨", () => document.getElementById("copied").textContent = "직접 드래그해서 복사해 주세요"); };
      document.getElementById("go").onclick = () => { const raw = val("raw"); if (!raw.trim()) { document.getElementById("src_err").textContent = "붙여 넣은 내용이 없습니다."; return; }
        const items = parseAI(raw); const force = document.getElementById("force").checked;
        if (items.length < CFG.min_items && !force) { document.getElementById("src_err").textContent = `문항이 ${items.length}개만 인식됐습니다. AI에게 '20문항을 모두 다시 보여줘'라고 요청해서 전체를 다시 붙여 넣어 주세요. 문항이 분명히 다 있는데도 이 말이 나오면 연구자를 불러 주세요.`; return; }
        const m = localMetrics(items, D.unit_text[unit] || "", (D.objectives || {})[unit] || [], (D.past_formats || {})[unit] || []);
        const rows = m.rows; delete m.rows;
        rec.sessions[k] = { unit, source: "ai", ai_app: val("app"), ai_app_other: val("app_other"), ai_model: val("model"), raw, parsed: items, n_parsed: items.length, parse_ok: items.length >= 10, forced: force, metrics: m, metric_rows: rows, warning: { shown: rec.group === "warn" }, practice: {}, judge: {}, test: {}, ts: now() };
        advance(rec, rec.group === "warn" ? `s${n}_warning` : `s${n}_practice`); }; }
    else { shell(`<h2>${n}번째 공부: ${esc(shortName(unit))} 단원</h2><div class="card"><p>이번 단원은 연구자가 준비한 연습 문제로 공부합니다. 다음을 누르면 문제가 나옵니다.</p><div class="row"><button class="primary" id="go">다음</button></div></div>`, rec);
      document.getElementById("go").onclick = () => { rec.sessions[k] = { unit, source: "exam", warning: { shown: false }, practice: {}, judge: {}, test: {}, ts: now() }; advance(rec, `s${n}_practice`); }; } }

  function pageWarning(rec) { const k = sessionKey(rec.stage), s = rec.sessions[k], m = s.metrics, n = k === "A" ? 1 : 2;
    if (!s.warning.shown_at) { s.warning.shown_at = now(); s.warning._t0 = Date.now(); saveRec(rec); }
    const notes = [];
    if (m.mean_overlap4 > 0.6 || m.high_overlap_ratio > 0.3) notes.push("교과서 문장을 거의 그대로 묻는 문항이 많습니다. 다른 표현으로 나오는 문제에도 답할 수 있는지 스스로 확인해 보세요.");
    if (m.missing_objectives && m.missing_objectives.length) notes.push("이 세트가 다루지 않은 학습목표: " + m.missing_objectives.slice(0, 6).map(o => o.text).join("; "));
    if (m.format_short && m.format_short.length) notes.push("기출에 비해 부족한 형식: " + m.format_short.join(", "));
    if (m.textbook_mentions.length) notes.push(`'교과서에 나온 것은?'처럼 교과서 자체를 가리키는 문항 [${m.textbook_mentions.join(", ")}]: 실제 시험에는 나오지 않는 형태입니다.`);
    if (m.missing_answers.length) notes.push(`정답이 안 보이는 문항 [${m.missing_answers.join(", ")}]`);
    if (m.n_mc < 16 || m.n_sa < 4) notes.push(`인식된 문항: 객관식 ${m.n_mc}개, 서술형 ${m.n_sa}개`);
    shell(`<h2>받은 문제 세트 검사 결과</h2><div class="card"><p>붙여 넣은 문제를 교과서 범위와 시험 형식에 비추어 확인한 결과입니다. 읽고 나서 아래 버튼을 누르면 연습이 시작됩니다.</p>
      <div class="metrics"><div class="metric"><b>${m.mean_overlap4.toFixed(2)}</b><span>교과서 문장 겹침</span></div><div class="metric"><b>${m.coverage_ratio == null ? "-" : Math.round(m.coverage_ratio * 100) + "%"}</b><span>학습목표 덮임(근사)</span></div><div class="metric"><b>${m.format_tv_vs_past == null ? "-" : m.format_tv_vs_past.toFixed(2)}</b><span>기출과 형식 거리</span></div></div>
      ${notes.length ? notes.map(t => `<div class="warn">${esc(t)}</div>`).join("") : `<div class="ok">눈에 띄는 점은 없습니다. 그래도 정답과 해설이 맞는지는 보장되지 않습니다.</div>`}
      <div class="row" style="margin-top:12px"><button class="primary" id="go">확인했습니다. 연습 시작</button></div></div>`, rec);
    document.getElementById("go").onclick = () => { s.warning.confirmed_at = now(); s.warning.dwell_s = s.warning._t0 ? +((Date.now() - s.warning._t0) / 1000).toFixed(1) : null; delete s.warning._t0; advance(rec, `s${n}_practice`); }; }

  // 문항에 img 가 있으면 원본 문항 이미지를 보여 준다 (그림, 숫자, 화학식이 그대로 보이도록)
  const itemBody = it => it.img ? `<div><b>${it.id}.</b></div><img class="qimg" src="${esc(it.img)}" alt="${it.id}번 문항">` : `<div><b>${it.id}.</b> ${esc(it.stem)}</div>${it.options && it.options.length ? `<div class="opts">${it.options.map((o, i) => `<div>${i + 1}) ${esc(o)}</div>`).join("")}</div>` : ""}`;
  const ansText = a => /^[1-5]$/.test(String(a || "")) ? `${a}번` : (a || "(없음)");
  function renderItems(items, showAnswers) { return items.map(it => `<div class="item">${itemBody(it)}${showAnswers ? `<details><summary>정답과 해설</summary><p>정답: ${esc(ansText(it.answer))}</p>${it.explanation ? `<p>해설: ${esc(it.explanation)}</p>` : ""}</details>` : ""}</div>`).join(""); }

  function pagePractice(rec) { const k = sessionKey(rec.stage), s = rec.sessions[k], unit = s.unit, n = k === "A" ? 1 : 2; const pr = s.practice;
    if (!pr.started_at) { pr.started_at = now(); pr._t0 = Date.now(); pr.confirm_count = 0; saveRec(rec); }
    const items = s.source === "ai" ? (s.parse_ok ? s.parsed : null) : (D.practice_sets[unit] || []);
    shell(`<h2>연습: ${esc(shortName(unit))} 단원 (${CFG.practice_minutes}분)</h2><p class="muted">시작 ${pr.started_at.slice(11, 16)} · 지금까지 약 <span id="elapsed">0</span>분 · 문제를 풀고 '정답과 해설'을 열어 확인하세요. 연습 중에는 AI에게 질문하지 않습니다.</p>
      <div class="row"><button id="confirm">교과서를 찾아봤다 (+1) · 현재 <span id="cc">${pr.confirm_count}</span>회</button><button class="primary" id="end">연습 끝내기</button></div>
      <div class="card" style="margin-top:14px">${items ? renderItems(items, true) : `<p class="muted">문항을 자동으로 나누지 못해 받은 답을 그대로 보여 줍니다.</p><pre class="prompt">${esc(s.raw)}</pre>`}</div>`, rec);
    const tick = () => { const el = document.getElementById("elapsed"); if (el) el.textContent = Math.floor((Date.now() - (pr._t0 || Date.now())) / 60000); };
    clearInterval(timer); timer = setInterval(tick, 10000); tick();
    document.getElementById("confirm").onclick = () => { pr.confirm_count = (pr.confirm_count || 0) + 1; document.getElementById("cc").textContent = pr.confirm_count; saveRec(rec); };
    document.getElementById("end").onclick = () => { clearInterval(timer); pr.ended_at = now(); pr.elapsed_min = +((Date.now() - (pr._t0 || Date.now())) / 60000).toFixed(1); delete pr._t0; advance(rec, `s${n}_judge`); }; }

  function pageJudge(rec) { const k = sessionKey(rec.stage), s = rec.sessions[k], n = k === "A" ? 1 : 2;
    shell(`<h2>연습을 마친 뒤의 생각</h2><div class="card"><p>곧 이 단원의 시험을 봅니다. ${CFG.test_items_note || "20문항이고 100점 만점입니다."}</p>
      ${sliderRow("pred", "이 단원 시험에서 몇 점을 받을 것 같나요?", 0, 100, 50, 5)}
      ${sliderRow("ready", "이 단원 시험 준비가 됐다고 느낀다 (1 전혀 ~ 7 매우)", 1, 7, 4)}
      ${sliderRow("sim", "방금 푼 연습 문제가 실제 시험과 비슷할 것 같다", 1, 7, 4)}
      ${sliderRow("ktrust", "연습 문제의 정답과 해설을 믿었다", 1, 7, 4)}
      <div class="row" style="margin-top:14px"><button class="primary" id="go">저장하고 시험 시작</button></div></div>`, rec);
    document.getElementById("go").onclick = () => { s.judge = { predicted: +val("pred"), readiness: +val("ready"), similar: +val("sim"), key_trust: +val("ktrust"), ts: now() }; advance(rec, `s${n}_test`); }; }

  function pageTest(rec) { const k = sessionKey(rec.stage), s = rec.sessions[k], unit = s.unit, items = D.tests[unit] || [];
    shell(`<h2>시험: ${esc(shortName(unit))} 단원 (${CFG.test_minutes}분)</h2><p class="muted">교과서, 필기, AI는 쓰지 않습니다. 모든 객관식에 답해야 제출됩니다.</p><div class="card">
      ${items.map(it => it.type === "객관식" ? `<div class="item">${it.img ? itemBody(it) : `<div><b>${it.id}.</b> ${esc(it.stem)}</div>`}<div class="row">${(it.options && it.options.length ? it.options : ["","","","",""]).map((o, i) => `<label class="opt" style="flex:1;min-width:${it.img ? "56px" : "100%"}"><input type="radio" name="q${it.id}" value="${i + 1}">${it.img ? CIRC[i] : `${i + 1}) ${esc(o)}`}</label>`).join("")}</div></div>` : `<div class="item">${itemBody(it)}<textarea id="sa${it.id}" style="min-height:90px"></textarea></div>`).join("")}
      <p class="err" id="test_err"></p><div class="row"><button class="primary" id="go">제출</button></div></div>`, rec);
    document.getElementById("go").onclick = () => { const answers = {}; const missing = [];
      items.forEach(it => { if (it.type === "객관식") { const r = document.querySelector(`input[name=q${it.id}]:checked`); answers[it.id] = r ? r.value : ""; if (!r) missing.push(it.id); } else answers[it.id] = val(`sa${it.id}`); });
      if (missing.length) { document.getElementById("test_err").textContent = `답하지 않은 객관식: [${missing.join(", ")}]`; return; }
      const mc = items.filter(it => it.type === "객관식"); const correct = mc.filter(it => answers[it.id] === String(it.answer)).length;
      s.test = { answers, mc_correct: correct, mc_total: mc.length, mc_pct: +(100 * correct / Math.max(1, mc.length)).toFixed(1), n_sa: items.length - mc.length, ts: now() };
      advance(rec, rec.stage === "s1_test" ? "s2_source" : "post"); }; }

  function pagePost(rec) { shell(`<h2>마지막 설문</h2><div class="card"><label>AI가 만든 문제 중에 틀렸거나 이상한 문항이 있었다고 생각하나요?</label>${["예","아니오","잘 모르겠다","AI 문제를 받지 않았다"].map(o => `<label class="opt"><input type="radio" name="saw" value="${o}">${o}</label>`).join("")}
      <label for="which">있었다면 몇 번이었나요? (기억나는 대로)</label><input type="text" id="which">
      <label>연습 중에 AI에게 질문한 적이 있나요? (솔직하게 답해도 불이익이 없습니다)</label>${["없다","한두 번","여러 번"].map(o => `<label class="opt"><input type="radio" name="used" value="${o}">${o}</label>`).join("")}
      <label for="comment">공부하면서 느낀 점 (자유롭게)</label><textarea id="comment" style="min-height:90px"></textarea>
      <p class="err" id="post_err"></p><div class="row"><button class="primary" id="go">제출</button></div></div>`, rec);
    document.getElementById("go").onclick = () => { const saw = document.querySelector("input[name=saw]:checked"), used = document.querySelector("input[name=used]:checked");
      if (!saw || !used) { document.getElementById("post_err").textContent = "두 질문에 모두 답해 주세요."; return; }
      rec.post_survey = { saw_errors: saw.value, which: val("which"), used_ai_in_practice: used.value, comment: val("comment"), ts: now() }; advance(rec, "done"); }; }

  function pageDone(rec) { const json = JSON.stringify(rec, null, 1);
    shell(`<div class="ok">참여해 주셔서 고맙습니다. 모든 과정이 끝났습니다.</div><div class="card"><h3>기록 보내기</h3><p id="rs" class="muted">저장 상태 확인 중...</p><p>아래 버튼을 누르면 <b>${esc(rec.id)}.json</b> 파일이 내려받아집니다. 연구자가 요청하면 그 파일을 보내 주세요. 내려받기가 안 되면 아래 상자의 내용을 전부 복사해서 보내도 됩니다.</p>
      <div class="row"><button class="primary" id="dl">JSON 파일 내려받기</button><button id="cp">내용 복사</button><span class="muted" id="cpmsg"></span></div>
      <textarea id="json" style="min-height:160px;margin-top:10px" readonly>${esc(json)}</textarea></div>
      <div class="card"><h3>연구 설명</h3><p>${esc(CFG.debrief)}</p><p class="muted">이 창은 닫아도 됩니다.</p></div>`, rec);
    remoteSave(rec).then(ok => { const el = document.getElementById("rs"); if (el) el.textContent = ok ? "기록이 연구자 컴퓨터에 자동 저장되었습니다. 파일 내려받기는 예비용입니다." : "자동 저장 서버가 없습니다. 아래에서 파일을 내려받아 연구자에게 보내 주세요."; });
    document.getElementById("dl").onclick = () => download(`${rec.id}.json`, json);
    document.getElementById("cp").onclick = () => { navigator.clipboard.writeText(json).then(() => document.getElementById("cpmsg").textContent = "복사됨", () => { const t = document.getElementById("json"); t.select(); document.getElementById("cpmsg").textContent = "상자 내용을 Ctrl+C 로 복사하세요"; }); }; }

  function render() { const pid = sessionStorage.getItem("frame:pid"); const rec = pid ? loadRec(pid) : null;
    if (!rec) { pageLogin(); return; }
    const st = rec.stage;
    if (st === "pre") pagePre(rec); else if (st.endsWith("_source")) pageSource(rec); else if (st.endsWith("_warning")) pageWarning(rec);
    else if (st.endsWith("_practice")) pagePractice(rec); else if (st.endsWith("_judge")) pageJudge(rec); else if (st.endsWith("_test")) pageTest(rec);
    else if (st === "post") pagePost(rec); else pageDone(rec);
    window.scrollTo(0, 0); }
  window.FRAME = { parseAI, localMetrics, assignment };
  render();
})();
