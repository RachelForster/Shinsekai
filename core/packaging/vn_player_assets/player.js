(function () {
  "use strict";

  var data = window.__SHINSEKAI_VN__;
  if (!data || !Array.isArray(data.entries) || !data.entries.length) return;

  var storyId = String(data.storyId || "default");
  var L = data.uiLabels || {};
  var SAVES_KEY = "shinsekai_vn:" + storyId + ":saves";
  var SETTINGS_KEY = "shinsekai_vn:" + storyId + ":settings";
  var VIDEO_RE = /\.(?:m4v|mov|mp4|webm)(?:[?#]|$)/i;
  var SLOT_IDS = ["1", "2", "3", "4", "5", "6"];
  var NARR_SPEAKERS = { "": 1, "旁白": 1, narr: 1, narration: 1 };
  var dom = { dialogBox: document.querySelector(".vn-dialog") };
  [
    "title-screen", "title-cover", "title-heading", "title-subtitle", "title-meta",
    "btn-start", "btn-continue", "stage", "bg-layer", "ambient-back", "sprite-layer",
    "ambient-front", "cg-layer", "cg-toggle", "stats-layer", "progress-pill",
    "player-portrait", "nameplate", "speaker-name", "dialog-text",
    "ctc", "tb-voice", "tb-auto", "tb-skip", "tb-backlog", "tb-save", "tb-load",
    "tb-hide", "tb-settings", "tb-title", "restore-hint", "end-overlay", "end-title",
    "end-restart", "end-title-btn", "modal-backdrop", "modal-title", "modal-close", "modal-body",
  ].forEach(function (slug) {
    var camel = slug.replace(/-([a-z])/g, function (_m, ch) { return ch.toUpperCase(); });
    dom[camel] = document.getElementById("vn-" + slug);
  });

  function mk(tag, cls, text, attrs) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    if (attrs) Object.keys(attrs).forEach(function (k) { node[k] = attrs[k]; });
    return node;
  }

  var label = function (k, fb) { return typeof L[k] === "string" && L[k] ? L[k] : fb; };
  function formatLabel(k, fb, vars) {
    var text = label(k, fb);
    if (vars) Object.keys(vars).forEach(function (v) { text = text.replace("{" + v + "}", String(vars[v])); });
    return text;
  }

  function readStorage(key, fallback) {
    try { var p = JSON.parse(window.localStorage.getItem(key) || "null"); return p && typeof p === "object" ? p : fallback; }
    catch (_e) { return fallback; }
  }
  function writeStorage(key, val) { try { window.localStorage.setItem(key, JSON.stringify(val)); } catch (_e) {} }

  var settings = Object.assign(
    { typeSpeed: 34, autoDelay: 1.6, bgmVolume: 0.45, ambientVolume: 0.5, voiceVolume: 1.0, autoVoice: true },
    readStorage(SETTINGS_KEY, {}),
  );
  var state = {
    started: false, index: 0, maxVisited: 0, typing: false, typedChars: 0, typeTimer: 0,
    autoMode: false, skipMode: false, autoTimer: 0, skipTimer: 0, uiHidden: false, cgDismissed: false,
    voicePlaying: false, activeBgUrl: "", activeCgUrl: "", activeBgmUrl: "",
    ambientAudio: new Map(), voiceToken: 0, modalKind: "",
  };
  var bgmAudio = Object.assign(new Audio(), { loop: true, preload: "auto" });
  var voiceAudio = Object.assign(new Audio(), { preload: "auto" });

  function createMediaElement(url) {
    if (VIDEO_RE.test(url)) {
      var video = mk("video", "", undefined, { src: url, autoplay: true, loop: true, muted: true, playsInline: true });
      video.play().catch(function () {});
      return video;
    }
    return mk("img", "", undefined, { src: url, alt: "" });
  }

  function applyBackground(url) {
    if (state.activeBgUrl === url) return;
    state.activeBgUrl = url; dom.bgLayer.innerHTML = "";
    if (url) dom.bgLayer.appendChild(createMediaElement(url));
  }

  function applyCg(url) {
    var effective = state.cgDismissed ? "" : url;
    dom.cgToggle.hidden = !url;
    if (url) dom.cgToggle.textContent = label(state.cgDismissed ? "cgView" : "cgExit", state.cgDismissed ? "View CG" : "Hide CG");
    if (state.activeCgUrl === effective) return;
    state.activeCgUrl = effective; dom.cgLayer.innerHTML = ""; dom.cgLayer.hidden = !effective;
    if (effective) dom.cgLayer.appendChild(createMediaElement(effective));
  }

  function syncAmbientEffects(effects) {
    var list = Array.isArray(effects) ? effects : [];
    dom.ambientBack.innerHTML = "";
    dom.ambientFront.innerHTML = "";
    var activeKeys = {};
    list.forEach(function (item) {
      if (!item || !item.url) return;
      (item.layer === "front" ? dom.ambientFront : dom.ambientBack).appendChild(createMediaElement(item.url));
      if (!item.audioUrl) return;
      var key = String(item.key || item.audioUrl);
      activeKeys[key] = item.audioUrl;
      var existing = state.ambientAudio.get(key);
      if (!existing || existing.url !== item.audioUrl) {
        if (existing) existing.audio.pause();
        var aud = new Audio(item.audioUrl);
        aud.loop = true;
        aud.volume = settings.ambientVolume;
        aud.play().catch(function () {});
        state.ambientAudio.set(key, { url: item.audioUrl, audio: aud });
      } else {
        existing.audio.volume = settings.ambientVolume;
      }
    });
    state.ambientAudio.forEach(function (entry, key) {
      if (!activeKeys[key]) { entry.audio.pause(); state.ambientAudio.delete(key); }
    });
  }

  function spriteAxisCenter(sprites, sprite, idx) {
    var count = sprites.length;
    if (count <= 1) return 50;
    var slot = typeof sprite.slot === "number" ? sprite.slot : idx;
    var span = count === 2 ? 44 : 68;
    return 50 - span / 2 + Math.min(Math.max(slot, 0), count - 1) * (span / Math.max(1, count - 1));
  }

  function applySprites(sprites, activeSpeaker) {
    dom.spriteLayer.innerHTML = "";
    var list = Array.isArray(sprites) ? sprites : [];
    if (!list.length) return;
    var speaker = String(activeSpeaker || "").trim();
    var hasSpeaker = speaker.length > 0 && list.some(function (sp) {
      return String(sp.characterName || sp.label || "").trim() === speaker;
    });
    list.forEach(function (sp, idx) {
      if (!sp || !sp.url) return;
      var speaking = hasSpeaker && String(sp.characterName || sp.label || "").trim() === speaker;
      var fig = mk("figure", "vn-sprite");
      fig.setAttribute("data-speaking", speaking ? "true" : "false");
      fig.setAttribute("data-dim", hasSpeaker && !speaking ? "true" : "false");
      fig.style.setProperty("--sprite-axis-center", spriteAxisCenter(list, sp, idx) + "%");
      fig.style.setProperty("--sprite-offset-x", (sp.x || 0) + "px");
      fig.style.setProperty("--sprite-offset-y", (sp.y || 0) + "px");
      fig.style.setProperty("--sprite-scale", String(sp.scale || 1));
      fig.style.zIndex = speaking ? "3" : "1";
      fig.appendChild(createMediaElement(sp.url));
      dom.spriteLayer.appendChild(fig);
    });
  }

  function applyStats(stats) {
    dom.statsLayer.innerHTML = "";
    var list = Array.isArray(stats) ? stats : [];
    dom.statsLayer.hidden = !list.length;
    list.forEach(function (st) {
      var card = mk("div", "vn-stat-item"), row = mk("div", "vn-stat-item__row");
      var hasMax = typeof st.max === "number" && st.max > 0;
      row.append(mk("span", "", String(st.label || "")), mk("strong", "", hasMax ? st.value + " / " + st.max : String(st.value)));
      card.appendChild(row);
      if (hasMax) {
        var bar = mk("div", "vn-stat-item__bar"), fill = mk("div", "vn-stat-item__fill");
        fill.style.width = Math.max(0, Math.min(100, (Number(st.value) / st.max) * 100)) + "%";
        bar.appendChild(fill); card.appendChild(bar);
      }
      dom.statsLayer.appendChild(card);
    });
  }

  function applyPortrait(portrait) {
    dom.playerPortrait.innerHTML = "";
    if (!portrait || !portrait.url) {
      dom.playerPortrait.hidden = true;
      dom.dialogBox.removeAttribute("data-has-portrait");
      return;
    }
    var img = mk("img", "", undefined, { src: portrait.url, alt: portrait.characterName || "" });
    if (portrait.crop && typeof portrait.crop.x === "number" && typeof portrait.crop.y === "number") {
      img.style.objectPosition = Math.round(portrait.crop.x * 100) + "% " + Math.round(portrait.crop.y * 100) + "%";
    }
    dom.playerPortrait.appendChild(img);
    dom.playerPortrait.hidden = false;
    dom.dialogBox.setAttribute("data-has-portrait", "true");
  }

  function syncBgm(url) {
    bgmAudio.volume = settings.bgmVolume;
    if (state.activeBgmUrl === url) return;
    state.activeBgmUrl = url;
    if (!url) { bgmAudio.pause(); bgmAudio.removeAttribute("src"); return; }
    bgmAudio.src = url;
    bgmAudio.play().catch(function () {});
  }

  function stopVoice() {
    state.voiceToken += 1;
    state.voicePlaying = false;
    voiceAudio.pause();
    voiceAudio.onended = voiceAudio.onerror = null;
  }

  function playVoiceList(urls, volume) {
    stopVoice();
    if (!Array.isArray(urls) || !urls.length) return;
    var token = state.voiceToken, segIdx = 0;
    state.voicePlaying = true;
    var playNext = function () {
      if (token !== state.voiceToken) return;
      if (segIdx >= urls.length) { state.voicePlaying = false; scheduleAutoIfReady(); return; }
      voiceAudio.src = urls[segIdx++];
      voiceAudio.volume = Math.max(0, Math.min(1, (typeof volume === "number" ? volume : 1) * settings.voiceVolume));
      voiceAudio.onended = voiceAudio.onerror = playNext;
      voiceAudio.play().catch(function () { state.voicePlaying = false; scheduleAutoIfReady(); });
    };
    playNext();
  }

  function finishTyping() {
    window.clearInterval(state.typeTimer);
    state.typeTimer = 0;
    state.typing = false;
    var entry = data.entries[state.index];
    dom.dialogText.textContent = entry ? entry.text || "" : "";
    dom.ctc.hidden = false;
    scheduleAutoIfReady();
  }

  function startTyping(text) {
    window.clearInterval(state.typeTimer);
    var chars = Array.from(text || "");
    if (state.skipMode || settings.typeSpeed >= 95 || !chars.length) return finishTyping();
    state.typing = true;
    state.typedChars = 0;
    dom.dialogText.textContent = "";
    dom.ctc.hidden = true;
    var intervalMs = Math.max(12, Math.round(1000 / Math.max(8, settings.typeSpeed)));
    state.typeTimer = window.setInterval(function () {
      state.typedChars += 1;
      dom.dialogText.textContent = chars.slice(0, state.typedChars).join("");
      if (state.typedChars >= chars.length) finishTyping();
    }, intervalMs);
  }

  function scheduleAutoIfReady() {
    window.clearTimeout(state.autoTimer);
    window.clearTimeout(state.skipTimer);
    if (!state.started || state.modalKind || !dom.endOverlay.hidden) return;
    if (state.skipMode) state.skipTimer = window.setTimeout(advance, 120);
    else if (state.autoMode && !state.typing && !state.voicePlaying) {
      state.autoTimer = window.setTimeout(advance, Math.round(settings.autoDelay * 1000));
    }
  }

  function saveSlot(slotId) {
    var entry = data.entries[state.index];
    if (!entry) return;
    var saves = readStorage(SAVES_KEY, {});
    saves[slotId] = {
      index: state.index, maxVisited: state.maxVisited, speaker: entry.speaker || "",
      excerpt: String(entry.text || "").slice(0, 64), savedAt: Date.now(),
    };
    writeStorage(SAVES_KEY, saves);
  }

  function renderEntry(index) {
    if (index < 0) index = 0;
    if (index >= data.entries.length) {
      setAuto(false); setSkip(false);
      dom.endOverlay.hidden = false;
      return;
    }
    dom.endOverlay.hidden = true;
    state.index = index;
    state.maxVisited = Math.max(state.maxVisited, index);
    state.cgDismissed = false;
    var entry = data.entries[index];
    applyBackground(entry.background || "");
    applyCg(entry.cg || "");
    syncAmbientEffects(entry.ambientEffects);
    applySprites(entry.sprites, entry.speaker);
    applyStats(entry.stats);
    applyPortrait(entry.playerPortrait);
    syncBgm(entry.bgm || "");
    var rawSpeaker = String(entry.speaker || "").trim();
    var isNarration = entry.role !== "user" && Boolean(NARR_SPEAKERS[rawSpeaker.toLowerCase()]);
    var dialogRole = entry.role === "user" ? "user" : (isNarration ? "narration" : "assistant");
    var speakerText = isNarration ? "" : (rawSpeaker || (entry.role === "system" ? label("system", "System") : ""));
    dom.dialogBox.setAttribute("data-role", dialogRole);
    dom.nameplate.hidden = !speakerText;
    dom.speakerName.textContent = speakerText;
    dom.progressPill.textContent = index + 1 + " / " + data.entries.length;
    dom.tbVoice.disabled = !(Array.isArray(entry.voices) && entry.voices.length > 0);
    startTyping(entry.text || "");
    if (settings.autoVoice && !state.skipMode && Array.isArray(entry.voices) && entry.voices.length) {
      playVoiceList(entry.voices, entry.voiceVolume);
    } else {
      stopVoice();
    }
    saveSlot("auto");
  }

  function advance() {
    window.clearTimeout(state.autoTimer);
    window.clearTimeout(state.skipTimer);
    if (!state.started || state.modalKind) return;
    if (state.uiHidden) return toggleUiHidden(false);
    if (state.typing) return finishTyping();
    renderEntry(state.index + 1);
  }

  function setAuto(on) {
    state.autoMode = Boolean(on);
    if (state.autoMode) setSkip(false);
    dom.tbAuto.setAttribute("data-active", state.autoMode ? "true" : "false");
    if (state.autoMode) scheduleAutoIfReady();
    else window.clearTimeout(state.autoTimer);
  }

  function setSkip(on) {
    state.skipMode = Boolean(on);
    if (state.skipMode) setAuto(false);
    dom.tbSkip.setAttribute("data-active", state.skipMode ? "true" : "false");
    if (state.skipMode) { stopVoice(); if (state.typing) finishTyping(); else scheduleAutoIfReady(); }
    else window.clearTimeout(state.skipTimer);
  }

  function toggleUiHidden(next) {
    state.uiHidden = typeof next === "boolean" ? next : !state.uiHidden;
    dom.stage.setAttribute("data-ui-hidden", state.uiHidden ? "true" : "false");
    dom.restoreHint.hidden = !state.uiHidden;
  }

  function startPlayback(startIndex) {
    state.started = true; dom.titleScreen.hidden = true; dom.stage.hidden = false; renderEntry(startIndex || 0);
  }

  function returnToTitle() {
    setAuto(false); setSkip(false); stopVoice(); syncBgm(""); syncAmbientEffects([]);
    state.started = false; dom.stage.hidden = dom.endOverlay.hidden = true;
    refreshTitleScreen(); dom.titleScreen.hidden = false;
  }

  function openModal(kind, titleText) {
    setAuto(false); setSkip(false); state.modalKind = kind;
    dom.modalTitle.textContent = titleText; dom.modalBody.innerHTML = "";
    dom.modalBackdrop.hidden = false; dom.modalClose.focus();
  }

  function closeModal() {
    state.modalKind = ""; dom.modalBackdrop.hidden = true; dom.modalBody.innerHTML = ""; scheduleAutoIfReady();
  }

  function openBacklog() {
    openModal("backlog", label("backlogTitle", "History"));
    for (var i = 0; i <= state.maxVisited && i < data.entries.length; i++) {
      (function (idx) {
        var entry = data.entries[idx], card = mk("article", "vn-backlog-item");
        var head = mk("div", "vn-backlog-item__head"), actions = mk("div");
        if (Array.isArray(entry.voices) && entry.voices.length) {
          var vBtn = mk("button", "vn-tb-btn", label("replayVoice", "Voice"), { type: "button" });
          vBtn.addEventListener("click", function () { playVoiceList(entry.voices, entry.voiceVolume); });
          actions.appendChild(vBtn);
        }
        var jBtn = mk("button", "vn-tb-btn", label("jumpHere", "Jump"), { type: "button" });
        jBtn.addEventListener("click", function () { closeModal(); renderEntry(idx); });
        actions.appendChild(jBtn);
        var backlogSpeaker = NARR_SPEAKERS[String(entry.speaker || "").trim().toLowerCase()]
          ? label("narration", "Narration")
          : entry.speaker;
        head.append(mk("strong", "", backlogSpeaker), actions);
        card.append(head, mk("p", "vn-backlog-item__text", entry.text || ""));
        dom.modalBody.appendChild(card);
      })(i);
    }
    dom.modalBody.scrollTop = dom.modalBody.scrollHeight;
  }

  function openSaveLoad(mode) {
    openModal(mode, label(mode === "save" ? "saveTitle" : "loadTitle", mode));
    var saves = readStorage(SAVES_KEY, {});
    (mode === "load" ? ["auto"].concat(SLOT_IDS) : SLOT_IDS).forEach(function (k) {
      var rec = saves[k], row = mk("article", "vn-slot-item"), head = mk("div", "vn-slot-item__head");
      var slotTitle = k === "auto" ? label("autosaveSlot", "Autosave") : formatLabel("manualSlot", "Slot {slot}", { slot: k });
      var btn = mk("button", "vn-tb-btn", label(mode === "save" ? "save" : "load", mode), { type: "button", disabled: mode === "load" && !rec });
      btn.addEventListener("click", function () {
        if (mode === "save") { saveSlot(k); openSaveLoad("save"); }
        else if (rec) { closeModal(); startPlayback(Math.min(data.entries.length - 1, Math.max(0, Number(rec.index) || 0))); }
      });
      head.append(mk("strong", "", slotTitle), btn);
      var summary = rec ? "#" + (Number(rec.index) + 1) + " · " + (rec.speaker ? rec.speaker + ": " : "") + rec.excerpt : label("emptySlot", "Empty");
      row.append(head, mk("p", "vn-backlog-item__text", summary));
      dom.modalBody.appendChild(row);
    });
  }

  function openSettings() {
    openModal("settings", label("settingsTitle", "Settings"));
    [["typeSpeed", "Text speed", 10, 100, 2], ["autoDelay", "Auto delay (s)", 0.4, 5, 0.2],
      ["bgmVolume", "BGM", 0, 1, 0.05], ["ambientVolume", "Ambient", 0, 1, 0.05], ["voiceVolume", "Voice", 0, 1, 0.05],
    ].forEach(function (item) {
      var key = item[0], row = mk("label", "vn-setting-row");
      var input = mk("input", "", undefined, { type: "range", min: String(item[2]), max: String(item[3]), step: String(item[4]), value: String(settings[key]) });
      input.addEventListener("input", function () {
        settings[key] = Number(input.value);
        bgmAudio.volume = settings.bgmVolume;
        state.ambientAudio.forEach(function (a) { a.audio.volume = settings.ambientVolume; });
        writeStorage(SETTINGS_KEY, settings);
      });
      row.append(mk("span", "", label(key, item[1])), input);
      dom.modalBody.appendChild(row);
    });
    var tRow = mk("label", "vn-setting-row"), check = mk("input", "", undefined, { type: "checkbox", checked: Boolean(settings.autoVoice) });
    check.addEventListener("change", function () { settings.autoVoice = check.checked; writeStorage(SETTINGS_KEY, settings); });
    tRow.append(mk("span", "", label("autoPlayVoice", "Auto-play voice")), check);
    dom.modalBody.appendChild(tRow);
  }

  function refreshTitleScreen() {
    var meta = data.meta || {};
    dom.titleHeading.textContent = meta.title || document.title;
    dom.titleSubtitle.textContent = meta.subtitle || "";
    dom.titleSubtitle.hidden = !meta.subtitle;
    dom.titleCover.innerHTML = "";
    if (meta.coverUrl) dom.titleCover.appendChild(createMediaElement(meta.coverUrl));
    dom.titleMeta.innerHTML = "";
    [formatLabel("linesCount", "{count} lines", { count: data.entries.length }),
      meta.voiceCount ? formatLabel("voicesCount", "{count} voices", { count: meta.voiceCount }) : ""].forEach(function (txt) {
      if (txt) dom.titleMeta.appendChild(mk("span", "vn-meta-chip", txt));
    });
    var saves = readStorage(SAVES_KEY, {});
    dom.btnContinue.hidden = !["auto"].concat(SLOT_IDS).some(function (k) { return Boolean(saves[k]); });
  }

  function wireEvents() {
    dom.restoreHint.textContent = label("restoreUiHint", "Click or press H / Esc to show UI");
    dom.endTitle.textContent = label("endTitle", "Fin");
    [
      [dom.btnStart, "start", "Start", function () { startPlayback(0); }],
      [dom.btnContinue, "continueGame", "Continue", function () {
        var saves = readStorage(SAVES_KEY, {}), latest = saves.auto;
        Object.keys(saves).forEach(function (k) { if (!latest || (saves[k] && saves[k].savedAt > latest.savedAt)) latest = saves[k]; });
        startPlayback(latest ? Number(latest.index) || 0 : 0);
      }],
      [dom.tbVoice, "replayVoice", "Voice", function () {
        var e = data.entries[state.index];
        if (e && Array.isArray(e.voices) && e.voices.length) playVoiceList(e.voices, e.voiceVolume);
      }],
      [dom.tbAuto, "autoPlay", "Auto", function () { setAuto(!state.autoMode); }],
      [dom.tbSkip, "skip", "Skip", function () { setSkip(!state.skipMode); }],
      [dom.tbBacklog, "backlog", "History", openBacklog],
      [dom.tbSave, "save", "Save", function () { openSaveLoad("save"); }],
      [dom.tbLoad, "load", "Load", function () { openSaveLoad("load"); }],
      [dom.tbHide, "hideUi", "Hide UI", function () { toggleUiHidden(true); }],
      [dom.tbSettings, "settings", "Settings", openSettings],
      [dom.tbTitle, "titleScreen", "Title", returnToTitle],
      [dom.endRestart, "endRestart", "Restart", function () { startPlayback(0); }],
      [dom.endTitleBtn, "endBackTitle", "Title", returnToTitle],
      [dom.modalClose, "modalClose", "Close", closeModal],
    ].forEach(function (item) {
      item[0].textContent = label(item[1], item[2]);
      item[0].addEventListener("click", function (ev) { ev.stopPropagation(); item[3](); });
    });

    dom.stage.addEventListener("click", function (ev) {
      if (!ev.target.closest("#vn-toolbar, #vn-cg-toggle, #vn-end-overlay")) advance();
    });
    dom.cgToggle.addEventListener("click", function (ev) {
      ev.stopPropagation(); state.cgDismissed = !state.cgDismissed;
      applyCg(data.entries[state.index] ? data.entries[state.index].cg || "" : "");
    });
    dom.modalBackdrop.addEventListener("click", function (ev) { if (ev.target === dom.modalBackdrop) closeModal(); });

    document.addEventListener("keydown", function (ev) {
      if (state.modalKind) { if (ev.key === "Escape") closeModal(); return; }
      if (!state.started) return;
      if (ev.key === " " || ev.key === "Enter" || ev.key === "ArrowRight") {
        if (document.activeElement && document.activeElement.tagName === "BUTTON") return;
        ev.preventDefault(); advance();
      } else if (ev.key === "ArrowLeft" && state.index > 0) {
        ev.preventDefault(); setAuto(false); setSkip(false); renderEntry(state.index - 1);
      } else if (ev.key === "a" || ev.key === "A") setAuto(!state.autoMode);
      else if (ev.key === "s" || ev.key === "S") setSkip(!state.skipMode);
      else if (ev.key === "l" || ev.key === "L") openBacklog();
      else if (ev.key === "h" || ev.key === "H" || ev.key === "Escape") toggleUiHidden();
    });
  }

  refreshTitleScreen();
  wireEvents();
})();
