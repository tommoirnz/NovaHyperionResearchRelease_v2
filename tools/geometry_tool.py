"""
geometry_tool.py
Nova geometric drawing tool — parametric curves, orbits, fractals, engineering geometry.

Output: SVG saved to web_images/, returns HTML <img> tag for Nova's LCARS web interface.

NOT for flowcharts or block diagrams — use create_diagram for those.
"""

import os
import re
import math
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import datetime
import time

# ── Config ────────────────────────────────────────────────────────────────────
# geometry_tool.py lives in tools/ — web_images/ is one level up at project root
WEB_IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'web_images')

LCARS_BG      = '#05080f'
LCARS_GRID    = '#0d1525'
LCARS_ACCENT  = '#4fc3f7'
LCARS_ACCENT2 = '#81c784'
LCARS_WARN    = '#ffe082'
LCARS_DIM     = '#2a3a5a'


# ── Public tool function ──────────────────────────────────────────────────────

def plot_geometry(query: str, log_callback=None) -> str:
    """
    Draws mathematical geometric figures and saves them to web_images for Nova's
    web interface. Returns an HTML <img> tag pointing to the saved file.

    Handles: parametric curves, spirals, Lissajous figures, rose curves,
    orbital ellipses (Keplerian), hypocycloids, epicycloids, sine/cosine waves,
    Koch snowflake fractal, solar system orbits, Fourier series, perspective grids.

    NOT for flowcharts or block diagrams — use create_diagram for those.

    Args:
        query:         Natural language description, e.g.:
                       "Lissajous figure a=3 b=2"
                       "Archimedean spiral 6 turns"
                       "orbit eccentricity 0.7"
                       "rose curve 7 petals"
                       "hypocycloid R=5 r=3"
                       "solar system orbits"
                       "sine wave frequency 3"
                       "Koch snowflake depth 4"
                       "Fourier square wave 7 terms"
        log_callback:  Optional Nova log function.
    Returns:
        HTML string with <img> tag and caption, ready for Nova's web renderer.
    """
    try:
        if log_callback:
            log_callback(f"[GEOMETRY] Drawing: {query}")

        os.makedirs(WEB_IMAGES_DIR, exist_ok=True)

        desc = query.lower().strip()

        # ── Dispatch ─────────────────────────────────────────────────────────
        if _match(desc, ['lissajous']):
            fig, caption = _lissajous(desc)

        elif _match(desc, ['spiral']):
            fig, caption = _spiral(desc)

        elif _match(desc, ['rose', 'rhodonea']):
            fig, caption = _rose(desc)

        elif _match(desc, ['solar system', 'planets', 'planetary']):

            PLANET_NAMES = ['mercury', 'venus', 'earth', 'mars', 'jupiter',

                            'saturn', 'uranus', 'neptune']

            named = [p for p in PLANET_NAMES if p in desc]

            has_system_kw = any(w in desc for w in

                                ['solar system', 'all planets', 'planetary'])

            if named and not has_system_kw:

                fig, caption = _named_orbits(named, desc)

            else:

                fig, caption = _solar_system(desc)

        elif _match(desc, ['orbit', 'ellipse', 'elliptical', 'kepler']):
            fig, caption = _orbit(desc)

        elif _match(desc, ['hypocycloid']):
            fig, caption = _hypocycloid(desc)

        elif _match(desc, ['epicycloid']):
            fig, caption = _epicycloid(desc)

        elif _match(desc, ['fourier', 'square wave', 'sawtooth', 'triangular wave', 'triangle wave']):
            fig, caption = _fourier(desc)

        elif _match(desc, ['sine', 'cosine', 'sinusoid', 'wave']):
            fig, caption = _sine_wave(desc)

        elif _match(desc, ['fractal', 'koch', 'snowflake']):
            fig, caption = _koch_snowflake(desc)

        elif _match(desc, ['grid', 'perspective']):
            fig, caption = _perspective_grid(desc)

        elif _match(desc, ['parametric']):
            fig, caption = _parametric(desc)

        else:
            fig, caption = _best_guess(desc)

        # ── Save SVG ─────────────────────────────────────────────────────────
        ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:19]
        filename = f"geometry_{ts}.svg"
        filepath = os.path.join(WEB_IMAGES_DIR, filename)
        fig.savefig(filepath, format='svg', bbox_inches='tight',
                    facecolor=LCARS_BG, edgecolor='none')
        plt.close(fig)

        if log_callback:
            log_callback(f"[GEOMETRY] Saved: {filename}")


        url = f"/web_images/{filename}"

        return f"[IMAGE:{filename}]\n{caption}"

    except Exception as e:
        if log_callback:
            log_callback(f"[GEOMETRY] Error: {e}")
        return f"Error: {str(e)}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _match(desc: str, keywords: list) -> bool:
    return any(k in desc for k in keywords)

def _num(desc: str, patterns: list, default: float) -> float:
    """Extract first matching number from description."""
    for pat in patterns:
        m = re.search(pat, desc)
        if m:
            return float(m.group(1))
    return default

def _base_fig(size=(7, 7)):
    fig, ax = plt.subplots(figsize=size, facecolor=LCARS_BG)
    ax.set_facecolor(LCARS_BG)
    ax.tick_params(colors=LCARS_DIM)
    for spine in ax.spines.values():
        spine.set_color(LCARS_DIM)
    ax.grid(True, color=LCARS_GRID, linewidth=0.5, linestyle='--')
    return fig, ax

def _finish(ax, title: str):
    ax.set_title(title, color=LCARS_ACCENT, fontsize=10,
                 fontfamily='monospace', pad=10)
    ax.set_aspect('equal', adjustable='datalim')
    ax.tick_params(colors=LCARS_DIM, labelsize=7)


# ── Kepler solver ─────────────────────────────────────────────────────────────

def _solve_kepler(M_arr: np.ndarray, e: float, iters: int = 12) -> np.ndarray:
    """Newton-Raphson solution for eccentric anomaly E given mean anomaly M."""
    E = M_arr.copy()
    for _ in range(iters):
        E = E - (E - e * np.sin(E) - M_arr) / (1.0 - e * np.cos(E))
    return E


# ── Drawing functions ─────────────────────────────────────────────────────────

def _lissajous(desc: str):
    a     = int(_num(desc, [r'a\s*[=:]\s*(\d+)', r'(\d+)\s*[,x]\s*\d+'], 3))
    b     = int(_num(desc, [r'b\s*[=:]\s*(\d+)', r'\d+\s*[,x]\s*(\d+)'], 2))
    delta = _num(desc, [r'delta\s*[=:]\s*([\d.]+)', r'phase\s*[=:]\s*([\d.]+)'],
                 math.pi / 4)

    t = np.linspace(0, 2 * math.pi, 4000)
    x = np.sin(a * t + delta)
    y = np.sin(b * t)

    fig, ax = _base_fig()
    ax.plot(x, y, color=LCARS_ACCENT, linewidth=1.2, alpha=0.9)
    _finish(ax, f'Lissajous Figure  a={a}  b={b}  δ={delta:.3f} rad')
    return fig, f'Lissajous Figure (a={a}, b={b})'


def _spiral(desc: str):
    turns = _num(desc, [r'(\d+)\s*turn', r'turns?\s*[=:]\s*(\d+)',
                         r'n\s*[=:]\s*(\d+)'], 6)
    style = 'log' if 'log' in desc else 'arch'

    t = np.linspace(0, turns * 2 * math.pi, 5000)
    if style == 'log':
        b = _num(desc, [r'b\s*[=:]\s*([\d.]+)'], 0.15)
        r = np.exp(b * t)
        label = f'Logarithmic Spiral (b={b})'
    else:
        r = t / (2 * math.pi)
        label = f'Archimedean Spiral ({int(turns)} turns)'

    x = r * np.cos(t)
    y = r * np.sin(t)

    fig, ax = _base_fig()
    points = np.array([x, y]).T.reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)
    from matplotlib.collections import LineCollection
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list('nova', [LCARS_DIM, LCARS_ACCENT, '#e0f0ff'])
    lc = LineCollection(segments, cmap=cmap, linewidth=1.2, alpha=0.9)
    lc.set_array(np.linspace(0, 1, len(segments)))
    ax.add_collection(lc)
    ax.autoscale()
    _finish(ax, label)
    return fig, label


def _rose(desc: str):
    k = int(_num(desc, [r'k\s*[=:]\s*(\d+)', r'(\d+)\s*petal',
                         r'petal.*?(\d+)'], 5))
    t_max = 2 * math.pi if k % 2 == 1 else 4 * math.pi
    t = np.linspace(0, t_max, 6000)
    r = np.cos(k * t)
    x = r * np.cos(t)
    y = r * np.sin(t)

    petals = k if k % 2 == 1 else 2 * k
    fig, ax = _base_fig()
    ax.plot(x, y, color=LCARS_ACCENT2, linewidth=1.4, alpha=0.85)
    ax.fill(x, y, color=LCARS_ACCENT2, alpha=0.08)
    _finish(ax, f'Rose Curve  k={k}  ({petals} petals)')
    return fig, f'Rose Curve (k={k}, {petals} petals)'


def _orbit(desc: str):
    e = _num(desc, [r'e\s*[=:]\s*([\d.]+)', r'eccentricity\s*[=:]\s*([\d.]+)',
                     r'ecc\s*([\d.]+)'], 0.5)
    a = _num(desc, [r'a\s*[=:]\s*([\d.]+)', r'semi.major\s*[=:]\s*([\d.]+)'], 5.0)
    e = min(e, 0.9999)

    M      = np.linspace(0, 2 * math.pi, 3000)
    E      = _solve_kepler(M, e)
    cos_E  = np.cos(E)
    sin_E  = np.sin(E)
    cos_v  = (cos_E - e) / (1 - e * cos_E)
    sin_v  = (np.sqrt(1 - e**2) * sin_E) / (1 - e * cos_E)
    r      = a * (1 - e * cos_E)
    x      = r * cos_v
    y      = r * sin_v

    fig, ax = _base_fig((8, 6))
    ax.set_aspect('equal', adjustable='datalim')

    from matplotlib.collections import LineCollection
    from matplotlib.colors import LinearSegmentedColormap
    pts   = np.array([x, y]).T.reshape(-1, 1, 2)
    segs  = np.concatenate([pts[:-1], pts[1:]], axis=1)
    speed = 1.0 / r[:-1]
    speed = (speed - speed.min()) / (speed.max() - speed.min())
    cmap  = LinearSegmentedColormap.from_list('speed',
                                               [LCARS_ACCENT, LCARS_WARN, '#ff6060'])
    lc = LineCollection(segs, cmap=cmap, linewidth=1.6, alpha=0.9)
    lc.set_array(speed)
    ax.add_collection(lc)

    ax.plot(0, 0, 'o', color='#ffeb3b', markersize=10,
            markerfacecolor='#ffe082', markeredgecolor='#ff8f00', zorder=5)
    ax.annotate('Primary\n(focus)', xy=(0, 0), xytext=(0.3, 0.5),
                color='#ffe082', fontsize=7, fontfamily='monospace')

    c_dist = -2 * a * e
    ax.plot(c_dist, 0, '+', color=LCARS_DIM, markersize=8, markeredgewidth=1)
    ax.annotate('empty\nfocus', xy=(c_dist, 0), xytext=(c_dist - 0.5, -0.8),
                color=LCARS_DIM, fontsize=7, fontfamily='monospace')

    peri_x = x[np.argmin(r)]
    apo_x  = x[np.argmax(r)]
    ax.plot(peri_x, 0, 'v', color=LCARS_WARN, markersize=6, zorder=6)
    ax.annotate(f'Periapsis\nr={a*(1-e):.2f}', xy=(peri_x, 0),
                xytext=(peri_x, -1.2), color=LCARS_WARN, fontsize=7,
                fontfamily='monospace', ha='center')
    ax.plot(apo_x, 0, '^', color=LCARS_ACCENT2, markersize=6, zorder=6)
    ax.annotate(f'Apoapsis\nr={a*(1+e):.2f}', xy=(apo_x, 0),
                xytext=(apo_x, 1.0), color=LCARS_ACCENT2, fontsize=7,
                fontfamily='monospace', ha='center')

    ax.autoscale()
    b_axis = a * math.sqrt(1 - e**2)
    ax.set_title(f'Keplerian Orbit  a={a:.1f}  e={e:.3f}  b={b_axis:.2f}'
                 f'  (colour = orbital speed)',
                 color=LCARS_ACCENT, fontsize=9, fontfamily='monospace', pad=10)
    ax.tick_params(colors=LCARS_DIM, labelsize=7)
    for spine in ax.spines.values():
        spine.set_color(LCARS_DIM)
    ax.grid(True, color=LCARS_GRID, linewidth=0.5, linestyle='--')

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(0, 1))
    sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, fraction=0.03, pad=0.02)
    cb.set_label('Orbital Speed (normalised)', color=LCARS_DIM,
                 fontsize=7, fontfamily='monospace')
    cb.ax.yaxis.set_tick_params(color=LCARS_DIM, labelsize=7)
    plt.setp(cb.ax.yaxis.get_ticklabels(), color=LCARS_DIM)

    return fig, f'Keplerian Orbit (a={a:.1f}, e={e:.3f})'


def _hypocycloid(desc: str):
    R = _num(desc, [r'R\s*[=:]\s*([\d.]+)', r'outer\s*[=:]\s*([\d.]+)'], 5.0)
    r = _num(desc, [r'r\s*[=:]\s*([\d.]+)', r'inner\s*[=:]\s*([\d.]+)'], 3.0)
    r = min(r, R - 0.01)

    t = np.linspace(0, 2 * math.pi * r, 8000)
    x = (R - r) * np.cos(t) + r * np.cos((R - r) * t / r)
    y = (R - r) * np.sin(t) - r * np.sin((R - r) * t / r)

    fig, ax = _base_fig()
    ax.plot(x, y, color=LCARS_ACCENT, linewidth=1.2, alpha=0.9)
    _finish(ax, f'Hypocycloid  R={R}  r={r}')
    return fig, f'Hypocycloid (R={R}, r={r})'


def _epicycloid(desc: str):
    R = _num(desc, [r'R\s*[=:]\s*([\d.]+)'], 4.0)
    r = _num(desc, [r'r\s*[=:]\s*([\d.]+)'], 1.0)

    t = np.linspace(0, 2 * math.pi * r, 8000)
    x = (R + r) * np.cos(t) - r * np.cos((R + r) * t / r)
    y = (R + r) * np.sin(t) - r * np.sin((R + r) * t / r)

    fig, ax = _base_fig()
    ax.plot(x, y, color=LCARS_ACCENT2, linewidth=1.2, alpha=0.9)
    _finish(ax, f'Epicycloid  R={R}  r={r}')
    return fig, f'Epicycloid (R={R}, r={r})'


def _fourier(desc: str):
    terms = int(_num(desc, [r'(\d+)\s*term', r'term.*?(\d+)',
                             r'n\s*[=:]\s*(\d+)'], 7))
    if 'triangle' in desc or 'triangular' in desc:
        kind = 'triangle'
    elif 'sawtooth' in desc or 'saw' in desc:
        kind = 'sawtooth'
    else:
        kind = 'square'

    t = np.linspace(-math.pi, math.pi, 4000)
    y = np.zeros_like(t)

    fig, ax = _base_fig((9, 5))
    ax.set_aspect('auto')

    colours = plt.cm.cool(np.linspace(0.2, 0.9, terms))

    if kind == 'triangle':
        # Odd harmonics only: bn = (8/π²) × (-1)^((n-1)/2) / n²
        odd_harmonics = [n for n in range(1, terms * 4, 2)][:terms]
        for n_idx, n in enumerate(odd_harmonics):
            yn = (8 / math.pi**2) * ((-1)**((n - 1) // 2)) / (n**2) * np.sin(n * t)
            y += yn
            ax.plot(t, y,
                    color=colours[n_idx] if n_idx < len(colours) else LCARS_ACCENT,
                    linewidth=0.8, alpha=0.6)

    elif kind == 'square':
        for n_idx, n in enumerate(range(1, terms * 2, 2)):
            yn = (4 / (n * math.pi)) * np.sin(n * t)
            y += yn
            ax.plot(t, y,
                    color=colours[n_idx] if n_idx < len(colours) else LCARS_ACCENT,
                    linewidth=0.8, alpha=0.6)

    else:  # sawtooth
        for n_idx, n in enumerate(range(1, terms + 1)):
            yn = (2 / (n * math.pi)) * ((-1) ** (n + 1)) * np.sin(n * t)
            y += yn
            ax.plot(t, y,
                    color=colours[n_idx] if n_idx < len(colours) else LCARS_ACCENT,
                    linewidth=0.8, alpha=0.6)

    ax.plot(t, y, color=LCARS_ACCENT, linewidth=2.0, alpha=0.95,
            label=f'Sum ({terms} terms)')
    ax.axhline(0, color=LCARS_DIM, linewidth=0.5)
    ax.set_xlim(-math.pi, math.pi)
    ax.set_xlabel('t', color=LCARS_DIM, fontsize=8)
    ax.set_ylabel('amplitude', color=LCARS_DIM, fontsize=8)
    ax.legend(fontsize=8, facecolor=LCARS_BG, edgecolor=LCARS_DIM,
              labelcolor=LCARS_ACCENT)
    title = f'Fourier Series — {kind.capitalize()} Wave ({terms} harmonics)'
    ax.set_title(title, color=LCARS_ACCENT, fontsize=10,
                 fontfamily='monospace', pad=10)
    ax.tick_params(colors=LCARS_DIM, labelsize=7)
    for spine in ax.spines.values():
        spine.set_color(LCARS_DIM)
    return fig, title
def _sine_wave(desc: str):
    freq  = _num(desc, [r'freq(?:uency)?\s*[=:]\s*([\d.]+)', r'(\d+)\s*hz',
                         r'f\s*[=:]\s*([\d.]+)'], 1.0)
    amp   = _num(desc, [r'amp(?:litude)?\s*[=:]\s*([\d.]+)',
                         r'a\s*[=:]\s*([\d.]+)'], 1.0)
    phase = _num(desc, [r'phase\s*[=:]\s*([\d.]+)',
                         r'phi\s*[=:]\s*([\d.]+)'], 0.0)
    use_cos = 'cos' in desc

    t  = np.linspace(0, 4 * math.pi, 2000)
    y1 = amp * np.sin(freq * t + phase)
    y2 = amp * np.cos(freq * t + phase)

    fig, ax = _base_fig((9, 4))
    ax.set_aspect('auto')
    ax.plot(t, y1, color=LCARS_ACCENT, linewidth=1.6,
            label=f'sin({freq}t + {phase:.2f})')
    if use_cos or 'both' in desc:
        ax.plot(t, y2, color=LCARS_ACCENT2, linewidth=1.6, linestyle='--',
                label=f'cos({freq}t + {phase:.2f})', alpha=0.8)
    ax.axhline(0, color=LCARS_DIM, linewidth=0.5)
    ax.set_xlabel('t (rad)', color=LCARS_DIM, fontsize=8)
    ax.set_ylabel('amplitude', color=LCARS_DIM, fontsize=8)
    ax.legend(fontsize=8, facecolor=LCARS_BG, edgecolor=LCARS_DIM,
              labelcolor=LCARS_ACCENT)
    title = f'Sinusoid  f={freq}  A={amp}  φ={phase:.2f}'
    ax.set_title(title, color=LCARS_ACCENT, fontsize=10,
                 fontfamily='monospace', pad=10)
    ax.tick_params(colors=LCARS_DIM, labelsize=7)
    for spine in ax.spines.values():
        spine.set_color(LCARS_DIM)
    return fig, title


def _koch_snowflake(desc: str):
    depth = int(_num(desc, [r'depth\s*[=:]\s*(\d+)', r'level\s*[=:]\s*(\d+)',
                             r'(\d+)\s*(?:level|depth|iteration)'], 4))
    depth = min(depth, 6)

    def _next_gen(points):
        result = []
        for i in range(len(points) - 1):
            p0, p1 = points[i], points[i + 1]
            dx = (p1[0] - p0[0]) / 3
            dy = (p1[1] - p0[1]) / 3
            a  = p0
            b  = (p0[0] + dx,                          p0[1] + dy)
            c  = (p0[0] + dx + dy * math.sqrt(3) / 3,
                  p0[1] + dy - dx * math.sqrt(3) / 3)
            d  = (p0[0] + 2 * dx,                      p0[1] + 2 * dy)
            result.extend([a, b, c, d])
        result.append(points[-1])
        return result

    h   = math.sqrt(3) / 2
    pts = [(0, 0), (1, 0), (0.5, h), (0, 0)]
    for _ in range(depth):
        pts = _next_gen(pts)

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]

    fig, ax = _base_fig()
    ax.fill(xs, ys, color=LCARS_ACCENT, alpha=0.06)
    ax.plot(xs, ys, color=LCARS_ACCENT, linewidth=0.8, alpha=0.9)
    _finish(ax, f'Koch Snowflake — depth {depth}  ({len(pts)-1:,} segments)')
    return fig, f'Koch Snowflake (depth={depth})'


def _perspective_grid(desc: str):
    lines = int(_num(desc, [r'(\d+)\s*line', r'lines?\s*[=:]\s*(\d+)'], 12))

    fig, ax = _base_fig((9, 6))
    ax.set_aspect('auto')

    vp_x, vp_y = 0.0, 0.3

    for i in range(lines + 1):
        t = i / lines
        y = -1 + 2 * t
        ax.plot([vp_x, -3], [vp_y, y], color=LCARS_ACCENT,
                alpha=0.25 + 0.4 * t, linewidth=0.7)
        ax.plot([vp_x,  3], [vp_y, y], color=LCARS_ACCENT,
                alpha=0.25 + 0.4 * t, linewidth=0.7)

    for d in np.linspace(0.05, 1.0, lines):
        frac = d ** 1.6
        y_lo = vp_y + ((-1) - vp_y) * frac
        y_hi = vp_y + (( 1) - vp_y) * frac
        x_lo = vp_x + ((-3) - vp_x) * frac
        x_hi = vp_x + (( 3) - vp_x) * frac
        ax.plot([x_lo, x_hi], [y_lo, y_hi], color=LCARS_WARN,
                alpha=0.15 + 0.3 * frac, linewidth=0.6)

    ax.plot(vp_x, vp_y, 'o', color=LCARS_WARN, markersize=5, zorder=5)
    ax.annotate('VP', xy=(vp_x, vp_y), xytext=(vp_x + 0.08, vp_y + 0.06),
                color=LCARS_WARN, fontsize=8, fontfamily='monospace')
    ax.set_xlim(-3, 3)
    ax.set_ylim(-1.1, 1.1)
    ax.set_title('One-Point Perspective Grid', color=LCARS_ACCENT,
                 fontsize=10, fontfamily='monospace', pad=10)
    ax.tick_params(colors=LCARS_DIM, labelsize=7)
    for spine in ax.spines.values():
        spine.set_color(LCARS_DIM)
    return fig, 'One-Point Perspective Grid'


def _solar_system(desc: str):
    PLANETS = [
        ('Mercury', 0.387, 0.206, '#b0b0b0', 3),
        ('Venus',   0.723, 0.007, '#e8c97a', 4),
        ('Earth',   1.000, 0.017, '#4fc3f7', 4),
        ('Mars',    1.524, 0.093, '#e07050', 3.5),
        ('Jupiter', 5.203, 0.049, '#c8a870', 9),
        ('Saturn',  9.537, 0.057, '#e8d89a', 7.5),
        ('Uranus',  19.19, 0.046, '#7de8e8', 6),
        ('Neptune', 30.07, 0.010, '#4060e8', 6),
    ]

    inner_only = 'inner' in desc
    outer_only = 'outer' in desc
    if inner_only:
        planets = [p for p in PLANETS if p[1] <= 1.6]
        xlim = 2.0
    elif outer_only:
        planets = [p for p in PLANETS if p[1] >= 5.0]
        xlim = 33.0
    else:
        planets = PLANETS
        xlim = 33.0

    fig, ax = plt.subplots(figsize=(8, 8), facecolor=LCARS_BG)
    ax.set_facecolor(LCARS_BG)

    rng = np.random.default_rng(42)
    sx  = rng.uniform(-xlim, xlim, 300)
    sy  = rng.uniform(-xlim, xlim, 300)
    sb  = rng.uniform(0.1, 0.6, 300)
    ax.scatter(sx, sy, s=rng.uniform(0.3, 2.0, 300), c='white', alpha=sb, zorder=0)

    ax.plot(0, 0, 'o', color='#ffeb3b', markersize=14,
            markerfacecolor='#fff176', markeredgecolor='#ff8f00',
            markeredgewidth=1.5, zorder=10)

    for name, a, e, color, pr in planets:
        b = a * math.sqrt(1 - e**2)
        f = a * e
        ellipse = mpatches.Ellipse((-f, 0), 2 * a, 2 * b,
                                   edgecolor=color, facecolor='none',
                                   linewidth=0.7, alpha=0.35, zorder=1)
        ax.add_patch(ellipse)
        px = a * (1 - e)
        ax.plot(px, 0, 'o', color=color, markersize=pr,
                markerfacecolor=color, markeredgecolor='white',
                markeredgewidth=0.4, zorder=5, alpha=0.9)
        ax.annotate(name, xy=(px, 0),
                    xytext=(px * 0.6, b * 0.55 + (0.4 if a < 2 else 0.8)),
                    color=color, fontsize=6.5, fontfamily='monospace',
                    ha='center', alpha=0.9)

    if not inner_only:
        theta  = rng.uniform(0, 2 * math.pi, 600)
        r_belt = rng.uniform(2.2, 3.2, 600)
        ax.scatter(r_belt * np.cos(theta), r_belt * np.sin(theta),
                   s=0.4, c='#6a5040', alpha=0.4, zorder=2)

    ax.set_xlim(-xlim, xlim)
    ax.set_ylim(-xlim, xlim)
    ax.set_aspect('equal')
    ax.set_title('Solar System — Orbital Diagram (planets at periapsis, scale: AU)',
                 color=LCARS_ACCENT, fontsize=9, fontfamily='monospace', pad=10)
    ax.tick_params(colors=LCARS_DIM, labelsize=7)
    ax.set_xlabel('AU', color=LCARS_DIM, fontsize=8)
    ax.set_ylabel('AU', color=LCARS_DIM, fontsize=8)
    for spine in ax.spines.values():
        spine.set_color(LCARS_DIM)
    ax.grid(True, color=LCARS_GRID, linewidth=0.4, linestyle='--')
    return fig, 'Solar System Orbital Diagram'

def _named_orbits(planet_names: list, description: str):
    """Plot only the named planets and the Sun — nothing else."""

    PLANET_DATA = {
        'mercury': dict(a=0.387, e=0.206, color='#b5b5b5', label='Mercury'),
        'venus':   dict(a=0.723, e=0.007, color='#e8cda0', label='Venus'),
        'earth':   dict(a=1.000, e=0.017, color='#4fa3e0', label='Earth'),
        'mars':    dict(a=1.524, e=0.093, color='#c1440e', label='Mars'),
        'jupiter': dict(a=5.203, e=0.049, color='#c88b3a', label='Jupiter'),
        'saturn':  dict(a=9.537, e=0.057, color='#e4d191', label='Saturn'),
        'uranus':  dict(a=19.19, e=0.046, color='#7de8e8', label='Uranus'),
        'neptune': dict(a=30.07, e=0.010, color='#4b70dd', label='Neptune'),
    }

    fig, ax = plt.subplots(figsize=(8, 8), facecolor=LCARS_BG)
    ax.set_facecolor(LCARS_BG)
    ax.set_aspect('equal')

    # Sun
    ax.plot(0, 0, 'o', color='#ffeb3b', markersize=18, label='Sun', zorder=5)

    for name in planet_names:
        if name not in PLANET_DATA:
            continue
        d = PLANET_DATA[name]
        a, e = d['a'], d['e']
        b = a * math.sqrt(1 - e**2)
        c = a * e
        theta = np.linspace(0, 2 * math.pi, 500)
        x = a * np.cos(theta) - c
        y = b * np.sin(theta)
        ax.plot(x, y, color=d['color'], linewidth=1.5, alpha=0.7)
        ax.plot(a - c, 0, 'o', color=d['color'], markersize=8,
                label=d['label'], zorder=5)

    ax.legend(loc='upper right', facecolor=LCARS_BG,
              labelcolor=LCARS_ACCENT, fontsize=9)
    title = f"Orbits: {', '.join(p.capitalize() for p in planet_names)}"
    ax.set_title(title, color=LCARS_ACCENT, fontsize=13,
                 fontfamily='monospace', pad=10)
    ax.tick_params(colors=LCARS_DIM, labelsize=7)
    for spine in ax.spines.values():
        spine.set_color(LCARS_DIM)
    ax.grid(True, color=LCARS_GRID, linewidth=0.4, linestyle='--')

    return fig, title


def _parametric(desc: str):
    xm = re.search(r'x\s*=\s*([^\s,]+)', desc)
    ym = re.search(r'y\s*=\s*([^\s,]+)', desc)
    t  = np.linspace(0, 2 * math.pi, 5000)

    if xm and ym:
        try:
            x = eval(xm.group(1).replace('^', '**'), {'t': t, **_np_safe()})
            y = eval(ym.group(1).replace('^', '**'), {'t': t, **_np_safe()})
        except Exception:
            x, y = np.cos(t), np.sin(t)
    else:
        x = np.cos(t) * np.sin(3 * t)
        y = np.sin(t) * np.sin(3 * t)

    fig, ax = _base_fig()
    ax.plot(x, y, color=LCARS_ACCENT, linewidth=1.2, alpha=0.9)
    _finish(ax, 'Parametric Curve')
    return fig, 'Parametric Curve'


def _np_safe():
    return {name: getattr(np, name)
            for name in ['sin', 'cos', 'tan', 'exp', 'log', 'sqrt',
                         'pi', 'e', 'abs', 'linspace', 'array']}


def _best_guess(desc: str):
    """Last resort — infer drawing type from loose keywords."""
    if any(w in desc for w in ['planet', 'moon', 'solar']):
        return _solar_system(desc)
    if any(w in desc for w in ['wave', 'signal', 'frequency', 'hz']):
        return _sine_wave(desc)
    if 'fractal' in desc:
        return _koch_snowflake(desc)
    return _rose(desc)


# ── Smoke test ────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    def _log(msg): print(msg)
    print(f"WEB_IMAGES_DIR: {WEB_IMAGES_DIR}")
    result = plot_geometry("Lissajous figure a=3 b=2", log_callback=_log)
    print("Result:", result[:120])