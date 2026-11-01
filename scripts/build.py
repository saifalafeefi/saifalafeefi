#!/usr/bin/env python3
"""Builds the boot-screen GitHub profile.

Fetches live data from the GitHub API, renders the animated SVGs in assets/,
and writes README.md. All wording lives in profile.json - edit that, not the
README.

    python scripts/build.py            # fetch live data, rebuild everything
    python scripts/build.py --offline  # rebuild from the cached assets/data.json

Set GITHUB_TOKEN to raise the API rate limit (the Action does this for you).
"""
import base64
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
CACHE = ASSETS / "data.json"

CW = 0.4  # VT323 is monospaced: every glyph advances 0.4em

BG = "#0d0a04"
AMBER = "#ffb000"
BRIGHT = "#ffe2a0"
DIM = "#9a6a00"
FAINT = "#3a2900"


def x(s):
    return escape(str(s), quote=True)


# --------------------------------------------------------------------------- data

def api(path):
    req = urllib.request.Request(
        "https://api.github.com" + path,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "boot-profile-builder"},
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def fetch(cfg):
    u = cfg["username"]
    user = api(f"/users/{u}")
    repos = [
        r for r in api(f"/users/{u}/repos?per_page=100&type=owner")
        if not r["fork"] and r["name"].lower() != u.lower()  # skip this profile repo
    ]

    ignore = set(cfg.get("ignore_languages", []))
    langs = {}
    for r in repos:
        for name, size in api(f"/repos/{u}/{r['name']}/languages").items():
            if name not in ignore:
                langs[name] = langs.get(name, 0) + size

    # newest commit authored by you, across the few most recently pushed repos
    last = None
    for r in sorted(repos, key=lambda r: r["pushed_at"], reverse=True)[:5]:
        try:
            commits = api(f"/repos/{u}/{r['name']}/commits?per_page=1&author={u}")
        except urllib.error.HTTPError:  # empty repos answer 409
            continue
        if commits:
            c = commits[0]["commit"]
            cand = {"repo": r["name"], "date": c["author"]["date"][:10],
                    "message": c["message"].strip().splitlines()[0] if c["message"].strip() else ""}
            if last is None or cand["date"] > last["date"]:
                last = cand

    return {
        "created_at": user["created_at"][:10],
        "repo_count": len(repos),
        "languages": dict(sorted(langs.items(), key=lambda kv: -kv[1])),
        "last_commit": last,
        "repos": {
            r["name"]: {"language": r["language"], "stars": r["stargazers_count"],
                        "pushed_at": r["pushed_at"][:10], "url": r["html_url"]}
            for r in repos
        },
    }


def uptime(created, today):
    a = dt.date.fromisoformat(created)
    months = (today.year - a.year) * 12 + today.month - a.month - (today.day < a.day)
    return f"{months // 12}y {months % 12}m"


# --------------------------------------------------------------------------- svg helpers

FONT_CSS = None


def font_css():
    global FONT_CSS
    if FONT_CSS is None:
        data = base64.b64encode((ASSETS / "fonts" / "VT323-latin.woff2").read_bytes()).decode()
        FONT_CSS = f"@font-face{{font-family:'BIOS';src:url(data:font/woff2;base64,{data}) format('woff2')}}"
    return FONT_CSS


# Animation model: every element's *static* style is its final state, and the
# animations only describe how it gets there. So with reduced motion (or a
# renderer that ignores CSS animation) the finished screen still shows.
KEYFRAMES = """
text{font-family:'BIOS','VT323','Courier New',monospace;white-space:pre}
@keyframes hide{from,to{opacity:0}}
@keyframes flash{from,to{opacity:1}}
@keyframes wipe{from{transform:scaleX(1)}}
@keyframes type{from{transform:translateX(0)}}
@keyframes blink{50%{opacity:0}}
@keyframes power{0%{transform:scale(.6,.004)}35%{transform:scale(1,.004)}100%{transform:scale(1,1)}}
@keyframes flicker{0%,47%,53%,100%{opacity:1}50%{opacity:.86}}
@keyframes roll{from{transform:translateY(-140px)}to{transform:translateY(var(--h))}}
@keyframes draw{from{stroke-dashoffset:var(--len)}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
"""


def svg_open(w, h, title, desc, extra_css=""):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-labelledby="t d" xml:space="preserve">\n'
        f"<title id=\"t\">{x(title)}</title><desc id=\"d\">{x(desc)}</desc>\n"
        f"<style>{font_css()}{KEYFRAMES}{extra_css}</style>\n"
    )


def defs(w, h, rx):
    return f"""<defs>
<clipPath id="screen"><rect width="{w}" height="{h}" rx="{rx}"/></clipPath>
<filter id="glow" x="-5%" y="-5%" width="110%" height="110%"><feGaussianBlur stdDeviation="2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<pattern id="scan" width="4" height="4" patternUnits="userSpaceOnUse"><rect width="4" height="2" fill="#000" opacity=".32"/></pattern>
<radialGradient id="vig" cx="50%" cy="50%" r="75%"><stop offset="60%" stop-color="#000" stop-opacity="0"/><stop offset="100%" stop-color="#000" stop-opacity=".6"/></radialGradient>
<linearGradient id="band" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{AMBER}" stop-opacity="0"/><stop offset=".5" stop-color="{AMBER}" stop-opacity=".05"/><stop offset="1" stop-color="{AMBER}" stop-opacity="0"/></linearGradient>
</defs>
"""


def crt_overlay(w, h):
    """Scanlines, a slow rolling refresh band, and a vignette - drawn above the text."""
    return (
        f'<rect width="{w}" height="140" fill="url(#band)" style="--h:{h + 140}px;animation:roll 7s linear infinite"/>\n'
        f'<rect width="{w}" height="{h}" fill="url(#scan)"/>\n'
        f'<rect width="{w}" height="{h}" fill="url(#vig)"/>\n'
    )


def text(px, py, s, size, fill=AMBER, style="", anchor=None):
    s = str(s)
    attrs = f'x="{px:.1f}" y="{py:.1f}" font-size="{size}" fill="{fill}"'
    if s.strip():
        attrs += f' textLength="{len(s) * size * CW:.1f}" lengthAdjust="spacing"'
    if anchor:
        attrs += f' text-anchor="{anchor}"'
    if style:
        attrs += f' style="{style}"'
    return f"<text {attrs}>{x(s)}</text>\n"


def show_at(t):
    """Hidden until t seconds, then visible for good."""
    return f"animation:hide {t:.2f}s step-end"


def wipe(px, py, n, size, start, dur, width=None):
    """A background-coloured cover over n characters (or `width` px in n steps) that steps away left to right."""
    w = width if width is not None else n * size * CW
    return (
        f'<rect x="{px:.1f}" y="{py - size * 0.8:.1f}" width="{w + 1:.1f}" height="{size * 1.05:.1f}" fill="{BG}" '
        f'style="transform:scaleX(0);transform-box:fill-box;transform-origin:right;'
        f'animation:wipe {dur:.2f}s steps({max(n, 1)}) {start:.2f}s backwards"/>\n'
    )


def typed(px, py, s, size, start, per_char, fill=BRIGHT):
    """Text typed out one character at a time, with a block cursor that keeps blinking."""
    n = len(s)
    cw = size * CW
    dur = n * per_char
    out = text(px, py, s, size, fill)
    out += wipe(px, py, n, size, start, dur)
    out += (
        f'<rect x="{px:.1f}" y="{py - size * 0.62:.1f}" width="{cw:.1f}" height="{size * 0.68:.1f}" fill="{fill}" '
        f'style="transform:translateX({n * cw + cw * 0.3:.1f}px);'
        f'animation:hide {start:.2f}s step-end,type {dur:.2f}s steps({n}) {start:.2f}s backwards,'
        f'blink 1.06s step-end {start + dur:.2f}s infinite"/>\n'
    )
    return out, start + dur


def chip(cx, cy, s, start):
    """Pixel microchip badge with the initials, drawn in the top-right corner."""
    half = s / 2
    pins, pl, pw = 5, s * 0.13, s * 0.07
    out = f'<g style="{show_at(start)}">\n'
    out += f'<rect x="{cx - half:.1f}" y="{cy - half:.1f}" width="{s}" height="{s}" rx="{s * .06:.1f}" fill="{BG}" stroke="{AMBER}" stroke-width="3"/>\n'
    out += f'<rect x="{cx - half + 10:.1f}" y="{cy - half + 10:.1f}" width="{s - 20}" height="{s - 20}" fill="none" stroke="{DIM}" stroke-width="1.5" stroke-dasharray="4 4"/>\n'
    for i in range(pins):
        off = -half + s * (i + 1) / (pins + 1) - pw / 2
        out += f'<rect x="{cx + off:.1f}" y="{cy - half - pl:.1f}" width="{pw:.1f}" height="{pl:.1f}" fill="{AMBER}"/>'
        out += f'<rect x="{cx + off:.1f}" y="{cy + half:.1f}" width="{pw:.1f}" height="{pl:.1f}" fill="{AMBER}"/>'
        out += f'<rect x="{cx - half - pl:.1f}" y="{cy + off:.1f}" width="{pl:.1f}" height="{pw:.1f}" fill="{AMBER}"/>'
        out += f'<rect x="{cx + half:.1f}" y="{cy + off:.1f}" width="{pl:.1f}" height="{pw:.1f}" fill="{AMBER}"/>\n'
    out += text(cx, cy + s * 0.15, "SA", int(s * 0.46), BRIGHT, anchor="middle")
    out += f'<circle cx="{cx + half - s * .17:.1f}" cy="{cy - half + s * .17:.1f}" r="{s * .045:.1f}" fill="{BRIGHT}" style="animation:pulse 1.4s step-end {start:.2f}s infinite"/>\n'
    out += "</g>\n"
    return out


# --------------------------------------------------------------------------- boot screen

def boot_screen(cfg, d, today, mobile=False):
    W = 600 if mobile else 1000
    size = 20 if mobile else 22
    cw = size * CW
    lh = size * 1.25
    left = 24 if mobile else 40
    body, y = [], 0

    def line(dy=1.0):
        nonlocal y
        y += lh * dy
        return y

    first_year = d["created_at"][:4]
    version = f"v{today:%y}.{today:%m}"
    os_name = cfg["os_name"]
    count = d["repo_count"]
    n_langs = len(d["languages"])

    # --- header
    t = 0.65
    y = 30 if mobile else 34
    body.append(text(left, line(), f"{os_name} BIOS {version}", size + 6, BRIGHT, show_at(t)))
    t += 0.2
    who = f"Copyright (C) {first_year}-{today.year}, {cfg['name']}"
    body.append(text(left, line(), who, size, DIM, show_at(t)))
    line(0.6)

    # --- operator / memory / uptime
    pad = 9 if mobile else 15
    t += 0.35
    op = cfg["name"] if mobile else f"{cfg['name']}, {cfg['role']} @ {cfg['org']}"
    body.append(text(left, line(), f"{'Operator':<{pad}}: {op}", size, AMBER, show_at(t)))

    t += 0.3
    yy = line()
    label = f"{'Memory':<{pad}}: " if mobile else f"{'Memory test':<{pad}}: "
    body.append(text(left, yy, label, size, AMBER, show_at(t)))
    cx = left + len(label) * cw
    frames = list(range(1, count + 1)) or [0]
    step = min(0.07, 0.9 / len(frames))
    for i, n in enumerate(frames):
        s = t + i * step
        if i == len(frames) - 1:
            st = show_at(s)
        else:
            st = f"opacity:0;animation:flash {step:.3f}s linear {s:.3f}s"
        body.append(text(cx, yy, f"{n:04d}", size, BRIGHT, st))
    t += len(frames) * step
    tail = " repos" if mobile else f" repos  {n_langs} languages"
    body.append(text(cx + 4 * cw, yy, tail, size, AMBER, show_at(t)))
    body.append(text(cx + (4 + len(tail) + 2) * cw, yy, "OK", size, BRIGHT, show_at(t + 0.15)))

    t += 0.35
    up = uptime(d["created_at"], today)
    since = "" if mobile else f"  (online since {d['created_at'][:7]})"
    body.append(text(left, line(), f"{'Uptime':<{pad}}: {up}{since}", size, AMBER, show_at(t)))
    line(0.6)

    # --- device scan
    t += 0.35
    body.append(text(left, line(), "Detecting devices ...", size, AMBER, show_at(t)))
    t += 0.3
    total = 40 if mobile else 84
    for dev in cfg["featured"]:
        yy = line()
        prefix = f" [{dev['port']}] {dev['id']:<16} " if mobile else f"  [{dev['port']:<4}]  {dev['id']:<18} "
        suffix = "" if mobile else f" {dev['kind']}"
        dots = max(3, total - len(prefix) - len(suffix))
        body.append(text(left, yy, prefix, size, AMBER, show_at(t)))
        dx = left + len(prefix) * cw
        body.append(text(dx, yy, "." * dots, size, DIM, show_at(t)))
        body.append(wipe(dx, yy, dots, size, t + 0.05, 0.35))
        ex = dx + dots * cw
        if suffix:
            body.append(text(ex, yy, suffix, size, AMBER, show_at(t + 0.42)))
        body.append(text(ex + (len(suffix) + 2) * cw, yy, "OK", size, BRIGHT, show_at(t + 0.45)))
        t += 0.55
    line(0.6)

    # --- last write (live)
    lc = d.get("last_commit")
    if lc:
        t += 0.2
        where = "" if mobile else f"  {lc['repo']}"
        body.append(text(left, line(), f"{'Last write':<{pad}}: {lc['date']}{where}", size, AMBER, show_at(t)))
        room = (W - 2 * left) // cw - pad - 4
        msg = lc["message"]
        if len(msg) > room:
            msg = msg[: int(room) - 3].rstrip() + "..."
        body.append(text(left + (pad + 2) * cw, line(), f'"{msg}"', size, DIM, show_at(t + 0.15)))
        line(0.4)
        t += 0.4

    # --- greeting
    big = size + (10 if mobile else 14)
    y += big * 1.25
    out, t = typed(left, y, f"> {cfg['greeting']}", big, t + 0.4, 0.075)
    body.append(out)

    if not mobile:
        y += lh * 1.6
        body.append(text(left, y, "Press F1 for PROJECTS, F2 for STACK, F3 for CONTACT", size, DIM,
                         f"{show_at(t + 0.3)},pulse 2.4s ease-in-out {t + 0.3:.2f}s infinite"))

    H = int(y + (22 if mobile else 30))
    chip_s = 70 if mobile else 110
    chip_svg = chip(W - left - chip_s / 2 - 12, 30 + chip_s / 2 + 12, chip_s, 0.75)

    desc = (f"An animated retro computer boot screen for {cfg['name']}: it checks memory "
            f"({count} repos), detects devices ({', '.join(f['title'] for f in cfg['featured'])}), "
            f"shows the latest commit, then types '{cfg['greeting']}'.")
    return (
        svg_open(W, H, f"{cfg['name']} - {os_name} boot screen", desc)
        + defs(W, H, 14)
        + '<g clip-path="url(#screen)">\n'
        + f'<rect width="{W}" height="{H}" fill="#050402"/>\n'
        + f'<g style="transform-origin:{W / 2}px {H / 2}px;animation:power .55s cubic-bezier(.2,.7,.2,1)">\n'
        + f'<rect width="{W}" height="{H}" fill="{BG}"/>\n'
        + '<g filter="url(#glow)" style="animation:flicker 5s linear 1s infinite">\n'
        + "".join(body)
        + chip_svg
        + "</g>\n</g>\n"
        + crt_overlay(W, H)
        + "</g>\n</svg>\n"
    )


# --------------------------------------------------------------------------- device cards

def wrap(s, cols):
    lines, cur = [], ""
    for word in s.split():
        if cur and len(cur) + 1 + len(word) > cols:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    return lines


def device_card(i, dev, d, today):
    W, H = 600, 330
    left = 28
    info = d["repos"].get(dev["repo"], {})
    pushed = info.get("pushed_at", "")
    active = bool(pushed) and (today - dt.date.fromisoformat(pushed)).days <= 45
    body = []

    body.append(text(left, 38, f"DEVICE {i:02d}  /dev/{dev['id']}", 18, DIM))
    status = "ACTIVE" if active else "IDLE"
    body.append(text(W - left, 38, status, 18, BRIGHT if active else DIM, anchor="end"))
    lx = W - left - len(status) * 18 * CW - 16
    led_anim = "animation:pulse 1.1s step-end infinite" if active else ""
    body.append(f'<circle cx="{lx:.1f}" cy="32" r="5" fill="{BRIGHT if active else DIM}" style="{led_anim}"/>\n')
    body.append(f'<line x1="{left}" y1="54" x2="{W - left}" y2="54" stroke="{FAINT}" stroke-width="2"/>\n')

    body.append(text(left, 100, dev["title"], 40, BRIGHT))
    body.append(text(left, 128, dev["kind"], 20, DIM))

    cols = int((W - 2 * left) / (20 * CW))
    y = 162
    for ln in wrap(dev["summary"], cols)[:3]:
        body.append(text(left, y, ln, 20, AMBER))
        y += 24
    if dev.get("role"):
        y += 6
        for ln in wrap("> " + dev["role"], cols)[:2]:
            body.append(text(left, y, ln, 20, DIM))
            y += 24

    body.append(f'<line x1="{left}" y1="{H - 62}" x2="{W - left}" y2="{H - 62}" stroke="{FAINT}" stroke-width="2"/>\n')
    stats = []
    if info.get("stars"):
        stars = info["stars"]
        stats.append(f"{stars} star{'s' if stars != 1 else ''}")
    if pushed:
        stats.append(f"last write {pushed}")
    stat_s = "  ".join(stats)
    body.append(text(W - left, H - 26, stat_s, 18, DIM, anchor="end"))

    tx = left
    limit = W - left - len(stat_s) * 18 * CW - 16
    for tag in dev["tags"]:
        tw = len(tag) * 18 * CW + 16
        if tx + tw > limit:
            break
        body.append(f'<rect x="{tx:.1f}" y="{H - 46}" width="{tw:.1f}" height="28" fill="none" stroke="{DIM}" stroke-width="1.5"/>\n')
        body.append(text(tx + 8, H - 26, tag, 18, AMBER))
        tx += tw + 8

    perim = 2 * (W + H)
    desc = f"{dev['title']} ({dev['kind']}): {dev['summary']}"
    return (
        svg_open(W, H, dev["title"], desc)
        + defs(W, H, 14)
        + '<g clip-path="url(#screen)">\n'
        + f'<rect width="{W}" height="{H}" fill="{BG}"/>\n'
        + '<g filter="url(#glow)">\n' + "".join(body) + "</g>\n"
        + crt_overlay(W, H)
        + "</g>\n"
        + f'<rect x="1.5" y="1.5" width="{W - 3}" height="{H - 3}" rx="13" fill="none" stroke="{DIM}" stroke-width="3" '
          f'stroke-dasharray="{perim}" style="--len:{perim}px;animation:draw 1.6s ease-out .2s backwards"/>\n'
        + "</svg>\n"
    )


# --------------------------------------------------------------------------- memory map

def memory_map(d, top=6):
    langs = list(d["languages"].items())
    total = sum(v for _, v in langs) or 1
    rows = langs[:top]
    rest = sum(v for _, v in langs[top:])
    if rest:
        rows.append(("other", rest))

    W, left, size = 1200, 40, 22
    cells, cell, gap = 40, 16, 4
    row_h = 36
    H = 96 + len(rows) * row_h + 24
    body = [
        text(left, 50, "MEMORY MAP", 30, BRIGHT),
        text(W - left, 50, f"bytes of code by language across {d['repo_count']} repos", size, DIM, anchor="end"),
        f'<line x1="{left}" y1="68" x2="{W - left}" y2="68" stroke="{FAINT}" stroke-width="2"/>\n',
    ]
    bar_x = left + 14 * size * CW
    t = 0.3
    for i, (name, v) in enumerate(rows):
        y = 104 + i * row_h
        pct = 100 * v / total
        filled = max(1, round(pct / 100 * cells))
        body.append(text(left, y, f"{name[:13]:<13}", size, AMBER))
        for c in range(cells):
            fill = AMBER if c < filled else FAINT
            body.append(f'<rect x="{bar_x + c * (cell + gap):.1f}" y="{y - 15}" width="{cell}" height="{cell}" fill="{fill}"/>')
        body.append("\n")
        body.append(wipe(bar_x, y, filled, size, t, filled * 0.03, width=filled * (cell + gap)))
        body.append(text(bar_x + cells * (cell + gap) + 16, y, f"{pct:5.1f}%", size, BRIGHT))
        t += 0.12

    desc = "Language breakdown: " + ", ".join(f"{n} {100 * v / total:.1f}%" for n, v in rows)
    return (
        svg_open(W, H, "Memory map - languages by bytes", desc)
        + defs(W, H, 14)
        + '<g clip-path="url(#screen)">\n'
        + f'<rect width="{W}" height="{H}" fill="{BG}"/>\n'
        + '<g filter="url(#glow)">\n' + "".join(body) + "</g>\n"
        + crt_overlay(W, H)
        + "</g>\n</svg>\n"
    )


# --------------------------------------------------------------------------- keycaps + footer

def keycap(key, label):
    W, H = 240, 84
    return (
        svg_open(W, H, f"{key} {label}", f"Keyboard key {key}: jump to {label.lower()}")
        + f'<rect x="2" y="2" width="{W - 4}" height="{H - 4}" rx="12" fill="#140f05" stroke="{DIM}" stroke-width="2"/>\n'
        + f'<rect x="10" y="7" width="{W - 20}" height="{H - 24}" rx="9" fill="#21180a" stroke="{FAINT}" stroke-width="2"/>\n'
        + text(22, 32, key, 20, DIM)
        + f'<g filter="url(#glow)">' + text(W / 2, 56, label, 30, AMBER, anchor="middle") + "</g>\n"
        + '<defs><filter id="glow" x="-10%" y="-30%" width="120%" height="160%"><feGaussianBlur stdDeviation="1.6" result="b"/>'
          '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>\n'
        + "</svg>\n"
    )


def footer():
    W, H = 1200, 110
    out, _ = typed(W / 2 - 23 * 30 * CW / 2 + 1, 74, "Press any key to reboot", 30, 0.4, 0.05, AMBER)
    return (
        svg_open(W, H, "Press any key to reboot", "End of the boot screen. Links back to the top of the profile.")
        + defs(W, H, 14)
        + '<g clip-path="url(#screen)">\n'
        + f'<rect width="{W}" height="{H}" fill="{BG}"/>\n'
        + text(W / 2, 36, "SYSTEM HALTED", 20, DIM, anchor="middle")
        + f'<g filter="url(#glow)">{out}</g>\n'
        + crt_overlay(W, H)
        + "</g>\n</svg>\n"
    )


# --------------------------------------------------------------------------- readme

def readme(cfg, d):
    u = cfg["username"]
    repos = d["repos"]
    L = [
        "<!-- Generated by scripts/build.py from profile.json. Edit those, not this file. -->",
        '<a id="top"></a>',
        "",
        '<p align="center">',
        '  <a href="#projects">',
        "    <picture>",
        '      <source media="(max-width: 600px)" srcset="./assets/boot-mobile.svg">',
        f'      <img src="./assets/boot.svg" width="100%" alt="{x(cfg["os_name"])} boot screen: {x(cfg["name"])}, {x(cfg["role"])} at {x(cfg["org"])}. {x(cfg["greeting"])}">',
        "    </picture>",
        "  </a>",
        "</p>",
        "",
        '<p align="center">',
        '  <a href="#projects"><img src="./assets/key-f1.svg" width="30%" alt="F1: projects"></a>',
        '  <a href="#stack"><img src="./assets/key-f2.svg" width="30%" alt="F2: stack"></a>',
        '  <a href="#contact"><img src="./assets/key-f3.svg" width="30%" alt="F3: contact"></a>',
        "</p>",
        "",
        '<p align="center">',
        f"  {x(cfg['tagline'])}",
        "</p>",
        "",
        '<a id="projects"></a>',
        "",
        "## `F1` Devices detected",
        "",
        '<p align="center">',
    ]
    for dev in cfg["featured"]:
        url = repos.get(dev["repo"], {}).get("url", f"https://github.com/{u}/{dev['repo']}")
        L.append(f'  <a href="{url}"><img src="./assets/device-{dev["id"]}.svg" width="49%" alt="{x(dev["title"])}: {x(dev["summary"])}"></a>')
    L += ["</p>", ""]

    if cfg.get("more"):
        L += [
            "<details>",
            "<summary><strong>More devices on the bus</strong></summary>",
            "",
            "| Device | What it does |",
            "| --- | --- |",
        ]
        for m in cfg["more"]:
            url = repos.get(m["repo"], {}).get("url", f"https://github.com/{u}/{m['repo']}")
            L.append(f"| [`{m['repo']}`]({url}) | {m['text']} |")
        L += ["", "</details>", ""]

    L += [
        '<a id="stack"></a>',
        "",
        "## `F2` Stack",
        "",
        '<p align="center"><img src="./assets/memory-map.svg" width="100%" alt="Languages by bytes of code across my public repositories"></p>',
        "",
        "```ini",
    ]
    width = max(len(k) for k in cfg["stack"]) + 2
    for k, v in cfg["stack"].items():
        L.append(f"{('[' + k + ']'):<{width + 2}} {', '.join(v)}")
    L += ["```", "", '<a id="contact"></a>', "", "## `F3` Open ports", ""]
    for c in cfg["contact"]:
        if c.get("url"):
            L.append(f"- **{c['label']}**: <{c['url']}>" if c["url"].startswith("http") else f"- **{c['label']}**: {c['url']}")
    L += [
        "",
        '<p align="center"><a href="#top"><img src="./assets/footer.svg" width="100%" alt="Press any key to reboot: back to top"></a></p>',
        "",
    ]
    return "\n".join(L)


# --------------------------------------------------------------------------- main

def main():
    cfg = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
    today = dt.date.today()

    if "--offline" in sys.argv:
        d = json.loads(CACHE.read_text(encoding="utf-8"))
    else:
        try:
            d = fetch(cfg)
            CACHE.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
        except (urllib.error.URLError, TimeoutError, KeyError) as e:
            if not CACHE.exists():
                raise
            print(f"GitHub API failed ({e}); using cached data", file=sys.stderr)
            d = json.loads(CACHE.read_text(encoding="utf-8"))

    files = {
        "boot.svg": boot_screen(cfg, d, today),
        "boot-mobile.svg": boot_screen(cfg, d, today, mobile=True),
        "memory-map.svg": memory_map(d),
        "key-f1.svg": keycap("F1", "PROJECTS"),
        "key-f2.svg": keycap("F2", "STACK"),
        "key-f3.svg": keycap("F3", "CONTACT"),
        "footer.svg": footer(),
    }
    for i, dev in enumerate(cfg["featured"]):
        files[f"device-{dev['id']}.svg"] = device_card(i, dev, d, today)
    for name, content in files.items():
        (ASSETS / name).write_text(content, encoding="utf-8")
    (ROOT / "README.md").write_text(readme(cfg, d), encoding="utf-8")
    print(f"built {len(files)} svgs + README.md ({d['repo_count']} repos, {len(d['languages'])} languages)")


if __name__ == "__main__":
    main()
