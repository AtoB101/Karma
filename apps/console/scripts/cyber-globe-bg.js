/* Karma Console — neural globe background
 * 旋转地球 + 大陆板块点簇 + 板块间荧光神经网络连线
 * 复用 #particles 全屏 canvas，官方青紫粉色系
 */
(function () {
  var canvas = document.getElementById('particles');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');
  var W, H, cx, cy, R;

  function resize() {
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
    // 左侧 sidebar 280px，地球放在内容区视觉中心
    cx = W > 700 ? (W + 280) / 2 : W / 2;
    cy = H / 2;
    R = Math.min(W - 280, H) * 0.34;
    if (R < 120) R = 120;
  }
  window.addEventListener('resize', resize);
  resize();

  var COLORS = ['34,211,238', '139,92,246', '232,121,249'];

  // 粗略大陆板块中心（纬度/经度，度）
  var continents = [
    { lat: 42, lon: -100 },  // 北美
    { lat: -15, lon: -60 },  // 南美
    { lat: 52, lon: 15 },    // 欧洲
    { lat: 5, lon: 20 },     // 非洲
    { lat: 38, lon: 95 },    // 亚洲
    { lat: -25, lon: 135 },  // 澳洲
    { lat: 30, lon: -10 }    // 大西洋岛弧点缀
  ];

  // 板块点簇 + 海洋散点
  var pts = [];
  continents.forEach(function (c, ci) {
    var n = 22 + ci * 2;
    for (var i = 0; i < n; i++) {
      var lat = c.lat + (Math.random() - 0.5) * 26;
      var lon = c.lon + (Math.random() - 0.5) * 32;
      pts.push({ lat: lat, lon: lon, c: COLORS[ci % COLORS.length] });
    }
  });
  for (var i = 0; i < 55; i++) {
    pts.push({ lat: (Math.random() - 0.5) * 140, lon: Math.random() * 360 - 180, c: COLORS[i % COLORS.length] });
  }

  // 经纬度 -> 单位球向量
  function ll2v(latDeg, lonDeg) {
    var lat = latDeg * Math.PI / 180, lon = lonDeg * Math.PI / 180;
    return {
      x: Math.cos(lat) * Math.cos(lon),
      y: Math.sin(lat),
      z: Math.cos(lat) * Math.sin(lon)
    };
  }
  var vecs = pts.map(function (p) { return ll2v(p.lat, p.lon); });

  // 预计算荧光连线（球面 cos 距离阈值）
  var links = [];
  var threshold = 0.62;
  for (var i = 0; i < vecs.length; i++) {
    for (var j = i + 1; j < vecs.length; j++) {
      var dot = vecs[i].x * vecs[j].x + vecs[i].y * vecs[j].y + vecs[i].z * vecs[j].z;
      if (dot > threshold) links.push([i, j]);
    }
  }

  var angle = 0;
  function rotY(v, a) {
    var x = v.x * Math.cos(a) + v.z * Math.sin(a);
    var z = -v.x * Math.sin(a) + v.z * Math.cos(a);
    return { x: x, y: v.y, z: z };
  }

  function tick() {
    ctx.clearRect(0, 0, W, H);
    angle += 0.004;

    // 投影所有点（绕 Y 轴自转）
    var proj = [];
    for (var k = 0; k < vecs.length; k++) {
      var r = rotY(vecs[k], angle);
      proj.push({
        x: cx + r.x * R,
        y: cy - r.y * R,
        z: r.z,
        depth: (r.z + 1) / 2,
        c: pts[k].c
      });
    }

    // 荧光连线
    for (var i = 0; i < links.length; i++) {
      var a = proj[links[i][0]], b = proj[links[i][1]];
      if (a.z < -0.25 && b.z < -0.25) continue;
      var alpha = 0.08 + Math.min(a.depth, b.depth) * 0.32;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.strokeStyle = 'rgba(34,211,238,' + alpha.toFixed(3) + ')';
      ctx.lineWidth = 0.6;
      ctx.stroke();
    }

    // 板块节点
    for (var m = 0; m < proj.length; m++) {
      var p = proj[m];
      if (p.z < -0.12) continue;
      var r = 1.0 + p.depth * 2.0;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(' + p.c + ',' + (0.25 + p.depth * 0.65).toFixed(3) + ')';
      ctx.fill();
      // 近点加光晕
      if (p.depth > 0.7) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, r * 2.6, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(' + p.c + ',0.10)';
        ctx.fill();
      }
    }

    // 球体轮廓
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(34,211,238,0.16)';
    ctx.lineWidth = 1.2;
    ctx.stroke();

    // 外圈光晕
    var g = ctx.createRadialGradient(cx, cy, R * 0.7, cx, cy, R * 1.5);
    g.addColorStop(0, 'rgba(139,92,246,0.10)');
    g.addColorStop(0.6, 'rgba(34,211,238,0.05)');
    g.addColorStop(1, 'rgba(232,121,249,0)');
    ctx.beginPath();
    ctx.arc(cx, cy, R * 1.5, 0, Math.PI * 2);
    ctx.fillStyle = g;
    ctx.fill();

    // 经纬线（增强地球感）
    ctx.beginPath();
    ctx.ellipse(cx, cy, R, R * 0.3, 0, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(139,92,246,0.10)';
    ctx.lineWidth = 0.7;
    ctx.stroke();
    ctx.beginPath();
    ctx.ellipse(cx, cy, R * 0.3, R, 0, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(139,92,246,0.10)';
    ctx.stroke();

    requestAnimationFrame(tick);
  }
  tick();
})();
