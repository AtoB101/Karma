/* Karma Console — self-contained WebGL Earth globe with golden light and flight arcs.
 *
 * No external libraries. The globe is a textured UV sphere rendered behind the
 * console shell and centred on the full viewport. Golden great-circle flight
 * routes and endpoint nodes are drawn as an additive overlay that rotates with
 * the globe. If WebGL or the texture is unavailable it falls back to a CSS
 * sphere in the same position.
 */
(function () {
  "use strict";

  var container = document.getElementById("bgGlobe");
  if (!container) return;

  var canvas = document.createElement("canvas");
  canvas.setAttribute("aria-hidden", "true");
  container.appendChild(canvas);

  var gl =
    canvas.getContext("webgl", {
      alpha: true,
      antialias: true,
      premultipliedAlpha: false,
    }) || canvas.getContext("experimental-webgl", { alpha: true, antialias: true });

  if (!gl) {
    container.classList.add("fallback");
    return;
  }

  gl.disable(gl.DEPTH_TEST);
  gl.disable(gl.CULL_FACE);

  var VERT_SRC = [
    "attribute vec3 aPosition;",
    "attribute vec2 aUv;",
    "varying vec2 vUv;",
    "varying vec3 vNormal;",
    "varying vec3 vViewDir;",
    "uniform float uTime;",
    "void main() {",
    "  float a = uTime * 0.045;",
    "  float ca = cos(a);",
    "  float sa = sin(a);",
    "  vec3 pos = vec3(",
    "    aPosition.x * ca - aPosition.z * sa,",
    "    aPosition.y,",
    "    aPosition.x * sa + aPosition.z * ca",
    "  );",
    "  vec3 normal = vec3(",
    "    aPosition.x * ca - aPosition.z * sa,",
    "    aPosition.y,",
    "    aPosition.x * sa + aPosition.z * ca",
    "  );",
    "  vUv = aUv;",
    "  vNormal = normal;",
    "  vViewDir = vec3(0.0, 0.0, 1.0) - pos;",
    "  gl_Position = vec4(pos * 0.82, 1.0);",
    "}",
  ].join("\n");

  var FRAG_SRC = [
    "precision highp float;",
    "varying vec2 vUv;",
    "varying vec3 vNormal;",
    "varying vec3 vViewDir;",
    "uniform sampler2D uTexture;",
    "void main() {",
    "  vec3 n = normalize(vNormal);",
    "  vec3 view = normalize(vViewDir);",
    "  vec3 lightDir = normalize(vec3(-0.42, 0.55, 0.72));",
    "  vec3 gold = vec3(1.0, 0.84, 0.48);",
    "  float diff = max(dot(n, lightDir), 0.0);",
    "  float fresnel = pow(1.0 - max(dot(n, view), 0.0), 3.0);",
    "  vec3 tex = texture2D(uTexture, vUv).rgb;",
    "  vec3 color = tex * (0.26 + 0.80 * diff);",
    "  color += gold * (0.30 * fresnel + 0.14 * diff * diff);",
    "  gl_FragColor = vec4(color, 0.92);",
    "}",
  ].join("\n");

  var ROUTE_VERT_SRC = [
    "attribute vec3 aPosition;",
    "attribute float aT;",
    "uniform float uTime;",
    "varying float vT;",
    "varying float vFade;",
    "void main() {",
    "  float a = uTime * 0.045;",
    "  float ca = cos(a);",
    "  float sa = sin(a);",
    "  vec3 pos = vec3(",
    "    aPosition.x * ca - aPosition.z * sa,",
    "    aPosition.y,",
    "    aPosition.x * sa + aPosition.z * ca",
    "  );",
    "  vT = aT;",
    "  vFade = 0.55 + 0.45 * clamp((pos.z + 1.0) * 0.5, 0.0, 1.0);",
    "  gl_Position = vec4(pos * 0.82, 1.0);",
    "}",
  ].join("\n");

  var ROUTE_FRAG_SRC = [
    "precision highp float;",
    "varying float vT;",
    "varying float vFade;",
    "uniform float uTime;",
    "uniform vec3 uColor;",
    "void main() {",
    "  float flow = fract(vT - uTime * 0.085);",
    "  float rise = smoothstep(0.0, 0.10, flow);",
    "  float fall = 1.0 - smoothstep(0.16, 0.30, flow);",
    "  float pulse = rise * fall;",
    "  float alpha = vFade * (0.28 + 0.72 * pulse);",
    "  gl_FragColor = vec4(uColor, alpha);",
    "}",
  ].join("\n");

  var POINT_VERT_SRC = [
    "attribute vec3 aPosition;",
    "uniform float uTime;",
    "uniform float uPointSize;",
    "varying float vFade;",
    "void main() {",
    "  float a = uTime * 0.045;",
    "  float ca = cos(a);",
    "  float sa = sin(a);",
    "  vec3 pos = vec3(",
    "    aPosition.x * ca - aPosition.z * sa,",
    "    aPosition.y,",
    "    aPosition.x * sa + aPosition.z * ca",
    "  );",
    "  vFade = 0.72 + 0.28 * clamp((pos.z + 1.0) * 0.5, 0.0, 1.0);",
    "  gl_Position = vec4(pos * 0.82, 1.0);",
    "  float pulse = 1.0 + 0.18 * sin(uTime * 2.6 + aPosition.x * 6.0 + aPosition.y * 4.0);",
    "  gl_PointSize = uPointSize * pulse;",
    "}",
  ].join("\n");

  var POINT_FRAG_SRC = [
    "precision highp float;",
    "varying float vFade;",
    "uniform vec3 uColor;",
    "void main() {",
    "  vec2 p = gl_PointCoord * 2.0 - 1.0;",
    "  float d = length(p);",
    "  if (d > 1.0) discard;",
    "  float glow = exp(-d * d * 4.0);",
    "  float core = smoothstep(1.0, 0.0, d);",
    "  gl_FragColor = vec4(uColor, vFade * (core * 0.85 + glow * 0.75));",
    "}",
  ].join("\n");

  function compile(type, source) {
    var shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      throw new Error(gl.getShaderInfoLog(shader) || "shader compile failed");
    }
    return shader;
  }

  function link(vertSrc, fragSrc) {
    var program = gl.createProgram();
    gl.attachShader(program, compile(gl.VERTEX_SHADER, vertSrc));
    gl.attachShader(program, compile(gl.FRAGMENT_SHADER, fragSrc));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(program) || "program link failed");
    }
    return program;
  }

  var program = link(VERT_SRC, FRAG_SRC);
  var posLoc = gl.getAttribLocation(program, "aPosition");
  var uvLoc = gl.getAttribLocation(program, "aUv");
  var timeLoc = gl.getUniformLocation(program, "uTime");
  var texLoc = gl.getUniformLocation(program, "uTexture");

  var routeProgram = link(ROUTE_VERT_SRC, ROUTE_FRAG_SRC);
  var routePosLoc = gl.getAttribLocation(routeProgram, "aPosition");
  var routeTLoc = gl.getAttribLocation(routeProgram, "aT");
  var routeTimeLoc = gl.getUniformLocation(routeProgram, "uTime");
  var routeColorLoc = gl.getUniformLocation(routeProgram, "uColor");

  var pointProgram = link(POINT_VERT_SRC, POINT_FRAG_SRC);
  var pointPosLoc = gl.getAttribLocation(pointProgram, "aPosition");
  var pointTimeLoc = gl.getUniformLocation(pointProgram, "uTime");
  var pointSizeLoc = gl.getUniformLocation(pointProgram, "uPointSize");
  var pointColorLoc = gl.getUniformLocation(pointProgram, "uColor");

  function buildSphere(latBands, lonBands) {
    var positions = [];
    var uvs = [];
    var indices = [];
    for (var lat = 0; lat <= latBands; lat += 1) {
      var theta = (lat * Math.PI) / latBands;
      var sinTheta = Math.sin(theta);
      var cosTheta = Math.cos(theta);
      for (var lon = 0; lon <= lonBands; lon += 1) {
        var phi = (lon * 2 * Math.PI) / lonBands;
        var sinPhi = Math.sin(phi);
        var cosPhi = Math.cos(phi);
        positions.push(cosPhi * sinTheta, cosTheta, sinPhi * sinTheta);
        uvs.push(lon / lonBands, 1 - lat / latBands);
      }
    }
    for (var lat2 = 0; lat2 < latBands; lat2 += 1) {
      for (var lon2 = 0; lon2 < lonBands; lon2 += 1) {
        var first = lat2 * (lonBands + 1) + lon2;
        var second = first + lonBands + 1;
        indices.push(first, second, first + 1, second, second + 1, first + 1);
      }
    }
    return { positions: positions, uvs: uvs, indices: indices };
  }

  function makeBuffer(data) {
    var buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(data), gl.STATIC_DRAW);
    return buffer;
  }

  function bindAttrib(location, buffer, size) {
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.enableVertexAttribArray(location);
    gl.vertexAttribPointer(location, size, gl.FLOAT, false, 0, 0);
  }

  function disableAttribs() {
    for (var i = 0; i < 4; i += 1) gl.disableVertexAttribArray(i);
  }

  var sphere = buildSphere(72, 96);
  var spherePosBuffer = makeBuffer(sphere.positions);
  var sphereUvBuffer = makeBuffer(sphere.uvs);
  var indexBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(sphere.indices), gl.STATIC_DRAW);

  function clampDot(value) {
    return Math.max(-1, Math.min(1, value));
  }

  function latLonToVec3(lat, lon) {
    var la = (lat * Math.PI) / 180;
    var lo = (lon * Math.PI) / 180;
    var cl = Math.cos(la);
    return [cl * Math.cos(lo), Math.sin(la), cl * Math.sin(lo)];
  }

  function slerp(a, b, t) {
    var dot = clampDot(a[0] * b[0] + a[1] * b[1] + a[2] * b[2]);
    var theta = Math.acos(dot);
    if (theta < 0.0001) {
      return [
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
      ];
    }
    var st = Math.sin(theta);
    var w0 = Math.sin((1 - t) * theta) / st;
    var w1 = Math.sin(t * theta) / st;
    return [a[0] * w0 + b[0] * w1, a[1] * w0 + b[1] * w1, a[2] * w0 + b[2] * w1];
  }

  var ROUTES = [
    { from: [40.7, -74.0], to: [51.5, -0.1] },
    { from: [51.5, -0.1], to: [25.2, 55.3] },
    { from: [25.2, 55.3], to: [1.35, 103.8] },
    { from: [1.35, 103.8], to: [35.7, 139.7] },
    { from: [35.7, 139.7], to: [37.8, -122.4] },
    { from: [37.8, -122.4], to: [40.7, -74.0] },
    { from: [-33.9, 18.4], to: [25.2, 55.3] },
    { from: [-33.9, 151.2], to: [1.35, 103.8] },
    { from: [-23.6, -46.6], to: [40.7, -74.0] },
    { from: [19.1, 72.9], to: [35.7, 139.7] },
  ];

  var ROUTE_SEGMENTS = 72;
  function buildRouteGeometry(routes) {
    var positions = [];
    var ts = [];
    var counts = [];
    routes.forEach(function (route) {
      var a = latLonToVec3(route.from[0], route.from[1]);
      var b = latLonToVec3(route.to[0], route.to[1]);
      var angular = Math.acos(clampDot(a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
      var height = 0.09 + 0.15 * Math.min(1, angular / 1.6);
      for (var i = 0; i <= ROUTE_SEGMENTS; i += 1) {
        var t = i / ROUTE_SEGMENTS;
        var base = slerp(a, b, t);
        var lift = 1 + Math.sin(Math.PI * t) * height;
        positions.push(base[0] * lift, base[1] * lift, base[2] * lift);
        ts.push(t);
      }
      counts.push(ROUTE_SEGMENTS + 1);
    });
    return { positions: positions, ts: ts, counts: counts };
  }

  function buildEndpointGeometry(routes) {
    var seen = {};
    var cities = [];
    routes.forEach(function (route) {
      [route.from, route.to].forEach(function (city) {
        var key = city[0].toFixed(3) + "," + city[1].toFixed(3);
        if (seen[key]) return;
        seen[key] = true;
        cities.push(city);
      });
    });
    var positions = [];
    cities.forEach(function (city) {
      var p = latLonToVec3(city[0], city[1]);
      positions.push(p[0], p[1], p[2]);
    });
    return { positions: positions, count: cities.length };
  }

  var routeGeometry = buildRouteGeometry(ROUTES);
  var routePosBuffer = makeBuffer(routeGeometry.positions);
  var routeTBuffer = makeBuffer(routeGeometry.ts);
  var endpoints = buildEndpointGeometry(ROUTES);
  var pointPosBuffer = makeBuffer(endpoints.positions);

  var texture = gl.createTexture();
  var image = new Image();
  image.onload = function () {
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, image);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.generateMipmap(gl.TEXTURE_2D);
    ready = true;
  };
  image.onerror = function () {
    container.classList.add("fallback");
  };
  image.src = container.getAttribute("data-texture") || "../../assets/earth-texture.jpg";

  var ready = false;
  var reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var start = null;
  var rafId = null;
  var size = 1;
  var pixelRatio = Math.min(window.devicePixelRatio || 1, 2);

  function resize() {
    var min = Math.min(window.innerWidth, window.innerHeight);
    size = Math.round(min * 0.9);
    pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.style.width = size + "px";
    canvas.style.height = size + "px";
    canvas.width = Math.round(size * pixelRatio);
    canvas.height = Math.round(size * pixelRatio);
    gl.viewport(0, 0, canvas.width, canvas.height);
  }

  function drawRoutes(time) {
    gl.useProgram(routeProgram);
    gl.uniform1f(routeTimeLoc, time);
    gl.uniform3f(routeColorLoc, 1.0, 0.82, 0.45);
    bindAttrib(routePosLoc, routePosBuffer, 3);
    bindAttrib(routeTLoc, routeTBuffer, 1);
    var offset = 0;
    for (var i = 0; i < routeGeometry.counts.length; i += 1) {
      var count = routeGeometry.counts[i];
      gl.drawArrays(gl.LINE_STRIP, offset, count);
      offset += count;
    }
  }

  function drawEndpoints(time) {
    gl.useProgram(pointProgram);
    gl.uniform1f(pointTimeLoc, time);
    gl.uniform1f(pointSizeLoc, 5.0 * pixelRatio);
    gl.uniform3f(pointColorLoc, 1.0, 0.86, 0.52);
    bindAttrib(pointPosLoc, pointPosBuffer, 3);
    gl.drawArrays(gl.POINTS, 0, endpoints.count);
  }

  function draw(now) {
    if (start === null) start = now;
    var time = reducedMotion ? 0 : (now - start) / 1000;
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);

    if (ready) {
      gl.disable(gl.BLEND);
      disableAttribs();
      gl.useProgram(program);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.uniform1i(texLoc, 0);
      gl.uniform1f(timeLoc, time);
      bindAttrib(posLoc, spherePosBuffer, 3);
      bindAttrib(uvLoc, sphereUvBuffer, 2);
      gl.drawElements(gl.TRIANGLES, sphere.indices.length, gl.UNSIGNED_SHORT, 0);

      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
      disableAttribs();
      drawRoutes(time);
      drawEndpoints(time);
      gl.disable(gl.BLEND);
    }

    rafId = window.requestAnimationFrame(draw);
  }

  function onVisibility() {
    if (document.hidden) {
      if (rafId !== null) window.cancelAnimationFrame(rafId);
      rafId = null;
    } else if (rafId === null) {
      rafId = window.requestAnimationFrame(draw);
    }
  }

  window.addEventListener("resize", resize);
  document.addEventListener("visibilitychange", onVisibility);
  resize();
  rafId = window.requestAnimationFrame(draw);
})();
