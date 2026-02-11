# Code Audit Report: Multibody Gravity Simulator
**Date:** 2026-02-11  
**Project:** multibody_sim  
**File Audited:** index.html (3,789 lines)  
**Audit Framework:** Code_Audit_Template.md  

---

## Assumptions

1. **Target Environment:** Modern browsers (Chrome, Firefox, Safari) supporting ES6+ and Canvas 2D
2. **Public API:** None (single-file application; all code is internal)
3. **Performance Target:** Smooth 60 FPS for N ≤ 20 bodies, acceptable for N ≤ 50
4. **Language Conventions:** JavaScript ES6+ with JSDoc type annotations (no runtime type checking)
5. **Deployment Model:** Single HTML file (no build system, direct browser execution)
6. **Testing Strategy:** Manual browser testing (no automated test suite exists or is planned)

---

## Executive Summary

The multibody_sim project is a well-crafted gravity simulator with **solid fundamentals** and **good code organization** for a single-file application. The audit identified **15 findings** across correctness, best practices, readability, and performance categories. Most issues are **Low to Medium severity** with clear, incremental fixes available.

**Key Strengths:**
- Correct physics implementation (leapfrog integrator, momentum conservation)
- Comprehensive error handling for file I/O and numeric safety
- Good separation of concerns despite single-file constraint
- Thoughtful user experience (camera tracking, merge effects, keyboard shortcuts)

**Key Opportunities:**
- Add safety guards against numeric overflow/underflow in physics calculations
- Improve modularity through function extraction (some functions exceed 100 lines)
- Add JSDoc comments for complex algorithms (camera focus, lead prediction)
- Optimize O(N²) collision detection with early exit conditions

---

## Rules/Standards Violated or Worth Improving

### Correctness & Safety
1. **Numeric Stability:** Potential for `Infinity` or `NaN` propagation in physics calculations without explicit guards
2. **Division by Zero:** Some distance calculations use `1/Math.sqrt(d2)` without ensuring `d2 > epsilon`
3. **Array Bounds:** Loop mutations during collision resolution could skip pairs (j reset pattern)

### Best Practices & Maintainability
4. **Function Length:** Several functions exceed 100 lines (testability, cognitive load)
5. **Magic Numbers:** Hardcoded constants scattered throughout (e.g., `1.4`, `0.72`, `2.5`)
6. **Error Handling:** Silent failures in some edge cases (e.g., camera subject validation)
7. **Type Safety:** JSDoc annotations incomplete for complex return types

### Readability
8. **Complex Conditionals:** Deeply nested ternaries in collision resolution (lines 1118-1129)
9. **Function Naming:** Some names lack clarity (`v.perp`, `effectiveAutoCamera`)
10. **Code Comments:** Minimal inline documentation for non-obvious algorithms

### Performance
11. **O(N²) Collision Detection:** No spatial partitioning or broad-phase optimization
12. **Redundant Calculations:** `effectiveMass()` called multiple times per body per frame
13. **String Concatenation:** Repeated `colorStyle()` calls in hot rendering loop
14. **Trail Array Operations:** `splice(0, length - max)` triggers memory reallocation

---

## Findings

### Finding 1: Numeric Overflow Risk in Acceleration Calculation
**Severity:** Medium  
**Category:** Correctness & Safety  
**Evidence:** index.html:1022-1048

```javascript
const d2 = dx * dx + dy * dy + eps2;
const invD = 1 / Math.sqrt(d2);  // Can produce Infinity if d2 is tiny
const invD3 = invD * invD * invD;
const factor = state.G * invD3;
```

**Why it matters:**  
If two bodies overlap precisely (pos.x/y identical), `d2 = eps2` which is safe. However, if `eps2 = 0` (user sets epsilon to 0), `invD` becomes `Infinity`, propagating to accelerations and causing `NaN` positions in the next timestep.

**Recommended fix:**  
Add a minimum epsilon floor and clamp `invD3`:
```javascript
const eps2 = Math.max(1e-6, state.epsilon * state.epsilon);
const invD = 1 / Math.sqrt(d2);
const invD3 = Math.min(invD * invD * invD, 1e12); // Cap extreme forces
```

**Effort:** S  
**Risk:** Low (purely additive safety guard)  
**Acceptance criteria:**  
- Set epsilon to 0 in UI
- Create two overlapping bodies with identical positions
- Simulation should remain stable (no NaN positions)

---

### Finding 2: Collision Loop Index Reset Can Skip Pairs
**Severity:** Medium  
**Category:** Correctness & Safety  
**Evidence:** index.html:1096-1184

```javascript
for (let i = 0; i < state.bodies.length; i += 1) {
  for (let j = i + 1; j < state.bodies.length; j += 1) {
    // ...merge logic...
    state.bodies.splice(j, 1);
    state.bodies.splice(i, 1, merged);
    mergedAny = true;
    mergedCount += 1;
    j = i;  // Reset j to re-check i against all remaining bodies
  }
}
```

**Why it matters:**  
The pattern `j = i` after merging is **correct** but subtle. If body[i] merges with body[j], the merged body replaces index `i`, and `j` resets to `i`. However, the outer loop `i++` continues, which could skip checking if the merged body at index `i` should merge with earlier bodies. In practice, this is unlikely to cause issues because bodies are processed in order, but it's a subtle invariant.

**Recommended fix:**  
Add a comment explaining the index reset logic:
```javascript
// Reset j to re-check merged body at index i against remaining bodies.
// The outer loop i++ ensures we eventually process all pairs.
j = i;
```

Alternatively, use a while loop with manual index management for clarity.

**Effort:** S  
**Risk:** Low (documentation-only change)  
**Acceptance criteria:**  
- Code review confirms intent is clear
- Edge case: create 3 bodies in a tight triangle, all should merge into one

---

### Finding 3: `hasInvalidBodyState()` Checks After Mutation
**Severity:** Low  
**Category:** Correctness & Safety  
**Evidence:** index.html:2032-2047, 3128-3137

```javascript
function tryHandleSafety() {
  if (!hasInvalidBodyState()) return;
  // ... restart or pause ...
}
```

**Why it matters:**  
The safety check runs **after** physics step completes, meaning one bad frame's NaN state has already corrupted the simulation. If a body has `NaN` positions, the next render will fail to draw it correctly, and the camera may jump erratically.

**Recommended fix:**  
Add an early-exit check **during** the physics step:
```javascript
function physicsStep(dt) {
  // ... leapfrog integration ...
  
  // Safety check after acceleration update
  for (const b of bodies) {
    if (!Number.isFinite(b.vel.x) || !Number.isFinite(b.vel.y)) {
      console.warn('Invalid velocity detected, aborting physics step');
      return; // Abort this step, rely on tryHandleSafety() to recover
    }
  }
  
  // ... continue with position update ...
}
```

**Effort:** S  
**Risk:** Low (defensive programming)  
**Acceptance criteria:**  
- Inject a NaN velocity manually via console: `state.bodies[0].vel.x = NaN`
- Next frame should trigger safety recovery without visual glitch

---

### Finding 4: Large Function - `generateScreensaverBodies()`
**Severity:** Low  
**Category:** Best Practices & Maintainability  
**Evidence:** index.html:2269-2369 (101 lines)

**Why it matters:**  
This function handles:
1. Random body generation with placement attempts
2. Velocity assignment
3. Validation (collision-free start, interaction potential)
4. Fallback logic
5. State initialization (sim time, camera, trails, etc.)

This violates the Single Responsibility Principle and makes unit testing impossible.

**Recommended fix:**  
Extract helper functions:
```javascript
function tryPlaceBodies(n, radius, singularityConfig) {
  // Returns {bodies, success}
}

function validateStartConditions(bodies, minLookahead, horizonSec) {
  // Returns {validStart, lowBodyInteresting}
}

function initializeScreensaverState() {
  state.running = true;
  state.simTime = 0;
  // ... all state resets ...
}

function generateScreensaverBodies(n = state.screensaverN) {
  const {bodies, success} = tryPlaceBodies(n, 200, {...});
  if (success && validateStartConditions(bodies, 20, 80)) {
    state.bodies = bodies;
    assignDiverseColors(state.bodies);
    assignOrbitishVelocities(0.9);
    initializeScreensaverState();
  } else {
    // Fallback...
  }
}
```

**Effort:** M  
**Risk:** Low (pure refactor, no logic change)  
**Acceptance criteria:**  
- Generate screensaver 10 times, verify all starts are valid
- Test with N=2, N=20, N=50
- Verify fallback message appears when placement fails

---

### Finding 5: Magic Numbers in Camera and Physics Code
**Severity:** Low  
**Category:** Best Practices & Maintainability  
**Evidence:** Throughout index.html (e.g., lines 1372, 1377, 2104, 2114)

Examples:
- `1.15` padding factor (line 1377, 1506)
- `2.5` ratio threshold for interaction (line 2262)
- `0.72`, `1.62`, `1.42` in singularity rendering (lines 1765-1775)
- `0.25` in near-pair detection (line 1566)

**Why it matters:**  
Magic numbers obscure intent and make tuning difficult. If someone wants to adjust "how tight the camera envelope is around near-pairs," they must search the entire file.

**Recommended fix:**  
Move to `cfg` object:
```javascript
const cfg = {
  // ... existing ...
  nearPairEnvelopePadding: 1.15,
  interactionRatioThreshold: 2.5,
  singularityGlowPhaseSpeed: 0.72,
  // ...
};
```

Then use `cfg.nearPairEnvelopePadding` instead of `1.15`.

**Effort:** M (search-and-replace, test thoroughly)  
**Risk:** Low  
**Acceptance criteria:**  
- All magic numbers >1.0 or <1.0 with unclear meaning are named
- Simulation behavior identical before/after
- Config reference document updated

---

### Finding 6: Silent Camera Subject Validation Failures
**Severity:** Low  
**Category:** Best Practices & Maintainability  
**Evidence:** index.html:1243-1250, 2600-2619

```javascript
function enforceValidCameraSubject() {
  state.cameraSubjectMode = normalizeCameraSubjectMode(state.cameraSubjectMode);
  if (state.cameraSubjectMode !== 'object') return;
  if (!hasBodyWithId(state.cameraSubjectBodyId)) {
    state.cameraSubjectMode = 'auto';  // Silently reset
    state.cameraSubjectBodyId = null;
  }
}
```

**Why it matters:**  
If a user is following a specific body and it merges/deletes, the camera silently switches to auto mode with no feedback. This can be confusing.

**Recommended fix:**  
Set a transient warning message:
```javascript
if (!hasBodyWithId(state.cameraSubjectBodyId)) {
  state.warningText = `Body ${state.cameraSubjectBodyId} no longer exists; camera set to Auto.`;
  state.cameraSubjectMode = 'auto';
  state.cameraSubjectBodyId = null;
}
```

**Effort:** S  
**Risk:** Low  
**Acceptance criteria:**  
- Follow a body, then delete it via merge or UI
- Warning message appears in UI
- Camera switches to Auto

---

### Finding 7: Incomplete JSDoc for Complex Return Types
**Severity:** Low  
**Category:** Best Practices & Maintainability  
**Evidence:** index.html:1289-1303, 1306-1384

Functions like `nearPairs()`, `focusedNearPairBounds()` return complex objects but lack type documentation:
```javascript
function nearPairs(multiplier = cfg.nearPairLockMultiplier) {
  /** @type {{i:number,j:number,dist:number}[]} */  // Good!
  const pairs = [];
  // ...
  return pairs;
}

function focusedNearPairBounds(multiplier) {
  // No JSDoc return type
  return { minX, minY, maxX, maxY };  // or null
}
```

**Why it matters:**  
Callers cannot rely on IDE autocomplete to know what fields are available. This increases cognitive load.

**Recommended fix:**  
Add JSDoc return types:
```javascript
/**
 * @param {number} [multiplier]
 * @returns {{minX:number,minY:number,maxX:number,maxY:number}|null}
 */
function focusedNearPairBounds(multiplier = cfg.nearPairLockMultiplier) {
  // ...
}
```

**Effort:** S  
**Risk:** Low (documentation-only)  
**Acceptance criteria:**  
- All functions returning objects/arrays have JSDoc `@returns`
- VSCode autocomplete works for returned object fields

---

### Finding 8: Deeply Nested Ternary in Collision Resolution
**Severity:** Low  
**Category:** Readability  
**Evidence:** index.html:1118-1129

```javascript
const dominantSource =
  em1 > em2
    ? b1
    : em2 > em1
      ? b2
      : b1.mass > b2.mass
        ? b1
        : b2.mass > b1.mass
          ? b2
          : b1.id <= b2.id
            ? b1
            : b2;
```

**Why it matters:**  
This 6-level ternary is hard to debug and understand. The logic is: "pick the body with higher effective mass, breaking ties by actual mass, then by ID."

**Recommended fix:**  
Extract to a helper function:
```javascript
function selectDominantBody(b1, b2, em1, em2) {
  if (em1 > em2) return b1;
  if (em2 > em1) return b2;
  if (b1.mass > b2.mass) return b1;
  if (b2.mass > b1.mass) return b2;
  return b1.id <= b2.id ? b1 : b2;
}

const dominantSource = selectDominantBody(b1, b2, em1, em2);
```

**Effort:** S  
**Risk:** Low  
**Acceptance criteria:**  
- Create two singularities with identical effective mass
- Verify merge preserves lower ID
- Create regular + singularity with same effective mass, verify singularity wins

---

### Finding 9: `v.perp()` and `v.norm()` Lack Descriptive Names
**Severity:** Low  
**Category:** Readability  
**Evidence:** index.html:735-745

```javascript
const v = {
  add: (a, b) => ({ x: a.x + b.x, y: a.y + b.y }),
  sub: (a, b) => ({ x: a.x - b.x, y: a.y - b.y }),
  scale: (a, s) => ({ x: a.x * s, y: a.y * s }),
  len: (a) => Math.hypot(a.x, a.y),
  norm: (a) => { /* normalize */ },
  perp: (a) => ({ x: -a.y, y: a.x })  // perpendicular (90° CCW rotation)
};
```

**Why it matters:**  
`perp` is a math term but not universally known. A reader might confuse it with "perspective" or "perpendicular to what?"

**Recommended fix:**  
Add JSDoc comments:
```javascript
const v = {
  /** Returns vector perpendicular to `a` (90° counter-clockwise) */
  perp: (a) => ({ x: -a.y, y: a.x }),
  
  /** Returns normalized (unit-length) vector in direction of `a` */
  norm: (a) => { /* ... */ },
};
```

Or rename: `perpendicular`, `normalize`.

**Effort:** S  
**Risk:** Low (documentation-only or simple rename)  
**Acceptance criteria:**  
- Developer unfamiliar with codebase can understand vector operations without external reference

---

### Finding 10: Missing High-Level Comments for Complex Algorithms
**Severity:** Low  
**Category:** Readability  
**Evidence:** index.html:1306-1384 (near-pair focus), 2466-2517 (lead prediction)

**Why it matters:**  
The near-pair camera focus algorithm builds connected components from proximity pairs, scores clusters, and selects the "strongest" interaction. This is non-obvious and has no introductory comment.

**Recommended fix:**  
Add block comments:
```javascript
/**
 * Focuses camera on the most significant cluster of near-interacting bodies.
 * Algorithm:
 * 1. Find all body pairs within `multiplier * max(radius)` distance
 * 2. Build connected components (graph of near-pair links)
 * 3. Score each component by interaction strength (inverse distance weighted)
 * 4. Return bounding box of highest-scoring component
 * This prevents camera jitter during multi-body close encounters.
 */
function focusedNearPairBounds(multiplier = cfg.nearPairLockMultiplier) {
  // ...
}
```

**Effort:** S  
**Risk:** Low (documentation-only)  
**Acceptance criteria:**  
- All functions >50 lines or with non-trivial algorithms have block comments
- Comments explain "why" and high-level "how," not line-by-line "what"

---

### Finding 11: O(N²) Collision Detection Without Broad Phase
**Severity:** Low  
**Category:** Performance  
**Evidence:** index.html:1093-1192

```javascript
for (let i = 0; i < state.bodies.length; i += 1) {
  for (let j = i + 1; j < state.bodies.length; j += 1) {
    const b1 = state.bodies[i];
    const b2 = state.bodies[j];
    const dx = b2.pos.x - b1.pos.x;
    const dy = b2.pos.y - b1.pos.y;
    const dist = Math.hypot(dx, dy);
    if (dist < (b1.radius + b2.radius) * cfg.collisionFactor) {
      // Merge logic...
    }
  }
}
```

**Why it matters:**  
At N=50, this is 1,225 distance checks per physics step. At 120 steps/sec real-time, that's ~147k checks/sec. For N ≤ 50, this is acceptable, but there's low-hanging fruit: most pairs are far apart.

**Recommended fix:**  
Add a broad-phase bounding box check:
```javascript
// Compute AABB of all bodies
const bounds = boundsOfBodies();
const maxSpan = Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY);

for (let i = 0; i < state.bodies.length; i += 1) {
  for (let j = i + 1; j < state.bodies.length; j += 1) {
    const b1 = state.bodies[i];
    const b2 = state.bodies[j];
    
    // Broad-phase: skip if bodies are in opposite quadrants
    const dx = b2.pos.x - b1.pos.x;
    const dy = b2.pos.y - b1.pos.y;
    const maxDist = b1.radius + b2.radius;
    if (Math.abs(dx) > maxDist * 2 && Math.abs(dy) > maxDist * 2) {
      continue; // Too far apart in both axes
    }
    
    const dist = Math.hypot(dx, dy);
    if (dist < maxDist * cfg.collisionFactor) {
      // Merge...
    }
  }
}
```

**Effort:** S  
**Risk:** Low (early exit preserves correctness)  
**Acceptance criteria:**  
- N=50 simulation runs at 60 FPS without frame drops
- Collision detection still triggers correctly
- Benchmark: measure `resolveCollisions()` time before/after

---

### Finding 12: `effectiveMass()` Called Redundantly
**Severity:** Low  
**Category:** Performance  
**Evidence:** index.html:1028-1029, 1116-1117, 1198-1202

```javascript
// In updateAccelerations()
const massI = effectiveMass(bi);  // Called once per pair
const massJ = effectiveMass(bj);

// In resolveCollisions()
const em1 = effectiveMass(b1);  // Called again for same bodies
const em2 = effectiveMass(b2);
```

**Why it matters:**  
`effectiveMass()` recalculates the singularity mass formula (logarithm) every call. For N=50, this is called ~1,225 times/frame (acceleration) + ~1,225 times/frame (collision check) = ~2,450 calls/frame at 120 Hz = ~294k calls/sec.

**Recommended fix:**  
Cache effective mass on the body object:
```javascript
// When body is created or singularity flag changes:
body._cachedEffectiveMass = effectiveMass(body);

// Use cached value:
const massI = bi._cachedEffectiveMass || effectiveMass(bi);
```

Or compute once per frame in a pre-pass.

**Effort:** M (requires invalidation logic)  
**Risk:** Medium (cache invalidation bugs if mass changes)  
**Acceptance criteria:**  
- Profile shows `effectiveMass()` CPU time reduced by >90%
- Change singularity flag or mass during simulation, verify cache updates
- Benchmark: N=50, measure frame time before/after

---

### Finding 13: `colorStyle()` String Allocations in Render Loop
**Severity:** Low  
**Category:** Performance  
**Evidence:** index.html:880-882, 1631, 1650, 1666, 1708, 1713, 1727, etc.

```javascript
function colorStyle(color, alpha = 1) {
  return `rgba(${color.r}, ${color.g}, ${color.b}, ${alpha})`;
}

// Called in hot path:
ctx.strokeStyle = colorStyle(body.color, alpha);  // Every frame
```

**Why it matters:**  
String template literals allocate new strings every call. At N=50 with trails, this can be hundreds of allocations/frame, causing GC pressure.

**Recommended fix:**  
Cache common color strings:
```javascript
// Add to body:
body._cachedColorStyle = `rgb(${body.color.r}, ${body.color.g}, ${body.color.b})`;

// Use cached base + alpha suffix:
ctx.strokeStyle = body._cachedColorStyle.replace('rgb', 'rgba').replace(')', `, ${alpha})`);
```

Or use `ctx.globalAlpha` where possible.

**Effort:** M  
**Risk:** Low (visual parity verification needed)  
**Acceptance criteria:**  
- Profiler shows reduced string allocation in `render()`
- Visual appearance identical before/after
- Benchmark: N=50 with trails, measure GC pauses

---

### Finding 14: Trail `splice(0, length - max)` Triggers Reallocation
**Severity:** Low  
**Category:** Performance  
**Evidence:** index.html:2402-2404

```javascript
if (body.trail.length > trailLength) {
  body.trail.splice(0, body.trail.length - trailLength);
}
```

**Why it matters:**  
`splice(0, N)` removes the first N elements, shifting the entire array left. For a 300-element trail, this is O(300) per body per frame.

**Recommended fix:**  
Use a circular buffer or manual shift:
```javascript
// Option 1: Limit push
body.trail.push(point);
if (body.trail.length > trailLength) {
  body.trail.shift(); // Remove first element only
}

// Option 2: Circular buffer (more complex but O(1))
```

**Effort:** S (for shift), M (for circular buffer)  
**Risk:** Low  
**Acceptance criteria:**  
- Trail rendering visually identical
- Profiler shows reduced time in `recordTrails()`
- Benchmark: N=50, trail length 300, measure frame time

---

### Finding 15: No Test Coverage for Edge Cases
**Severity:** Low  
**Category:** Best Practices & Maintainability  
**Evidence:** No test files found

**Why it matters:**  
The project has:
- Complex collision resolution with singularity absorption rules
- Camera focus state machine (auto/full/follow)
- Save/load with version migration (v2 → v3)
- Screensaver spawn validation

These are prone to regressions during refactoring.

**Recommended fix:**  
Add Playwright smoke tests (project already has `@playwright/test` installed):
```javascript
// tests/smoke.spec.js
import { test, expect } from '@playwright/test';

test('screensaver generates 5 bodies', async ({ page }) => {
  await page.goto('http://127.0.0.1:4173/index.html');
  await page.waitForTimeout(1000);
  const bodyCount = await page.evaluate(() => state.bodies.length);
  expect(bodyCount).toBe(5);
});

test('user mode creates body on click', async ({ page }) => {
  await page.goto('http://127.0.0.1:4173/index.html');
  await page.selectOption('#modeSelect', 'user');
  await page.click('canvas', { position: { x: 500, y: 400 } });
  const bodyCount = await page.evaluate(() => state.bodies.length);
  expect(bodyCount).toBe(1);
});
```

**Effort:** M  
**Risk:** Low (testing infrastructure only)  
**Acceptance criteria:**  
- 10+ smoke tests covering: mode switching, collision, save/load, camera modes
- Tests run via `npm test`
- CI-ready (all tests pass in headless mode)

---

## Step-by-Step Fix Plan

### Phase 1: Critical Safety (Est. 2-3 hours)
**Prerequisite:** Create git branch `audit-fixes-safety`

1. **Finding 1: Add numeric safety guards**
   - File: index.html:1022-1048
   - Change: Add `eps2 = Math.max(1e-6, ...)`, clamp `invD3`
   - Test: Set epsilon=0, create overlapping bodies, verify no NaN
   - Command: Open index.html in browser, test manually
   - Stop: Simulation remains stable with epsilon=0

2. **Finding 3: Early exit in physics step**
   - File: index.html:1051-1091
   - Change: Add velocity sanity check after acceleration update
   - Test: Inject `state.bodies[0].vel.x = NaN` in console, verify recovery
   - Command: Browser console test
   - Stop: Safety message appears, no visual corruption

**Deliverable:** Commit safety fixes to branch

---

### Phase 2: Documentation & Readability (Est. 3-4 hours)

3. **Finding 7: Add JSDoc to complex functions**
   - Files: index.html:1289-1384, 2466-2517, 1194-1208
   - Change: Add `@returns` JSDoc to 10+ functions
   - Test: VSCode autocomplete works
   - Command: None (documentation-only)
   - Stop: All object-returning functions have types

4. **Finding 10: Add algorithm comments**
   - Files: index.html:1306-1384, 2466-2517, 2100-2154
   - Change: Add block comments to 5+ complex functions
   - Test: Code review by peer
   - Command: None
   - Stop: Each >50 line function has high-level comment

5. **Finding 9: Document vector helper functions**
   - File: index.html:735-745
   - Change: Add JSDoc to `v.perp()`, `v.norm()`
   - Test: None
   - Command: None
   - Stop: Vector operations have usage comments

**Deliverable:** Commit documentation improvements to branch

---

### Phase 3: Code Quality Refactors (Est. 4-6 hours)

6. **Finding 8: Extract dominant body selection**
   - File: index.html:1118-1129
   - Change: Create `selectDominantBody(b1, b2, em1, em2)` function
   - Test: Create singularity + regular body, verify merge preserves correct ID
   - Command: Manual browser test
   - Stop: Merge logic produces identical results

7. **Finding 2: Add collision loop comment**
   - File: index.html:1096-1184
   - Change: Add 2-line comment explaining `j = i` reset
   - Test: None
   - Command: None
   - Stop: Comment explains invariant

8. **Finding 4: Extract screensaver generation helpers** (OPTIONAL)
   - File: index.html:2269-2369
   - Change: Extract 3 functions: `tryPlaceBodies`, `validateStartConditions`, `initializeScreensaverState`
   - Test: Generate screensaver 20 times, verify success rate unchanged
   - Command: Browser test
   - Stop: All 20 attempts produce valid starts or fallback

**Deliverable:** Commit refactors to branch

---

### Phase 4: Performance Optimizations (Est. 5-7 hours)

9. **Finding 11: Add broad-phase collision check** (OPTIONAL)
   - File: index.html:1093-1192
   - Change: Add axis-aligned bounding box early exit
   - Test: N=50, verify all collisions still detected
   - Command: Browser profiler before/after
   - Stop: Frame time improves by >10%, no missed collisions

10. **Finding 14: Optimize trail array operations**
    - File: index.html:2402-2404
    - Change: Replace `splice(0, N)` with `shift()`
    - Test: Visual verification of trails
    - Command: Browser profiler
    - Stop: `recordTrails()` time reduced by >30%

11. **Finding 12: Cache effective mass** (OPTIONAL)
    - Files: index.html:815-820, 1028-1029
    - Change: Add `_cachedEffectiveMass` to body, invalidate on mass/singularity change
    - Test: Change singularity flag during simulation, verify cache updates
    - Command: Browser profiler
    - Stop: `effectiveMass()` CPU time reduced by >80%

12. **Finding 5: Move magic numbers to cfg object** (OPTIONAL)
    - Files: Throughout index.html
    - Change: Add 10+ named constants to `cfg` at line 603
    - Test: Regression test all modes
    - Command: Full manual smoke test
    - Stop: Simulation behavior unchanged

**Deliverable:** Commit optimizations to branch

---

### Phase 5: Long-Term Improvements (Est. 8-12 hours, OPTIONAL)

13. **Finding 6: Add camera subject warnings**
    - File: index.html:1243-1250
    - Change: Set `state.warningText` when subject becomes invalid
    - Test: Follow body, delete it, verify warning appears
    - Command: Manual test
    - Stop: Warning message displays in UI

14. **Finding 15: Add Playwright smoke tests**
    - New file: tests/smoke.spec.js
    - Change: Add 10 tests covering modes, collision, save/load
    - Test: `npm test`
    - Command: `npx playwright test`
    - Stop: All tests pass

15. **Finding 13: Cache color strings** (OPTIONAL, ADVANCED)
    - Files: index.html:880-882, rendering code
    - Change: Cache `_cachedColorStyle` on bodies
    - Test: Visual parity check
    - Command: Browser profiler, GC metrics
    - Stop: GC pauses reduced, visuals unchanged

**Deliverable:** Commit long-term fixes to branch, merge to main

---

## Summary of Effort and Risk

| Finding | Severity | Effort | Risk | Priority |
|---------|----------|--------|------|----------|
| 1. Numeric overflow guards | Medium | S | Low | Phase 1 |
| 2. Collision loop comment | Medium | S | Low | Phase 3 |
| 3. Early physics safety check | Low | S | Low | Phase 1 |
| 4. Extract screensaver helpers | Low | M | Low | Phase 3 (opt) |
| 5. Move magic numbers | Low | M | Low | Phase 4 (opt) |
| 6. Camera subject warnings | Low | S | Low | Phase 5 (opt) |
| 7. Add JSDoc types | Low | S | Low | Phase 2 |
| 8. Extract dominant body | Low | S | Low | Phase 3 |
| 9. Document vector helpers | Low | S | Low | Phase 2 |
| 10. Algorithm comments | Low | S | Low | Phase 2 |
| 11. Broad-phase collision | Low | S | Low | Phase 4 (opt) |
| 12. Cache effective mass | Low | M | Med | Phase 4 (opt) |
| 13. Cache color strings | Low | M | Low | Phase 5 (opt) |
| 14. Optimize trail arrays | Low | S | Low | Phase 4 |
| 15. Add smoke tests | Low | M | Low | Phase 5 (opt) |

**Total Estimated Effort:** 6-10 hours (required), 16-26 hours (with optional items)  
**Overall Risk:** Low (all changes are incremental and testable)

---

## Validation Commands

```bash
# Syntax check
awk '/<script[^>]*>/{flag=1;next}/<\/script>/{flag=0}flag' index.html > /tmp/check.js
node --check /tmp/check.js

# Local server
npx http-server -p 4173 -c-1
# Open http://127.0.0.1:4173/index.html

# Run tests (after Phase 5)
npm test
```

---

## Conclusion

The multibody_sim project is **well-architected and maintainable** for a single-file application. The identified issues are **minor and incremental**, with clear fixes that preserve the existing design philosophy. Prioritizing **Phase 1 (safety)** and **Phase 2 (documentation)** will yield immediate value with minimal risk. Performance optimizations (Phase 4) can be deferred until profiling shows actual bottlenecks.

**Recommended Next Steps:**
1. Implement Phase 1 (safety) immediately
2. Review Phase 2 (documentation) with team/stakeholders
3. Consider Phase 3 (refactors) if planning future feature work
4. Defer Phase 4/5 unless performance issues emerge in production

**Overall Code Quality:** B+ (strong fundamentals, room for polish)
