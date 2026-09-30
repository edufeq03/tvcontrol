# Changelog

All notable changes to the IgnoControl project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-09-30

### 🚀 Production Architecture & Performance (Sprint 4 & 5)
- **Production WSGI Server**: Migrated default server to `waitress` with multi-threaded request processing, removing development server warnings and boosting concurrency.
- **Persistent Sleep Timer**: Sleep timer state is now saved to disk (`~/.config/ignocontrol/timer_state.json`) and automatically restored upon service restarts.
- **Client Resilience & Heartbeat**: Real-time `/ping` heartbeat monitoring with visual live badge (`Online` / `Offline (Reconnecting)`) and reconnection toast notifications.
- **Offline PWA Support**: Implemented Service Worker (`sw.js`) precaching CSS, JS, icon, and manifest for 100% offline shell availability.
- **Native Typography Stack**: Replaced external Google Fonts with native system font stack for instant 0ms FCP and full network independence.
- **Security Policy & Documentation**: Added comprehensive `SECURITY.md` threat model, updated English and Portuguese READMEs, and pinned dependencies in `requirements.txt`.

### 🏗️ Modular Architecture & CI (Sprint 3)
- **Package Decomposition**: Modularized `remote.py` monolith into the `tvcontrol/` package:
  - `tvcontrol/app.py`: Application factory with security middleware.
  - `tvcontrol/config.py`: Strict schema validation, caching, and custom exceptions.
  - `tvcontrol/auth.py`: Constant-time authentication, rate limiter, and pairing manager.
  - `tvcontrol/services/`: Isolated services (`input`, `audio`, `media`, `power`, `tv`).
  - `tvcontrol/routes/`: Specialized Flask blueprints (`main`, `mouse`, `keyboard`, `volume`, `timer`, `media`).
  - `tvcontrol/static/` & `tvcontrol/templates/`: Clean template rendering with Jinja2 autoescaping.
- **Compact Entrypoint**: Reduced root `remote.py` from 3,113 lines to < 100 lines.
- **Automated Testing Suite**: 28 automated unit and integration tests using `pytest` achieving > 72% coverage across all modules.
- **Continuous Integration**: Added GitHub Actions workflow (`.github/workflows/ci.yml`) running multi-version matrix tests (Python 3.8, 3.10, 3.12), Bandit security analysis, and Pytest coverage.
- **Repository Hygiene**: Removed legacy `setup_autostart.sh` and hardcoded desktop files.

### 🛡️ Structural Security (Sprint 2)
- **Session Authentication**: Issued `HttpOnly`, `SameSite=Lax` session cookies; eliminated permanent tokens from query strings.
- **One-Time QR Pairing**: QR codes now embed ephemeral, single-use 5-minute pairing tokens (`?pair=...`).
- **Brute Force Protection**: Implemented sliding-window `RateLimiter` blocking IPs with 10 failed login attempts (HTTP 429).
- **Zero Shell Injection**: Refactored command execution to `subprocess.run(..., shell=False)` using `shlex.split` and fallback chains.
- **Static Analysis Compliance**: Resolved all high-severity Bandit issues (`bandit -lll` reports 0 findings).
- **Web Security Headers**: Enforced `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and `Referrer-Policy: no-referrer`.
- **DNS Rebinding Prevention**: Added Host header whitelist filtering incoming requests to RFC 1918 private subnets and localhost.
- **Audit Logging**: Rotating structured audit log (`~/.config/ignocontrol/audit.log`) without logging typed sensitive keys.
- **Systemd Hardening**: Sandboxed user service with `NoNewPrivileges=yes`, `PrivateTmp=yes`, `ProtectSystem=strict`, and `ProtectHome=read-only`.

### 📱 Mobile Layout & UX (Sprint 1)
- **Thumb-Friendly Navigation**: Bottom fixed tab bar with safe-area inset support and SVG icons.
- **Dynamic Touchpad & Keyboard**: Collapsible text typing panel preventing layout squishing.
- **Android TV D-Pad**: True cross directional navigation (Up, Down, Left, Right, OK, Back, Home, Play, Vol+, Vol-, Power).
- **Viewport Hardening**: Removed `maximum-scale=1` and `user-scalable=no`, configured input `font-size: 16px` to prevent iOS Safari auto-zoom.
- **Touch Gestures**: Multi-touch 2-finger scroll detection and `touchcancel` gesture reset.

### 🚨 Security Emergency Fixes (Sprint 0)
- **Protected Endpoints**: Blocked unauthenticated access to `/`, `/qrcode`, and `/manifest.json`.
- **Default Token Elimination**: Removed committed default tokens; auto-generated 32-byte secret in `~/.config/ignocontrol/config.json` with 0600 permissions.
- **Action Route Lockdown**: Restricted action routes (`/exec`, `/play`, `/vol-up`, `/vol-down`, `/poweroff`) strictly to `POST`.
- **Input Sanitization**: Validated `/timer/set` (1 to 720 minutes) and enforced `ALLOWED_KEYS` whitelist for `/key`.
- **Network Restriction**: Documented and applied firewall rules limiting port 7000 to RFC 1918 private subnets.
