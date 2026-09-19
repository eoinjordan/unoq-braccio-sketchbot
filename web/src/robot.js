import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export function modelRotations(workspace, pose) {
  const mapping = workspace.servo_calibration;
  const geometric = (name, value) => THREE.MathUtils.degToRad((value - mapping[name].offset) / mapping[name].sign);
  return {
    base: geometric("base", pose[0]), shoulder: geometric("shoulder", pose[1]),
    elbow: geometric("elbow", pose[2]), wrist: geometric("wrist_vertical", pose[3]),
    roll: THREE.MathUtils.degToRad(pose[4] - 90),
    paper: THREE.MathUtils.degToRad(workspace.paper.rotation_deg || 0),
  };
}

export function createRobotView(host, onJoint, onPaper) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#edf3f1");
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.setClearColor("#edf3f1");
  renderer.domElement.setAttribute("aria-label", "Interactive Braccio robot model");
  renderer.domElement.setAttribute("role", "img");
  host.append(renderer.domElement);
  const camera = new THREE.PerspectiveCamera(42, 1, 0.5, 3000);
  const orbit = new OrbitControls(camera, renderer.domElement);
  orbit.enableDamping = true;
  orbit.minDistance = 240;
  orbit.maxDistance = 1100;
  orbit.maxPolarAngle = Math.PI / 2 - 0.025;
  const resetView = () => { camera.position.set(450, 300, 480); orbit.target.set(90, 145, 0); orbit.update(); };
  resetView();
  scene.add(new THREE.HemisphereLight(0xffffff, 0x7d9387, 2.5));
  const light = new THREE.DirectionalLight(0xffffff, 3.2);
  light.position.set(180, 550, 230);
  light.castShadow = true;
  light.shadow.mapSize.set(2048, 2048);
  Object.assign(light.shadow.camera, { left: -500, right: 500, top: 600, bottom: -500, near: 1, far: 1200 });
  light.shadow.normalBias = 0.5;
  scene.add(light);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(1100, 1100), new THREE.ShadowMaterial({ opacity: 0.14 }));
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  scene.add(floor);
  const grid = new THREE.GridHelper(840, 28, 0xb7c8c1, 0xd8e3de);
  grid.position.y = -0.3;
  scene.add(grid);
  const root = new THREE.Group();
  scene.add(root);
  let workspace;
  let activeTools = { active: "sketch" };
  let joints = [];
  let fingers = [];
  let paperMesh;
  let paperGroup;
  let selected = 0;
  let desired = [90, 45, 180, 180, 90, 10];
  let displayed = [...desired];
  let pickables = [];
  let frameCount = 0;
  const colors = { orange: 0xf37020, dark: 0x252e33, silver: 0x9eadae, green: 0x009e72 };

  function material(color) { return new THREE.MeshStandardMaterial({ color, roughness: 0.52, metalness: 0.12 }); }
  function mesh(parent, geometry, color, position, joint = null) {
    const object = new THREE.Mesh(geometry, material(color));
    object.position.set(...position);
    object.castShadow = true;
    object.receiveShadow = true;
    if (joint !== null) { object.userData.joint = joint; pickables.push(object); }
    parent.add(object);
    return object;
  }
  function axle(parent, position, joint, radius = 18) {
    const cylinder = mesh(parent, new THREE.CylinderGeometry(radius, radius, 48, 32), colors.dark, position, joint);
    cylinder.rotation.x = Math.PI / 2;
    for (const side of [-1, 1]) {
      const cap = mesh(parent, new THREE.CylinderGeometry(9, 9, 3, 24), colors.silver,
        [position[0], position[1], position[2] + side * 25], joint);
      cap.rotation.x = Math.PI / 2;
    }
  }
  function link(parent, length, joint) {
    for (const side of [-1, 1]) {
      const plate = mesh(parent, new THREE.CapsuleGeometry(12, Math.max(1, length - 24), 5, 16),
        colors.orange, [length / 2, 0, side * 18], joint);
      plate.scale.z = 0.28;
      plate.rotation.z = -Math.PI / 2;
      mesh(parent, new THREE.BoxGeometry(length * 0.46, 9, 2), colors.dark,
        [length / 2, 0, side * 22], joint);
    }
    mesh(parent, new THREE.BoxGeometry(27, 23, 34), colors.dark, [23, 0, 0], joint);
    axle(parent, [0, 0, 0], joint);
  }
  function cameraBody(parent, position, joint = null) {
    mesh(parent, new THREE.BoxGeometry(24, 17, 27), colors.dark, position, joint);
    const lens = mesh(parent, new THREE.CylinderGeometry(7, 7, 6, 24), 0x376c9e,
      [position[0] + 15, position[1], position[2]], joint);
    lens.rotation.z = Math.PI / 2;
  }
  function rebuild(nextWorkspace, cameraSpecs, tools = { active: "sketch" }) {
    workspace = nextWorkspace;
    activeTools = tools;
    renderer.domElement.dataset.tool = tools.active;
    root.traverse(object => { object.geometry?.dispose(); object.material?.dispose(); });
    root.clear(); pickables = []; joints = []; fingers = [];
    const links = workspace.links;
    const base = new THREE.Group(); root.add(base); joints.push(base);
    mesh(base, new THREE.CylinderGeometry(49, 61, 14, 48), colors.orange, [0, 7, 0], 0);
    mesh(base, new THREE.CylinderGeometry(37, 37, 12, 48), colors.dark, [0, 20, 0], 0);
    for (const side of [-1, 1]) {
      mesh(base, new THREE.BoxGeometry(32, Math.max(20, links.base_height_mm - 28), 11), colors.orange,
        [0, (links.base_height_mm + 28) / 2, side * 25], 0);
    }
    const shoulder = new THREE.Group(); shoulder.position.y = links.base_height_mm; base.add(shoulder); joints.push(shoulder);
    link(shoulder, links.shoulder_mm, 1);
    const elbow = new THREE.Group(); elbow.position.x = links.shoulder_mm; shoulder.add(elbow); joints.push(elbow);
    link(elbow, links.elbow_mm, 2);
    const wrist = new THREE.Group(); wrist.position.x = links.elbow_mm; elbow.add(wrist); joints.push(wrist);
    axle(wrist, [0, 0, 0], 3, 16);
    mesh(wrist, new THREE.BoxGeometry(39, 26, 28), colors.orange, [28, 0, 0], 3);
    const roll = new THREE.Group(); roll.position.x = 45; wrist.add(roll); joints.push(roll);
    mesh(roll, new THREE.BoxGeometry(26, 24, 32), colors.dark, [8, 0, 0], 4);
    for (const side of [-1, 1]) {
      const length = tools.active === "gripper" ? Math.max(8, links.wrist_pen_mm - 65) : 37;
      const position = tools.active === "gripper" ? links.wrist_pen_mm - 45 - length / 2 : 26;
      const finger = mesh(roll, new THREE.BoxGeometry(length, 8, 8), colors.silver, [position, side * 12, 0], 5);
      fingers.push(finger);
    }
    if (tools.active === "sketch") {
    mesh(wrist, new THREE.BoxGeometry(29, 16, 19), 0x657174, [86, 0, 0], 5);
    const penLength = Math.max(12, links.wrist_pen_mm - 95);
    const pen = mesh(wrist, new THREE.CylinderGeometry(3.4, 3.4, penLength, 18), colors.dark,
      [95 + penLength / 2 - 4, 0, 0], 5);
    pen.rotation.z = -Math.PI / 2;
    const tip = mesh(wrist, new THREE.ConeGeometry(3.4, 8, 16), 0xb6bfc0, [links.wrist_pen_mm - 4, 0, 0], 5);
    tip.rotation.z = -Math.PI / 2;
    }
    if (cameraSpecs?.face?.mounted_on_arm) cameraBody(wrist, [45, 28, 0], 3);
    else {
      mesh(root, new THREE.CylinderGeometry(20, 24, 6, 24), colors.dark, [70, 3, -210]);
      mesh(root, new THREE.CylinderGeometry(3, 3, 55, 12), colors.silver, [70, 30, -210]);
      cameraBody(root, [70, 60, -210]);
    }
    const paper = workspace.paper;
    paperGroup = new THREE.Group(); paperGroup.rotation.y = modelRotations(workspace, displayed).paper; root.add(paperGroup);
    const sheet = mesh(paperGroup, new THREE.BoxGeometry(Math.max(75, paper.width_mm + 30), 1, Math.max(70, paper.height_mm + 30)),
      0xffffff, [paper.origin_x_mm + paper.width_mm / 2, 1, -paper.origin_y_mm - paper.height_mm / 2]);
    sheet.receiveShadow = true;
    paperMesh = mesh(paperGroup, new THREE.PlaneGeometry(paper.width_mm, paper.height_mm), 0xe1f5eb,
      [paper.origin_x_mm + paper.width_mm / 2, 1.6, -paper.origin_y_mm - paper.height_mm / 2]);
    paperMesh.rotation.x = -Math.PI / 2;
    paperMesh.userData.paper = true;
    pickables.push(paperMesh);
    const edge = new THREE.LineSegments(new THREE.EdgesGeometry(paperMesh.geometry), new THREE.LineBasicMaterial({ color: colors.green }));
    paperMesh.add(edge);
    paperGroup.visible = tools.active === "sketch";
    if (tools.active === "gripper") {
      pickables = pickables.filter(object => object !== paperMesh);
      for (const [name, color] of [["pick", 0x009e72], ["place", 0x4453c7]]) {
        const target = tools.gripper[name];
        const pad = mesh(root, new THREE.CylinderGeometry(22, 22, 2, 48), color, [target.x, 1.2, -target.y]);
        pad.material.transparent = true; pad.material.opacity = 0.42;
        pad.userData.target = { ...target, z: tools.gripper.lift_z_mm };
        pickables.push(pad);
        const ring = new THREE.Mesh(new THREE.TorusGeometry(12, 0.8, 8, 40), material(color));
        ring.rotation.x = Math.PI / 2; ring.position.set(target.x, target.z, -target.y); root.add(ring);
      }
    }
    select(selected);
    applyPose();
  }
  function applyPose() {
    if (!workspace || joints.length < 5) return;
    const rotations = modelRotations(workspace, displayed);
    joints[0].rotation.y = rotations.base;
    joints[1].rotation.z = rotations.shoulder;
    joints[2].rotation.z = rotations.elbow;
    joints[3].rotation.z = rotations.wrist;
    joints[4].rotation.x = rotations.roll;
    const grip = activeTools.gripper;
    const gap = activeTools.active === "gripper" ? 3 + 16 * THREE.MathUtils.clamp(
      (displayed[5] - grip.closed_deg) / (grip.open_deg - grip.closed_deg), 0, 1) : 6 + displayed[5] / 9;
    fingers.forEach((finger, index) => { finger.position.y = (index ? 1 : -1) * gap; });
  }
  function select(index) {
    selected = index;
    for (const object of pickables) {
      if (object.userData.joint !== undefined) {
        object.material.emissive.setHex(object.userData.joint === index ? 0x442400 : 0x000000);
      }
    }
  }
  const raycaster = new THREE.Raycaster();
  let downPoint = null;
  renderer.domElement.addEventListener("pointerdown", event => { downPoint = [event.clientX, event.clientY]; });
  renderer.domElement.addEventListener("pointerup", event => {
    if (!downPoint || Math.hypot(event.clientX - downPoint[0], event.clientY - downPoint[1]) > 6) return;
    const rect = renderer.domElement.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1,
      -(event.clientY - rect.top) / rect.height * 2 + 1), camera);
    const hit = raycaster.intersectObjects(pickables, false)[0];
    if (hit?.object.userData.target) {
      onPaper(null, null, hit.object.userData.target);
    } else if (hit?.object.userData.paper) {
      const point = paperGroup.worldToLocal(hit.point.clone());
      onPaper(point.x - workspace.paper.origin_x_mm, -point.z - workspace.paper.origin_y_mm);
    } else if (hit?.object.userData.joint !== undefined) onJoint(hit.object.userData.joint);
  });
  const observer = new ResizeObserver(() => {
    const width = Math.max(1, host.clientWidth), height = Math.max(1, host.clientHeight);
    renderer.setSize(width, height); camera.aspect = width / height; camera.updateProjectionMatrix();
  });
  observer.observe(host);
  renderer.setAnimationLoop(() => {
    displayed = displayed.map((value, index) => THREE.MathUtils.lerp(value, desired[index], 0.16));
    applyPose(); orbit.update(); renderer.render(scene, camera);
    renderer.domElement.dataset.rendered = String(++frameCount);
    renderer.domElement.dataset.pose = displayed.map(value => value.toFixed(1)).join(",");
  });
  return {
    rebuild, select, resetView,
    setPose: pose => { desired = [...pose]; },
    topView: () => { camera.position.set(150, 750, 0.01); orbit.target.set(150, 0, 0); orbit.update(); },
    zoom: factor => { camera.position.sub(orbit.target).multiplyScalar(factor).add(orbit.target); orbit.update(); },
  };
}