# Security Policy & Threat Model

## 🛡️ Supported Versions

We actively provide security patches and hardening updates for the following versions:

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

---

## 🔒 Threat Model & Security Architecture

IgnoControl is designed to run securely on local area networks (LANs) and untrusted environments through a defense-in-depth security approach:

1. **Authentication & Session Management**:
   - Authentication requires a cryptographically strong 32-byte secret token (`secrets.token_urlsafe(32)`).
   - Once authenticated, the server issues an `HttpOnly`, `SameSite=Lax` session cookie.
   - Tokens never travel in query strings during regular API operations, preventing leakage into browser history, proxies, or server access logs.
   - Constant-time string comparison (`hmac.compare_digest`) prevents timing attacks.

2. **Ephemeral Pairing**:
   - QR Codes generated for pairing use single-use, cryptographically random pairing tokens with a 5-minute time-to-live (TTL).
   - Once redeemed by scanning, the code is immediately invalidated.

3. **Brute Force & DoS Protection**:
   - An in-memory sliding-window `RateLimiter` tracks authentication failures by client IP.
   - 10 consecutive failed attempts result in an automatic IP block (HTTP `429 Too Many Requests`) for 10 minutes.
   - High-frequency simulation routes (`/mouse/move`, `/mouse/scroll`, `/key`, `/type`) are rate-limited to 60 req/sec per client IP.

4. **Zero Shell Injection**:
   - All external processes are executed via `subprocess.run(..., shell=False)` with argument lists parsed safely via `shlex.split`.
   - Android TV commands validate destination IPv4 addresses via `ipaddress.ip_address` and restrict keycodes to an immutable whitelist.
   - Static analysis via Bandit confirms zero high-severity findings (`bandit -lll`).

5. **Audit Logging & Privacy**:
   - Structured audit logging records client IP, timestamp, action, and result in a rotating file (`~/.config/ignocontrol/audit.log`, max 2MB, 3 rotations).
   - Keystrokes sent via `/type` are audited only by character count, never logging raw textual content or passwords.

6. **Web Security Headers & DNS Rebinding**:
   - `Content-Security-Policy`: Restricts resource loading to self-hosted assets.
   - `X-Frame-Options: DENY`: Mitigates clickjacking.
   - `X-Content-Type-Options: nosniff`: Prevents MIME-type confusion attacks.
   - `Referrer-Policy: no-referrer`: Prevents leaking sensitive origins.
   - Host Header Validation: Blocks DNS rebinding attacks by validating incoming Host headers against RFC 1918 private IP subnets and localhost.

---

## 🚨 Reporting a Vulnerability

If you discover a security vulnerability within IgnoControl, please do **NOT** open a public issue.

Instead, please report the vulnerability privately via GitHub Security Advisories or by emailing the project maintainer directly.

When reporting, please include:
- A detailed description of the vulnerability.
- Steps to reproduce or proof-of-concept (PoC).
- Potential impact and suggested mitigations.

You will receive an acknowledgment within 24 hours and regular status updates as the patch is prepared.
