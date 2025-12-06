/**
 * Rock Paper Scissors Simulator
 */

// --- Configuration & State ---
const CONFIG = {
    count: 20,
    speedMultiplier: 5,
    iconSize: 48, // Size in pixels
    collisionRadius: 24, // Roughly half icon size
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

    // Load Images
    await Promise.all(Object.values(ASSETS).map(asset => {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.src = asset.src;
            img.onload = () => {
                asset.img = img;
                resolve();
            };
            img.onerror = reject;
        });
    }));

    // Check System Theme
    applyTheme(themeSelect.value);

    // Event Listeners
    window.addEventListener('resize', resizeCanvas);
    restartBtn.addEventListener('click', startSimulation);

    countInput.addEventListener('change', () => {
        let val = parseInt(countInput.value);
        if (val < 2) val = 2;
        if (val > 200) val = 200; // Cap at 200 for performance/sanity
        countInput.value = val;
        CONFIG.count = val;
    });

    speedInput.addEventListener('input', () => {
        CONFIG.speedMultiplier = parseInt(speedInput.value);
        speedValue.textContent = CONFIG.speedMultiplier;
        // Update velocities of existing items to match new speed scalar? 
        // Or just let it apply to new items/bounce? 
        // User asked "adjust speed of movement". 
        // Best approach: normalize current velocity and re-scale.
        updateSpeed();
    });

    themeSelect.addEventListener('change', (e) => applyTheme(e.target.value));

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
