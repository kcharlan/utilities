# Utilities Repo: Gap Analysis & Opportunity Map

*Generated 2026-03-08*

---

## Your Builder Profile

After reviewing all ~40 projects, here's the pattern:

**Domains:** Personal finance (dominant), LLM/AI tooling, media processing, developer tools, self-hosted infrastructure, browser games.

**Architecture preferences:** Self-bootstrapping Python with embedded React SPAs (FastAPI + CDN-loaded React 18 + Tailwind). Single-file HTML/JS for lightweight apps. Docker for infrastructure. Zero-setup, localhost-only, no cloud lock-in.

**What you value:** Data sovereignty, export-everything, graceful degradation, dark mode, CLI + web UI hybrids, professional-grade polish.

**Tech stack:** Python (FastAPI, Streamlit), vanilla JS, Zsh, SQLite, YAML/CSV/Parquet, Docker. macOS-native where needed.

---

## Part 1: Gaps Where Existing Tools Are the Right Answer

These are mature, free/cheap tools that align with your local-first philosophy. Building your own would be reinventing the wheel.

### Tier 1: Strongly Recommended

**Paperless-ngx** (free, Docker) -- [github.com/paperless-ngx/paperless-ngx](https://github.com/paperless-ngx/paperless-ngx)

You said everything has a digital footprint -- credit card charges, PDF invoices. Paperless-ngx watches a folder (or email inbox), OCRs incoming documents, auto-tags and auto-files them, and makes everything full-text searchable. Fits your Docker stack pattern. You have `docpipe` for ad-hoc conversion and `pdf-split` for chunking, but nothing providing a persistent, searchable document archive. If you install one thing from this analysis, this is probably it.

**Portfolio Performance** (free, Java desktop) -- [portfolio-performance.info](https://www.portfolio-performance.info/en/)

Offline portfolio tracker. True Time-Weighted Return, IRR, dividend tracking, Fidelity CSV import. No cloud, no subscription. Covers the investment tracking gap without duplicating what Moneydance already does for day-to-day ledger work.

**Promptfoo** (free, CLI + browser UI) -- [promptfoo.dev](https://www.promptfoo.dev/)

Systematic prompt testing across models. Config-driven test cases, side-by-side comparison, red-teaming. Self-hostable. Fills the gap between routerview (cost analytics) and llm_proxy (provider bridging) -- neither of which addresses prompt quality evaluation.

### Tier 2: Practical Docker Additions

**Uptime Kuma** (free, Docker) -- [github.com/louislam/uptime-kuma](https://github.com/louislam/uptime-kuma)

Monitors your five Docker stacks (actual-data, excalidraw, llm_collector, mermaid, webserver). Alerts when something goes down. Single container, 5-minute setup. Not exciting, but practical.

**changedetection.io** (free, Docker) -- [github.com/dgtlmoon/changedetection.io](https://github.com/dgtlmoon/changedetection.io)

Web page change monitoring with alerts. Useful for price drops, documentation changes, release announcements for tools you depend on. Nice to have, not critical.

### Tier 3: Available but Lower Priority

**czkawka** (free, Rust) -- File deduplication with similar-image detection. [github.com/qarmin/czkawka](https://github.com/qarmin/czkawka)

**ncdu** (free, `brew install ncdu`) -- Terminal disk usage visualization. One install away.

**Linkding** (free, Docker) -- Minimal self-hosted bookmark manager. [github.com/sissbruecker/linkding](https://github.com/sissbruecker/linkding)

---

## Part 2: Worth Building Yourself

These have no good existing fit, integrate with your specific ecosystem, or offer genuine learning value.

### 1. Git Multi-Repo Dashboard

**What it would do:** Scan a directory of repos (or this monorepo's top-level projects), show: last commit per project, uncommitted changes, stale branches, dependency staleness (outdated pip/npm packages), lines-of-code trends over time. Treemap or heatmap of activity.

**Why build it:**
- `dloc` only does daily line counts for one repo; this is the "fleet view"
- With 40+ projects, knowing what's stale or drifting is genuinely useful
- Nothing open source does "scan a directory of heterogeneous projects and give me health metrics"
- Natural fit for your embedded React SPA pattern

**Effort:** 2-3 days. **Daily utility:** High.

### 2. Project Scaffolder

**What it would do:** Generate new projects from your established patterns. Pick a template (FastAPI+React SPA, single-file HTML, Python CLI, Docker service), answer a few questions (name, default port, deps), get a working skeleton with your self-bootstrapping pattern, standard structure, .gitignore, README stub.

**Why build it:**
- You've built 40+ projects and refined strong conventions, but starting new ones still means copying/gutting an existing one
- CLAUDE.md documents these patterns in prose; a scaffolder makes them executable
- Cookiecutter/copier exist but are generic -- yours encodes the CDN-loaded React stack, the `~/.toolname_venv` convention, the argparse-with-port-scanning pattern
- Small project, big ROI on every new project

**Effort:** 1 day. **Daily utility:** Medium (high per-use, low frequency).

### 3. Moneydance Export Analyzer

**What it would do:** Take CSV output from `md-json` (which already flattens exports with account hierarchy) and run analytics: spending trends by category, month-over-month deltas, anomaly detection (unexpected charges, duplicate transactions, subscription price creep), seasonal patterns, "financial pulse" summary.

**Why build it:**
- You have a deep Moneydance pipeline (md-json, prep_ledger, qif_div_converter, md-autotax, tax2) but it's all about moving data in/out. Nothing analyzes the data itself.
- Moneydance shows balances and registers but isn't great at cross-account trend analysis or anomaly detection
- Sits naturally at the end of your existing pipeline -- md-json already does the hard flattening work
- Learning: pandas time-series, anomaly detection (z-score/IQR), charting

**Effort:** 2-3 days. **Daily utility:** Medium (monthly review cadence).

### 4. LLM API Cost Guard

**What it would do:** Lightweight proxy layer (could integrate with `llm_proxy`) that enforces configurable spend limits: per-hour, per-day, per-month, per-project. Blocks requests or auto-downgrades to a cheaper model when thresholds are hit.

**Why build it:**
- Usage is bursty now -- that's exactly when you want a guard rail, not a forecast
- Different from routerview (read-only analytics) -- this is active prevention
- OpenRouter has account-wide limits but not per-project or per-time-window
- Could be a thin layer added to llm_proxy rather than a separate project

**Effort:** 1-2 days. **Daily utility:** High during heavy usage periods.

### 5. Cross-Project Semantic Search

**What it would do:** Index your entire utilities repo (code, READMEs, comments) into a local vector store. Search by meaning: "How did I handle pagination?" returns relevant code from editdb, routerview, jtree. "Where do I parse CSV?" finds prep_ledger, md-json, apple-health-extract.

**Why build it:**
- With 40+ projects, you've solved many problems before. `rg` finds exact text but can't find conceptually similar code
- You already have LLM infrastructure (routerview, llm_proxy); embeddings are cheap
- Learning: vector databases (ChromaDB or LanceDB, both local/SQLite-backed), embedding models, retrieval patterns
- Practical daily value: "I know I solved this before, somewhere" becomes a searchable query

**Effort:** 3-4 days. **Daily utility:** Medium-high.

---

## Summary Matrix

| Gap | Action | Effort | Utility | Notes |
|-----|--------|--------|---------|-------|
| Document archive | Install Paperless-ngx | 30 min | High | Searchable invoice/PDF history |
| Portfolio tracking | Install Portfolio Performance | 30 min | Medium | Offline, handles Fidelity CSV |
| Prompt eval | Install Promptfoo | 30 min | Medium | Complements routerview |
| Docker monitoring | Install Uptime Kuma | 15 min | Medium | Alerts when services drop |
| Git multi-repo dashboard | **Build** | 2-3 days | High | Fleet view of 40+ projects |
| Project scaffolder | **Build** | 1 day | Medium | Encodes your patterns as templates |
| Moneydance analyzer | **Build** | 2-3 days | Medium | Spending trends, anomaly detection |
| LLM API cost guard | **Build** | 1-2 days | High | Active spend limits, not just analytics |
| Semantic code search | **Build** | 3-4 days | Med-High | "I solved this before" retrieval |
