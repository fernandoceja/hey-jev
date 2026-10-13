/* Hey Jev tutor visuals. KaTeX and Three.js are loaded beside this file.
   Their licenses are katex/LICENSE and three/LICENSE. This file does not
   fetch anything and does not eval model text. */
(function () {
  var state = { index: 0, lesson: null, token: 0 };

  function lesson() {
    return state.lesson || { title: "", steps: [], answer: "", visual: { type: "none" } };
  }

  function typeset(el, latex) {
    el.textContent = "";
    var source = latex || "";
    if (!source || typeof katex === "undefined") {
      el.textContent = source;
      return;
    }
    try {
      katex.render(source, el, { throwOnError: false, displayMode: true });
    } catch (err) {
      el.textContent = source;
    }
  }

  function render() {
    var data = lesson();
    var steps = data.steps || [];
    document.getElementById("title").textContent = data.title || "";
    var list = document.getElementById("steps");
    list.textContent = "";
    steps.forEach(function (step, index) {
      var item = document.createElement("li");
      item.className = "step" + (index === state.index ? " current" : "");
      var math = document.createElement("div");
      math.className = "math";
      typeset(math, step.latex || "");
      item.appendChild(math);
      if (step.note) {
        var note = document.createElement("p");
        note.className = "note";
        note.textContent = step.note;
        item.appendChild(note);
      }
      list.appendChild(item);
    });
    var progress = document.getElementById("progress");
    var count = steps.length || 1;
    progress.textContent = "Step " + (state.index + 1) + " of " + count;
    typeset(document.getElementById("answer"), data.answer || "");
    var current = list.querySelector(".current");
    if (current && current.scrollIntoView) {
      current.scrollIntoView({ block: "nearest" });
    }
  }

  function hostSize(host) {
    var width = host.clientWidth || 640;
    var height = 320;
    return { width: width, height: height };
  }

  function canvasFor(host) {
    var size = hostSize(host);
    var canvas = document.createElement("canvas");
    canvas.width = Math.max(320, Math.floor(size.width));
    canvas.height = size.height;
    canvas.style.width = "100%";
    canvas.style.height = size.height + "px";
    host.appendChild(canvas);
    return canvas.getContext("2d");
  }

  function showPlot(host, points) {
    if (!points || points.length < 2) {
      return;
    }
    var ctx = canvasFor(host);
    var canvas = ctx.canvas;
    var pad = 36;
    var minX = points[0][0];
    var maxX = points[0][0];
    var minY = points[0][1];
    var maxY = points[0][1];
    points.forEach(function (point) {
      minX = Math.min(minX, point[0]);
      maxX = Math.max(maxX, point[0]);
      minY = Math.min(minY, point[1]);
      maxY = Math.max(maxY, point[1]);
    });
    if (minY === maxY) {
      minY -= 1;
      maxY += 1;
    }
    if (minX === maxX) {
      minX -= 1;
      maxX += 1;
    }
    function sx(x) {
      return pad + (x - minX) / (maxX - minX) * (canvas.width - pad * 2);
    }
    function sy(y) {
      return canvas.height - pad - (y - minY) / (maxY - minY) * (canvas.height - pad * 2);
    }
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "#d9d3c7";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(sx(minX), sy(0));
    ctx.lineTo(sx(maxX), sy(0));
    ctx.moveTo(sx(0), sy(minY));
    ctx.lineTo(sx(0), sy(maxY));
    ctx.stroke();
    ctx.strokeStyle = "#2c6bed";
    ctx.lineWidth = 2;
    ctx.beginPath();
    points.forEach(function (point, index) {
      var x = sx(point[0]);
      var y = sy(point[1]);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  function showProjectile(host, points, token) {
    if (!points || points.length < 2) {
      return;
    }
    if (typeof THREE === "undefined") {
      showPlot(host, points);
      return;
    }
    var size = hostSize(host);
    var scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf7f4ee);
    var camera = new THREE.PerspectiveCamera(40, size.width / size.height, 0.1, 1000);
    var renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(size.width, size.height);
    host.appendChild(renderer.domElement);
    var flat = [];
    var min = [Infinity, Infinity, Infinity];
    var max = [-Infinity, -Infinity, -Infinity];
    points.forEach(function (point) {
      for (var i = 0; i < 3; i++) {
        var value = Number(point[i] || 0);
        min[i] = Math.min(min[i], value);
        max[i] = Math.max(max[i], value);
      }
    });
    var span = Math.max(max[0] - min[0], max[1] - min[1], 1);
    function place(point) {
      return [
        (Number(point[0] || 0) - min[0]) / span * 8,
        (Number(point[1] || 0) - min[1]) / span * 8,
        (Number(point[2] || 0) - min[2]) / span * 8
      ];
    }
    points.forEach(function (point) {
      var placed = place(point);
      flat.push(placed[0], placed[1], placed[2]);
    });
    var geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(flat, 3));
    var line = new THREE.Line(
      geometry,
      new THREE.LineBasicMaterial({ color: 0x2c6bed })
    );
    scene.add(line);
    var sphere = new THREE.Mesh(
      new THREE.SphereGeometry(0.16, 18, 14),
      new THREE.MeshBasicMaterial({ color: 0xe07a3d })
    );
    scene.add(sphere);
    var ground = new THREE.GridHelper(10, 10, 0xd9d3c7, 0xe7e1d6);
    ground.position.y = 0;
    scene.add(ground);
    camera.position.set(4, 3.2, 9);
    camera.lookAt(4, 1.5, 0);
    var frame = 0;
    function tick() {
      if (state.token !== token) return;
      var placed = place(points[frame % points.length]);
      sphere.position.set(placed[0], placed[1], placed[2]);
      frame += 1;
      renderer.render(scene, camera);
      window.requestAnimationFrame(tick);
    }
    tick();
  }

  function showVectors(host, vectors) {
    if (!vectors || !vectors.length) return;
    if (typeof THREE === "undefined") {
      var flat = vectors.map(function (vector) {
        return [0, 0, vector.x, vector.y];
      });
      showPlot(host, flat.map(function (row) { return [row[2], row[3]]; }));
      return;
    }
    var size = hostSize(host);
    var scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf7f4ee);
    var camera = new THREE.PerspectiveCamera(40, size.width / size.height, 0.1, 1000);
    var renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(size.width, size.height);
    host.appendChild(renderer.domElement);
    var colors = [0x2c6bed, 0xe07a3d, 0x2f9e78, 0x8a4fff];
    vectors.forEach(function (vector, index) {
      var direction = new THREE.Vector3(Number(vector.x) || 0, Number(vector.y) || 0, Number(vector.z) || 0);
      var length = direction.length() || 1;
      direction.normalize();
      var arrow = new THREE.ArrowHelper(direction, new THREE.Vector3(0, 0, 0), length, colors[index % colors.length]);
      scene.add(arrow);
    });
    camera.position.set(4, 4, 8);
    camera.lookAt(0, 0, 0);
    renderer.render(scene, camera);
  }

  function drawVisual() {
    var node = document.getElementById("visual");
    state.token += 1;
    var token = state.token;
    node.textContent = "";
    var visual = lesson().visual || { type: "none" };
    if (visual.type === "plot") showPlot(node, visual.points || []);
    else if (visual.type === "projectile") showProjectile(node, visual.points || [], token);
    else if (visual.type === "vector") showVectors(node, visual.vectors || []);
  }

  window.tutorShow = function (index) {
    var steps = lesson().steps || [];
    var last = Math.max(0, steps.length - 1);
    var next = index | 0;
    if (next < 0) next = 0;
    if (next > last) next = last;
    state.index = next;
    render();
  };

  window.tutorReplay = function () {
    drawVisual();
  };

  var raw = document.getElementById("lesson-data");
  state.lesson = JSON.parse(raw ? raw.textContent || "{}" : "{}");
  render();
  drawVisual();
}());
