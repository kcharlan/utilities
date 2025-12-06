/**
 * Rock Paper Scissors Simulator
 */

// --- Configuration & State ---
const CONFIG = {
    count: 20,
    speedMultiplier: 5,
    scaleLevel: 4,      // 1-10
    baseSize: 24,       // Size at level 1
    iconSize: 96,       // Calculated: baseSize * scaleLevel
    collisionRadius: 48, // Calculated: iconSize / 2
};

const TYPES = {
    ROCK: 0,
    PAPER: 1,
    SCISSORS: 2
};
// Rules: Key beats Value
const RULES = {
    [TYPES.ROCK]: TYPES.SCISSORS,
    [TYPES.SCISSORS]: TYPES.PAPER,
    [TYPES.PAPER]: TYPES.ROCK
};

const ASSETS = {
    [TYPES.ROCK]: { src: 'rock.png', img: null },
    [TYPES.PAPER]: { src: 'paper.png', img: null },
    [TYPES.SCISSORS]: { src: 'scissors.png', img: null },
};

let canvas, ctx;
let items = [];
let animationId;
let isRunning = false;
let width, height;

// --- Elements ---
const restartBtn = document.getElementById('restartBtn');
const countInput = document.getElementById('countInput');
const speedInput = document.getElementById('speedInput');
const speedValue = document.getElementById('speedValue');
const sizeRange = document.getElementById('sizeRange');
const sizeInput = document.getElementById('sizeInput');
const themeSelect = document.getElementById('themeSelect');
const stats = {
    rock: document.getElementById('rockCount'),
    paper: document.getElementById('paperCount'),
    scissors: document.getElementById('scissorsCount')
};

// --- Initialization ---
async function init() {
    canvas = document.getElementById('simCanvas');
    ctx = canvas.getContext('2d');

    // --- Check System Theme ---
    applyTheme(themeSelect.value);

    // --- Event Listeners (Attach FIRST so they always work) ---
    window.addEventListener('resize', resizeCanvas);
    restartBtn.addEventListener('click', startSimulation);

    countInput.addEventListener('change', () => {
        let val = parseInt(countInput.value);
        if (val < 2) val = 2;
        if (val > 200) val = 200;
        countInput.value = val;
        CONFIG.count = val;
    });

    speedInput.addEventListener('input', () => {
        CONFIG.speedMultiplier = parseInt(speedInput.value);
        speedValue.textContent = CONFIG.speedMultiplier;
        updateSpeed();
    });

    // Size Inputs
    const handleSizeChange = (val) => {
        let v = parseInt(val);
        if (v < 1) v = 1;
        if (v > 10) v = 10;
        CONFIG.scaleLevel = v;
        sizeRange.value = v;
        sizeInput.value = v;
        updateSize();
    };

    sizeRange.addEventListener('input', (e) => handleSizeChange(e.target.value));
    sizeInput.addEventListener('change', (e) => handleSizeChange(e.target.value));

    themeSelect.addEventListener('change', (e) => applyTheme(e.target.value));

    // --- Load Images ---
    // Note: Local file security restrictions prevent pixel manipulation (getImageData)
    // without a web server. We try-catch to gracefully fallback if it fails.
    try {
        await Promise.all(Object.values(ASSETS).map(asset => {
            return new Promise((resolve, reject) => {
                const img = new Image();
                // img.crossOrigin = "Anonymous"; // REMOVED: Blocks file:// loading in Chrome
                img.src = asset.src;
                img.onload = () => {
                    try {
                        // Attempt "Magic Wand" transparency
                        asset.img = processImage(img);
                    } catch (e) {
                        console.warn("Transparency processing failed (likely CORS/file-protocol restriction). Using original image.", e);
                        asset.img = img;
                    }
                    resolve();
                };
                img.onerror = (e) => {
                    console.error("Failed to load image:", asset.src, e);
                    // Resolve anyway to let simulation start with fallbacks (circles)
                    resolve();
                };
            });
        }));
    } catch (e) {
        console.error("Image loading error", e);
    }

    // Initial Setup
    resizeCanvas();
    startSimulation();
}

function updateSpeed() {
    items.forEach(item => {
        const currentSpeed = Math.sqrt(item.vx * item.vx + item.vy * item.vy);
        if (currentSpeed === 0) return;
        // We want base speed ~ 1-2 pixels/frame * multiplier?
        // Let's say max speed is multiplier * 0.5
        const targetSpeed = (CONFIG.speedMultiplier * 0.5) + 0.5; // Ensure non-zero
        const scale = targetSpeed / currentSpeed;
        item.vx *= scale;
        item.vy *= scale;
    });
}

function updateSize() {
    CONFIG.iconSize = CONFIG.baseSize * CONFIG.scaleLevel;
    CONFIG.collisionRadius = CONFIG.iconSize / 2;

    // Update existing items
    items.forEach(item => {
        item.radius = CONFIG.collisionRadius;
    });
    // Re-check bounds immediately in case they grew into a wall
    resizeCanvas();
}

/**
 * Removes white/near-white background from an image using Flood Fill
 * Returns a new HTMLImageElement (or Canvas)
 */
function processImage(sourceImg) {
    const w = sourceImg.width;
    const h = sourceImg.height;

    const scratchCanvas = document.createElement('canvas');
    scratchCanvas.width = w;
    scratchCanvas.height = h;
    const scratchCtx = scratchCanvas.getContext('2d');

    scratchCtx.drawImage(sourceImg, 0, 0);
    const imageData = scratchCtx.getImageData(0, 0, w, h);
    const data = imageData.data;

    // BFS Flood Fill from (0,0) and corners to catch background
    // Assuming background is top-left pixel color (which should be white)
    // We check 0,0; w-1,0; 0,h-1; w-1,h-1 just to be safe

    const visited = new Uint8Array(w * h); // 1 if visited
    const queue = [];

    // Helper to add if consistent with background
    // We'll consider "white-ish" as R>200, G>200, B>200
    const isBackground = (idx) => {
        const r = data[idx];
        const g = data[idx + 1];
        const b = data[idx + 2];
        // Strict white or near white
        return (r > 240 && g > 240 && b > 240);
    };

    const seeds = [
        { x: 0, y: 0 },
        { x: w - 1, y: 0 },
        { x: 0, y: h - 1 },
        { x: w - 1, y: h - 1 }
    ];

    seeds.forEach(p => {
        const idx = (p.y * w + p.x) * 4;
        if (isBackground(idx)) {
            queue.push(p);
            visited[p.y * w + p.x] = 1;
        }
    });

    while (queue.length > 0) {
        const { x, y } = queue.shift();
        const baseIdx = (y * w + x) * 4;

        // Clear pixel
        data[baseIdx + 3] = 0; // Alpha 0

        // Neighbors
        const neighbors = [
            { x: x + 1, y: y }, { x: x - 1, y: y },
            { x: x, y: y + 1 }, { x: x, y: y - 1 }
        ];

        neighbors.forEach(n => {
            if (n.x >= 0 && n.x < w && n.y >= 0 && n.y < h) {
                const nOffset = n.y * w + n.x;
                if (!visited[nOffset]) {
                    const nIdx = nOffset * 4;
                    if (isBackground(nIdx)) {
                        visited[nOffset] = 1;
                        queue.push(n);
                    }
                }
            }
        });
    }

    scratchCtx.putImageData(imageData, 0, 0);

    // Convert back to image
    const newImg = new Image();
    newImg.src = scratchCanvas.toDataURL();
    return newImg;
}

function resizeCanvas() {
    width = canvas.parentElement.clientWidth;
    height = canvas.parentElement.clientHeight;
    // Handle High DPI
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    // Bounds check immediately to prevent items stuck outside
    if (items.length > 0) {
        items.forEach(item => {
            item.x = Math.min(Math.max(item.x, CONFIG.collisionRadius), width - CONFIG.collisionRadius);
            item.y = Math.min(Math.max(item.y, CONFIG.collisionRadius), height - CONFIG.collisionRadius);
        });
    }
}

function applyTheme(theme) {
    document.body.classList.remove('light-theme', 'dark-theme');
    if (theme === 'light') document.body.classList.add('light-theme');
    if (theme === 'dark') document.body.classList.add('dark-theme');
}

// --- Game Logic ---

class Item {
    constructor() {
        this.radius = CONFIG.collisionRadius;
        this.type = Math.floor(Math.random() * 3);

        // Random Position (respecting bounds)
        this.x = Math.random() * (width - 2 * this.radius) + this.radius;
        this.y = Math.random() * (height - 2 * this.radius) + this.radius;

        // Random Direction
        const angle = Math.random() * Math.PI * 2;
        const speed = (CONFIG.speedMultiplier * 0.5) + 0.5;
        this.vx = Math.cos(angle) * speed;
        this.vy = Math.sin(angle) * speed;

        // Cooldown to prevent double-processing collisions
        this.cooldown = 0;
    }

    draw() {
        const img = ASSETS[this.type].img;
        if (img) {
            // Draw centered
            const size = CONFIG.iconSize;
            ctx.drawImage(img, this.x - size / 2, this.y - size / 2, size, size);
        } else {
            // Fallback
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
            ctx.fillStyle = this.getColor();
            ctx.fill();
        }
    }

    getColor() {
        switch (this.type) {
            case TYPES.ROCK: return '#888';
            case TYPES.PAPER: return '#eee';
            case TYPES.SCISSORS: return '#f00';
        }
    }

    move() {
        this.x += this.vx;
        this.y += this.vy;

        // Wall Bouncing
        if (this.x - this.radius < 0) {
            this.x = this.radius;
            this.vx *= -1;
        } else if (this.x + this.radius > width) {
            this.x = width - this.radius;
            this.vx *= -1;
        }

        if (this.y - this.radius < 0) {
            this.y = this.radius;
            this.vy *= -1;
        } else if (this.y + this.radius > height) {
            this.y = height - this.radius;
            this.vy *= -1;
        }

        if (this.cooldown > 0) this.cooldown--;
    }
}

function startSimulation() {
    isRunning = true;
    items = [];
    CONFIG.count = parseInt(countInput.value);
    CONFIG.speedMultiplier = parseInt(speedInput.value);

    for (let i = 0; i < CONFIG.count; i++) {
        items.push(new Item());
    }

    if (animationId) cancelAnimationFrame(animationId);
    loop();
}

function loop() {
    if (!isRunning) return;

    ctx.clearRect(0, 0, width, height);

    // Move & Wall Collisions
    items.forEach(item => {
        item.move();
    });

    // Object Collisions
    // Naive O(N^2) check. Given N <= 200, this is negligible logic time (40k checks max).
    for (let i = 0; i < items.length; i++) {
        for (let j = i + 1; j < items.length; j++) {
            checkCollision(items[i], items[j]);
        }
    }

    // Draw
    items.forEach(item => item.draw());

    // Stats & End Condition
    updateStats();

    animationId = requestAnimationFrame(loop);
}

function checkCollision(p1, p2) {
    const dx = p2.x - p1.x;
    const dy = p2.y - p1.y;
    const dist = Math.sqrt(dx * dx + dy * dy);

    if (dist < p1.radius + p2.radius) {
        // Collision Detected

        // 1. Resolve Overlap (push apart)
        const overlap = (p1.radius + p2.radius - dist) / 2;
        const nx = dx / dist; // Normal X
        const ny = dy / dist; // Normal Y

        p1.x -= nx * overlap;
        p1.y -= ny * overlap;
        p2.x += nx * overlap;
        p2.y += ny * overlap;

        // 2. Resolve Velocity (Elastic Collision)
        // Normal component of velocities
        const v1n = p1.vx * nx + p1.vy * ny;
        const v2n = p2.vx * nx + p2.vy * ny;

        // Tangent component (unchanged)
        const tx = -ny;
        const ty = nx;
        const v1t = p1.vx * tx + p1.vy * ty;
        const v2t = p2.vx * tx + p2.vy * ty;

        // New normal velocities (swap for equal mass elastic)
        const v1nFinal = v2n;
        const v2nFinal = v1n;

        // Convert back to x,y
        p1.vx = v1nFinal * nx + v1t * tx;
        p1.vy = v1nFinal * ny + v1t * ty;
        p2.vx = v2nFinal * nx + v2t * tx;
        p2.vy = v2nFinal * ny + v2t * ty;

        // 3. Apply Game Rules (only if cooldown allows to prevent rapid fluttering)
        // Actually, simple type swap is fine.
        if (p1.type !== p2.type) {
            // p1 beats p2?
            if (RULES[p1.type] === p2.type) {
                p2.type = p1.type;
            }
            // p2 beats p1?
            else if (RULES[p2.type] === p1.type) {
                p1.type = p2.type;
            }
        }
    }
}

function updateStats() {
    let counts = { [TYPES.ROCK]: 0, [TYPES.PAPER]: 0, [TYPES.SCISSORS]: 0 };
    items.forEach(item => counts[item.type]++);

    stats.rock.textContent = `Rock: ${counts[TYPES.ROCK]}`;
    stats.paper.textContent = `Paper: ${counts[TYPES.PAPER]}`;
    stats.scissors.textContent = `Scissors: ${counts[TYPES.SCISSORS]}`;

    // End Condition
    const activeTypes = Object.values(counts).filter(c => c > 0).length;
    if (activeTypes === 1 && items.length > 0) {
        // Game Over - Stop Simulation
        isRunning = false;

        // Draw one last frame to show final state clearly
        ctx.clearRect(0, 0, width, height);
        items.forEach(item => item.draw());

        // Overlay?
        ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
        ctx.fillRect(0, 0, width, height);

        ctx.fillStyle = '#fff';
        ctx.font = 'bold 48px sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';

        const winnerType = items[0].type;
        let winnerText = "DRAW";
        if (winnerType === TYPES.ROCK) winnerText = "ROCK WINS!";
        if (winnerType === TYPES.PAPER) winnerText = "PAPER WINS!";
        if (winnerType === TYPES.SCISSORS) winnerText = "SCISSORS WINS!";

        ctx.fillText(winnerText, width / 2, height / 2);
    }
}

// Start
init();
