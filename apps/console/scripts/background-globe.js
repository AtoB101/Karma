/* Karma Console — self-contained WebGL Earth globe with golden light.
 *
 * No external libraries. The globe is a textured UV sphere rendered behind the
 * console shell and centred on the full viewport. If WebGL or the texture is
 * unavailable it falls back to a CSS sphere in the same position.
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

  function compile(type, source) {
    var shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      throw new Error(gl.getShaderInfoLog(shader) || "shader compile failed");
    }
    return shader;
  }

  var program = gl.createProgram();
  gl.attachShader(program, compile(gl.VERTEX_SHADER, VERT_SRC));
  gl.attachShader(program, compile(gl.FRAGMENT_SHADER, FRAG_SRC));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(program) || "program link failed");
  }
  gl.useProgram(program);

  var posLoc = gl.getAttribLocation(program, "aPosition");
  var uvLoc = gl.getAttribLocation(program, "aUv");
  var timeLoc = gl.getUniformLocation(program, "uTime");
  var texLoc = gl.getUniformLocation(program, "uTexture");

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

  function bindBuffer(target, data, loc, size) {
    var buffer = gl.createBuffer();
    gl.bindBuffer(target, buffer);
    gl.bufferData(target, new Float32Array(data), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
    return buffer;
  }

  var sphere = buildSphere(72, 96);
  bindBuffer(gl.ARRAY_BUFFER, sphere.positions, posLoc, 3);
  bindBuffer(gl.ARRAY_BUFFER, sphere.uvs, uvLoc, 2);
  var indexBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(sphere.indices), gl.STATIC_DRAW);

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

  function resize() {
    var min = Math.min(window.innerWidth, window.innerHeight);
    size = Math.round(min * 0.9);
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.style.width = size + "px";
    canvas.style.height = size + "px";
    canvas.width = Math.round(size * dpr);
    canvas.height = Math.round(size * dpr);
    gl.viewport(0, 0, canvas.width, canvas.height);
  }

  function draw(now) {
    if (start === null) start = now;
    var time = reducedMotion ? 0 : (now - start) / 1000;
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (ready) {
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.uniform1i(texLoc, 0);
      gl.uniform1f(timeLoc, time);
      gl.drawElements(gl.TRIANGLES, sphere.indices.length, gl.UNSIGNED_SHORT, 0);
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

