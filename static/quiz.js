// Quiz Shorts: Claude writes questions, you check them, ClipForge builds an Editor project and exports it.
// Uses helpers from app.js ($, api, waitJob, setProgress, errText, money, state, loadSounds).
const qz = { kind: null, questions: [], count: 8, voices: null, credits: null };
const QZ_SECONDS = { intro: 2.6, question: 7.8, outro: 2.8 };  // rough, for the length estimate
const esc = (v) => String(v ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

function qzSettings() {
  try { return JSON.parse(localStorage.getItem("clipforge:quiz") || "{}"); } catch (e) { return {}; }
}
function qzRemember() {
  try {
    localStorage.setItem("clipforge:quiz", JSON.stringify({ kind: $("#qzKind").value, length: $("#qzLength").value,
      voice: $("#qzVoice").value, music: $("#qzMusic").value }));
  } catch (e) { /* storage unavailable */ }
}

// ---------- voices ----------
async function qzLoadVoices(force) {
  if (qz.voices && !force) return qzFillVoices();
  qz.voices = { ms: state.voices && state.voices.length ? state.voices : [], el: [] };
  qz.credits = null;
  qzFillVoices();
  if (!state.hasEleven) return;
  $("#qzCredits").textContent = "Loading your ElevenLabs voices...";
  try {
    const r = await api("/api/eleven/voices");
    qz.voices.el = r.voices;
    qz.credits = r.credits;
  } catch (e) {
    $("#qzCredits").textContent = errText(e.message);
    return;
  }
  qzFillVoices();
}
window.qzLoadVoices = qzLoadVoices;
function qzFillVoices() {
  const sel = $("#qzVoice");
  const keep = sel.value || qzSettings().voice;
  const opt = (v, label) => `<option value="${esc(v.id)}">${esc(label)}</option>`;
  let html = "";
  if (qz.voices.el.length) {
    const mine = qz.voices.el.filter((v) => v.mine), theirs = qz.voices.el.filter((v) => !v.mine);
    if (mine.length) html += `<optgroup label="ElevenLabs: My Voices">${mine.map((v) => opt(v, v.name + (v.detail ? ` (${v.detail})` : ""))).join("")}</optgroup>`;
    if (theirs.length) html += `<optgroup label="ElevenLabs: built-in">${theirs.map((v) => opt(v, v.name + (v.detail ? ` (${v.detail})` : ""))).join("")}</optgroup>`;
  }
  html += `<optgroup label="Free Microsoft voices">${qz.voices.ms.map((v) => opt(v, v.name)).join("")}</optgroup>`;
  sel.innerHTML = html;
  if (keep && [...sel.options].some((o) => o.value === keep)) sel.value = keep;
  qzShowCredits();
}
function qzShowCredits() {
  const el = $("#qzVoice").value.startsWith("el:");
  const c = qz.credits;
  let msg = "";
  if (el && c) {
    msg = `ElevenLabs: ${c.left.toLocaleString()} of ${c.limit.toLocaleString()} credits left. This quiz needs about ${qzChars().toLocaleString()}.`;
    if (c.tier === "free") msg += " Free plan: not allowed in monetized videos.";
  } else if (!el) {
    msg = state.hasEleven ? "Free voice." : "Free voice. Add an ElevenLabs key in Settings for their voices.";
  }
  $("#qzCredits").textContent = msg;
}

// ---------- questions ----------
function qzUsed() { return qz.questions.filter((q) => q.use); }
function qzChars() {
  // Roughly what the voice reads: the hook, each question and answer, and the outro.
  const per = { emoji: 30, truefalse: 120, versus: 120 }[qz.kind] || 100;
  return $("#qzHook").value.length + 45 + qzUsed().length * per;
}
function qzUpdateLength() {
  const n = qzUsed().length;
  const secs = QZ_SECONDS.intro + QZ_SECONDS.outro + n * QZ_SECONDS.question;
  const tiktok = secs >= 60 ? "long enough for TikTok rewards" : "under 1 minute: fine for Shorts, too short for TikTok rewards";
  $("#qzLen").textContent = n ? `${n} question${n > 1 ? "s" : ""}, about ${Math.round(secs)} seconds (${tiktok})` : "Tick at least one question.";
  $("#qzMake").disabled = !n;
  qzShowCredits();
}
function qzRow(q, i) {
  const row = document.createElement("div");
  row.className = "qz-q" + (q.use ? "" : " off");
  const check = q.sure ? "" : `<span class="qz-unsure" title="Claude isn't sure about this one">CHECK</span>`;
  let fields;
  if (qz.kind === "emoji") {
    fields = `<input class="qz-emoji" data-k="emojis" type="text" value="${esc(q.emojis)}" aria-label="Emojis">
      <span class="muted">=</span><input data-k="answer" type="text" value="${esc(q.answer)}" aria-label="Answer">`;
  } else if (qz.kind === "truefalse") {
    fields = `<input class="qz-wide" data-k="statement" type="text" value="${esc(q.statement)}" aria-label="Statement">
      <select data-k="answer" aria-label="Answer"><option value="true">True</option><option value="false">False</option></select>
      <input data-k="fact" type="text" value="${esc(q.fact)}" aria-label="Why" placeholder="Why (read after the answer)">`;
  } else {
    fields = `<select data-k="kind" aria-label="Question"><option value="older">Which is older?</option><option value="popular">Which is more popular?</option></select>
      <input data-k="a" type="text" value="${esc(q.a)}" aria-label="Game A"><span class="muted">vs</span>
      <input data-k="b" type="text" value="${esc(q.b)}" aria-label="Game B">
      <select data-k="answer" aria-label="Correct answer"><option value="a">Answer: first</option><option value="b">Answer: second</option></select>
      <input class="qz-wide" data-k="fact" type="text" value="${esc(q.fact)}" aria-label="Proof" placeholder="Proof (read after the answer)">`;
  }
  row.innerHTML = `<input type="checkbox" ${q.use ? "checked" : ""} aria-label="Use this question">
    <div class="qz-fields"><span class="qz-num">${i + 1}</span>${fields}${check}</div>`;
  row.querySelectorAll("select[data-k]").forEach((s) => { s.value = String(q[s.dataset.k]); });
  row.querySelectorAll("[data-k]").forEach((input) => {
    input.addEventListener(input.tagName === "SELECT" ? "change" : "input", () => {
      const k = input.dataset.k;
      q[k] = qz.kind === "truefalse" && k === "answer" ? input.value === "true" : input.value;
      qzShowCredits();
    });
  });
  row.querySelector("input[type=checkbox]").onchange = (e) => {
    q.use = e.target.checked;
    row.classList.toggle("off", !q.use);
    qzUpdateLength();
  };
  return row;
}
function qzRenderList() {
  $("#qzList").replaceChildren(...qz.questions.map(qzRow));
  qzUpdateLength();
}

$("#qzWrite").onclick = async () => {
  const prog = $("#qzWriteProgress");
  $("#qzWrite").disabled = true;
  qzRemember();
  try {
    const { job } = await api("/api/quiz/write", { kind: $("#qzKind").value, length: $("#qzLength").value, topic: $("#qzTopic").value });
    const r = await waitJob(job, prog, "Writing quiz questions");
    qz.kind = $("#qzKind").value;
    qz.count = r.count;
    qz.questions = r.questions.map((q, i) => ({ ...q, use: i < r.count }));
    $("#qzHook").value = r.hook;
    setProgress(prog, 1, `Done. Cost ${money(r.cost)}. Check them below.`);
    $("#qzReview").classList.remove("hidden");
    qzRenderList();
    await qzLoadVoices();
    $("#qzReview").scrollIntoView({ behavior: "smooth" });
  } catch (e) {
    setProgress(prog, 0, errText(e.message));
  } finally {
    $("#qzWrite").disabled = false;
  }
};
$("#qzHook").oninput = qzShowCredits;
$("#qzVoice").onchange = () => { qzShowCredits(); qzRemember(); };
$("#qzMusic").onchange = qzRemember;

$("#qzHear").onclick = async () => {
  const voice = $("#qzVoice").value;
  $("#qzHear").disabled = true;
  try {
    const r = voice.startsWith("el:")
      ? await api("/api/eleven/preview", { voice })
      : await api("/api/tts/preview", { text: "Can you guess this Roblox game?", voice });
    new Audio(r.url).play();
  } catch (e) {
    $("#qzCredits").textContent = errText(e.message);
  } finally {
    $("#qzHear").disabled = false;
  }
};

$("#qzMake").onclick = async () => {
  const prog = $("#qzMakeProgress");
  const questions = qzUsed().map(({ use, ...q }) => q);
  const blank = questions.some((q) => Object.entries(q).some(([k, v]) => k !== "sure" && typeof v === "string" && !v.trim()));
  if (blank) { setProgress(prog, 0, "Fill in every box of the ticked questions first."); return; }
  $("#qzMake").disabled = true;
  qzRemember();
  try {
    const { job } = await api("/api/quiz/make", { kind: qz.kind, questions, hook: $("#qzHook").value,
      voice: $("#qzVoice").value, music: $("#qzMusic").value, name: $("#qzTopic").value.trim() ? `Quiz: ${$("#qzTopic").value.trim()}` : "" });
    const r = await waitJob(job, prog, "Recording the voice");
    setProgress(prog, 1, `Built a ${Math.round(r.seconds)} second quiz. Opening it in the Editor and exporting...`);
    if (qz.credits) qzLoadVoices(true);  // refresh credits left
    await window.edOpenProject(r.project, true);
  } catch (e) {
    setProgress(prog, 0, errText(e.message));
  } finally {
    $("#qzMake").disabled = false;
  }
};

window.qzOnShow = async () => {
  const saved = qzSettings();
  if (saved.kind && !qz.kind) $("#qzKind").value = saved.kind;
  if (saved.length && !qz.kind) $("#qzLength").value = saved.length;
  const music = state.sounds.music || [];
  $("#qzMusic").innerHTML = `<option value="">No music</option>` + music.map((m) => `<option value="${esc(m.id)}">${esc(m.name)}</option>`).join("");
  const pick = saved.music !== undefined ? saved.music : (music.find((m) => /upbeat/i.test(m.name)) || {}).id;
  if (pick !== undefined && [...$("#qzMusic").options].some((o) => o.value === pick)) $("#qzMusic").value = pick;
  if (qz.questions.length) qzLoadVoices();
};
