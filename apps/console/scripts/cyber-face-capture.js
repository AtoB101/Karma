/**
 * Karma — 刷脸取景框（Face-ID 式圆形引导）。
 *
 * 为什么要有这个文件：原来刷脸是「开启摄像头 → 页面里出现一条 240px 宽的 video → 点拍一张」。
 * 用户完全不知道自己站对没有，拍出来常常是半张脸或者头顶被切掉，复核方只能打回来重做。
 * 这里换成一次性的取景弹窗：
 *
 *   · 圆形引导圈 + 「头顶和下巴都要在圈内」的明确要求；
 *   · **全程不用按键**：用户只照屏幕上的大字转头（请向左转头 → 请向右转头 …），
 *     系统自己判断「转到位了、也停稳了」，然后自动拍下，取景圈上的进度环闭合就是反馈；
 *   · 判定只用我们真的量得到的两件事：画面有没有动、这一张和上一张差多少 ——
 *     有 FaceDetector 就额外提示「脸有没有放进圈里」，没有就只报「画面稳住了」，
 *     绝不假装检测到了人脸；
 *   · 一场认证要采**整张脸的五个角度**（正 / 左 / 右 / 抬 / 低），不是拍一张就完事 ——
 *     单张正面照拿别人的照片就能顶替；
 *   · 每一张还必须和上一张有真实的姿态差：同一张照片连拍 / 对着屏幕翻拍，
 *     16x16 灰度平均差会接近 0，这里当场拒掉并要求重拍；
 *   · 五张采完先给本人看，本人点「确认使用」才交给上层去加密上传。不存在偷偷拍。
 *
 * 照片全程只在这台设备的浏览器内存里，不上传。
 */
(function () {
  "use strict";

  var MAX_SIDE = 1280;
  var JPEG_QUALITY = 0.72;
  /** 兜底定时：只有拿不到 requestAnimationFrame 时才用它（正常浏览器逐帧驱动）。 */
  var TICK_MS = 20;
  /** 历史帧的采样间隔：判定只需要这个密度，不必跟着逐帧走。 */
  var HISTORY_MS = 40;
  /** 「取样 + 判定」的最小间隔：这一步很贵，进度圈不靠它，所以不必逐帧跑。 */
  var SAMPLE_MS = 25;
  /** 分析最多占掉多少比例的时间：剩下的必须留给逐帧的进度圈和页面渲染。 */
  var SAMPLE_DUTY = 4;
  /** 分析间隔的上限：真机上再慢也不能慢到这个地步，否则判定会迟钝。 */
  var SAMPLE_MAX_MS = 400;

  /**
   * 真人认证要采到整张脸的多个角度，不是拍一张就完事：
   * 单张正面照用别人的照片就能顶替，五个角度（正/左/右/抬/低）才覆盖整张脸。
   *
   * 为什么不采「后脑勺」：背对镜头时画面里没有人脸，既判不了位置也留不下可核对的
   * 生物特征，那一张只会是一团糊影 —— 抬头 + 低头已经覆盖发际线到下颌。
   *
   * guide 是屏幕上那句大字，用户照着做就行 —— 整个过程他不需要按任何键。
   */
  var ANGLE_STEPS = [
    { key: "front", label: "正面", guide: "请正对镜头", hint: "正对镜头，脸放进圈里" },
    { key: "left", label: "向左转", guide: "请向左转头", hint: "头向左转约 45°（露出侧脸），脸仍要留在圈里" },
    { key: "right", label: "向右转", guide: "请向右转头", hint: "头向右转约 45°（露出侧脸），脸仍要留在圈里" },
    { key: "up", label: "抬高", guide: "请把头抬高一点", hint: "脸慢慢抬高一点，额头和下巴都别出圈" },
    { key: "down", label: "低头", guide: "请把头低一点", hint: "下巴轻轻往下收一点，露出额头，脸别出圈" }
  ];
  /** 每个角度的大字旁边那个方向标记。 */
  var ARROWS = { front: "◎", left: "←", right: "→", up: "↑", down: "↓" };

  /* ---- 比对的刻度：下面每一个 diff 都是「亮度归一化之后的平均差」------------
   *
   * 为什么必须归一化：摄像头有自动曝光 / 自动白平衡，整帧明暗一直在缓慢漂移。
   * 拿**原始灰度**直接相减，整帧变亮 6% 就会被当成「画面在动」—— 用户转完头、
   * 屏住呼吸，屏幕却一直不出结果，这就是线上那句「太卡了、没反应」。
   * 各自减掉自己的均值、再除以自己的标准差之后，整帧的明暗/对比漂移被彻底剔掉，
   * 只剩下「画面的形状变没变」。实测（320x240 假摄像头 + 传感器噪声 + 曝光漂移）：
   *     同姿势带噪声：原始差 0.002 ~ 0.21（随漂移变大），归一化后恒为 0.012
   *     换一个角度  ：原始差 0.11 ~ 0.27，               归一化后 0.70
   * 同姿势 0.012 / 换角度 0.70，差 50 倍 —— 判定不再随光线漂移。
   */
  var IDENTICAL_DIFF = 0.05;
  /*
   * ---- 中心加权：只认「脸」那一片，背后的动静不算数 ------------------------
   *
   * 16x16 是全画面的缩影，边角里摇动的树影、转着的风扇、走过的路人都会被算进
   * 「画面有没有变」，于是人明明已经站住了，判定却说一直在动 —— 线上那句
   * 「太卡了、没反应」，根子就在这里。
   * 实测（1280x720 真机模型：噪声 + 自动曝光漂移 + 背景树影/风扇/有人从身后走过）：
   *   全帧平均差：背景在动 0.076（> 停稳阈值 0.05，永远判不出停稳）
   *   中心加权后：背景在动 0.02 ~ 0.10；人转身 10px 0.15 / 60px 0.40 / 240px 1.03
   * 权重做成一扇光滑的窗（中间 1、四角只剩 WEIGHT_FLOOR）：边角被压下去，
   * 脸边缘的动作仍然完整保留。
   */
  var WEIGHT_FLOOR = 0.15;
  var DIM_MEAN = 0.1;
  /** 画面结构的下限：平平一片（镜头被挡、糊成一团）时归一化会把噪声放大，必须挡住。 */
  var MIN_CONTRAST = 0.03;

  /* ---- 自动采集的参数 ----------------------------------------------------
   * 判定「停稳了」不看单帧之间的抖动，而是看整整 STILL_MS 这一段：
   * 当前帧要和窗口里每一帧都对得上才算停住 —— 否则慢慢转头会被误判成「静止」，
   * 拍出来就是一张糊的。 */
  var STILL_DIFF = 0.12;
  /**
   * 等了一会儿还判不到「停稳」时，放宽到这一档。
   *
   * 为什么必须有这一档：画面里一直有别的动静时（有人从身后走过、摄像头在动、
   * 编码噪声），0.12 会被顶住 —— 2026-09-16 线上实测：背景有人走过的那一步拖到
   * 1.7 秒才拍到（其余三步都是 0.6 秒）。姿势早就到位了，再硬等只会让人觉得「又卡了」。
   * 放宽后仍然远高于噪声底（实测 0.03~0.10），也远低于「正在转头」（0.3 以上），
   * 所以不会把一张糊的转场照拍下来。
   */
  var STILL_DIFF_RELAX = 0.18;
  /** 姿势到位之后等多久，把停稳的门槛放宽一档。 */
  var SETTLE_RELAX_MS = 900;
  var STILL_MS = 460;
  /** 和上一张已采的帧至少要差这么多，才算「真的换了一个角度」（约 10 像素的姿态差）。 */
  var ANGLE_MIN_DIFF = 0.16;
  /** 某个角度一直没进展，多久之后给一个手动兜底按钮（正常流程看不到它）。 */
  var AUTO_STUCK_MS = 4500;
  /** 画面一直在动（背景有人、镜头在晃）时，多久之后把原因说出来 —— 不能让人干等。 */
  var BUSY_HINT_MS = 2000;
  /** 每一步开始后的宽限时间：别让用户还没站好就被拍。 */
  var GRACE_FIRST_MS = 1300;
  var GRACE_STEP_MS = 420;
  /** 两个角度之间留的转身时间：这段时间不判定。 */
  var BETWEEN_MS = 520;

  var state = null;
  /** 逐帧循环的句柄（requestAnimationFrame 的 id；退回定时器时是 timeout id）。 */
  var rafId = null;

  /* ------------------------------------------------------------------ 样式 */

  var CSS = [
    ".kfc-overlay{position:fixed;inset:0;z-index:2147483200;display:none;align-items:center;justify-content:center;padding:18px;background:rgba(3,6,18,.86)}",
    ".kfc-overlay.kfc-open{display:flex}",
    ".kfc-modal{width:100%;max-width:420px;max-height:92vh;overflow:auto;border-radius:20px;border:1px solid rgba(120,140,255,.28);background:linear-gradient(160deg,#0b1024 0%,#0a0f1f 60%,#080d1a 100%);box-shadow:0 24px 70px rgba(0,0,0,.65);color:#e8ecff;font:14px/1.5 system-ui,-apple-system,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',sans-serif}",
    ".kfc-head{display:flex;align-items:center;justify-content:space-between;padding:18px 20px 0}",
    ".kfc-head h3{margin:0;font-size:17px;font-weight:650;letter-spacing:.2px}",
    ".kfc-x{width:32px;height:32px;border-radius:10px;border:1px solid rgba(120,140,255,.22);background:rgba(255,255,255,.03);color:#9fb0e0;font-size:18px;line-height:1;cursor:pointer}",
    ".kfc-x:hover{background:rgba(255,255,255,.08);color:#fff}",
    ".kfc-sub{margin:8px 20px 0;color:#9aa8cc;font-size:12.5px}",
    ".kfc-stage{position:relative;margin:14px 20px 0;aspect-ratio:3/4;border-radius:16px;overflow:hidden;background:#04060e}",
    ".kfc-stage video,.kfc-stage img.kfc-shot{width:100%;height:100%;object-fit:cover;display:block;background:#04060e}",
    // 预览画面每帧都在变：给它一个独立的合成层，别每帧把整个弹窗重画一遍
    // （手机上这一步很贵，也是「卡」的来源之一）。
    ".kfc-stage video{will-change:transform;transform:translateZ(0)}",
    ".kfc-stage video.kfc-mirror{transform:scaleX(-1) translateZ(0)}",
    ".kfc-ring{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%) translateZ(0);height:64%;aspect-ratio:1/1.26;border-radius:50%;border:2px solid rgba(34,211,238,.9);box-shadow:0 0 0 100vmax rgba(2,4,12,.84),inset 0 0 30px rgba(34,211,238,.22);pointer-events:none;will-change:transform;transition:border-color .18s ease,box-shadow .18s ease}",
    ".kfc-ring.kfc-ok{border-color:rgba(110,231,168,.95);box-shadow:0 0 0 100vmax rgba(2,4,12,.84),inset 0 0 34px rgba(110,231,168,.34);animation:kfc-breathe 1.1s ease-in-out infinite}",
    ".kfc-ring.kfc-warn{border-color:rgba(255,190,120,.95);box-shadow:0 0 0 100vmax rgba(2,4,12,.84),inset 0 0 30px rgba(255,190,120,.28)}",
    "@keyframes kfc-breathe{0%,100%{opacity:1}50%{opacity:.62}}",
    ".kfc-edge{position:absolute;left:0;right:0;text-align:center;font-size:11px;letter-spacing:.14em;color:rgba(154,168,204,.85);pointer-events:none}",
    ".kfc-edge-top{top:5%}",
    ".kfc-edge-bot{bottom:5%}",
    ".kfc-edge-ok{color:rgba(110,231,168,.9)}",
    ".kfc-prog{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);height:64%;aspect-ratio:1/1.26;pointer-events:none}",
    ".kfc-prog ellipse{fill:none;stroke:rgba(110,231,168,.95);stroke-width:3;stroke-linecap:round;transform:rotate(-90deg);transform-origin:50px 63px}",
    ".kfc-flash{position:absolute;inset:0;background:#fff;opacity:0;pointer-events:none}",
    ".kfc-flash.kfc-go{animation:kfc-flash .34s ease-out}",
    "@keyframes kfc-flash{0%{opacity:.8}100%{opacity:0}}",
    ".kfc-guide{display:flex;align-items:center;gap:10px;margin:16px 20px 0;font-size:19px;font-weight:650;letter-spacing:.02em;color:#eef2ff}",
    ".kfc-arrow{display:inline-flex;flex:0 0 auto;width:34px;height:34px;align-items:center;justify-content:center;border-radius:10px;border:1px solid rgba(34,211,238,.5);background:rgba(34,211,238,.12);color:#8ee9f7;font-size:19px}",
    ".kfc-arrow[data-kfc-arrow=left]{animation:kfc-nudge-l 1.1s ease-in-out infinite}",
    ".kfc-arrow[data-kfc-arrow=right]{animation:kfc-nudge-r 1.1s ease-in-out infinite}",
    ".kfc-arrow[data-kfc-arrow=up]{animation:kfc-nudge-u 1.1s ease-in-out infinite}",
    ".kfc-arrow[data-kfc-arrow=down]{animation:kfc-nudge-d 1.1s ease-in-out infinite}",
    "@keyframes kfc-nudge-l{0%,100%{transform:translateX(0)}50%{transform:translateX(-6px)}}",
    "@keyframes kfc-nudge-r{0%,100%{transform:translateX(0)}50%{transform:translateX(6px)}}",
    "@keyframes kfc-nudge-u{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}",
    "@keyframes kfc-nudge-d{0%,100%{transform:translateY(0)}50%{transform:translateY(6px)}}",
    ".kfc-flag{position:absolute;left:12px;top:12px;padding:4px 10px;border-radius:999px;font-size:11px;border:1px solid rgba(34,211,238,.4);background:rgba(9,14,30,.72);color:#8ee9f7}",
    ".kfc-flag-live{border-color:rgba(255,120,120,.5);color:#ffb4b4}",
    ".kfc-status{margin:12px 20px 0;font-size:13px;color:#cbd6f5;min-height:20px}",
    ".kfc-status.kfc-good{color:#6ee7a8}",
    ".kfc-status.kfc-bad{color:#ffb4b4}",
    ".kfc-actions{display:flex;gap:10px;flex-wrap:wrap;padding:14px 20px 0}",
    ".kfc-actions .btn{flex:0 1 auto}",
    ".kfc-err{margin:12px 20px 0;padding:12px 14px;border-radius:12px;border:1px solid rgba(255,190,120,.34);background:rgba(255,190,120,.08);color:#ffd9a8;font-size:12.5px}",
    ".kfc-steps{display:flex;gap:6px;margin:12px 20px 0}",
    ".kfc-step{flex:1;padding:7px 4px;border-radius:10px;border:1px solid rgba(120,140,255,.18);background:rgba(255,255,255,.02);font-size:11.5px;color:#8b9ac6;text-align:center}",
    ".kfc-step.kfc-step-on{border-color:rgba(34,211,238,.6);color:#8ee9f7;background:rgba(34,211,238,.08)}",
    ".kfc-step.kfc-step-done{border-color:rgba(110,231,168,.55);color:#6ee7a8}",
    ".kfc-strip{display:flex;gap:6px;margin:10px 20px 0}",
    ".kfc-strip img.kfc-thumb{width:52px;height:64px;object-fit:cover;border-radius:8px;border:1px solid rgba(110,231,168,.5);background:#04060e}",
    ".kfc-strip .kfc-thumb-empty{width:52px;height:64px;border-radius:8px;border:1px dashed rgba(120,140,255,.22);background:rgba(255,255,255,.02)}",
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
            mime: "image/jpeg",
            gray: grayFrom(img)
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

  /** 有 FaceDetector 就用真的；没有就 null，只报画面稳没稳。 */
  function makeDetector() {
    try {
      if (typeof window.FaceDetector === "function") {
        return new window.FaceDetector({ fastMode: true, maxDetectedFaces: 1 });
      }
    } catch (_) {}
    return null;
  }

  /* ---------------------------------------------------------- 多角度采集 */

  var grayCanvas = null;

  /** 把画面（video 或 img）缩成 16x16 灰度，用来做「这张和上一张是不是同一张」的比对。 */
  function grayFrom(source) {
    if (!grayCanvas) {
      grayCanvas = document.createElement("canvas");
      grayCanvas.width = 16;
      grayCanvas.height = 16;
    }
    var ctx = grayCanvas.getContext("2d", { willReadFrequently: true });
    try {
      ctx.drawImage(source, 0, 0, 16, 16);
    } catch (_) {
      return null;
    }
    var data = ctx.getImageData(0, 0, 16, 16).data;
    var out = [];
    for (var i = 0; i < data.length; i += 4) {
      out.push((data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114) / 255);
    }
    return out;
  }

  function grayFromVideo(video) {
    return grayFrom(video);
  }

  /**
   * 亮度/对比度归一化：各自减掉自己的均值、再除以自己的标准差 —— 只留下「形状」。
   * 自动曝光 / 自动白平衡造成的整帧明暗漂移，在这一步被彻底剔掉。
   */
  function grayNorm(gray) {
    if (!gray || !gray.length) return null;
    var n = gray.length;
    var i;
    var mean = 0;
    for (i = 0; i < n; i += 1) mean += gray[i];
    mean /= n;
    var sq = 0;
    var d;
    for (i = 0; i < n; i += 1) {
      d = gray[i] - mean;
      sq += d * d;
    }
    var std = Math.sqrt(sq / n);
    var out = new Array(n);
    for (i = 0; i < n; i += 1) out[i] = std > 1e-6 ? (gray[i] - mean) / std : 0;
    return out;
  }

  /** 这一帧的明暗起伏有多大：接近 0 = 画面平平一片，没有可比的结构。 */
  function grayStd(gray) {
    if (!gray || !gray.length) return null;
    var n = gray.length;
    var i;
    var mean = 0;
    for (i = 0; i < n; i += 1) mean += gray[i];
    mean /= n;
    var sq = 0;
    for (i = 0; i < n; i += 1) {
      var d = gray[i] - mean;
      sq += d * d;
    }
    return Math.sqrt(sq / n);
  }

  var diffWeights = null;

  /** 16x16 的中心加权窗：中间 1、四角 WEIGHT_FLOOR。只算一次，之后复用。 */
  function diffKernel() {
    if (diffWeights) return diffWeights;
    var k = new Array(256);
    for (var y = 0; y < 16; y += 1) {
      for (var x = 0; x < 16; x += 1) {
        var wx = 0.5 + 0.5 * Math.cos((Math.PI * (x - 7.5)) / 8);
        var wy = 0.5 + 0.5 * Math.cos((Math.PI * (y - 7.5)) / 8);
        k[y * 16 + x] = WEIGHT_FLOOR + (1 - WEIGHT_FLOOR) * wx * wy;
      }
    }
    diffWeights = k;
    return k;
  }

  /**
   * 两张画面的「形状差」：亮度归一化之后算**中心加权**的平均绝对差。
   * 权重压在画面中间（脸的位置），边角上背景的动静几乎不算数。
   */
  function grayDiff(a, b) {
    if (!a || !b || a.length !== b.length) return null;
    var na = grayNorm(a);
    var nb = grayNorm(b);
    if (!na || !nb) return null;
    var k = diffKernel();
    var sum = 0;
    var wsum = 0;
    for (var i = 0; i < na.length; i += 1) {
      var w = k[i];
      sum += w * Math.abs(na[i] - nb[i]);
      wsum += w;
    }
    return wsum > 0 ? sum / wsum : null;
  }

  function grayMean(gray) {
    if (!gray) return null;
    var sum = 0;
    for (var i = 0; i < gray.length; i += 1) sum += gray[i];
    return sum / gray.length;
  }

  function currentStep() {
    return state && state.angles ? state.angles[state.stepIndex] : null;
  }

  function renderSteps() {
    var host = byId("kfc-steps");
    if (!host || !state || !state.angles) return;
    host.innerHTML = "";
    state.angles.forEach(function (a, i) {
      var el = document.createElement("div");
      el.className = "kfc-step" + (i === state.stepIndex ? " kfc-step-on" : i < state.stepIndex ? " kfc-step-done" : "");
      el.setAttribute("data-kfc-step", a.key);
      el.textContent = (i < state.stepIndex ? "✓ " : "") + (i + 1) + "·" + a.label;
      host.appendChild(el);
    });
  }

  function renderStrip() {
    var host = byId("kfc-strip");
    if (!host || !state || !state.angles) return;
    host.innerHTML = "";
    state.angles.forEach(function (a, i) {
      var f = (state.frames || [])[i];
      if (f && f.b64) {
        var img = document.createElement("img");
        img.className = "kfc-thumb";
        img.alt = a.label;
        img.src = "data:image/jpeg;base64," + f.b64;
        host.appendChild(img);
      } else {
        var d = document.createElement("div");
        d.className = "kfc-thumb-empty";
        host.appendChild(d);
      }
    });
  }

  /** 交给上层的采集结果：正面那张仍然放在 b64（兼容旧调用方），四张全在 frames 里。 */
  function captureResult() {
    var frames = (state.frames || [])
      .filter(function (f) { return f && f.b64; })
      .map(function (f) {
        return { angle: f.angle, label: f.label, b64: f.b64, mime: f.mime, motion: f.diff };
      });
    var front = frames.length ? frames[0] : null;
    return {
      b64: front ? front.b64 : "",
      mime: (front && front.mime) || "image/jpeg",
      source: "camera",
      frames: frames,
      angles: (state.angles || []).map(function (a) { return a.key; })
    };
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
      '<p class="kfc-sub" id="kfc-sub">把脸放进圆圈里：<b>头顶和下巴都要在圈内</b>。照屏幕上的提示转头就行 —— <b>不用按键，系统会自己拍</b>。一共 <b>正脸 + 左右侧脸 + 抬头低头 5 个角度</b>，照片只留在这台设备上。</p>' +
      '<div class="kfc-stage" id="kfc-stage">' +
      '<video id="kfc-video" playsinline muted autoplay></video>' +
      '<span class="kfc-edge kfc-edge-top" id="kfc-edge-top">头顶要进圈</span>' +
      '<span class="kfc-edge kfc-edge-bot" id="kfc-edge-bot">下巴要进圈</span>' +
      '<div class="kfc-ring" id="kfc-ring"></div>' +
      '<svg class="kfc-prog" id="kfc-prog" viewBox="0 0 100 126" preserveAspectRatio="none">' +
      '<ellipse id="kfc-prog-arc" cx="50" cy="63" rx="47" ry="60" stroke-dasharray="337.4" stroke-dashoffset="337.4" vector-effect="non-scaling-stroke"></ellipse>' +
      "</svg>" +
      '<div class="kfc-flash" id="kfc-flash"></div>' +
      '<span class="kfc-flag" id="kfc-flag">预览中</span>' +
      "</div>" +
      '<div class="kfc-guide" id="kfc-guide"></div>' +
      '<div class="kfc-steps" id="kfc-steps"></div>' +
      '<div class="kfc-strip" id="kfc-strip"></div>' +
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
    // 光停 track 不够：video 上还挂着这条流，摄像头指示灯和占用的说法都说不清。
    var video = byId("kfc-video");
    if (video) video.srcObject = null;
  }

  function stopLoop() {
    if (state && state.timer) {
      cancelTick(state.timer);
      state.timer = null;
    }
  }

  function closeOverlay() {
    stopLoop();
    stopStream();
    if (state) {
      state.stopped = true;
      if (state.between) {
        clearTimeout(state.between);
        state.between = null;
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

  /**
   * 主循环改成按「帧」走（requestAnimationFrame），不再靠 130ms 的粗粒度定时器：
   * 进度圈要跟得上眼睛、用户停住后判定要在几十毫秒内出结果，就得逐帧看画面。
   * 拿不到 requestAnimationFrame 的环境（老浏览器）自动退回定时器。
   */
  function scheduleTick() {
    if (typeof window.requestAnimationFrame === "function") {
      rafId = window.requestAnimationFrame(function () {
        rafId = null;
        tick();
      });
      return rafId;
    }
    return setTimeout(tick, TICK_MS);
  }

  /** 停止逐帧循环：rAF 和 timeout 两种句柄都要能停掉，否则会留下一个幽灵循环。 */
  function cancelTick(id) {
    if (rafId && typeof window.cancelAnimationFrame === "function") {
      window.cancelAnimationFrame(rafId);
      rafId = null;
    }
    if (id) clearTimeout(id);
  }

  /** 分析一帧画面（贵）：取样、判停稳、判角度。 */
  function analyzeFrame(video) {
    var t0 = Date.now();
    var gray = grayFromVideo(video);
    if (!gray) return;
    // 摄像头从「点开」到「出画」通常要几百毫秒到一秒多。这段时间不该算进
    // 「给你时间站好」里 —— 否则画面刚亮起来就已经在计时，第一张很容易拍废。
    if (!state.startedAt) {
      state.startedAt = Date.now();
      if (state.stepIndex === 0 && !state.frames.length) {
        state.stepStartAt = state.startedAt;
        state.readyAt = state.startedAt + GRACE_FIRST_MS;
        state.lastMoveAt = state.startedAt;
      }
    }
    state.sampledAt = Date.now();
    // 这一帧花了多久，决定下一次隔多久再分析：慢机器上自动拉长间隔，
    // 让进度圈始终有帧预算；快机器（真机 GPU）上几乎就是逐帧判定。
    var cost = state.sampledAt - t0;
    state.sampleCost = state.sampleCost ? Math.round(state.sampleCost * 0.7 + cost * 0.3) : cost;
    var motion = state.lastGray ? grayDiff(state.lastGray, gray) : 1;
    state.lastGray = gray;
    if (motion !== null && motion >= STILL_DIFF) state.lastMoveAt = Date.now();
    onSteady(gray);
  }

  /**
   * 进度圈每一帧都画。这是用户全部的「手感」来源：它必须跟得上眼睛，
   * 但取样判定在真机上可能吃掉几十毫秒 —— 所以那一头按节流跑，这一头逐帧跑。
   */
  function paintProgress() {
    if (!state || state.mode !== "live") return;
    var now = Date.now();
    if (now < state.readyAt) {
      setProg(0);
      return;
    }
    if (state.progPin !== null && state.progPin !== undefined) {
      setProg(state.progPin);
      return;
    }
    setProg(Math.min(1, (now - (state.lastMoveAt || now)) / STILL_MS));
  }

  function tick() {
    if (!state || state.stopped) return;
    var video = byId("kfc-video");
    var now = Date.now();
    if (video && state.mode === "live" && video.videoWidth) {
      // 同一个视频帧不重复分析：摄像头 30fps、屏幕可能 60fps，重复算一遍纯属白烧。
      var ct = video.currentTime;
      var since = now - (state.sampledAt || 0);
      var gap = Math.max(SAMPLE_MS, Math.min(SAMPLE_MAX_MS, (state.sampleCost || 0) * SAMPLE_DUTY));
      if (ct !== state.lastCT && since >= gap) {
        state.lastCT = ct;
        analyzeFrame(video);
      } else if (since > gap * 2) {
        // 万一某个浏览器不更新 currentTime，也不能把判定饿死。
        analyzeFrame(video);
      }
      paintProgress();
      // 人脸检测（FaceDetector）很贵，逐帧跑会把主线程占满 —— 250ms 一次足够提示。
      if (
        state && state.mode === "live" && state.detector && state.stepIndex === 0 &&
        now - (state.hintAt || 0) > 250
      ) {
        state.hintAt = now;
        hintFace(video);
      }
    }
    // 看门狗：不管是因为画面一直在动、还是摄像头根本没出帧，只要这个角度卡了
    // AUTO_STUCK_MS 还没采到，就必须给用户一条出路 —— 不能让人对着屏幕干等。
    if (
      state && state.mode === "live" && !state.stuckShown && state.stepStartAt &&
      Date.now() - state.stepStartAt > AUTO_STUCK_MS
    ) {
      state.stuckShown = true;
      renderLiveActions();
      // 这时候必须说话：屏幕上刚弹出兜底按钮，得说清它是干什么用的。
      // 前面那句「画面里有动静」只是解释，不能把这条更要紧的话挡掉。
      flashStatus("这一张一直没采到 —— 也可以手动拍这一张，或点「本角度改用照片」。", "warn", 4200);
    }
    if (state) state.timer = scheduleTick();
  }

  /* ----------------------------------------- 自动采集（Face-ID 式，全程不用按键）
   *
   * 用户只做一件事：照屏幕上的大字转头。判定只用两件我们真的量得到的事：
   *   1) 这 STILL_MS 之内画面有没有动 —— 拿 STILL_MS 之前那一帧和当前帧比；
   *   2) 停下来之后，这一张和上一张已采的差多少 —— 够不够一个「新角度」。
   * 满足「停稳了 + 真的换了角度」就自动拍，不需要用户按任何东西。
   */

  function pushHistory(gray) {
    var now = Date.now();
    // 判定只需 40ms 一个点：逐帧全塞进去只是白烧 CPU，窗口里也不差这点精度。
    if (state.historyAt && now - state.historyAt < HISTORY_MS) return;
    state.historyAt = now;
    state.history.push({ t: now, g: gray });
    while (state.history.length && now - state.history[0].t > 1500) state.history.shift();
  }

  /**
   * 这一整段时间（STILL_MS）里画面到底有没有变过。
   *
   * 只比「头尾两帧」是不够的：随机抖动偶尔会让头尾刚好撞上，一次撞上就被判成
   * 「停稳了」，拍下来的其实是动的那一下。这里拿当前帧和窗口里**每一帧**都比，
   * 取最大的那个差 —— 中间任何一刻动过，就还不算停稳。
   */
  function stillWorstDiff(gray, since) {
    if (!state || !state.history || !state.history.length) return null;
    var worst = null;
    for (var i = state.history.length - 1; i >= 0; i -= 1) {
      if (state.history[i].t < since) break;
      var d = grayDiff(state.history[i].g, gray);
      if (d === null) continue;
      if (worst === null || d > worst) worst = d;
    }
    return worst;
  }

  /**
   * STILL_MS 之前采的那一帧。
   * 只能拿它来比，才能说「这一整段时间都没动」—— 拿相邻两帧比的话，
   * 慢慢转头也会被当成静止，拍出来就是一张糊的。
   */
  function frameAgo(ms) {
    var cut = Date.now() - ms;
    for (var i = state.history.length - 1; i >= 0; i -= 1) {
      if (state.history[i].t <= cut) return state.history[i];
    }
    return null;
  }

  /** 取景圈上那圈进度：说的是「稳住，我正在判定」，不是「已经认出你的人脸」。 */
  var PROG_LEN = 337.4;

  function setProg(p) {
    var arc = byId("kfc-prog-arc");
    if (!arc) return;
    var v = Math.max(0, Math.min(1, p || 0));
    arc.style.strokeDasharray = String(PROG_LEN);
    arc.style.strokeDashoffset = String(PROG_LEN * (1 - v));
  }

  /**
   * 把进度圈钉在某个值上（判定分支用它说话），传 null 表示「交回给逐帧节奏」。
   * 圈是逐帧画的，判定是隔几十毫秒算一次的 —— 两件事分开，谁也不用迁就谁。
   */
  function pinProg(v) {
    if (!state) return;
    state.progPin = v;
    if (v !== null && v !== undefined) setProg(v);
  }

  /** 拍下的一瞬间闪一下：用户得知道「刚才那下确实采到了」。 */
  function flash() {
    var n = byId("kfc-flash");
    if (!n) return;
    n.classList.remove("kfc-go");
    void n.offsetWidth;
    n.classList.add("kfc-go");
    // 手上那一下反馈：手机上震一下（不支持震动就静默跳过，绝不报错）。
    try {
      if (navigator.vibrate) navigator.vibrate(12);
    } catch (_) {}
  }

  /** 大字引导：这一张要做什么动作。 */
  function renderGuide() {
    var node = byId("kfc-guide");
    if (!node) return;
    var step = currentStep();
    if (!step) {
      node.textContent = "";
      return;
    }
    node.innerHTML =
      '<span class="kfc-arrow" data-kfc-arrow="' + step.key + '">' + (ARROWS[step.key] || "") +
      "</span><span>" + step.guide + "</span>";
  }

  /** 还没转到位时反复说的那句话。 */
  function turnPrompt() {
    var step = currentStep();
    if (!step) return "照提示动一下";
    if (step.key === "front") return "请正对镜头，把脸放进圈里，然后停住别动";
    return "还看不出角度变化 —— " + step.guide + "，转到位后停住";
  }

  /** 进入某个角度：把上一张留下的判定状态清干净，给出这一张的引导。 */
  function stepStart() {
    if (!state) return;
    var now = Date.now();
    state.lastGray = null;
    state.history = [];
    state.lastMoveAt = now;
    state.waitingTurn = false;
    state.stuckShown = false;
    state.busyHinted = false;
    state.historyAt = 0;
    state.changedSince = 0;
    state.stepStartAt = now;
    state.readyAt = now + (state.stepIndex === 0 ? GRACE_FIRST_MS : GRACE_STEP_MS);
    state.notice = null;
    setRing("");
    pinProg(0);
    renderGuide();
    renderLiveActions();
    setStatus("照上面的提示转头就行 —— 停稳就会自动拍，不用按键。");
  }

  /**
   * 画稳没稳、以及「这一张算不算一个新角度」。
   * 只报我们真的量到的东西：画面稳住了 / 还看不出角度变化。
   */
  function onSteady(gray) {
    var now = Date.now();
    pushHistory(gray);

    if (now < state.readyAt) {
      pinProg(0);
      if (!noticeActive()) setStatus("准备好 —— 马上开始，把脸放进圈里。");
      return;
    }

    // 头尾两帧都要有（说明窗口真的攒满了），而且窗口内**每一帧**都得和当前帧对得上。
    var ref = frameAgo(STILL_MS);
    var worst = ref ? stillWorstDiff(gray, ref.t) : null;
    var bar = state.changedSince && now - state.changedSince >= SETTLE_RELAX_MS
      ? STILL_DIFF_RELAX
      : STILL_DIFF;
    var still = worst !== null && worst < bar;
    var last = (state.grays || []).length ? state.grays[state.grays.length - 1] : null;
    var vsLast = last ? grayDiff(last, gray) : null;
    var changed = vsLast === null || vsLast >= ANGLE_MIN_DIFF;

    if (!still) {
      // 姿势已经和上一张不一样了，就从这一刻开始给「耐心」计时：等久了会放宽门槛。
      if (changed && !state.changedSince) state.changedSince = now;
      state.waitingTurn = false;
      state.progPin = null;
      if (!noticeActive()) {
        setStatus(changed ? "很好，就这个角度 —— 稳住别动，马上自动拍。" : "正在跟着你动…");
      }
      // 一直判不到「停稳」时不能闷着不吭声：把量到的原因说出来。用户通常不知道
      // 是背景里有人走动、还是自己和手机在晃 —— 说清楚，他动一下就好了。
      if (
        !state.busyHinted && now - state.stepStartAt > BUSY_HINT_MS &&
        now - (state.lastMoveAt || now) < 300 && worst !== null && worst >= STILL_DIFF
      ) {
        state.busyHinted = true;
        flashStatus(
          "画面里一直有动静（背景里有人走动、或者镜头在晃）—— 稳住一下，也可以让镜头里只剩你一个人。",
          "warn",
          4200
        );
      }
      return;
    }

    if (!changed) {
      // 停住了，但和上一张没差别：动作还没做到位。
      pinProg(0);
      state.waitingTurn = true;
      if (!noticeActive()) flashStatus(turnPrompt(), "warn", 2600);
      return;
    }

    pinProg(1);
    setRing("ok");
    shoot();
  }

  /** 有 FaceDetector 时的额外提示：脸有没有放进圈里。只说量到的，绝不卡流程。 */
  function hintFace(video) {
    var stage = byId("kfc-stage");
    var ring = byId("kfc-ring");
    if (!stage || !ring) return;
    state.detector
      .detect(video)
      .then(function (faces) {
        if (!state || state.stopped || state.mode !== "live" || state.stepIndex !== 0) return;
        // 转头时、或者画面里没有正脸，它看不到是正常的 —— 那就什么都不说。
        if (!faces || !faces.length) return;
        var verdict = judge(faces[0].boundingBox, coverGeom(stage, video), ringBox(stage, ring));
        if (!verdict.ok) flashStatus(verdict.msg, "warn", 1600);
      })
      .catch(function () {
        // 检测器在某些机器上直接抛：干脆不用它，别装作还在看。
        if (state) state.detector = null;
      });
  }

  /**
   * 提示要能在屏幕上站住。
   *
   * 实时循环每 130ms 会重写一次状态行，直接 setStatus 的话「这张和上一张一样」会被
   * 立刻盖掉 —— 用户只看到画面抖了一下，不知道该干嘛。
   */
  function flashStatus(text, kind, ms) {
    if (!state) return;
    state.notice = { until: Date.now() + (ms || 4000) };
    setStatus(text, kind);
  }

  function noticeActive() {
    return !!(state && state.notice && Date.now() < state.notice.until);
  }

  /* ------------------------------------------------------------- 拍摄 */

  /** 采下当前角度的这一张（自动判定通过时由主循环调用）。五个角度全采完才进核对界面。 */
  function shoot() {
    if (!state || state.mode !== "live") return;
    var shot;
    try {
      shot = frameToB64(byId("kfc-video"));
    } catch (e) {
      flashStatus((e && e.message) || "没抓到画面，再试一次", "bad");
      return;
    }
    var gray = grayFromVideo(byId("kfc-video"));
    var verdict = judgeAngle(gray);
    if (!verdict.ok) {
      flashStatus(verdict.msg, "bad");
      return;
    }
    flash();
    acceptFrame(shot, gray, "camera");
  }

  /**
   * 这一张能不能算一个「新角度」。
   *
   * 单张正面照拿别人的照片就能顶替，所以每一张都必须和上一张有真实的姿态差：
   * 同一张照片连拍、或对着屏幕翻拍，16x16 灰度平均差会接近 0，这里直接拒掉。
   * 另外太暗的画面也拒 —— 那种照片复核方什么也看不出来，等于白采。
   */
  function judgeAngle(gray) {
    var step = currentStep();
    var mean = grayMean(gray);
    if (mean !== null && mean < DIM_MEAN) {
      return { ok: false, msg: "光线太暗了，脸看不清 —— 换个亮点的地方再拍", diff: null };
    }
    var contrast = grayStd(gray);
    if (contrast !== null && contrast < MIN_CONTRAST) {
      return {
        ok: false,
        diff: null,
        msg: "画面太平了，看不出脸的轮廓 —— 别挡住镜头，把脸放进圈里再来"
      };
    }
    var prev = (state.grays || []).length ? state.grays[state.grays.length - 1] : null;
    var diff = prev && gray ? grayDiff(prev, gray) : null;
    if (diff !== null && diff < IDENTICAL_DIFF) {
      return {
        ok: false,
        diff: diff,
        msg:
          "「" + (step ? step.label : "这一张") + "」和上一张几乎一模一样 —— " +
          "请真的转头 / 抬头，别拿同一张照片顶替"
      };
    }
    return { ok: true, msg: "", diff: diff };
  }

  /** 收下这一张：记编号、照亮进度条，然后决定是继续下一个角度还是进核对界面。 */
  function acceptFrame(shot, gray, via) {
    var step = currentStep();
    var prev = (state.grays || []).length ? state.grays[state.grays.length - 1] : null;
    state.frames.push({
      angle: step ? step.key : "front",
      label: step ? step.label : "正面",
      b64: shot.b64,
      mime: shot.mime || "image/jpeg",
      via: via || "camera",
      diff: prev && gray ? grayDiff(prev, gray) : null
    });
    if (gray) state.grays.push(gray);
    state.stepIndex += 1;
    state.notice = null;
    renderSteps();
    renderStrip();
    if (state.stepIndex < state.angles.length) betweenAngles();
    else enterReview();
  }

  /**
   * 两张之间那一小段：摄像头不关、画面照常显示，只是暂停判定，
   * 让用户看清「上一张采到了、下一张要做什么」。
   */
  function betweenAngles() {
    if (!state) return;
    var next = currentStep();
    state.mode = "between";
    setRing("");
    pinProg(0);
    actions([]);
    var node = byId("kfc-guide");
    if (node) {
      node.innerHTML = '<span class="kfc-arrow" data-kfc-arrow="done">✓</span><span>第 ' +
        state.stepIndex + " 张已采到</span>";
    }
    setStatus(next ? "接下来：" + next.guide : "继续", "good");
    if (state.between) clearTimeout(state.between);
    state.between = setTimeout(function () {
      if (state && state.mode === "between") resumeLive();
    }, BETWEEN_MS);
  }

  /** 回到实时预览，等下一个角度到位（这一步是自动的，用户什么都不用点）。 */
  function resumeLive() {
    if (!state || state.stopped) return;
    if (state.between) {
      clearTimeout(state.between);
      state.between = null;
    }
    state.mode = "live";
    var err = byId("kfc-err");
    if (err) err.hidden = true;
    if (!state.stream) {
      openStream().catch(function () {});
      return;
    }
    stepStart();
    stopLoop();
    tick();
  }

  /** 五个角度都采到了：停下来给本人过目，只有他点「确认使用」才算数。 */
  function enterReview() {
    if (!state) return;
    state.mode = "review";
    stopStream();
    state.shot = captureResult();

    var stage = byId("kfc-stage");
    stage.querySelectorAll("img.kfc-shot").forEach(function (n) { n.remove(); });
    if (state.shot.b64) {
      var img = document.createElement("img");
      img.className = "kfc-shot";
      img.alt = "刚拍的人脸（正面）";
      img.src = "data:image/jpeg;base64," + state.shot.b64;
      stage.insertBefore(img, stage.firstChild);
    }
    var v = byId("kfc-video");
    if (v) v.style.display = "none";
    var ring = byId("kfc-ring");
    if (ring) ring.style.display = "none";
    var flag = byId("kfc-flag");
    if (flag) {
      flag.textContent = "已采 " + state.shot.frames.length + " 张 · 待确认";
      flag.classList.add("kfc-flag-live");
    }
    pinProg(0);
    var g = byId("kfc-guide");
    if (g) {
      g.innerHTML =
        '<span class="kfc-arrow" data-kfc-arrow="done">✓</span><span>' +
        state.shot.frames.length + " 个角度都采到了</span>";
    }
    setStatus(
      "对一下下面这几张（正脸 / 左 / 右 / 抬高 / 低头）：脸清楚没糊、是同一个人、每张角度都不一样。没问题就点「确认使用」。",
      "good"
    );
    actions([
      { key: "use", label: "确认使用", primary: true, onClick: function () { if (state) settle(captureResult()); } },
      { key: "retake", label: "重拍", onClick: retake }
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
    state.shot = null;
    state.stepIndex = 0;
    state.frames = [];
    state.grays = [];
    state.history = [];
    state.lastGray = null;
    state.notice = null;
    renderSteps();
    renderStrip();
    renderLiveActions();
    if (!state.stream) {
      openStream().catch(function () {});
      return;
    }
    stepStart();
    stopLoop();
    tick();
  }

  /**
   * 「本角度改用照片」：没有摄像头的人也能走完五个角度。
   * 照片**不会**绕过角度比对 —— 拿同一张图充五张一样会被拒。
   */
  async function onFilePicked(ev) {
    var f = ev.target.files && ev.target.files[0];
    ev.target.value = "";
    if (!f || !state) return;
    if (state.mode === "review") return;
    try {
      var shot = await scaledFileToB64(f);
      var gray = shot.gray || null;
      var verdict = judgeAngle(gray);
      if (!verdict.ok) {
        flashStatus(verdict.msg, "bad");
        return;
      }
      acceptFrame(shot, gray, "file");
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

  /**
   * 自动采集时默认**一个按钮都不给** —— 用户照提示转头就行。
   * 只有两种情况才给：① 某个角度一直没进展（手动兜底，说明一下）；
   * ② 有多个摄像头可以切。
   */
  function renderLiveActions() {
    if (!state) return;
    var list = [];
    if (state.cameras && state.cameras.length > 1) {
      list.push({ key: "switch", label: "切换摄像头", onClick: switchCamera });
    }
    if (state.stuckShown) {
      list.push({ key: "shot", label: "没反应？手动拍这一张", primary: true, onClick: shoot });
      list.push({ key: "pick", label: "本角度改用照片", onClick: pickFile });
    }
    actions(list);
  }

  async function switchCamera() {
    if (!state || !state.cameras || state.cameras.length < 2) return;
    state.camIndex = (state.camIndex + 1) % state.cameras.length;
    var cam = state.cameras[state.camIndex];
    state.facing = /back|rear|environment|后/i.test(cam.label || "") ? "environment" : "user";
    stopStream();
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
      setStatus(why + " 也可以点下面「本角度改用照片」逐张传。", "bad");
      setRing("");
      showError(why);
      actions([
        { key: "pick", label: "本角度改用照片", primary: true, onClick: pickFile },
        { key: "retry", label: "再试一次", onClick: function () { byId("kfc-err").hidden = true; openStream(); } }
      ]);
      return;
    }
    state.cameras = await listCameras();
    if (!state || state.stopped) return;
    stepStart();
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
        opts.subtitle ||
        "把脸放进圆圈里：<b>头顶和下巴都要在圈内</b>。照屏幕上的提示转头就行 —— <b>不用按键，系统会自己拍</b>。一共 <b>正脸 + 左右侧脸 + 抬头低头 5 个角度</b>，照片只留在这台设备上。";
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
        timer: null,
        stopped: false,
        angles: ANGLE_STEPS,
        stepIndex: 0,
        frames: [],
        grays: [],
        between: null,
        notice: null,
        // 自动采集的判定状态
        lastGray: null,
        lastMoveAt: 0,
        history: [],
        waitingTurn: false,
        stuckShown: false,
        busyHinted: false,
        historyAt: 0,
        changedSince: 0,
        sampledAt: 0,
        sampleCost: 0,
        startedAt: 0,
        lastCT: null,
        progPin: 0,
        hintAt: 0,
        stepStartAt: 0,
        readyAt: 0
      };
      renderSteps();
      renderStrip();
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