// ClipForge front end: analyze a video, review AI clip picks, style them, render.
const $ = (s, el = document) => el.querySelector(s);
const state = { project: null, clips: [], sounds: { sfx: [], music: [] }, voices: [], player: null, playerReady: false, stopAt: null };

// ---------- helpers ----------
const fmt = (sec) => {
  sec = Math.max(0, sec);
  const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = (sec % 60).toFixed(1).padStart(4, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
};
const parseTime = (txt) => {
  const parts = String(txt).trim().split(":").map(Number);
  if (parts.some(isNaN)) return null;
  return parts.reduce((acc, p) => acc * 60 + p, 0);
};
async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}
function setProgress(el, p, msg) {
  el.classList.remove("hidden");
  $(".bar", el).style.width = `${Math.round(p * 100)}%`;
  $("span", el).textContent = msg;
}
async function waitJob(id, el, what) {
  let asked = false;
  for (;;) {
    const job = await api(`/api/job/${id}`);
    setProgress(el, job.progress, job.status === "error" ? errText(job.error) : job.message);
    if (job.status === "needs_approval" && !asked) {
      asked = true;
      showApproval(id, job.approval, what);
    }
    if (job.status === "done") { loadUsage(); return job.result; }
    if (job.status === "error") { loadUsage(); throw new Error(job.error); }
    await new Promise((r) => setTimeout(r, 800));
  }
}

const errText = (msg) => (msg.startsWith("Cancelled") ? msg : `Error: ${msg}`);

// ---------- spending & approval ----------
const money = (n) => `$${n.toFixed(n < 1 ? 3 : 2)}`;
function showApproval(jobId, a, what = "Finding clips in this video") {
  const over = a.max > a.remaining;
  $("#approvalWhat").textContent = what;
  $("#approvalText").innerHTML = `
    <p>Claude will read about <b>${a.input_tokens.toLocaleString()}</b> tokens.</p>
    <p class="big-cost">Usually ${money(a.low)} to ${money(a.typical_high)}</p>
    <p class="muted">Absolute maximum: ${money(a.max)}</p>
    <p>Spent so far: ${money(a.spent)} of your ${money(a.budget)} budget. Left: <b>${money(Math.max(a.remaining, 0))}</b></p>
    ${over ? `<p class="over">Warning: this could go over your budget. If your Anthropic credit runs out, the request just fails and nothing more is charged.</p>` : ""}`;
  $("#approvalBackdrop").classList.remove("hidden");
  const answer = async (approve) => {
    $("#approvalBackdrop").classList.add("hidden");
    await api(`/api/job/${jobId}/answer`, { approve });
  };
  $("#approveYes").onclick = () => answer(true);
  $("#approveNo").onclick = () => answer(false);
}
async function loadUsage() {
  const u = await api("/api/usage");
  const badge = $("#spendBadge");
  badge.textContent = `AI spend: ${money(u.spent)} of ${money(u.budget)}`;
  badge.classList.toggle("low", u.remaining < u.budget * 0.2);
  $("#budget").value = u.budget;
  $("#usageTable").innerHTML = u.entries.length
    ? `<tr><th>When</th><th>Video</th><th>Tokens in / out</th><th>Cost</th></tr>` +
      u.entries.map((e) => `<tr><td>${e.time}</td><td>${e.title.replace(/</g, "&lt;")}</td>
        <td>${e.input_tokens.toLocaleString()} / ${e.output_tokens.toLocaleString()}</td><td>${money(e.cost)}</td></tr>`).join("")
    : `<tr><td class="muted">Nothing spent yet.</td></tr>`;
}
$("#spendBadge").onclick = () => $("#usagePanel").classList.toggle("hidden");
$("#saveBudget").onclick = async () => {
  await api("/api/config", { budget: $("#budget").value });
  loadUsage();
};
const saveKey = () => state.project && `clipforge:${state.project.video_id}`;
function persist() {
  try { if (saveKey()) localStorage.setItem(saveKey(), JSON.stringify(state.clips)); } catch (e) { /* storage unavailable */ }
}
function wordsText(start, end) {
  return state.project.words.filter((w) => w.s >= start - 0.05 && w.s < end).map((w) => w.w).join(" ");
}

// ---------- settings & status ----------
async function loadStatus() {
  const s = await api("/api/status");
  $("#keyHint").textContent = s.has_key ? `(saved key ${s.key_hint})` : "(not set)";
  $("#ytBrowser").value = s.yt_browser;
  $("#cookieStatus").textContent = s.has_cookies ? "cookies.txt saved (used instead of the browser login)" : "";
  $("#removeCookies").classList.toggle("hidden", !s.has_cookies);
  const warns = [];
  if (!s.ffmpeg) warns.push("FFmpeg was not found. Close this app and run install.bat again.");
  if (!s.has_key) warns.push('No API key yet. Click Settings (top right) and paste your Anthropic API key.');
  $("#warnings").innerHTML = warns.map((w) => `<div class="warn">${w}</div>`).join("");
  if (!s.has_key) $("#settings").classList.remove("hidden");
}
$("#settingsBtn").onclick = () => $("#settings").classList.toggle("hidden");
$("#saveKey").onclick = async () => {
  await api("/api/config", { api_key: $("#apiKey").value });
  $("#apiKey").value = "";
  $("#settings").classList.add("hidden");
  loadStatus();
};

$("#ytBrowser").onchange = () => api("/api/config", { yt_browser: $("#ytBrowser").value }).then(loadStatus);
$("#cookieFile").onchange = async () => {
  const form = new FormData();
  form.append("file", $("#cookieFile").files[0]);
  await fetch("/api/cookies", { method: "POST", body: form });
  $("#cookieFile").value = "";
  loadStatus();
};
$("#removeCookies").onclick = () => fetch("/api/cookies", { method: "POST" }).then(loadStatus);

// ---------- sounds ----------
async function loadSounds() {
  state.sounds = await api("/api/sounds");
  const label = (s) => `${s.name}${s.source === "mine" ? " (mine)" : " (starter)"}`;
  let cur = $("#music").value;
  try { cur = cur || (JSON.parse(localStorage.getItem("clipforge:style") || "{}").music ?? ""); } catch (e) { /* ignore */ }
  $("#music").innerHTML = `<option value="">No music</option>` +
    state.sounds.music.map((s) => `<option value="${s.id}">${label(s)}</option>`).join("");
  if (cur) $("#music").value = cur;
  document.querySelectorAll(".sfx select").forEach((sel) => fillSfxSelect(sel, sel.value));
}
function fillSfxSelect(sel, value) {
  sel.innerHTML = state.sounds.sfx.map((s) =>
    `<option value="${s.id}">${s.name}${s.source === "mine" ? " (mine)" : ""}</option>`).join("");
  if (value) sel.value = value;
}
let audioEl = null;
function playSound(id) {
  if (audioEl) audioEl.pause();
  audioEl = new Audio(`/sounds/${id}`);
  audioEl.volume = 0.8;
  audioEl.play();
}
$("#previewMusic").onclick = () => {
  if (audioEl && !audioEl.paused) { audioEl.pause(); return; }
  if ($("#music").value) playSound($("#music").value);
};
document.querySelectorAll(".upload input").forEach((inp) => {
  inp.onchange = async () => {
    const form = new FormData();
    form.append("kind", inp.dataset.kind);
    [...inp.files].forEach((f) => form.append("files", f));
    await fetch("/api/sounds/upload", { method: "POST", body: form });
    inp.value = "";
    loadSounds();
  };
});

// ---------- YouTube preview player ----------
function loadPlayerApi() {
  return new Promise((resolve) => {
    if (window.YT && YT.Player) return resolve();
    window.onYouTubeIframeAPIReady = resolve;
    const s = document.createElement("script");
    s.src = "https://www.youtube.com/iframe_api";
    document.head.appendChild(s);
  });
}
let stopTimer = null;
function watchStopAt() {
  if (stopTimer) return;
  stopTimer = setInterval(() => {
    if (state.stopAt !== null && state.playerReady && state.player.getCurrentTime() >= state.stopAt) {
      state.player.pauseVideo();
      state.stopAt = null;
    }
  }, 200);
}
function resetPlayerBox() {
  state.player = null;
  state.playerReady = false;
  $("#playerWrap").innerHTML = `<div id="player"></div>`;
}
async function setupPlayer(videoId) {
  watchStopAt();
  if (videoId.startsWith("local_")) {
    // Uploaded file: a plain <video> wrapped to look like the YouTube player.
    resetPlayerBox();
    const v = document.createElement("video");
    v.src = `/media/${videoId}`;
    v.controls = true;
    v.style.width = "100%";
    v.style.height = "100%";
    $("#playerWrap").replaceChildren(v);
    state.player = {
      local: true,
      seekTo: (t) => { v.currentTime = t; },
      playVideo: () => v.play().catch(() => {}),
      pauseVideo: () => v.pause(),
      getCurrentTime: () => v.currentTime,
    };
    state.playerReady = true;
    return;
  }
  if (state.player && state.player.local) resetPlayerBox();
  await loadPlayerApi();
  if (state.player) { state.player.cueVideoById(videoId); return; }
  state.player = new YT.Player("player", {
    videoId, playerVars: { rel: 0, modestbranding: 1 },
    events: {
      onReady: () => { state.playerReady = true; },
      onError: () => {
        $("#playerWrap").innerHTML = `<p style="padding:16px">This video can't be previewed here.
          <a target="_blank" href="${state.project.url}">Open it on YouTube</a> to check timestamps.</p>`;
      },
    },
  });
}
const playerTime = () => (state.playerReady ? state.player.getCurrentTime() : null);
function previewRange(start, end) {
  if (!state.playerReady) return;
  state.player.seekTo(start, true);
  state.player.playVideo();
  state.stopAt = end;
}

// ---------- clip cards ----------
function renderClips() {
  const box = $("#clips");
  box.innerHTML = "";
  state.clips.forEach((clip) => box.appendChild(clipCard(clip)));
  updateRenderBtn();
}
function updateRenderBtn() {
  const n = state.clips.filter((c) => c.approved).length;
  $("#renderBtn").textContent = n ? `Render ${n} approved clip${n > 1 ? "s" : ""}` : "Approve at least one clip";
  $("#renderBtn").disabled = !n;
}
function clipCard(clip) {
  const el = $("#clipTpl").content.firstElementChild.cloneNode(true);
  const sync = () => {
    $(".start", el).value = fmt(clip.start);
    $(".end", el).value = fmt(clip.end);
    $(".len", el).textContent = `${(clip.end - clip.start).toFixed(1)}s`;
    el.classList.toggle("on", !!clip.approved);
    if (clip.caption_text == null) $(".caps", el).value = wordsText(clip.start, clip.end);
    persist();
  };
  $(".approved", el).checked = !!clip.approved;
  $(".approved", el).onchange = (e) => { clip.approved = e.target.checked; sync(); updateRenderBtn(); };
  $(".title", el).value = clip.title || "";
  $(".title", el).oninput = (e) => { clip.title = e.target.value; persist(); };
  $(".hook", el).textContent = clip.hook || "";
  const scoreLabel = String(clip.id).startsWith("hype") ? "Hype score" : "AI score";
  $(".score", el).textContent = clip.score ? `${scoreLabel} ${clip.score}/10` : "Custom clip";
  ["start", "end"].forEach((f) => {
    $(`.${f}`, el).onchange = (e) => {
      const t = parseTime(e.target.value);
      if (t !== null) clip[f] = t;
      sync();
    };
  });
  el.querySelectorAll(".nudge").forEach((b) => {
    b.onclick = () => { clip[b.dataset.f] = Math.max(0, clip[b.dataset.f] + Number(b.dataset.d)); sync(); };
  });
  el.querySelectorAll(".setnow").forEach((b) => {
    b.onclick = () => { const t = playerTime(); if (t !== null) { clip[b.dataset.f] = t; sync(); } };
  });
  $(".preview", el).onclick = () => previewRange(clip.start, clip.end);
  $(".editCaps", el).onclick = () => $(".capsBox", el).classList.toggle("hidden");
  $(".caps", el).oninput = (e) => { clip.caption_text = e.target.value; persist(); };
  $(".resetCaps", el).onclick = (e) => { e.preventDefault(); clip.caption_text = null; sync(); };
  $(".remove", el).onclick = () => {
    state.clips = state.clips.filter((c) => c !== clip);
    persist();
    renderClips();
  };
  clip.sfx = clip.sfx || [];
  const list = $(".sfxList", el);
  const drawSfx = () => {
    list.innerHTML = "";
    clip.sfx.forEach((fx) => {
      const row = document.createElement("div");
      row.className = "sfx";
      row.innerHTML = `<select></select>
        <input type="text" title="Seconds from clip start" value="${fx.at.toFixed(1)}">
        <input type="range" min="0" max="150" value="${Math.round(fx.volume * 100)}" title="Volume">
        <button class="ghost tiny now">At now</button><button class="ghost tiny play">Play</button><button class="ghost tiny del">x</button>`;
      const [sel, at, vol] = row.querySelectorAll("select, input");
      fillSfxSelect(sel, fx.sound);
      fx.sound = sel.value;
      sel.onchange = () => { fx.sound = sel.value; persist(); };
      at.onchange = () => { const t = parseTime(at.value); if (t !== null) fx.at = t; drawSfx(); persist(); };
      vol.oninput = () => { fx.volume = vol.value / 100; persist(); };
      $(".now", row).onclick = () => {
        const t = playerTime();
        if (t !== null) { fx.at = Math.max(0, t - clip.start); drawSfx(); persist(); }
      };
      $(".play", row).onclick = () => playSound(fx.sound);
      $(".del", row).onclick = () => { clip.sfx = clip.sfx.filter((x) => x !== fx); drawSfx(); persist(); };
      list.appendChild(row);
    });
    if (clip.sfx.length) {
      const hint = document.createElement("p");
      hint.className = "muted small";
      hint.textContent = "Time = seconds after the clip starts. Pause the player at the right moment and press \"At now\".";
      list.appendChild(hint);
    }
  };
  $(".addSfx", el).onclick = () => {
    const first = state.sounds.sfx[0];
    if (!first) return;
    clip.sfx.push({ sound: first.id, at: 0, volume: 0.8 });
    drawSfx();
    persist();
  };
  drawSfx();
  setupVoiceover(clip, el);
  sync();
  return el;
}
$("#addClip").onclick = () => {
  const t = playerTime() || 0;
  state.clips.unshift({ id: `my${Date.now()}`, title: "My clip", start: t, end: t + 30, approved: true, sfx: [] });
  persist();
  renderClips();
};

// ---------- AI voiceover ----------
const DEFAULT_VOICES = [
  ["en-US-ChristopherNeural", "Christopher: deep US male"], ["en-US-AndrewNeural", "Andrew: warm US male"],
  ["en-US-BrianNeural", "Brian: casual US male"], ["en-US-GuyNeural", "Guy: announcer US male"],
  ["en-US-JennyNeural", "Jenny: friendly US female"], ["en-US-AriaNeural", "Aria: confident US female"],
].map(([id, name]) => ({ id, name }));
async function loadVoices() {
  // Show the built-in list right away, then add the full online list if it arrives.
  state.voices = DEFAULT_VOICES;
  const refill = () => document.querySelectorAll(".voVoice").forEach((sel) => fillVoices(sel, sel.value));
  try { state.voices = (await api("/api/voices")).voices; } catch (e) { /* keep defaults */ }
  refill();
  try {
    const full = (await api("/api/voices?full=1")).voices;
    if (full.length >= state.voices.length) { state.voices = full; refill(); }
  } catch (e) { /* keep what we have */ }
}
function fillVoices(sel, value) {
  sel.innerHTML = state.voices.map((v) => `<option value="${v.id}">${v.name}</option>`).join("");
  if (value) sel.value = value;
}
function setupVoiceover(clip, el) {
  const box = $(".voBox", el);
  const vo = () => {
    clip.voiceover = clip.voiceover || { text: "", voice: "", rate: "+10%", at: 0, volume: 1, captions: "voice" };
    return clip.voiceover;
  };
  const show = () => {
    const v = vo();
    box.classList.remove("hidden");
    $(".voText", el).value = v.text;
    fillVoices($(".voVoice", el), v.voice);
    v.voice = $(".voVoice", el).value;
    $(".voRate", el).value = v.rate;
    $(".voAt", el).value = v.at;
    $(".voCaps", el).value = v.captions;
  };
  if (clip.voiceover) show();
  $(".addVo", el).onclick = () => (box.classList.contains("hidden") ? show() : box.classList.add("hidden"));
  $(".voText", el).oninput = (e) => { vo().text = e.target.value; persist(); };
  $(".voVoice", el).onchange = (e) => { vo().voice = e.target.value; persist(); };
  $(".voRate", el).onchange = (e) => { vo().rate = e.target.value; persist(); };
  $(".voAt", el).onchange = (e) => { vo().at = Math.max(0, Number(e.target.value) || 0); e.target.value = vo().at; persist(); };
  $(".voCaps", el).onchange = (e) => { vo().captions = e.target.value; persist(); };
  $(".voPreview", el).onclick = async () => {
    const v = vo();
    const info = $(".voInfo", el);
    info.textContent = "Recording...";
    try {
      const r = await api("/api/tts/preview", { text: v.text, voice: v.voice, rate: v.rate });
      const len = clip.end - clip.start - v.at;
      info.textContent = `${r.duration.toFixed(1)}s of speech` +
        (r.duration > len ? ` (too long: the clip only has ${len.toFixed(1)}s left. Shorten the text or speed it up.)` : "");
      if (audioEl) audioEl.pause();
      audioEl = new Audio(r.url);
      audioEl.play();
    } catch (e) {
      info.textContent = `Error: ${e.message}`;
    }
  };
  $(".voWrite", el).onclick = async () => {
    const btn = $(".voWrite", el);
    btn.disabled = true;
    const prog = $(".voProgress", el);
    try {
      const { job } = await api("/api/voiceover/script", {
        video_id: state.project.video_id, url: state.project.url, title: state.project.title,
        clip: { start: clip.start, end: clip.end, title: clip.title },
        style: $(".voStyle", el).value, notes: $(".voNotes", el).value,
      });
      const r = await waitJob(job, prog, `Writing a voiceover for "${clip.title}"`);
      vo().text = r.script;
      $(".voText", el).value = r.script;
      persist();
      setProgress(prog, 1, `Done (cost ${money(r.cost)}). Edit it if you like, then press "Hear it".`);
    } catch (e) {
      setProgress(prog, 0, errText(e.message));
    } finally {
      btn.disabled = false;
    }
  };
}

// ---------- analyze ----------
$("#analyzeBtn").onclick = async () => {
  const url = $("#url").value.trim();
  if (!url) return;
  $("#analyzeBtn").disabled = true;
  const prog = $("#analyzeProgress");
  try {
    const { job } = await api("/api/analyze", {
      url, force: $("#forceAi").checked, mode: $("#mode").value, clip_len: Number($("#clipLen").value),
    });
    openProject(await waitJob(job, prog), prog);
  } catch (e) {
    setProgress(prog, 0, errText(e.message));
  } finally {
    $("#analyzeBtn").disabled = false;
  }
};
function openProject(project, prog) {
  state.project = project;
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(saveKey()) || "null"); } catch (e) { saved = null; }
  state.clips = saved && !$("#forceAi").checked ? saved : project.clips.map((c) => ({ approved: false, sfx: [], ...c }));
  $("#videoTitle").textContent = project.title;
  const src = { "youtube-auto": "YouTube auto captions", "youtube-manual": "YouTube captions", whisper: "Whisper", none: "none (no speech found)" }[project.caption_source];
  const how = project.mode === "hype" ? "hype moments found" : "clips suggested";
  $("#videoMeta").textContent = `${fmt(project.duration || 0)} long, transcript: ${src}, ${project.clips.length} ${how}`;
  $("#workspace").classList.remove("hidden");
  setProgress(prog, 1, "Done. Review the clips below.");
  renderClips();
  setupPlayer(project.video_id);
}
$("#videoFile").onchange = async () => {
  const f = $("#videoFile").files[0];
  if (!f) return;
  $("#videoFile").value = "";
  const prog = $("#analyzeProgress");
  if ($("#mode").value === "talk") {
    setProgress(prog, 0.02, "Tip: footage without talking works best in Gameplay mode. Uploading anyway...");
  }
  const form = new FormData();
  form.append("file", f);
  form.append("mode", $("#mode").value);
  form.append("clip_len", $("#clipLen").value);
  setProgress(prog, 0.02, `Uploading ${f.name} (big files take a minute)...`);
  try {
    const res = await fetch("/api/upload-video", { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Upload failed (${res.status})`);
    openProject(await waitJob(data.job, prog), prog);
  } catch (e) {
    setProgress(prog, 0, errText(e.message));
  }
};

// ---------- montage ----------
const montage = { items: [] };
$("#montageBtn").onclick = () => $("#montagePanel").classList.toggle("hidden");
$("#montageFiles").onchange = () => {
  [...$("#montageFiles").files].forEach((file) => {
    const item = { file, name: file.name, url: URL.createObjectURL(file), start: 0, end: null, duration: null };
    const probe = document.createElement("video");
    probe.preload = "metadata";
    probe.onloadedmetadata = () => {
      item.duration = probe.duration;
      if (item.end === null) item.end = probe.duration;
      drawMontage();
    };
    probe.src = item.url;
    montage.items.push(item);
  });
  $("#montageFiles").value = "";
  drawMontage();
};
const isTop = () => $("#montageFormat").value === "top";
const topN = () => Math.min(Number($("#topCount").value), montage.items.length);
$("#montageFormat").onchange = () => {
  ["#topCountWrap", "#topTitleWrap", "#topHelp"].forEach((id) => $(id).classList.toggle("hidden", !isTop()));
  drawMontage();
};
$("#topCount").onchange = () => {
  // Keep the number in the title in step with the count, if it's still the default style.
  $("#topTitle").value = $("#topTitle").value.replace(/^Top \d+/i, `Top ${$("#topCount").value}`);
  drawMontage();
};
function drawMontage() {
  const box = $("#montageList");
  box.innerHTML = "";
  montage.items.forEach((it, i) => {
    const row = document.createElement("div");
    row.className = "mItem";
    const top = isTop();
    const scoreTxt = it.score !== undefined ? `${it.score > 0 ? "+" : ""}${it.score.toFixed(1)}` : "";
    const rank = top
      ? (i < topN() ? "" : ` <span class="score">not used (only top ${topN()})</span>`)
      : (it.score !== undefined ? ` <span class="score">${i === 0 ? "Hook" : "Pick"} ${scoreTxt}</span>` : "");
    const labelBox = top && i < topN()
      ? `<input type="text" class="mLabel" placeholder="Label, e.g. Boss fight" value="${(it.label || "").replace(/"/g, "&quot;")}" style="grid-column: 2 / -1">`
      : "";
    row.innerHTML = `<b>${top ? "#" : ""}${i + 1}${top ? "" : "."}</b>
      <span>${it.name.replace(/</g, "&lt;")}${it.link ? ` <span class="muted small">(link)</span>` : ""} <span class="muted small">${it.duration ? `(${it.duration.toFixed(1)}s)` : "(reading...)"}</span>${rank}</span>
      <label class="check">from <input type="text" class="mStart" value="${it.start.toFixed(1)}"></label>
      <label class="check">to <input type="text" class="mEnd" value="${it.end !== null ? it.end.toFixed(1) : ""}"></label>
      <button class="ghost tiny mPlay">Play</button>
      <button class="ghost tiny mUp" ${i === 0 ? "disabled" : ""}>Up</button>
      <button class="ghost tiny mDown" ${i === montage.items.length - 1 ? "disabled" : ""}>Down</button>
      <button class="ghost tiny mDel">x</button>${labelBox}`;
    if ($(".mLabel", row)) $(".mLabel", row).oninput = (e) => { it.label = e.target.value; };
    $(".mStart", row).onchange = (e) => { const t = parseTime(e.target.value); if (t !== null) it.start = Math.max(0, t); drawMontage(); };
    $(".mEnd", row).onchange = (e) => {
      const t = parseTime(e.target.value);
      if (t !== null) it.end = it.duration ? Math.min(t, it.duration) : t;
      drawMontage();
    };
    $(".mPlay", row).onclick = () => {
      const v = $("#montagePreview");
      v.classList.remove("hidden");
      v.src = it.url;
      v.currentTime = it.start;
      v.ontimeupdate = () => { if (it.end !== null && v.currentTime >= it.end) v.pause(); };
      v.play().catch(() => {});
    };
    const move = (d) => { const j = i + d; [montage.items[i], montage.items[j]] = [montage.items[j], montage.items[i]]; drawMontage(); };
    $(".mUp", row).onclick = () => move(-1);
    $(".mDown", row).onclick = () => move(1);
    $(".mDel", row).onclick = () => { if (it.file) URL.revokeObjectURL(it.url); montage.items.splice(i, 1); drawMontage(); };
    box.appendChild(row);
  });
  const used = isTop() ? montage.items.slice(0, topN()) : montage.items;
  const known = used.filter((it) => it.end !== null);
  const total = known.reduce((sum, it) => sum + Math.max(0, it.end - it.start), 0);
  const unknown = used.length - known.length;
  $("#montageTotal").textContent = montage.items.length
    ? `Total: ${total.toFixed(1)}s` + (unknown ? ` plus ${unknown} clip(s) at full length` : "") +
      (total > 60 ? " (over 60s: YouTube Shorts must be 60s or less, so trim some clips)" : "")
    : "";
  $("#montageBuild").disabled = montage.items.length < 1;
  $("#montageAuto").disabled = montage.items.length < 1;
}
// Uploaded files go up with the form; linked clips are already on the server, sent by id.
function appendSources(form, items) {
  const refs = [];
  items.forEach((it) => {
    if (it.link) refs.push({ kind: "link", id: it.link });
    else { refs.push({ kind: "file", index: refs.filter((r) => r.kind === "file").length }); form.append("files", it.file); }
  });
  form.append("items", JSON.stringify(refs));
}
$("#linkAdd").onclick = async () => {
  const url = $("#linkUrl").value.trim();
  if (!url) return;
  const from = $("#linkFrom").value.trim(), to = $("#linkTo").value.trim();
  const prog = $("#linkProgress");
  $("#linkAdd").disabled = true;
  try {
    const { job } = await api("/api/montage/fetch", {
      url, start: from ? parseTime(from) : null, end: to ? parseTime(to) : null,
    });
    const r = await waitJob(job, prog);
    montage.items.push({ link: r.id, name: r.title, url: r.media, start: 0, end: r.duration, duration: r.duration });
    $("#linkUrl").value = ""; $("#linkFrom").value = ""; $("#linkTo").value = "";
    setProgress(prog, 1, `Added "${r.title}" (${r.duration.toFixed(1)}s). Paste another link to keep going.`);
    drawMontage();
  } catch (e) {
    setProgress(prog, 0, errText(e.message));
  } finally {
    $("#linkAdd").disabled = false;
  }
};
$("#montageAuto").onclick = async () => {
  const btn = $("#montageAuto");
  btn.disabled = true;
  $("#montageAutoInfo").textContent = "Watching and listening to every clip...";
  const form = new FormData();
  appendSources(form, montage.items);
  const target = Number($("#montageTarget").value);
  // Top list: only the top N get used, so give each of them its share of the target.
  form.append("target", isTop() ? target * montage.items.length / topN() : target);
  try {
    const res = await fetch("/api/montage/autopick", { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Auto-pick failed (${res.status})`);
    data.picks.forEach((p, i) => Object.assign(montage.items[i], { start: p.start, end: p.end, score: p.score }));
    montage.items = data.order.map((i) => montage.items[i]);
    $("#montageAutoInfo").textContent = isTop()
      ? "Done: ranked best to worst (#1 at the top). The video will count down and save #1 for last. Add labels, check with Play, then Build."
      : "Done: best part of each clip picked, strongest clip first as the hook. Press Play to check, adjust if you like, then Build.";
    drawMontage();
  } catch (e) {
    $("#montageAutoInfo").textContent = `Error: ${e.message}`;
  } finally {
    btn.disabled = montage.items.length < 1;
  }
};
$("#montageBuild").onclick = async () => {
  const prog = $("#analyzeProgress");
  const form = new FormData();
  let parts = montage.items.map((it) => ({ it, rank: null }));
  if (isTop()) {
    // Rows are ranked #1 first; the video counts down, so #1 plays last.
    parts = montage.items.slice(0, topN()).map((it, i) => ({ it, rank: i + 1 })).reverse();
    form.append("format", "top");
    form.append("top_title", $("#topTitle").value.trim());
  }
  appendSources(form, parts.map((p) => p.it));
  form.append("trims", JSON.stringify(parts.map((p) => ({ start: p.it.start, end: p.it.end, rank: p.rank, label: p.it.label || "" }))));
  form.append("whoosh", $("#montageWhoosh").checked ? "1" : "0");
  $("#montageBuild").disabled = true;
  setProgress(prog, 0.05, "Uploading clips...");
  try {
    const res = await fetch("/api/montage", { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Upload failed (${res.status})`);
    openProject(await waitJob(data.job, prog), prog);
    setProgress(prog, 1, "Montage ready. Add a voiceover on the clip below, then Render.");
    $("#montagePanel").classList.add("hidden");
  } catch (e) {
    setProgress(prog, 0, errText(e.message));
  } finally {
    $("#montageBuild").disabled = false;
  }
};

// ---------- style controls ----------
const syncLabels = () => {
  $("#sizeVal").textContent = $("#size").value;
  $("#musicVolVal").textContent = `${$("#musicVol").value}%`;
};
["size", "musicVol"].forEach((id) => { $(`#${id}`).oninput = syncLabels; });
const STYLE_IDS = ["font", "size", "color", "highlight", "position", "wordsPerLine", "uppercase", "pop", "cropMode", "music", "musicVol"];
function saveStyle() {
  const v = {};
  STYLE_IDS.forEach((id) => { const el = $(`#${id}`); v[id] = el.type === "checkbox" ? el.checked : el.value; });
  try { localStorage.setItem("clipforge:style", JSON.stringify(v)); } catch (e) { /* ignore */ }
}
function loadStyle() {
  let v = null;
  try { v = JSON.parse(localStorage.getItem("clipforge:style") || "null"); } catch (e) { v = null; }
  if (v) STYLE_IDS.forEach((id) => {
    const el = $(`#${id}`);
    if (v[id] === undefined) return;
    if (el.type === "checkbox") el.checked = v[id]; else el.value = v[id];
  });
  syncLabels();
}
STYLE_IDS.forEach((id) => $(`#${id}`).addEventListener("change", saveStyle));

// ---------- render ----------
$("#renderBtn").onclick = async () => {
  const clips = state.clips.filter((c) => c.approved).map((c) => ({
    id: c.id, title: c.title, start: c.start, end: c.end,
    caption_text: c.caption_text ?? null,
    sfx: c.sfx.map((f) => ({ sound: f.sound, at: f.at, volume: f.volume })),
    voiceover: c.voiceover && c.voiceover.text.trim() ? c.voiceover : null,
    overlays: c.overlays || null,
  }));
  const payload = {
    video_id: state.project.video_id, url: state.project.url, clips,
    crop_mode: $("#cropMode").value,
    style: {
      font: $("#font").value, size: Number($("#size").value), color: $("#color").value,
      highlight: $("#highlight").value, position: $("#position").value,
      words_per_line: Number($("#wordsPerLine").value), uppercase: $("#uppercase").checked, pop: $("#pop").checked,
    },
    music: { sound: $("#music").value, volume: Number($("#musicVol").value) / 100 },
  };
  $("#renderBtn").disabled = true;
  const prog = $("#renderProgress");
  try {
    const { job } = await api("/api/render", payload);
    const results = await waitJob(job, prog);
    setProgress(prog, 1, `Done! ${results.length} clip${results.length > 1 ? "s" : ""} saved in the "output" folder.`);
    const stamp = Date.now();
    $("#results").innerHTML = results.map((r) => `
      <div class="result">
        <video src="/output/${encodeURIComponent(r.file)}?t=${stamp}" controls preload="metadata"></video>
        <div><b>${r.title || r.file}</b><br><span class="muted small">${r.file}</span><br>
        <a class="dl" href="/output/${encodeURIComponent(r.file)}?download=1">Download MP4</a></div>
      </div>`).join("") + `<button class="ghost" id="openOut">Open output folder</button>`;
    $("#openOut").onclick = () => api("/api/open-output", {});
  } catch (e) {
    setProgress(prog, 0, errText(e.message));
  } finally {
    updateRenderBtn();
  }
};

// ---------- sound lab ----------
const lab = { source: null, audio: new Audio(), items: [], sel: { start: 0, end: 1 }, stopAt: null, drag: null };
$("#labBtn").onclick = () => $("#labPanel").classList.toggle("hidden");

async function labLoad(form) {
  const prog = $("#labProgress");
  $("#labWork").classList.add("hidden");
  setProgress(prog, 0.02, "Starting...");
  try {
    const res = await fetch("/api/soundlab/load", { method: "POST", body: form });
    if (!res.ok) throw new Error(`Load failed (${res.status})`);
    const { job } = await res.json();
    lab.source = await waitJob(job, prog);
    lab.items = [];
    lab.audio.src = `/soundlab/${lab.source.source_id}/preview.mp3`;
    $("#labTitle").textContent = lab.source.title;
    $("#labDur").textContent = `(${fmt(lab.source.duration)})`;
    $("#labWork").classList.remove("hidden");
    setProgress(prog, 1, "Ready. Cut a sound or click \"Find sounds\".");
    lab.sel = { start: 0, end: Math.min(1, lab.source.duration) };
    labSyncSel();
    drawLabList();
  } catch (e) {
    setProgress(prog, 0, errText(e.message));
  }
}
$("#labLoadUrl").onclick = () => {
  const url = $("#labUrl").value.trim();
  if (!url) return;
  const form = new FormData();
  form.append("url", url);
  labLoad(form);
};
$("#labFile").onchange = () => {
  const f = $("#labFile").files[0];
  if (!f) return;
  const form = new FormData();
  form.append("file", f);
  $("#labFile").value = "";
  setProgress($("#labProgress"), 0.02, `Uploading ${f.name}...`);
  labLoad(form);
};

// Waveform
function drawWave() {
  const c = $("#wave");
  if (!lab.source) return;
  c.width = c.clientWidth * devicePixelRatio;
  c.height = 120 * devicePixelRatio;
  const g = c.getContext("2d");
  const W = c.width, H = c.height, dur = lab.source.duration;
  const x = (t) => (t / dur) * W;
  g.clearRect(0, 0, W, H);
  lab.items.forEach((it) => {
    g.fillStyle = it.keep ? "rgba(46,204,113,.18)" : "rgba(139,147,167,.12)";
    g.fillRect(x(it.start), 0, Math.max(1, x(it.end) - x(it.start)), H);
  });
  g.fillStyle = "rgba(255,230,0,.28)";
  g.fillRect(x(lab.sel.start), 0, Math.max(2, x(lab.sel.end) - x(lab.sel.start)), H);
  const peaks = lab.source.peaks;
  g.fillStyle = "#ff5a6e";
  const bw = W / peaks.length;
  peaks.forEach((p, i) => {
    const h = Math.max(1, p * H * 0.95);
    g.fillRect(i * bw, (H - h) / 2, Math.max(1, bw - 0.5), h);
  });
  g.fillStyle = "#fff";
  g.fillRect(x(lab.audio.currentTime || 0), 0, 2 * devicePixelRatio, H);
}
const waveTime = (e) => {
  const r = $("#wave").getBoundingClientRect();
  return Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1) * lab.source.duration;
};
$("#wave").onmousedown = (e) => { if (lab.source) lab.drag = { from: waveTime(e), moved: false }; };
window.addEventListener("mousemove", (e) => {
  if (!lab.drag) return;
  const t = waveTime(e);
  if (Math.abs(t - lab.drag.from) > lab.source.duration / 400) {
    lab.drag.moved = true;
    lab.sel = { start: Math.min(t, lab.drag.from), end: Math.max(t, lab.drag.from) };
    labSyncSel();
  }
});
window.addEventListener("mouseup", (e) => {
  if (!lab.drag) return;
  if (!lab.drag.moved) { lab.audio.currentTime = lab.drag.from; lab.stopAt = null; }
  lab.drag = null;
  drawWave();
});
window.addEventListener("resize", drawWave);

// Playback
function labPlayRange(start, end) {
  lab.audio.currentTime = start;
  lab.stopAt = end;
  lab.audio.play();
}
$("#labPlay").onclick = () => {
  if (lab.audio.paused) { lab.stopAt = null; lab.audio.play(); } else lab.audio.pause();
};
lab.audio.addEventListener("play", () => { $("#labPlay").textContent = "Pause"; });
lab.audio.addEventListener("pause", () => { $("#labPlay").textContent = "Play"; });
setInterval(() => {
  if (!lab.source) return;
  if (lab.stopAt !== null && lab.audio.currentTime >= lab.stopAt) { lab.audio.pause(); lab.stopAt = null; }
  $("#labTime").textContent = fmt(lab.audio.currentTime || 0);
  if (!lab.audio.paused || lab.drag) drawWave();
}, 50);

// Manual selection
function labSyncSel() {
  $("#labStart").value = fmt(lab.sel.start);
  $("#labEnd").value = fmt(lab.sel.end);
  drawWave();
}
["Start", "End"].forEach((k) => {
  const key = k.toLowerCase();
  $(`#lab${k}`).onchange = (e) => { const t = parseTime(e.target.value); if (t !== null) lab.sel[key] = t; labSyncSel(); };
  $(`#lab${k}Now`).onclick = () => { lab.sel[key] = lab.audio.currentTime || 0; labSyncSel(); };
});
$("#labPreviewSel").onclick = () => labPlayRange(lab.sel.start, lab.sel.end);
$("#labAddSel").onclick = () => {
  if (lab.sel.end - lab.sel.start < 0.05) return;
  const long = lab.sel.end - lab.sel.start > 20;
  lab.items.push({ start: lab.sel.start, end: lab.sel.end, name: `sound_${lab.items.length + 1}`,
                   kind: long ? "music" : "sfx", keep: true, manual: true });
  drawLabList();
};

// Auto split
const syncLabSliders = () => {
  $("#threshVal").textContent = `${$("#thresh").value} dB`;
  $("#gapVal").textContent = `${($("#gap").value / 100).toFixed(2)}s`;
};
$("#thresh").oninput = syncLabSliders;
$("#gap").oninput = syncLabSliders;
syncLabSliders();
$("#labSplit").onclick = async () => {
  $("#labSplit").disabled = true;
  $("#labSplit").textContent = "Finding...";
  try {
    const { segments } = await api("/api/soundlab/split", {
      source_id: lab.source.source_id, threshold_db: Number($("#thresh").value), min_silence: $("#gap").value / 100,
    });
    const manual = lab.items.filter((it) => it.manual);
    lab.items = manual.concat(segments.map((s, i) => ({ ...s, name: `sound_${i + 1}`, kind: "sfx", keep: true })));
    drawLabList();
  } catch (e) {
    alert(e.message);
  } finally {
    $("#labSplit").disabled = false;
    $("#labSplit").textContent = "Find sounds";
  }
};

// List of sounds to save
function drawLabList() {
  const box = $("#labList");
  if (!lab.items.length) {
    box.innerHTML = `<p class="muted small">Nothing yet. Cut a sound or click "Find sounds".</p>`;
    drawWave();
    return;
  }
  box.innerHTML = `<p class="muted small">${lab.items.length} sound${lab.items.length > 1 ? "s" : ""}. Untick the ones you don't want, give the rest a name.</p>`;
  lab.items.forEach((it) => {
    const row = document.createElement("div");
    row.className = "labItem";
    row.innerHTML = `<input type="checkbox" ${it.keep ? "checked" : ""}>
      <button class="ghost tiny play">Play</button>
      <span class="muted small">${fmt(it.start)} to ${fmt(it.end)} (${(it.end - it.start).toFixed(1)}s)</span>
      <input type="text" value="${it.name}">
      <select><option value="sfx">Sound effect</option><option value="music">Music</option></select>
      <button class="ghost tiny edit">Edit</button>`;
    const [keep, name] = row.querySelectorAll("input");
    const kind = $("select", row);
    kind.value = it.kind;
    keep.onchange = () => { it.keep = keep.checked; drawWave(); };
    name.oninput = () => { it.name = name.value; };
    kind.onchange = () => { it.kind = kind.value; };
    $(".play", row).onclick = () => labPlayRange(it.start, it.end);
    $(".edit", row).onclick = () => {
      // Load into the manual cutter to fine-tune, then "+ Add to list" again.
      lab.sel = { start: it.start, end: it.end };
      lab.items = lab.items.filter((x) => x !== it);
      labSyncSel();
      drawLabList();
    };
    box.appendChild(row);
  });
  drawWave();
}
$("#labSave").onclick = async () => {
  const items = lab.items.filter((it) => it.keep).map((it) => ({
    start: it.start, end: it.end, name: it.name, kind: it.kind, normalize: $("#labNorm").checked,
  }));
  if (!items.length) return;
  $("#labSave").disabled = true;
  $("#labSaved").textContent = `Saving ${items.length} sound${items.length > 1 ? "s" : ""}...`;
  try {
    const { saved } = await api("/api/soundlab/save", { source_id: lab.source.source_id, items });
    $("#labSaved").textContent = `Saved ${saved.length} to your library: ${saved.map((s) => s.name).join(", ")}`;
    loadSounds();
  } catch (e) {
    $("#labSaved").textContent = `Error: ${e.message}`;
  } finally {
    $("#labSave").disabled = false;
  }
};

$("#mode").onchange = () => $("#clipLenWrap").classList.toggle("hidden", $("#mode").value !== "hype");

loadStyle();
loadStatus();
loadVoices();
loadUsage();
loadSounds();
