/* ═══════════════════════════════════════════════════════════════════════
   J.A.R.V.I.S — 3D Workspace Controller (Three.js)
   Particle-based modeling environment
   ═══════════════════════════════════════════════════════════════════════ */

const Workspace3D = {
    scene: null,
    camera: null,
    renderer: null,
    objects: {},         // id -> { mesh, particles, data }
    selectedId: null,
    animationId: null,
    pollInterval: null,
    container: null,

    init() {
        this.container = document.getElementById('viewport-3d');
        if (!this.container || typeof THREE === 'undefined') return;

        this.setupScene();
        this.setupLights();
        this.setupGrid();
        this.animate();

        // Poll scene state from Python backend
        this.pollInterval = setInterval(() => this.pollScene(), 200);

        window.addEventListener('resize', () => this.onResize());

        // Toolbar
        this.bindToolbar();
    },

    /* ── Three.js setup ──────────────────────────────────────────────── */
    setupScene() {
        this.scene = new THREE.Scene();
        this.scene.fog = new THREE.FogExp2(0x050510, 0.08);

        const w = this.container.clientWidth;
        const h = this.container.clientHeight;

        this.camera = new THREE.PerspectiveCamera(60, w / h, 0.1, 100);
        this.camera.position.set(0, 2, 5);
        this.camera.lookAt(0, 0, 0);

        this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        this.renderer.setSize(w, h);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.setClearColor(0x050510, 1);
        this.container.appendChild(this.renderer.domElement);

        // Orbit controls if available
        if (typeof THREE.OrbitControls !== 'undefined') {
            this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
            this.controls.enableDamping = true;
            this.controls.dampingFactor = 0.08;
            this.controls.maxDistance = 20;
        }
    },

    setupLights() {
        const ambient = new THREE.AmbientLight(0x224466, 0.5);
        this.scene.add(ambient);

        const point = new THREE.PointLight(0x00e6ff, 1.5, 20);
        point.position.set(3, 4, 3);
        this.scene.add(point);

        const point2 = new THREE.PointLight(0xff8c00, 0.8, 15);
        point2.position.set(-3, 2, -2);
        this.scene.add(point2);
    },

    setupGrid() {
        const grid = new THREE.GridHelper(20, 40, 0x005f6b, 0x0a1a20);
        grid.position.y = -0.5;
        this.scene.add(grid);

        // Add floating particles for ambient effect
        const particleCount = 200;
        const pGeometry = new THREE.BufferGeometry();
        const positions = new Float32Array(particleCount * 3);
        for (let i = 0; i < particleCount * 3; i++) {
            positions[i] = (Math.random() - 0.5) * 16;
        }
        pGeometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        const pMaterial = new THREE.PointsMaterial({
            color: 0x00e6ff,
            size: 0.03,
            transparent: true,
            opacity: 0.4,
        });
        this.ambientParticles = new THREE.Points(pGeometry, pMaterial);
        this.scene.add(this.ambientParticles);
    },

    /* ── Object creation with particle mesh ──────────────────────────── */
    createObject(data) {
        if (this.objects[data.id]) return; // already exists

        const particleCount = data.particle_count || 5000;
        const shape = data.shape || 'cube';
        const color = new THREE.Color(data.color || '#00e6ff');

        // Create instanced mesh for particles
        const sphereGeo = new THREE.SphereGeometry(0.02, 4, 4);
        const material = new THREE.MeshPhongMaterial({
            color: color,
            emissive: color,
            emissiveIntensity: 0.3,
            transparent: true,
            opacity: 0.85,
        });

        const instancedMesh = new THREE.InstancedMesh(sphereGeo, material, particleCount);
        const dummy = new THREE.Object3D();
        const particlePositions = [];

        // Distribute particles on surface based on shape
        for (let i = 0; i < particleCount; i++) {
            const p = this.sampleShape(shape, i, particleCount);
            particlePositions.push(p);
            dummy.position.set(p.x, p.y, p.z);
            dummy.updateMatrix();
            instancedMesh.setMatrixAt(i, dummy.matrix);
        }
        instancedMesh.instanceMatrix.needsUpdate = true;

        // Container group
        const group = new THREE.Group();
        group.add(instancedMesh);
        group.position.set(
            data.position?.[0] || 0,
            data.position?.[1] || 0,
            data.position?.[2] || 0,
        );

        this.scene.add(group);
        this.objects[data.id] = {
            group,
            mesh: instancedMesh,
            particles: particlePositions,
            data,
            material,
        };

        // Highlight selected
        if (data.id === this.selectedId) {
            this.highlightObject(data.id, true);
        }
    },

    sampleShape(shape, index, total) {
        switch (shape) {
            case 'sphere': {
                const phi = Math.acos(1 - 2 * (index + 0.5) / total);
                const theta = Math.PI * (1 + Math.sqrt(5)) * index;
                return {
                    x: Math.sin(phi) * Math.cos(theta),
                    y: Math.sin(phi) * Math.sin(theta),
                    z: Math.cos(phi),
                };
            }
            case 'cylinder': {
                const angle = (index / total) * Math.PI * 2 * 20;
                const h = (index / total) * 2 - 1;
                const r = 0.8;
                const onCap = Math.random() < 0.2;
                if (onCap) {
                    const cr = Math.random() * r;
                    return {
                        x: cr * Math.cos(angle),
                        y: h > 0 ? 1 : -1,
                        z: cr * Math.sin(angle),
                    };
                }
                return {
                    x: r * Math.cos(angle),
                    y: h,
                    z: r * Math.sin(angle),
                };
            }
            default: { // cube
                const face = Math.floor(Math.random() * 6);
                const u = Math.random() * 2 - 1;
                const v = Math.random() * 2 - 1;
                switch (face) {
                    case 0: return { x: 1, y: u, z: v };
                    case 1: return { x: -1, y: u, z: v };
                    case 2: return { x: u, y: 1, z: v };
                    case 3: return { x: u, y: -1, z: v };
                    case 4: return { x: u, y: v, z: 1 };
                    default: return { x: u, y: v, z: -1 };
                }
            }
        }
    },

    /* ── Scene manipulation commands ─────────────────────────────────── */
    handleCommand(cmd) {
        switch (cmd.action) {
            case 'create_object':
                this.createObject(cmd.params);
                break;

            case 'delete': {
                const obj = this.objects[cmd.object_id];
                if (obj) {
                    this.scene.remove(obj.group);
                    obj.mesh.dispose();
                    obj.material.dispose();
                    delete this.objects[cmd.object_id];
                }
                break;
            }

            case 'select':
                this.selectObject(cmd.object_id);
                break;

            case 'translate': {
                const obj2 = this.objects[cmd.object_id];
                if (obj2 && cmd.params.position) {
                    obj2.group.position.set(...cmd.params.position);
                }
                break;
            }

            case 'rotate': {
                const obj3 = this.objects[cmd.object_id];
                if (obj3 && cmd.params.rotation) {
                    obj3.group.rotation.set(...cmd.params.rotation);
                }
                break;
            }

            case 'scale': {
                const obj4 = this.objects[cmd.object_id];
                if (obj4 && cmd.params.scale) {
                    obj4.group.scale.set(...cmd.params.scale);
                }
                break;
            }

            case 'deform':
                this.deformObject(cmd.object_id, cmd.params);
                break;

            case 'clear':
                Object.keys(this.objects).forEach(id => {
                    const o = this.objects[id];
                    this.scene.remove(o.group);
                    o.mesh.dispose();
                    o.material.dispose();
                });
                this.objects = {};
                break;
        }
    },

    selectObject(id) {
        // Unhighlight previous
        if (this.selectedId) this.highlightObject(this.selectedId, false);
        this.selectedId = id;
        if (id) this.highlightObject(id, true);
    },

    highlightObject(id, highlight) {
        const obj = this.objects[id];
        if (!obj) return;
        obj.material.emissiveIntensity = highlight ? 0.6 : 0.3;
        obj.material.opacity = highlight ? 1.0 : 0.85;
    },

    deformObject(id, params) {
        const obj = this.objects[id];
        if (!obj) return;

        const force = params.force || 1;
        const radius = params.radius || 0.5;
        const pos = params.position || [0, 0, 0];
        const deformPos = new THREE.Vector3(
            pos[0] * 4 - 2, pos[1] * -4 + 2, pos[2] * 4
        );

        const dummy = new THREE.Object3D();
        const damping = 0.92;

        for (let i = 0; i < obj.particles.length; i++) {
            const p = obj.particles[i];
            const worldP = new THREE.Vector3(p.x, p.y, p.z).add(obj.group.position);
            const dist = worldP.distanceTo(deformPos);

            if (dist < radius) {
                const factor = (1 - dist / radius) * force * 0.05;
                const dir = worldP.clone().sub(deformPos).normalize();
                p.x += dir.x * factor * damping;
                p.y += dir.y * factor * damping;
                p.z += dir.z * factor * damping;

                dummy.position.set(p.x, p.y, p.z);
                dummy.updateMatrix();
                obj.mesh.setMatrixAt(i, dummy.matrix);
            }
        }
        obj.mesh.instanceMatrix.needsUpdate = true;
    },

    /* ── Toolbar ─────────────────────────────────────────────────────── */
    bindToolbar() {
        const createBtns = document.querySelectorAll('[data-create]');
        createBtns.forEach(btn => {
            btn.addEventListener('click', async () => {
                const shape = btn.dataset.create;
                try {
                    const result = JSON.parse(await pywebview.api.create_object(shape));
                    if (result.id) {
                        this.createObject({
                            id: result.id,
                            shape: result.shape,
                            position: [0, 0, 0],
                            rotation: [0, 0, 0],
                            scale: [1, 1, 1],
                            particle_count: 5000,
                            color: '#00e6ff',
                        });
                    }
                } catch (_) {}
            });
        });
    },

    /* ── Animation loop ──────────────────────────────────────────────── */
    animate() {
        this.animationId = requestAnimationFrame(() => this.animate());

        // Rotate ambient particles slowly
        if (this.ambientParticles) {
            this.ambientParticles.rotation.y += 0.0003;
        }

        if (this.controls) this.controls.update();
        if (this.renderer && this.scene && this.camera) {
            this.renderer.render(this.scene, this.camera);
        }
    },

    onResize() {
        if (!this.container || !this.camera || !this.renderer) return;
        const w = this.container.clientWidth;
        const h = this.container.clientHeight;
        this.camera.aspect = w / h;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(w, h);
    },

    /* ── Polling ─────────────────────────────────────────────────────── */
    async pollScene() {
        try {
            const scene = JSON.parse(await pywebview.api.get_scene());
            const objectCount = document.getElementById('object-count');
            if (objectCount) objectCount.textContent = scene.length;

            // Sync objects
            scene.forEach(objData => {
                if (!this.objects[objData.id]) {
                    this.createObject(objData);
                } else {
                    // Update position / rotation / scale
                    const obj = this.objects[objData.id];
                    obj.group.position.set(...objData.position);
                    obj.group.rotation.set(...objData.rotation);
                    obj.group.scale.set(...objData.scale);
                }
            });
        } catch (_) {}
    },

    destroy() {
        if (this.animationId) cancelAnimationFrame(this.animationId);
        if (this.pollInterval) clearInterval(this.pollInterval);
        if (this.renderer) {
            this.renderer.dispose();
            this.container?.removeChild(this.renderer.domElement);
        }
    },
};

window.addEventListener('pywebviewready', () => Workspace3D.init());
document.addEventListener('DOMContentLoaded', () => {
    setTimeout(() => { if (!window.pywebview) Workspace3D.init(); }, 2000);
});
