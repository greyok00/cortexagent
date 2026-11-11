/* assist-model.js — the optional local LLM for the curation assist pane.
 *
 * Runs entirely in the visitor's browser: WebGPU through the vendored WebLLM
 * (SmolLM2-360M, weights + wasm self-hosted under /assets/), falling back to
 * a CPU/wasm path through transformers.js (SmolLM2-135M) in a worker. The
 * server's GPU is never touched; when nothing loads, the pane stays on the
 * heuristic scores, which are always present.
 *
 * The judgement task is deliberately narrow: for each shortlisted paragraph
 * the model answers keep|burn|maybe with a few words of why. It is advisory;
 * the heuristic suggestion stays the baseline.
 */
(function () {
  "use strict";

  var MODEL_ID = "SmolLM2-360M-Instruct-q4f16_1-MLC";
  var MODEL_DIR = "/assets/models/SmolLM2-360M-Instruct-q4f16_1-MLC";
  var MODEL_LIB = "/assets/vendor/web-llm/SmolLM2-360M-Instruct-q4f16_1_cs1k-webgpu.wasm";
  var CPU_MODEL = "hf/SmolLM2-135M-Instruct";   // relative: localModelPath root
  var CPU_MODEL_ROOT = "/assets/models/";
  var CPU_WORKER = "/assets/vendor/cpu-worker.js";

  var state = {
    kind: "",          // "webgpu" | "cpu" | ""
    engine: null,      // WebLLM engine or the cpu worker
    loading: false,
    ready: false,
    error: "",
    note: "",          // human line about which backend answered
  };
  var listeners = [];

  function emit(progress, text) {
    listeners.forEach(function (fn) {
      try { fn(progress, text, state); } catch (e) { /* one bad pane */ }
    });
  }

  function on(fn) { listeners.push(fn); }

  function status() {
    return { kind: state.kind, ready: state.ready, loading: state.loading,
             error: state.error, note: state.note };
  }

  function gpuAvailable() {
    try {
      var g = navigator.gpu;
      if (!g) return Promise.resolve(false);
      // the q4f16_1 weights need shader-f16; a GPU without it is "no gpu"
      // for this model, and the CPU path takes over
      return g.requestAdapter().then(function (a) {
        return !!(a && a.features && a.features.has("shader-f16"));
      }).catch(function () { return false; });
    } catch (e) { return Promise.resolve(false); }
  }

  function loadWebGPU() {
    emit(0.02, "Starting the local model (WebGPU)…");
    return import("/assets/vendor/web-llm/index.js").then(function (webllm) {
      // appConfig shape: { model_list: [record] }; engine.reload takes the
      // model id, not the config — the config rides on the constructor.
      var appConfig = {
        model_list: [{
          model_id: MODEL_ID,
          // absolute URL: WebLLM rewrites relative model urls as
          // <model>/resolve/main/ for HF, which breaks local dirs
          model: location.origin + MODEL_DIR,
          model_lib: location.origin + MODEL_LIB,
          overrides: { context_window_size: 4096 },
        }],
      };
      var engine = new webllm.MLCEngine({ appConfig: appConfig });
      var lastPct = 0;
      engine.setInitProgressCallback(function (r) {
        var p = Number(r.progress || 0);
        lastPct = p;
        emit(0.02 + p * 0.93, r.text || "loading the model…");
      });
      return engine.reload(MODEL_ID).then(function () {
        state.kind = "webgpu";
        state.engine = engine;
        state.ready = true;
        state.loading = false;
        state.note = "local model on your GPU (WebGPU) — SmolLM2 360M";
        emit(1, state.note);
        return state;
      }).catch(function (e) {
        // shader-f16 is a hard requirement of the q4f16_1 weights; a GPU
        // without it (many iGPUs, swiftshader) must fall back, not error
        try { engine.unload(); } catch (er) {}
        throw e;
      });
    });
  }

  function loadCPU() {
    emit(0.02, "No WebGPU — starting the CPU compatibility model…");
    return new Promise(function (resolve, reject) {
      var w;
      try {
        w = new Worker(CPU_WORKER, { type: "module" });
      } catch (e) { reject(e); return; }
      var settled = false;
      var timer = setTimeout(function () {
        if (!settled) { settled = true; reject(new Error("cpu model did not start in 180s")); }
      }, 180000);
      w.onmessage = function (ev) {
        var m = ev.data || {};
        if (m.type === "progress") emit(0.02 + (m.progress || 0) * 0.93, m.text || "loading…");
        else if (m.type === "ready") {
          settled = true; clearTimeout(timer);
          state.kind = "cpu"; state.engine = w; state.ready = true;
          state.loading = false;
          state.note = "local model on your CPU (wasm) — SmolLM2 135M";
          emit(1, state.note);
          resolve(state);
        } else if (m.type === "error") {
          settled = true; clearTimeout(timer);
          reject(new Error(m.message || "cpu model failed"));
        }
      };
      w.onerror = function (e) {
        if (!settled) { settled = true; clearTimeout(timer); reject(new Error(e.message || "worker error")); }
      };
      w.postMessage({ type: "init", model: CPU_MODEL, dtype: "int8",
                      mirror: "", localModelPath: CPU_MODEL_ROOT });
      state.engine = w;
    });
  }

  /* ---- generation ------------------------------------------------------ */

  var pendingId = null, cpuText = "", streamCb = null, streamTick = null;

  function chat(messages, onStream) {
    if (!state.ready) return Promise.reject(new Error("model not loaded"));
    if (state.kind === "webgpu") {
      return state.engine.chat.completions.create({
        messages: messages, temperature: 0.2, max_tokens: 900, stream: true,
      }).then(function (it) {
        var full = "";
        function step() {
          var next = it.next();
          if (next.done) return Promise.resolve(full);
          var t = ((next.value.choices || [{}])[0].delta || {}).content || "";
          if (t) { full += t; if (onStream) onStream(full); }
          return step();
        }
        return step();
      });
    }
    // cpu worker: one generate at a time; tokens land via polling the
    // accumulated text on a short interval (the worker also pushes its own
    // token events; polling is the safety net for dropped messages).
    return new Promise(function (resolve, reject) {
      if (pendingId !== null) { reject(new Error("a reply is already running")); return; }
      cpuText = "";
      var settle = function (err) {
        clearInterval(streamTick); streamTick = null;
        var t = cpuText; pendingId = null; cpuText = "";
        if (err && !t) reject(new Error(err));
        else resolve(t);
      };
      var handler = function (ev) {
        var m = ev.data || {};
        if (m.type === "token" && m.text) cpuText += m.text;
        else if (m.type === "done") settle("");
        else if (m.type === "generate-error") settle(m.message || "generation failed");
      };
      state.engine.addEventListener("message", handler);
      // poll as a safety net in case a token or done event is missed
      streamTick = setInterval(function () {
        if (onStream && cpuText) onStream(cpuText);
        if (pendingId === null) {
          state.engine.removeEventListener("message", handler);
          clearInterval(streamTick); streamTick = null;
        }
      }, 150);
      pendingId = "g" + String(Date.now());
      var sys = messages[0] && messages[0].role === "system" ? messages[0] : null;
      var msgs = sys ? messages : (messages || []);
      state.engine.postMessage({ type: "generate", id: pendingId,
                                 messages: msgs, maxTokens: 700,
                                 temperature: 0.2 });
    });
  }

  function load() {
    if (state.ready || state.loading) return Promise.resolve(state);
    state.loading = true; state.error = "";
    emit(0, "preparing…");
    return gpuAvailable().then(function (ok) {
      var p = ok ? loadWebGPU().catch(function (e) {
        if (state.engine && state.engine.unload) { try { state.engine.unload(); } catch (er) {} }
        return loadCPU();
      }) : loadCPU();
      return p.catch(function (e) {
        state.loading = false; state.ready = false;
        state.error = String(e && e.message || e);
        emit(0, "the local model did not load — heuristic guidance stays");
        throw e;
      });
    });
  }

  /* The judgment prompt: verdict per paragraph, one line each, parseable. */
  /* The judgment prompt: verdict per note, one line each, parseable. */
  var SYSTEM = {
    role: "system",
    content:
      "You label research notes. For each note output one line like " +
      "\"0=keep relevant detail\" or \"1=burn filler text\". Nothing else.",
  };

  var VERDICT_RE = /\b(\d+)\s*[.=:]\s*(keep|burn|maybe|drop)\b/i;

  /* judge(items, question, onLine): items [{pid, text, score}]
     resolves [{pid, verdict, why}] — unparsable lines are skipped. Tolerant
     of small-model formats: "1=Keep", "1 - keep: filler", "1 keep". */
  function judge(items, question, onLine) {
    var body = "Question: " + question + "\n\nNotes:\n" + items.map(function (it, i) {
      var t = String(it.text || "").replace(/\s+/g, " ").trim();
      if (t.length > 380) t = t.slice(0, 380) + "…";
      return i + ". " + t;
    }).join("\n");
    var out = [];
    return chat([
      SYSTEM,
      { role: "user", content: body +
        "\n\nExample output:\n0=keep answers the question\n1=burn not about the question" },
    ], onLine ? function (partial) {
      String(partial).split(/\n|;/).forEach(function (ln) {
        var m = ln.match(VERDICT_RE);
        if (!m) return;
        var idx = Number(m[1]);
        var it = items[idx] || {};
        if (it.pid === undefined) return;
        if (out.some(function (o) { return o.pid === it.pid; })) return;
        var vv = m[2].toLowerCase() === "drop" ? "burn" : m[2].toLowerCase();
        out.push({ pid: it.pid, verdict: vv,
                   why: String(ln).replace(m[0], "").replace(/[^A-Za-z0-9 ,'-]/g, " ")
                     .replace(/\s+/g, " ").trim().slice(0, 60) });
        onLine(out.slice());
      });
    } : undefined).then(function () { return out; });
  }

  /* judgeYesNo(notes, question, onNote): the small-model-reliable format.
     One YES/NO generate per note, sequential; resolves
     [{index, keep, raw}]. Works on every SmolLM2 variant (the batch
     "N=keep" format needs a bigger model; on WebGPU boxes judge() is
     preferred for its reasons). */
  function judgeYesNo(notes, question, onNote) {
    var out = [];
    var chain = Promise.resolve();
    notes.forEach(function (note, i) {
      chain = chain.then(function () {
        return chat([
          { role: "system", content: "Answer YES or NO only." },
          { role: "user", content:
            "Question: " + question +
            "\nIs this note useful for answering it?\nNote: " + note },
        ]).then(function (text) {
          var t = String(text || "").toUpperCase();
          var r = { index: i, keep: t.indexOf("YES") >= 0,
                    raw: String(text || "").trim().slice(0, 60) };
          out.push(r);
          if (onNote) onNote(r);
        });
      });
    });
    return chain.then(function () { return out; });
  }

  window.GSAssistModel = {
    load: load, status: status, on: on, judge: judge,
    judgeYesNo: judgeYesNo,
  };
})();
