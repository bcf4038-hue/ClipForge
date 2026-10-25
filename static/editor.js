// ClipForge Editor: a timeline editor for 9:16 videos. Uses helpers from app.js ($, api, waitJob,
// setProgress, errText, fmt, money, state, st, loadSounds, showView).
const ed = {
  p: null,            // the open project
  media: {},          // media id -> {title, duration, media (url), has_audio, ...}
  style: null,        // what ClipForge has learned (null until the first save)
  sel: null,          // {type: "clip" | "text" | "sound" | "music", id}
  time: 0,
  playing: false,
  pps: 70,            // timeline pixels per second
  undo: [],
  audio: {},          // sound path -> Audio, for preview
  soundDur: {},       // sound path -> seconds
  ready: false,
};
const LABEL_W = 70;
const uid = () => Math.random().toString(16).slice(2, 10);
const clipLen = (c) => Math.max(0, c.out - c.in);
const total = () => ed.p.clips.reduce((sum, c) => sum + clipLen(c), 0);
const clipStarts = () => { let t = 0; return ed.p.clips.map((c) => { const s = t; t += clipLen(c); return s; }); };
const cutTimes = () => clipStarts().slice(1);
const findSel = () => {
  if (!ed.sel) return null;
  if (ed.sel.type === "music") return ed.p.music;
  return (ed.p[ed.sel.type + "s"] || []).find((x) => x.id === ed.sel.id) || null;
};
const TEXT_DEFAULT = { text: "Your text", font: "Arial Black", size: 90, color: "#FFFFFF", outline: 8, outline_color: "#000000",
  box: false, box_color: "#000000", box_opacity: 0.6, x: 0.5, y: 0.2, anim: "pop", uppercase: true };
const fonts = () => (st.fonts && st.fonts.length ? st.fonts : ["Arial Black", "Impact", "Segoe UI Black", "Arial"]);

// ---------- undo ----------
function snapshot() {
  ed.undo.push(JSON.stringify(ed.p));
  if (ed.undo.length > 60) ed.undo.shift();
  $("#edUndo").disabled = false;
}
function undo() {
  if (!ed.undo.length) return;
  ed.p = JSON.parse(ed.undo.pop());
  $("#edUndo").disabled = !ed.undo.length;
  if (!findSel()) ed.sel = null;
  refresh();
}

// ---------- projects ----------
async function edLoadList(selectId) {
  const data = await api("/api/editor/projects");
  ed.style = data.style;
  $("#edOpen").innerHTML = `<option value="">Open a project...</option>` +
    data.projects.map((p) => `<option value="${p.id}">${p.name.replace(/</g, "&lt;")} (${p.clips} clips)</option>`).join("");
  $("#edOpen").value = selectId || "";
  edShowLearn();
}
function edShowLearn() {
  const s = ed.style;
  $("#edLearn").textContent = s
    ? `Learned from ${s.projects} project${s.projects > 1 ? "s" : ""}: ~${s.clip_length}s clips` +
      `${s.cut_sound ? ", sound on cuts" : ""}${s.title ? ", title style" : ""}${s.music ? ", music" : ""}`
    : "Save an edit you like and ClipForge starts learning your style.";
  $("#edArrange").disabled = !s;
}
async function edNew() {
  const data = await api("/api/editor/new");
  ed.p = data.project;
  ed.style = data.style;
  ed.media = {};
  ed.undo = [];
  ed.sel = null;
  ed.time = 0;
  $("#edUndo").disabled = true;
  $("#edAudioNew").value = (ed.style && ed.style.audio) || "keep";
  $("#edName").value = ed.p.name;
  $("#edOpen").value = "";
  $("#edResultPanel").classList.add("hidden");
  edShowLearn();
  refresh();
}
async function edOpen(id) {
  if (!id) return;
  const { project } = await api(`/api/editor/project/${id}`);
  const ids = [...new Set(project.clips.map((c) => c.media))];
  const { media } = await api("/api/editor/media", { ids });
  ed.p = project;
  ed.media = media;
  ed.undo = [];
  ed.sel = null;
  ed.time = 0;
  $("#edUndo").disabled = true;
  $("#edName").value = project.name;
  const missing = ids.filter((m) => !media[m]).length;
  setProgress($("#edBinProgress"), missing ? 0 : 1, missing ? `${missing} clip file(s) are missing. Add them again.` : "Project opened.");
  refresh();
}
async function edSave(quiet) {
  ed.p.name = $("#edName").value.trim() || "Untitled";
  const r = await api("/api/editor/save", { project: ed.p });
  ed.style = r.style;
  await edLoadList(ed.p.id);
  if (!quiet) setProgress($("#edBinProgress"), 1, "Saved. ClipForge learned from this edit.");
}

// ---------- media ----------
function addClip(meta) {
  ed.media[meta.id] = meta;
  snapshot();
  const audio = $("#edAudioNew").value;
  ed.p.clips.push({ id: uid(), media: meta.id, in: 0, out: Math.round(meta.duration * 100) / 100, volume: 1,
    audio, framing: (ed.style && ed.style.framing) || "fill", media_duration: meta.duration });
  refresh();
  if (audio === "voice") ensureVoices(meta.id);
}
const audioMode = (c) => c.audio || (c.muted ? "mute" : "keep");
const voicing = new Set();  // media ids being cleaned right now
async function ensureVoices(mid) {
  const m = ed.media[mid];
  if (!m || m.voice || voicing.has(mid)) return;
  if (!m.has_audio) return;
  voicing.add(mid);
  const prog = $("#edBinProgress");
  try {
    const { job } = await api("/api/editor/voice", { media: mid });
    await waitJob(job, prog);
    m.voice = true;
    setProgress(prog, 1, `Background music removed from "${m.title}".`);
  } catch (e) {
    setProgress(prog, 0, errText(e.message));
  } finally {
    voicing.delete(mid);
    refresh();
  }
}
function renderBin() {
  const used = new Set(ed.p.clips.map((c) => c.media));
  const items = Object.values(ed.media);
  $("#edMediaList").innerHTML = items.length ? "" : `<p class="muted small">Clips you add show up here.</p>`;
  items.forEach((m) => {
    const row = document.createElement("div");
    row.className = "ed-item";
    row.innerHTML = `<span><b>${m.title.replace(/</g, "&lt;")}</b><br><span class="muted">${m.duration.toFixed(1)}s${m.has_audio ? "" : ", no audio"}${used.has(m.id) ? ", on timeline" : ""}</span></span>
      <button class="ghost tiny">+ Add</button><span></span>`;
    $("button", row).onclick = () => addClip(m);
    $("#edMediaList").appendChild(row);
  });
  const soundRow = (s, kind) => {
    const row = document.createElement("div");
    row.className = "ed-item";
    row.innerHTML = `<b>${s.name}${s.source === "mine" ? " (mine)" : ""}</b><button class="ghost tiny">Play</button>
      <button class="tiny">${kind === "music" ? "Use" : "+ Add"}</button>`;
    const [play, add] = row.querySelectorAll("button");
    play.onclick = () => playSound(s.id);
    add.onclick = () => {
      snapshot();
      if (kind === "music") {
        ed.p.music = { sound: s.id, volume: (ed.p.music && ed.p.music.volume) || 0.2 };
        ed.sel = { type: "music" };
      } else {
        const item = { id: uid(), sound: s.id, start: Math.round(ed.time * 100) / 100, volume: 0.8 };
        ed.p.sounds.push(item);
        ed.sel = { type: "sound", id: item.id };
      }
      refresh();
    };
    return row;
  };
  $("#edSfxList").replaceChildren(...state.sounds.sfx.map((s) => soundRow(s, "sfx")));
  $("#edMusicList").replaceChildren(...state.sounds.music.map((s) => soundRow(s, "music")));
}
$("#edAddLink").onclick = async () => {
  const url = $("#edUrl").value.trim();
  if (!url) return;
  const from = $("#edFrom").value.trim(), to = $("#edTo").value.trim();
  const prog = $("#edBinProgress");
  $("#edAddLink").disabled = true;
  try {
    const { job } = await api("/api/montage/fetch", { url, start: from ? parseTime(from) : null, end: to ? parseTime(to) : null });
    const meta = await waitJob(job, prog);
    addClip(meta);
    $("#edUrl").value = ""; $("#edFrom").value = ""; $("#edTo").value = "";
    setProgress(prog, 1, `Added "${meta.title}". Paste another link to keep going.`);
  } catch (e) {
    setProgress(prog, 0, errText(e.message));
  } finally {
    $("#edAddLink").disabled = false;
  }
};
$("#edUpload").onchange = async () => {
  const prog = $("#edBinProgress");
  const files = [...$("#edUpload").files];
  $("#edUpload").value = "";
  for (let i = 0; i < files.length; i++) {
    setProgress(prog, i / files.length, `Uploading ${files[i].name}...`);
    const form = new FormData();
    form.append("file", files[i]);
    const res = await fetch("/api/editor/upload", { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { setProgress(prog, 0, `Error: ${data.error || "upload failed"}`); return; }
    addClip(data);
  }
  setProgress(prog, 1, `Added ${files.length} clip${files.length > 1 ? "s" : ""}.`);
};
document.querySelectorAll(".ed-tab").forEach((t) => {
  t.onclick = () => {
    document.querySelectorAll(".ed-tab").forEach((x) => x.classList.toggle("on", x === t));
    document.querySelectorAll(".ed-pane").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== t.dataset.tab));
  };
});
document.querySelectorAll(".ed-preset").forEach((b) => {
  b.onclick = () => {
    const learned = ed.style || {};
    const at = ed.time, starts = clipStarts();
    const idx = Math.max(0, starts.filter((s) => s <= at + 0.001).length - 1);
    const clipEnd = ed.p.clips.length ? starts[idx] + clipLen(ed.p.clips[idx]) : at + 3;
    const presets = {
      title: { ...(learned.title || {}), text: ed.p.name && ed.p.name !== "Untitled" ? ed.p.name : "Top 5 craziest moments",
        y: (learned.title && learned.title.y) || 0.1, size: (learned.title && learned.title.size) || 72,
        box: learned.title ? learned.title.box : true, start: 0, end: Math.max(total(), 3) },
      number: { ...(learned.per_clip || {}), text: "#1", size: (learned.per_clip && learned.per_clip.size) || 220,
        color: (learned.per_clip && learned.per_clip.color) || "#FFE600", y: (learned.per_clip && learned.per_clip.y) || 0.45,
        start: ed.p.clips.length ? starts[idx] : at, end: clipEnd },
      label: { text: "Label", size: 70, y: 0.56, start: ed.p.clips.length ? starts[idx] : at, end: clipEnd },
      caption: { text: "Your text", size: 80, y: 0.75, start: at, end: at + 3 },
    }[b.dataset.preset];
    snapshot();
    const item = { ...TEXT_DEFAULT, ...presets, id: uid() };
    item.start = Math.round(item.start * 100) / 100;
    item.end = Math.round(item.end * 100) / 100;
    ed.p.texts.push(item);
    ed.sel = { type: "text", id: item.id };
    refresh();
  };
});

// ---------- timeline ----------
function laneRows(items, endOf) {
  // Stack overlapping items into rows so nothing hides behind anything else.
  const rows = [];
  const placed = items.slice().sort((a, b) => a.start - b.start).map((it) => {
    let r = rows.findIndex((end) => end <= it.start + 0.001);
    if (r < 0) { r = rows.length; rows.push(0); }
    rows[r] = endOf(it);
    return { it, row: r };
  });
  return { placed, count: Math.max(1, rows.length) };
}
function renderTimeline() {
  const dur = total();
  const width = Math.max((dur + 6) * ed.pps, $("#edTl").clientWidth - LABEL_W);
  $("#edTlInner").style.width = `${width + LABEL_W}px`;
  // Ruler
  const step = ed.pps >= 120 ? 1 : ed.pps >= 50 ? 2 : 5;
  $("#edRuler").innerHTML = "";
  for (let t = 0; t * ed.pps < width; t += step) {
    const tick = document.createElement("span");
    tick.className = "ed-tick";
    tick.style.left = `${t * ed.pps}px`;
    tick.textContent = `${t}s`;
    $("#edRuler").appendChild(tick);
  }
  // Video
  const lane = $("#edLaneClips");
  lane.innerHTML = "";
  const starts = clipStarts();
  ed.p.clips.forEach((c, i) => {
    const m = ed.media[c.media];
    const b = block("clip", c.id, starts[i], clipLen(c), m ? m.title : "Missing clip");
    const mode = audioMode(c);
    const tag = !(m && m.has_audio) || mode === "mute" ? "no audio"
      : mode === "voice" ? (m.voice ? "voices only" : "removing music...") : "";
    if (tag) b.insertAdjacentHTML("beforeend", `<span class="muted-tag">${tag}</span>`);
    addHandles(b, c, "clip");
    lane.appendChild(b);
  });
  // Text
  const tl = laneRows(ed.p.texts, (t) => t.end);
  $("#edLaneTexts").innerHTML = "";
  $("#edLaneTexts").style.height = `${tl.count * 28 + 8}px`;
  tl.placed.forEach(({ it, row }) => {
    const b = block("text", it.id, it.start, it.end - it.start, it.text || "(empty)");
    b.style.top = `${4 + row * 28}px`;
    addHandles(b, it, "text");
    $("#edLaneTexts").appendChild(b);
  });
  // Sounds
  const sl = laneRows(ed.p.sounds, (s) => s.start + soundLength(s.sound));
  $("#edLaneSounds").innerHTML = "";
  $("#edLaneSounds").style.height = `${sl.count * 28 + 8}px`;
  sl.placed.forEach(({ it, row }) => {
    const b = block("sound", it.id, it.start, soundLength(it.sound), it.sound.split("/").pop().replace(/\.\w+$/, ""));
    b.style.top = `${4 + row * 28}px`;
    $("#edLaneSounds").appendChild(b);
  });
  // Music
  $("#edLaneMusic").innerHTML = "";
  if (ed.p.music && ed.p.music.sound) {
    const name = ed.p.music.sound.split("/").pop().replace(/\.\w+$/, "");
    $("#edLaneMusic").appendChild(block("music", "music", 0, Math.max(dur, 1), `${name} (${Math.round(ed.p.music.volume * 100)}%)`));
  }
  movePlayhead();
}
function soundLength(path) {
  if (ed.soundDur[path] === undefined) {
    ed.soundDur[path] = 1;
    const a = new Audio(`/sounds/${path}`);
    a.preload = "metadata";
    a.onloadedmetadata = () => { ed.soundDur[path] = Math.min(a.duration || 1, 8); renderTimeline(); };
  }
  return ed.soundDur[path];
}
function block(type, id, start, len, label) {
  const b = document.createElement("div");
  b.className = `ed-block ${type}${ed.sel && ed.sel.type === type && (type === "music" || ed.sel.id === id) ? " sel" : ""}`;
  b.style.left = `${start * ed.pps}px`;
  b.style.width = `${Math.max(len * ed.pps, 14)}px`;
  b.dataset.type = type;
  b.dataset.id = id;
  b.title = label;
  b.append(document.createTextNode(label));
  return b;
}
function addHandles(b, item, type) {
  ["l", "r"].forEach((side) => {
    const h = document.createElement("span");
    h.className = `ed-handle ${side}`;
    h.dataset.side = side;
    b.appendChild(h);
  });
}
function movePlayhead() {
  $("#edPlayhead").style.left = `${LABEL_W + ed.time * ed.pps}px`;
  $("#edTime").textContent = `${fmt(ed.time)} / ${fmt(total())}`;
}
function timeFromEvent(e) {
  const lane = $("#edLaneClips").getBoundingClientRect();
  return Math.max(0, Math.min(total(), (e.clientX - lane.left) / ed.pps));
}

// One pointer handler for every timeline drag: seek, move, reorder and trim.
$("#edTl").addEventListener("pointerdown", (e) => {
  const blk = e.target.closest(".ed-block");
  if (!blk) {
    if (e.target.closest(".ed-lane")) {
      ed.sel = null;
      seek(timeFromEvent(e));
      refresh();
      const move = (ev) => seek(timeFromEvent(ev));
      const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    }
    return;
  }
  e.preventDefault();
  const type = blk.dataset.type, id = blk.dataset.id;
  ed.sel = { type, id };
  if (type === "music") { refresh(); return; }
  const item = findSel();
  const side = e.target.dataset.side;
  const x0 = e.clientX;
  const orig = JSON.parse(JSON.stringify(item));
  const before = JSON.stringify(ed.p);
  let changed = false;
  blk.classList.add("dragging", "sel");
  const onMove = (ev) => {
    const dt = (ev.clientX - x0) / ed.pps;
    if (Math.abs(ev.clientX - x0) > 3) changed = true;
    if (!changed) return;
    if (type === "clip") {
      const maxOut = (ed.media[item.media] && ed.media[item.media].duration) || item.media_duration || orig.out;
      if (side === "l") item.in = Math.min(Math.max(0, orig.in + dt), item.out - 0.3);
      else if (side === "r") item.out = Math.max(Math.min(maxOut, orig.out + dt), item.in + 0.3);
      else { blk.style.transform = `translateX(${ev.clientX - x0}px)`; return; }
    } else if (type === "text") {
      if (side === "l") item.start = Math.min(Math.max(0, orig.start + dt), item.end - 0.2);
      else if (side === "r") item.end = Math.max(orig.end + dt, item.start + 0.2);
      else { const len = orig.end - orig.start; item.start = Math.max(0, orig.start + dt); item.end = item.start + len; }
    } else if (type === "sound") {
      item.start = Math.max(0, orig.start + dt);
    }
    ["in", "out", "start", "end"].forEach((k) => { if (k in item) item[k] = Math.round(item[k] * 100) / 100; });
    renderTimeline();
    renderStage();
  };
  const onUp = (ev) => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    if (type === "clip" && !side && changed) {
      // Reorder: drop the clip where its middle landed.
      const starts = clipStarts();
      const from = ed.p.clips.indexOf(item);
      const mid = starts[from] + clipLen(item) / 2 + (ev.clientX - x0) / ed.pps;
      let to = starts.filter((s, i) => i !== from && s + clipLen(ed.p.clips[i]) / 2 < mid).length;
      ed.p.clips.splice(from, 1);
      ed.p.clips.splice(to, 0, item);
    }
    if (changed) { ed.undo.push(before); $("#edUndo").disabled = false; }
    refresh();
  };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
});
$("#edZoom").oninput = () => { ed.pps = Number($("#edZoom").value); renderTimeline(); };

// ---------- inspector ----------
function field(label, value, type, onChange, opts = {}) {
  const wrap = document.createElement("label");
  let input;
  if (type === "bool") {
    wrap.className = "check";
    input = document.createElement("input");
    input.type = "checkbox";
    input.checked = !!value;
    wrap.append(input, document.createTextNode(" " + label));
  } else {
    wrap.append(document.createTextNode(label));
    if (type === "select") {
      input = document.createElement("select");
      // Keep values that aren't in the list (like quiz voice lines) instead of silently showing another.
      const options = opts.options.some(([v]) => v === value) || value == null ? opts.options
        : [[value, String(value).split("/").pop().replace(/\.\w+$/, "")], ...opts.options];
      input.innerHTML = options.map(([v, t]) => `<option value="${v}">${t}</option>`).join("");
      input.value = value;
    } else if (type === "textarea") {
      input = document.createElement("textarea");
      input.value = value;
    } else {
      input = document.createElement("input");
      input.type = type === "pct" ? "range" : type === "color" ? "color" : "text";
      if (type === "pct") { input.min = 0; input.max = opts.max || 100; input.value = Math.round(value * 100); }
      else input.value = value;
    }
    wrap.appendChild(input);
  }
  if (opts.wide) wrap.style.gridColumn = "1 / -1";
  let snapped = false;
  const read = () => {
    if (!snapped) { snapshot(); snapped = true; }
    let v = type === "bool" ? input.checked : type === "pct" ? Number(input.value) / 100 : input.value;
    if (type === "num") { v = Number(v); if (Number.isNaN(v)) return; }
    if (type === "time") { v = parseTime(v); if (v === null) return; }
    onChange(v);
    renderTimeline();
    renderStage();
  };
  input.addEventListener(type === "bool" || type === "select" || type === "color" ? "change" : "input", read);
  input.addEventListener("change", () => { snapped = false; });
  return wrap;
}
function renderInspector() {
  const box = $("#edInspector");
  box.innerHTML = "";
  const item = findSel();
  if (!item) {
    $("#edInspTitle").textContent = "Nothing selected";
    box.innerHTML = `<p class="muted small">Click a clip, text or sound on the timeline to change it.</p>`;
    return;
  }
  const grid = document.createElement("div");
  grid.className = "grid";
  const add = (...els) => els.forEach((el) => grid.appendChild(el));
  const buttons = document.createElement("div");
  buttons.className = "row";
  const btn = (text, fn, ghost = true) => {
    const b = document.createElement("button");
    b.textContent = text;
    if (ghost) b.className = "ghost tiny";
    b.onclick = fn;
    buttons.appendChild(b);
  };
  if (ed.sel.type === "clip") {
    const m = ed.media[item.media] || { title: "Missing clip", duration: item.out };
    $("#edInspTitle").textContent = "Clip";
    box.insertAdjacentHTML("beforeend", `<p class="small"><b>${m.title.replace(/</g, "&lt;")}</b><br><span class="muted">Source is ${m.duration.toFixed(1)}s long</span></p>`);
    add(field("Start in source", fmt(item.in), "time", (v) => { item.in = Math.min(Math.max(0, v), item.out - 0.3); }),
      field("End in source", fmt(item.out), "time", (v) => { item.out = Math.max(Math.min(m.duration, v), item.in + 0.3); }),
      field("Original audio", audioMode(item), "select", (v) => { item.audio = v; delete item.muted; if (v === "voice") ensureVoices(item.media); },
        { options: [["keep", "Keep everything"], ["voice", "Remove background music (keep voices)"], ["mute", "Mute"]], wide: true }),
      field("Volume", item.volume, "pct", (v) => { item.volume = v; }, { max: 150 }),
      field("Framing", item.framing || "fill", "select", (v) => { item.framing = v; },
        { options: [["fill", "Fill the screen"], ["fit", "Whole frame + blur"]] }));
    btn("Split at playhead", splitAtPlayhead);
    btn("Duplicate", () => { snapshot(); const i = ed.p.clips.indexOf(item); ed.p.clips.splice(i + 1, 0, { ...item, id: uid() }); refresh(); });
  } else if (ed.sel.type === "text") {
    $("#edInspTitle").textContent = "Text";
    add(field("Text", item.text, "textarea", (v) => { item.text = v; }, { wide: true }),
      field("Font", item.font, "select", (v) => { item.font = v; }, { options: fonts().map((f) => [f, f]) }),
      field("Size", item.size, "num", (v) => { item.size = Math.max(20, Math.min(400, v)); }),
      field("Color", item.color, "color", (v) => { item.color = v; }),
      field("Outline", item.outline, "num", (v) => { item.outline = Math.max(0, Math.min(40, v)); }),
      field("Outline color", item.outline_color, "color", (v) => { item.outline_color = v; }),
      field("Box behind", item.box, "bool", (v) => { item.box = v; }),
      field("Box color", item.box_color, "color", (v) => { item.box_color = v; }),
      field("Box opacity", item.box_opacity, "pct", (v) => { item.box_opacity = v; }),
      field("Animation", item.anim, "select", (v) => { item.anim = v; }, { options: [["pop", "Pop in"], ["fade", "Fade"], ["none", "None"]] }),
      field("ALL CAPS", item.uppercase, "bool", (v) => { item.uppercase = v; }),
      field("Shows from", fmt(item.start), "time", (v) => { item.start = Math.min(Math.max(0, v), item.end - 0.2); }),
      field("Until", fmt(item.end), "time", (v) => { item.end = Math.max(v, item.start + 0.2); }));
    btn("Whole video", () => { snapshot(); item.start = 0; item.end = Math.max(total(), 1); refresh(); });
    btn("Duplicate", () => { snapshot(); const copy = { ...item, id: uid(), y: Math.min(0.95, item.y + 0.08) }; ed.p.texts.push(copy); ed.sel = { type: "text", id: copy.id }; refresh(); });
  } else if (ed.sel.type === "sound") {
    $("#edInspTitle").textContent = "Sound effect";
    add(field("Sound", item.sound, "select", (v) => { item.sound = v; }, { options: state.sounds.sfx.map((s) => [s.id, s.name]), wide: true }),
      field("Starts at", fmt(item.start), "time", (v) => { item.start = Math.max(0, v); }),
      field("Volume", item.volume, "pct", (v) => { item.volume = v; }, { max: 150 }));
    btn("Play", () => playSound(item.sound));
    btn("Move to playhead", () => { snapshot(); item.start = Math.round(ed.time * 100) / 100; refresh(); });
  } else if (ed.sel.type === "music") {
    $("#edInspTitle").textContent = "Music";
    add(field("Track", item.sound, "select", (v) => { item.sound = v; }, { options: state.sounds.music.map((s) => [s.id, s.name]), wide: true }),
      field("Volume", item.volume, "pct", (v) => { item.volume = v; }, { max: 100 }));
    btn("Play", () => playSound(item.sound));
  }
  btn("Delete", deleteSel);
  box.append(grid, buttons);
}
function deleteSel() {
  if (!ed.sel) return;
  snapshot();
  if (ed.sel.type === "music") ed.p.music = null;
  else ed.p[ed.sel.type + "s"] = ed.p[ed.sel.type + "s"].filter((x) => x.id !== ed.sel.id);
  ed.sel = null;
  refresh();
}
function splitAtPlayhead() {
  const starts = clipStarts();
  const i = starts.findIndex((s, k) => ed.time > s + 0.15 && ed.time < s + clipLen(ed.p.clips[k]) - 0.15);
  if (i < 0) return;
  snapshot();
  const c = ed.p.clips[i];
  const cut = Math.round((c.in + ed.time - starts[i]) * 100) / 100;
  const second = { ...c, id: uid(), in: cut };
  c.out = cut;
  ed.p.clips.splice(i + 1, 0, second);
  ed.sel = { type: "clip", id: second.id };
  refresh();
}

// ---------- preview ----------
const video = $("#edVideo");
function clipAt(t) {
  const starts = clipStarts();
  for (let i = ed.p.clips.length - 1; i >= 0; i--) if (t >= starts[i] - 0.0001) return { c: ed.p.clips[i], local: t - starts[i] };
  return null;
}
function syncVideo(force) {
  const hit = ed.p.clips.length ? clipAt(Math.min(ed.time, total() - 0.01)) : null;
  $("#edEmpty").classList.toggle("hidden", !!hit);
  if (!hit) { video.removeAttribute("src"); return; }
  const m = ed.media[hit.c.media];
  if (!m) return;
  const want = hit.c.in + hit.local;
  if (!video.src.endsWith(m.media)) {
    video.src = m.media;
    video.onloadedmetadata = () => { video.currentTime = want; if (ed.playing) video.play().catch(() => {}); };
  } else if (force || Math.abs(video.currentTime - want) > 0.3) {
    video.currentTime = want;
  }
  video.classList.toggle("fit", hit.c.framing === "fit");
  const mode = audioMode(hit.c);
  // "Voices only": play the cleaned track in sync and silence the video's own audio.
  const useVoice = mode === "voice" && m.voice;
  video.volume = Math.min(1, mode === "mute" ? 0 : hit.c.volume);
  video.muted = mode === "mute" || hit.c.volume === 0 || useVoice;
  if (useVoice) {
    const url = `/voice/${m.id}`;
    if (!voiceEl.src.endsWith(url)) voiceEl.src = url;
    voiceEl.volume = Math.min(1, hit.c.volume);
    if (force || Math.abs(voiceEl.currentTime - want) > 0.3) voiceEl.currentTime = want;
    if (ed.playing && voiceEl.paused) voiceEl.play().catch(() => {});
    if (!ed.playing && !voiceEl.paused) voiceEl.pause();
  } else if (!voiceEl.paused) {
    voiceEl.pause();
  }
}
const voiceEl = new Audio();
// The preview shows the very same images the export uses, so the two always match.
const textCache = new Map();  // look of a text -> {url, w, h}
function textImage(t) {
  const key = JSON.stringify(["text", "font", "size", "color", "outline", "outline_color", "box", "box_color",
    "box_opacity", "uppercase"].map((k) => t[k]));
  if (!textCache.has(key)) {
    if (textCache.size > 300) textCache.clear();
    textCache.set(key, rasterText(t));
  }
  return textCache.get(key);
}
document.fonts.addEventListener("loadingdone", () => { textCache.clear(); if (ed.p) renderStage(); });
function renderStage() {
  const stage = $("#edStage");
  const scale = stage.clientWidth / 1080;
  const box = $("#edTexts");
  box.innerHTML = "";
  ed.p.texts.filter((t) => ed.time >= t.start && ed.time < t.end && String(t.text || "").trim()).forEach((t) => {
    const img = textImage(t);
    const el = document.createElement("img");
    el.className = `ed-text${ed.sel && ed.sel.type === "text" && ed.sel.id === t.id ? " sel" : ""}`;
    el.src = img.url;
    el.alt = t.text;
    el.draggable = false;
    el.style.left = `${t.x * 100}%`;
    el.style.top = `${t.y * 100}%`;
    el.style.width = `${img.w * scale}px`;
    el.style.height = `${img.h * scale}px`;
    el.dataset.id = t.id;
    box.appendChild(el);
  });
}
// Drag text on the preview to place it.
$("#edTexts").addEventListener("pointerdown", (e) => {
  const el = e.target.closest(".ed-text");
  if (!el || ed.playing) return;
  e.preventDefault();
  const t = ed.p.texts.find((x) => x.id === el.dataset.id);
  ed.sel = { type: "text", id: t.id };
  snapshot();
  const rect = $("#edStage").getBoundingClientRect();
  const move = (ev) => {
    t.x = Math.round(Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width)) * 1000) / 1000;
    t.y = Math.round(Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height)) * 1000) / 1000;
    renderStage();
  };
  const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); refresh(); };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
  renderInspector();
  renderStage();
});
function seek(t) {
  ed.time = Math.max(0, Math.min(t, total()));
  syncVideo(true);
  renderStage();
  movePlayhead();
}
let lastFrame = 0, music = null;
function tick(now) {
  if (!ed.playing) return;
  const prev = ed.time;
  ed.time += (now - lastFrame) / 1000;
  lastFrame = now;
  if (ed.time >= total()) { ed.time = total(); stop(); movePlayhead(); return; }
  ed.p.sounds.forEach((s) => { if (s.start > prev && s.start <= ed.time) fire(s.sound, s.volume); });
  syncVideo(false);
  renderStage();
  movePlayhead();
  requestAnimationFrame(tick);
}
function fire(path, volume) {
  const a = new Audio(`/sounds/${path}`);
  a.volume = Math.min(1, volume);
  a.play().catch(() => {});
}
function play() {
  if (!ed.p.clips.length) return;
  if (ed.time >= total() - 0.05) ed.time = 0;
  ed.playing = true;
  $("#edPlay").textContent = "Pause";
  syncVideo(true);
  video.play().catch(() => {});
  ed.p.sounds.filter((s) => Math.abs(s.start - ed.time) < 0.02).forEach((s) => fire(s.sound, s.volume));
  if (ed.p.music && ed.p.music.sound) {
    music = new Audio(`/sounds/${ed.p.music.sound}`);
    music.loop = true;
    music.volume = Math.min(1, ed.p.music.volume);
    music.onloadedmetadata = () => { music.currentTime = ed.time % (music.duration || 1); };
    music.play().catch(() => {});
  }
  lastFrame = performance.now();
  requestAnimationFrame(tick);
}
function stop() {
  ed.playing = false;
  $("#edPlay").textContent = "Play";
  video.pause();
  voiceEl.pause();
  if (music) { music.pause(); music = null; }
}
$("#edPlay").onclick = () => (ed.playing ? stop() : play());
$("#edSplit").onclick = splitAtPlayhead;
$("#edDelete").onclick = deleteSel;
$("#edUndo").onclick = undo;
$("#edNew").onclick = () => { stop(); edNew(); };
$("#edOpen").onchange = () => { stop(); edOpen($("#edOpen").value); };
$("#edName").oninput = () => { ed.p.name = $("#edName").value; scheduleAutosave(); };
$("#edSave").onclick = () => edSave(false).catch((e) => setProgress($("#edBinProgress"), 0, errText(e.message)));
$("#edArrange").onclick = async () => {
  try {
    const { project } = await api("/api/editor/arrange", { project: ed.p });
    snapshot();
    ed.p = project;
    ed.sel = null;
    refresh();
    setProgress($("#edBinProgress"), 1, "Re-cut in your style. Ctrl+Z puts it back.");
  } catch (e) {
    setProgress($("#edBinProgress"), 0, errText(e.message));
  }
};
$("#edRender").onclick = async () => {
  stop();
  const prog = $("#edRenderProgress");
  $("#edResultPanel").classList.remove("hidden");
  $("#edRender").disabled = true;
  try {
    await edSave(true);
    setProgress(prog, 0.01, "Drawing your text...");
    const text_images = await rasterTexts();
    const { job } = await api("/api/editor/render", { project: ed.p, text_images });
    const r = await waitJob(job, prog);
    setProgress(prog, 1, "Done! Saved in the output folder.");
    $("#edResults").innerHTML = `<div class="result"><video src="/output/${encodeURIComponent(r.file)}?t=${Date.now()}" controls preload="metadata"></video>
      <div><b>${(r.title || r.file).replace(/</g, "&lt;")}</b><br><span class="muted small">${r.file}</span><br>
      <a class="dl" href="/output/${encodeURIComponent(r.file)}?download=1">Download MP4</a></div></div>`;
    $("#edResultPanel").scrollIntoView({ behavior: "smooth" });
  } catch (e) {
    setProgress(prog, 0, errText(e.message));
  } finally {
    $("#edRender").disabled = false;
  }
};
document.addEventListener("keydown", (e) => {
  // Shortcuts pause only while typing; sliders and checkboxes keep them working.
  const typing = e.target.closest("textarea, select, input[type=text], input[type=password]");
  if ($("#view-edit").classList.contains("hidden") || typing) return;
  if (e.key === " ") { e.preventDefault(); ed.playing ? stop() : play(); }
  else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); deleteSel(); }
  else if (e.key.toLowerCase() === "s" && !e.ctrlKey) splitAtPlayhead();
  else if (e.key.toLowerCase() === "z" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); undo(); }
});

// ---------- exact text for the export ----------
// The export uses these images, drawn by the same browser that draws the preview, so fonts,
// outlines and color emoji come out exactly as you see them.
function hexAlpha(hex, opacity) {
  const h = hex.replace("#", "");
  return `rgba(${parseInt(h.slice(0, 2), 16)}, ${parseInt(h.slice(2, 4), 16)}, ${parseInt(h.slice(4, 6), 16)}, ${opacity})`;
}
function rasterText(t) {
  const text = t.uppercase ? t.text.toUpperCase() : t.text;
  const lines = text.split("\n");
  const font = `${t.size}px "${t.font}", "Arial Black", sans-serif`;
  const canvas = document.createElement("canvas");
  const g = canvas.getContext("2d");
  g.font = font;
  const lineH = t.size * 1.1;  // matches the preview's line-height
  const stroke = t.box ? 0 : t.outline * 2;
  const padX = (t.box ? 18 : 6) + stroke / 2, padY = (t.box ? 12 : 2) + stroke / 2;
  const width = Math.max(...lines.map((l) => g.measureText(l).width), 1);
  canvas.width = Math.ceil(width + padX * 2);
  canvas.height = Math.ceil(lineH * lines.length + padY * 2);
  g.font = font;
  g.textAlign = "center";
  g.textBaseline = "middle";
  if (t.box) {
    g.fillStyle = hexAlpha(t.box_color, t.box_opacity);
    g.fillRect(0, 0, canvas.width, canvas.height);
  }
  lines.forEach((line, i) => {
    const y = padY + lineH * (i + 0.5);
    if (stroke) {
      g.lineJoin = "round";
      g.lineWidth = stroke;
      g.strokeStyle = t.outline_color;
      g.strokeText(line, canvas.width / 2, y);
    }
    g.fillStyle = t.color;
    g.fillText(line, canvas.width / 2, y);
  });
  return { url: canvas.toDataURL("image/png"), w: canvas.width, h: canvas.height };
}
async function rasterTexts() {
  const out = {};
  for (const t of ed.p.texts) {
    if (!String(t.text || "").trim()) continue;
    try { await document.fonts.load(`${t.size}px "${t.font}"`); } catch (e) { /* use the fallback font */ }
    out[t.id] = rasterText(t).url;
  }
  return out;
}

// ---------- autosave ----------
// Saves a few seconds after every change, so closing the page never loses work.
let autosaveTimer = null, lastSaved = "";
function scheduleAutosave() {
  clearTimeout(autosaveTimer);
  autosaveTimer = setTimeout(async () => {
    if (!ed.p || !ed.p.clips.length) return;
    const snap = JSON.stringify(ed.p);
    if (snap === lastSaved) return;
    try {
      ed.p.name = $("#edName").value.trim() || "Untitled";
      await api("/api/editor/save", { project: ed.p, autosave: true });
      lastSaved = snap;
      $("#edSaved").textContent = `Autosaved ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
    } catch (e) {
      $("#edSaved").textContent = "Autosave failed. Click Save.";
    }
  }, 2500);
}

function refresh() {
  scheduleAutosave();
  if (ed.time > total()) ed.time = total();
  renderBin();
  renderTimeline();
  renderInspector();
  syncVideo(false);
  renderStage();
}
window.edOnShow = async () => {
  if (!ed.ready) {
    ed.ready = true;
    await edLoadList();
    // Pick up where you left off: open the most recent project if there is one.
    const latest = [...$("#edOpen").options].find((o) => o.value);
    if (latest) { await edOpen(latest.value); $("#edOpen").value = latest.value; }
    else await edNew();
  } else {
    refresh();
  }
};
window.edOnHide = () => stop();
// Open a project made somewhere else (like the quiz maker) and optionally export it right away.
window.edOpenProject = async (id, render) => {
  ed.ready = true;
  await edLoadList(id);
  await edOpen(id);
  showView("edit");
  if (render) $("#edRender").click();
};
