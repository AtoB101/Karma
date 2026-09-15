/**
 * Karma — 刷脸取景框（Face-ID 式圆形引导）。
 *
 * 为什么要有这个文件：原来刷脸是「开启摄像头 → 页面里出现一条 240px 宽的 video → 点拍一张」。
 * 用户完全不知道自己站对没有，拍出来常常是半张脸或者头顶被切掉，复核方只能打回来重做。
 * 这里换成一次性的取景弹窗：
 *
 *   · 圆形引导圈 + 「头顶和下巴都要在圈内」的明确要求；
 *   · 浏览器给了 FaceDetector 就做**真实**的位置/大小判定，位置对了自动倒数拍；
 *   · 没有 FaceDetector 就退化成「画面稳住了就提示可以确认」——
 *     只报我们真的量到的东西，绝不假装检测到了人脸；
 *   · 拍完先给本人看，本人点「确认使用」才交给上层去加密上传。不存在偷偷拍。
 *
 * 照片全程只在这台设备的浏览器内存里，不上传。
 */
(function () {
  "use strict";

  var MAX_SIDE = 1280;
  var JPEG_QUALITY = 0.72;
  var COUNT_STEP_MS = 700;
  var TICK_MS = 130;

  var state = null;

  /* ------------------------------------------------------------------ 样式 */

  var CSS = [
    ".kfc-overlay{position:fixed;inset:0;z-index:2147483200;display:none;align-items:center;justify-content:center;padding:18px;background:rgba(3,6,18,.8);backdrop-filter:blur(6px)}",
    ".kfc-overlay.kfc-open{display:flex}",
    ".kfc-modal{width:100%;max-width:420px;max-height:92vh;overflow:auto;border-radius:20px;border:1px solid rgba(120,140,255,.28);background:linear-gradient(160deg,#0b1024 0%,#0a0f1f 60%,#080d1a 100%);box-shadow:0 24px 70px rgba(0,0,0,.65);color:#e8ecff;font:14px/1.5 system-ui,-apple-system,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif}",
    ".kfc-head{display:flex;align-items:center;justify-content:space-between;padding:18px 20px 0}",
    ".kfc-head h3{margin:0;font-size:17px;font-weight:650;letter-spacing:.2px}",
    ".kfc-x{width:32px;height:32px;border-radius:10px;border:1px solid rgba(120,140,255,.22);background:rgba(255,255,255,.03);color:#9fb0e0;font-size:18px;line-height:1;cursor:pointer}",
    ".kfc-x:hover{background:rgba(255,255,255,.08);color:#fff}",
    ".kfc-sub{margin:8px 20px 0;color:#9aa8cc;font-size:12.5px}",
    ".kfc-stage{position:relative;margin:14px 20px 0;aspect-ratio:3/4;border-radius:16px;overflow:hidden;background:#04060e}",
    ".kfc-stage video,.kfc-stage img.kfc-shot{width:100%;height:100%;object-fit:cover;display:block;background:#04060e}",
    ".kfc-stage video.kfc-mirror{transform:scaleX(-1)}",
    ".kfc-ring{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);height:64%;aspect-ratio:1/1.26;border-radius:50%;border:2px solid rgba(34,211,238,.9);box-shadow:0 0 0 100vmax rgba(2,4,12,.84),inset 0 0 30px rgba(34,211,238,.22);pointer-events:none;transition:border-color .18s ease,box-shadow .18s ease}",
    ".kfc-ring.kfc-ok{border-color:rgba(110,231,168,.95);box-shadow:0 0 0 100vmax rgba(2,4,12,.84),inset 0 0 34px rgba(110,231,168,.34);animation:kfc-breathe 1.1s ease-in-out infinite}",
    ".kfc-ring.kfc-warn{border-color:rgba(255,190,120,.95);box-shadow:0 0 0 100vmax rgba(2,4,12,.84),inset 0 0 30px rgba(255,190,120,.28)}",
    "@keyframes kfc-breathe{0%,100%{opacity:1}50%{opacity:.62}}",
    ".kfc-edge{position:absolute;left:0;right:0;text-align:center;font-size:11px;letter-spacing:.14em;color:rgba(154,168,204,.85);pointer-events:none}",
    ".kfc-edge-top{top:5%}",
    ".kfc-edge-bot{bottom:5%}",
    ".kfc-edge-ok{color:rgba(110,231,168,.9)}",
    ".kfc-count{position:absolute;inset:0;display:none;align-items:center;justify-content:center;font-size:64px;font-weight:700;color:#6ee7a8;text-shadow:0 0 30px rgba(110,231,168,.6);pointer-events:none}",
    ".kfc-count.kfc-on{display:flex}",
    ".kfc-flag{position:absolute;left:12px;top:12px;padding:4px 10px;border-radius:999px;font-size:11px;border:1px solid rgba(34,211,238,.4);background:rgba(9,14,30,.72);color:#8ee9f7}",
    ".kfc-flag-live{border-color:rgba(255,120,120,.5);color:#ffb4b4}",
    ".kfc-status{margin:12px 20px 0;font-size:13px;color:#cbd6f5;min-height:20px}",
    ".kfc-status.kfc-good{color:#6ee7a8}",
    ".kfc-status.kfc-bad{color:#ffb4b4}",
    ".kfc-actions{display:flex;gap:10px;flex-wrap:wrap;padding:14px 20px 0}",
    ".kfc-actions .btn{flex:0 1 auto}",
    ".kfc-err{margin:12px 20px 0;padding:12px 14px;border-radius:12px;border:1px solid rgba(255,190,120,.34);background:rgba(255,190,120,.08);color:#ffd9a8;font-size:12.5px}",
    ".kfc-note{display:block;padding:14px 20px 18px;color:#7d8bb5;font-size:11.5px}",
    "@media(max-width:520px){.kfc-modal{max-width:100%}}"
  ].join("");

  function injectCss() {
    if (document.getElementById("kfc-styles")) return;
    var s = document.createElement("style");
    s.id = "kfc-styles";
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  /* ------------------------------------------------------------- 小工具 */

  function byId(id) {
    return document.getElementById(id);
  }

  function cameraSupported() {
    return !!(navigator.mediaDevices && typeof navigator.mediaDevices.getUserMedia === "function");
  }

  function frameToB64(video) {
    var w = video && video.videoWidth;
    var h = video && video.videoHeight;
    if (!w || !h) throw new Error("摄像头还没有出画面");
    var scale = Math.min(1, MAX_SIDE / Math.max(w, h));
    var canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(w * scale));
    canvas.height = Math.max(1, Math.round(h * scale));
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    return { b64: canvas.toDataURL("image/jpeg", JPEG_QUALITY).split(",")[1] || "", mime: "image/jpeg" };
  }

  function scaledFileToB64(file) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onerror = function () { reject(new Error("读取文件失败")); };
      reader.onload = function () {
        var img = new Image();
        img.onerror = function () { reject(new Error("这不是一张能识别的图片")); };
        img.onload = function () {
          var scale = Math.min(1, MAX_SIDE / Math.max(img.width, img.height));
          var canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.round(img.width * scale));
          canvas.height = Math.max(1, Math.round(img.height * scale));
          canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
          resolve({
            b64: canvas.toDataURL("image/jpeg", JPEG_QUALITY).split(",")[1] || "",
            mime: "image/jpeg"
          });
        };
        img.src = String(reader.result);
      };
      reader.readAsDataURL(file);
    });
  }

  /* --------------------------------------------------------- 几何与判定 */

  /** video 用了 object-fit:cover，这里把它裁掉的偏移算回来，才能拿圈去比。 */
  function coverGeom(stage, video) {
    var sw = stage.clientWidth || 1;
    var sh = stage.clientHeight || 1;
    var vw = video.videoWidth || sw;
    var vh = video.videoHeight || sh;
    var scale = Math.max(sw / vw, sh / vh);
    return { scale: scale, ox: (sw - vw * scale) / 2, oy: (sh - vh * scale) / 2 };
  }

  function ringBox(stage, ring) {
    var s = stage.getBoundingClientRect();
    var r = ring.getBoundingClientRect();
    return {
      cx: r.left - s.left + r.width / 2,
      cy: r.top - s.top + r.height / 2,
      rx: Math.max(1, r.width / 2),
      ry: Math.max(1, r.height / 2)
    };
  }

  /**
   * 判定人脸框有没有「站对位置」。
   *
   * FaceDetector 给的是人脸区域（大致眉毛到下巴），不含头发，所以这里不假装能测到
   * 头顶 —— 「头顶和下巴都要在圈内」是给用户的取景要求，真正卡的是人脸框的位置、
   * 大小和上下留白。
   */
  function judge(face, geom, box) {
    var x = face.x * geom.scale + geom.ox;
    var y = face.y * geom.scale + geom.oy;
    var w = face.width * geom.scale;
    var h = face.height * geom.scale;
    var dx = (x + w / 2 - box.cx) / box.rx;
    var dy = (y + h / 2 - box.cy) / box.ry;
    var fill = h / (2 * box.ry);
    var topGap = (y - (box.cy - box.ry)) / (2 * box.ry);
    var botGap = (box.cy + box.ry - (y + h)) / (2 * box.ry);

    if (Math.abs(dx) > 0.24 || Math.abs(dy) > 0.26) return { ok: false, msg: "把脸放到圈中间" };
    if (fill < 0.42) return { ok: false, msg: "再靠近一点，让脸占满圈" };
    if (fill > 0.96) return { ok: false, msg: "退后一点，脸太大了" };
    if (topGap < 0.02) return { ok: false, msg: "头再抬一点，别切到上方" };
    if (botGap < 0.02) return { ok: false, msg: "下巴也要在圈内" };
    return { ok: true, msg: "位置合适，别动" };
  }

  /* --------------------------------------------------------- 稳定性兜底 */

  /**
   * 没有 FaceDetector 时的兜底：把画面缩成 16x16 灰度，比较相邻两帧的平均差。
   * 这只说明「画面稳住了」，不说明圈里有人脸 —— 文案必须照实说。
   */
  function makeSteadyMeter() {
    var canvas = document.createElement("canvas");
    canvas.width = 16;
    canvas.height = 16;
    var ctx = canvas.getContext("2d", { willReadFrequently: true });
    var prev = null;
    var lastDiff = 1;
    return {
      feed: function (video) {
        try {
          ctx.drawImage(video, 0, 0, 16, 16);
        } catch (_) {
          return lastDiff;
        }
        var data = ctx.getImageData(0, 0, 16, 16).data;
        var now = [];
        for (var i = 0; i < data.length; i += 4) {
          now.push((data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114) / 255);
        }
        if (prev) {
          var sum = 0;
          for (var j = 0; j < now.length; j += 1) sum += Math.abs(now[j] - prev[j]);
          lastDiff = lastDiff * 0.6 + (sum / now.length) * 0.4;
        }
        prev = now;
        return lastDiff;
      }
    };
  }

  /** 有 FaceDetector 就用真的；没有就 null，走稳定性兜底。 */
  function makeDetector() {
    try {
      if (typeof window.FaceDetector === "function") {
        return new window.FaceDetector({ fastMode: true, maxDetectedFaces: 1 });
      }
    } catch (_) {}
    return null;
  }

  /* ---------------------------------------------------------------- 弹窗 */

  function build() {
    injectCss();
    var node = document.createElement("div");
    node.id = "kfc-overlay";
    node.className = "kfc-overlay";
    node.setAttribute("role", "dialog");
    node.setAttribute("aria-modal", "true");
    node.innerHTML =
      '<div class="kfc-modal">' +
      '<div class="kfc-head"><h3 id="kfc-title">刷脸认证</h3>' +
      '<button type="button" class="kfc-x" data-kfc-close aria-label="关闭">×</button></div>' +
      '<p class="kfc-sub" id="kfc-sub">把脸放进圆圈里：<b>头顶和下巴都要在圈内</b>。照片只留在这台设备上。</p>' +
      '<div class="kfc-stage" id="kfc-stage">' +
      '<video id="kfc-video" playsinline muted autoplay></video>' +
      '<span class="kfc-edge kfc-edge-top" id="kfc-edge-top">头顶要进圈</span>' +
      '<span class="kfc-edge kfc-edge-bot" id="kfc-edge-bot">下巴要进圈</span>' +
      '<div class="kfc-ring" id="kfc-ring"></div>' +
      '<div class="kfc-count" id="kfc-count">3</div>' +
      '<span class="kfc-flag" id="kfc-flag">预览中</span>' +
      "</div>" +
      '<div class="kfc-status" id="kfc-status">正在打开摄像头…</div>' +
      '<div class="kfc-err" id="kfc-err" hidden></div>' +
      '<div class="kfc-actions" id="kfc-actions"></div>' +
      '<span class="kfc-note">🔒 照片不会离开这台设备 · 加密后才上传 · 全程不接触私钥 / 助记词</span>' +
      '<input type="file" id="kfc-file" accept="image/*" hidden />' +
      "</div>";
    document.body.appendChild(node);

    node.addEventListener("click", function (ev) {
      if (ev.target === node || ev.target.closest("[data-kfc-close]")) cancel();
    });
    // 只绑一次：绑在 document 上，靠 state 判断当前有没有弹窗，
    // 这样「取消一次之后再打开」ESC 依然好使。
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && state) cancel();
    });
    byId("kfc-file").addEventListener("change", onFilePicked);
    return node;
  }

  function setStatus(text, kind) {
    var n = byId("kfc-status");
    if (!n) return;
    n.textContent = text;
    n.className = "kfc-status" + (kind ? " kfc-" + kind : "");
  }

  function setRing(kind) {
    var r = byId("kfc-ring");
    if (r) r.className = "kfc-ring" + (kind ? " kfc-" + kind : "");
    // 圈到位的时候，把「头顶 / 下巴」两条提示也点亮，用户一眼知道是整张脸都进去了。
    var lit = kind === "ok" ? " kfc-edge-ok" : "";
    ["kfc-edge-top", "kfc-edge-bot"].forEach(function (id) {
      var n = byId(id);
      if (n) n.className = "kfc-edge " + (id === "kfc-edge-top" ? "kfc-edge-top" : "kfc-edge-bot") + lit;
    });
  }

  function actions(list) {
    var wrap = byId("kfc-actions");
    if (!wrap) return;
    wrap.innerHTML = "";
    list.forEach(function (a) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "btn" + (a.primary ? " primary" : "");
      b.setAttribute("data-kfc-act", a.key);
      b.textContent = a.label;
      b.addEventListener("click", a.onClick);
      wrap.appendChild(b);
    });
  }

  function pickFile() {
    var input = byId("kfc-file");
    if (input) input.click();
  }

  function stopStream() {
    if (state && state.stream) {
      state.stream.getTracks().forEach(function (t) {
        try { t.stop(); } catch (_) {}
      });
      state.stream = null;
    }
  }

  function stopLoop() {
    if (state && state.timer) {
      clearTimeout(state.timer);
      state.timer = null;
    }
  }

  function closeOverlay() {
    stopLoop();
    stopStream();
    if (state) {
      state.stopped = true;
      if (state.countdown) {
        clearTimeout(state.countdown);
        state.countdown = null;
      }
    }
    var node = byId("kfc-overlay");
    if (node) node.classList.remove("kfc-open");
    var video = byId("kfc-video");
    if (video) video.srcObject = null;
  }

  function settle(shot) {
    var done = state && state.done;
    closeOverlay();
    state = null;
    if (done) done(shot);
  }

  function cancel() {
    settle(null);
  }

  /* ------------------------------------------------------------ 摄像头 */

  async function listCameras() {
    try {
      var devices = await navigator.mediaDevices.enumerateDevices();
      return devices.filter(function (d) { return d.kind === "videoinput"; });
    } catch (_) {
      return [];
    }
  }

  async function startStream(facing, deviceId) {
    var constraints = deviceId
      ? { video: { deviceId: { exact: deviceId }, width: { ideal: 720 }, height: { ideal: 960 } } }
      : { video: { facingMode: { ideal: facing }, width: { ideal: 720 }, height: { ideal: 960 } } };
    var stream = await navigator.mediaDevices.getUserMedia(constraints);
    // 用户可能在授权弹窗那几秒里按了取消：这时必须把刚到手的摄像头关掉，
    // 否则摄像头的灯会一直亮着。
    if (!state || state.stopped) {
      stream.getTracks().forEach(function (t) {
        try { t.stop(); } catch (_) {}
      });
      return null;
    }
    var video = byId("kfc-video");
    video.srcObject = stream;
    video.classList.toggle("kfc-mirror", (facing || "user") === "user");
    state.stream = stream;
    await video.play();
    return stream;
  }

  /* ------------------------------------------------------------- 主循环 */

  function tick() {
    if (!state || state.stopped) return;
    var video = byId("kfc-video");
    var stage = byId("kfc-stage");
    var ring = byId("kfc-ring");
    if (video && stage && ring && state.mode === "live" && video.videoWidth) {
      if (state.detector) {
        state.detector
          .detect(video)
          .then(function (faces) {
            if (!state || state.stopped || state.mode !== "live") return;
            onFaces(faces, stage, video, ring);
          })
          .catch(function () {
            // 检测器在某些机器上直接抛：退化成稳定性提示，不装作还在检测。
            if (!state) return;
            state.detector = null;
          });
      } else {
        onSteady(video);
      }
    }
    state.timer = setTimeout(tick, TICK_MS);
  }

  function onFaces(faces, stage, video, ring) {
    if (!faces || !faces.length) {
      setRing("");
      stopCountdown();
      setStatus("把脸放进圈里 —— 头顶和下巴都要在圈内");
      return;
    }
    var verdict = judge(faces[0].boundingBox, coverGeom(stage, video), ringBox(stage, ring));
    if (!verdict.ok) {
      setRing("warn");
      stopCountdown();
      setStatus(verdict.msg);
      return;
    }
    setRing("ok");
    if (state.countdown) return;
    var n = 3;
    var countNode = byId("kfc-count");
    setStatus("位置合适，别动 —— 正在自动拍摄", "good");
    var step = function () {
      if (!state || state.stopped || state.mode !== "live") return;
      if (n <= 0) {
        if (countNode) countNode.classList.remove("kfc-on");
        state.countdown = null;
        shoot();
        return;
      }
      if (countNode) {
        countNode.textContent = String(n);
        countNode.classList.add("kfc-on");
      }
      n -= 1;
      state.countdown = setTimeout(step, COUNT_STEP_MS);
    };
    step();
  }

  function stopCountdown() {
    if (state && state.countdown) {
      clearTimeout(state.countdown);
      state.countdown = null;
    }
    var c = byId("kfc-count");
    if (c) c.classList.remove("kfc-on");
  }

  function onSteady(video) {
    var diff = state.meter.feed(video);
    if (diff < 0.02) {
      state.steadyFrames += 1;
    } else {
      state.steadyFrames = 0;
    }
    if (state.steadyFrames > 6) {
      setRing("ok");
      setStatus("画面稳住了 —— 点「确认这张」", "good");
    } else {
      setRing("");
      setStatus("把脸放进圈里 —— 头顶和下巴都要在圈内；稳住别动");
    }
  }

  /* ------------------------------------------------------------- 拍摄 */

  function shoot() {
    if (!state || state.mode !== "live") return;
    var shot;
    try {
      shot = frameToB64(byId("kfc-video"));
    } catch (e) {
      setStatus((e && e.message) || "没抓到画面，再试一次", "bad");
      return;
    }
    state.shot = shot;
    state.mode = "review";
    stopStream();
    stopCountdown();

    var stage = byId("kfc-stage");
    stage.querySelectorAll("img.kfc-shot").forEach(function (n) { n.remove(); });
    var img = document.createElement("img");
    img.className = "kfc-shot";
    img.alt = "刚拍的人脸";
    img.src = "data:image/jpeg;base64," + shot.b64;
    stage.insertBefore(img, stage.firstChild);
    var v = byId("kfc-video");
    if (v) v.style.display = "none";
    var ring = byId("kfc-ring");
    if (ring) ring.style.display = "none";
    var flag = byId("kfc-flag");
    if (flag) {
      flag.textContent = "已拍 · 待确认";
      flag.classList.add("kfc-flag-live");
    }
    setStatus("对一下：头顶和下巴都在圈内、脸清楚没糊。没问题就点「确认使用」。", "good");
    actions([
      { key: "use", label: "确认使用", primary: true, onClick: function () { if (state) settle(state.shot); } },
      { key: "retake", label: "重拍", onClick: retake },
      { key: "pick", label: "改用照片", onClick: pickFile }
    ]);
  }

  function retake() {
    if (!state) return;
    var stage = byId("kfc-stage");
    stage.querySelectorAll("img.kfc-shot").forEach(function (n) { n.remove(); });
    var v = byId("kfc-video");
    if (v) v.style.display = "";
    var ring = byId("kfc-ring");
    if (ring) ring.style.display = "";
    var flag = byId("kfc-flag");
    if (flag) {
      flag.textContent = "预览中";
      flag.classList.remove("kfc-flag-live");
    }
    state.mode = "live";
    state.steadyFrames = 0;
    state.countdown = null;
    state.shot = null;
    renderLiveActions();
    openStream().catch(function () {});
  }

  async function onFilePicked(ev) {
    var f = ev.target.files && ev.target.files[0];
    ev.target.value = "";
    if (!f || !state) return;
    try {
      var shot = await scaledFileToB64(f);
      settle(shot);
    } catch (e) {
      showError((e && e.message) || "这张图片读不出来");
    }
  }

  function showError(text) {
    var n = byId("kfc-err");
    if (!n) return;
    n.textContent = text;
    n.hidden = false;
  }

  function renderLiveActions() {
    if (!state) return;
    var list = [
      { key: "shot", label: "确认这张", primary: true, onClick: shoot },
      { key: "pick", label: "用照片", onClick: pickFile }
    ];
    if (state.cameras && state.cameras.length > 1) {
      list.splice(1, 0, { key: "switch", label: "切换摄像头", onClick: switchCamera });
    }
    actions(list);
  }

  async function switchCamera() {
    if (!state || !state.cameras || state.cameras.length < 2) return;
    state.camIndex = (state.camIndex + 1) % state.cameras.length;
    var cam = state.cameras[state.camIndex];
    state.facing = /back|rear|environment|后/i.test(cam.label || "") ? "environment" : "user";
    stopStream();
    stopCountdown();
    try {
      var stream = await startStream(state.facing, cam.deviceId);
      if (!stream) return;
      setStatus("已切到：" + (cam.label || "摄像头 " + (state.camIndex + 1)));
    } catch (e) {
      showError("这个摄像头打不开：" + ((e && e.message) || e));
    }
  }

  async function openStream() {
    try {
      var stream = await startStream(state.facing, state.deviceId);
      if (!stream) return;
    } catch (e) {
      var name = (e && e.name) || "";
      var why = "打不开摄像头。";
      if (name === "NotAllowedError" || name === "SecurityError") {
        why = "摄像头权限被拒绝了（或这个页面不是 HTTPS）。在浏览器地址栏那边允许一次就行。";
      } else if (name === "NotFoundError" || name === "OverconstrainedError") {
        why = "这台设备上没有找到摄像头。";
      } else if (name === "NotReadableError" || name === "TrackStartError") {
        why = "摄像头被别的程序占着（会议软件、相机），关掉再试。";
      }
      setStatus(why + " 也可以点下面「用照片」直接传一张。", "bad");
      setRing("");
      showError(why);
      actions([
        { key: "pick", label: "用照片", primary: true, onClick: pickFile },
        { key: "retry", label: "再试一次", onClick: function () { byId("kfc-err").hidden = true; openStream(); } }
      ]);
      return;
    }
    state.cameras = await listCameras();
    if (!state || state.stopped) return;
    renderLiveActions();
    setStatus(
      state.detector
        ? "把脸放进圈里 —— 位置对了会自动拍"
        : "把脸放进圈里 —— 头顶和下巴都要在圈内；稳住后点「确认这张」"
    );
    stopLoop();
    tick();
  }

  /**
   * 打开取景框。resolve 出 { b64, mime }；用户取消则 resolve(null)。
   * 不 reject —— 打不开摄像头这种事在弹窗里说清楚。
   */
  function open(options) {
    var opts = options || {};
    if (!cameraSupported()) {
      // 连 getUserMedia 都没有（http 页面 / 老浏览器）：把选择权交回给调用方的「用照片」。
      return Promise.resolve(null);
    }
    return new Promise(function (resolve) {
      var node = byId("kfc-overlay") || build();
      node.classList.add("kfc-open");
      byId("kfc-title").textContent = opts.title || "刷脸认证";
      byId("kfc-sub").innerHTML =
        opts.subtitle || "把脸放进圆圈里：<b>头顶和下巴都要在圈内</b>。照片只留在这台设备上。";
      var err = byId("kfc-err");
      err.hidden = true;
      err.textContent = "";
      var v = byId("kfc-video");
      v.style.display = "";
      var ring = byId("kfc-ring");
      ring.style.display = "";
      ring.className = "kfc-ring";
      var flag = byId("kfc-flag");
      flag.textContent = "预览中";
      flag.classList.remove("kfc-flag-live");
      byId("kfc-stage").querySelectorAll("img.kfc-shot").forEach(function (n) { n.remove(); });
      setStatus("正在打开摄像头…");

      state = {
        done: resolve,
        stream: null,
        mode: "live",
        facing: opts.facing || "user",
        deviceId: null,
        camIndex: -1,
        cameras: [],
        shot: null,
        detector: makeDetector(),
        meter: makeSteadyMeter(),
        steadyFrames: 0,
        countdown: null,
        timer: null,
        stopped: false
      };
      renderLiveActions();
      openStream().catch(function () {});
    });
  }

  window.KarmaFaceCapture = {
    open: open,
    supported: cameraSupported,
    hasFaceDetector: function () { return !!makeDetector(); }
  };
})();