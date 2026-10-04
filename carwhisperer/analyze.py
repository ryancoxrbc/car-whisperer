"""Statistics and frequency content of a captured engine-speed recording."""
import json
import statistics

FRAME_RATE = 100.0   # 0618A001 is broadcast every 10 ms


def load_bursts(path: str) -> list[list[int]]:
    """A capture file is a list of bursts; each burst is a list of hex data strings."""
    with open(path) as fh:
        raw = json.load(fh)
    return [[int(f[4:8], 16) for f in burst if len(f) >= 16] for burst in raw]


def summary(bursts: list[list[int]]) -> dict:
    flat = [r for b in bursts for r in b]
    changes = sum(1 for b in bursts for i in range(1, len(b)) if b[i] != b[i - 1])
    return {
        "frames": len(flat), "min": min(flat), "max": max(flat),
        "mean": statistics.mean(flat), "stdev": statistics.pstdev(flat),
        "value_changes_per_second": changes / (len(flat) / FRAME_RATE),
        "largest_drop_between_frames": max((b[i - 1] - b[i] for b in bursts for i in range(1, len(b))), default=0),
    }


def spectrum(bursts: list[list[int]], n: int = 960):
    """Amplitude spectrum averaged over bursts (Hann window). Returns (freqs, amplitude in rpm)."""
    import numpy as np
    power = None
    used = 0
    for b in bursts:
        if len(b) < n:
            continue
        x = np.array(b[:n], float)
        x -= x.mean()
        w = np.hanning(n)
        s = np.abs(np.fft.rfft(x * w)) * 2 / w.sum()
        power = s ** 2 if power is None else power + s ** 2
        used += 1
    if not used:
        raise ValueError("no burst is long enough")
    return np.fft.rfftfreq(n, 1 / FRAME_RATE), np.sqrt(power / used)


def engine_orders(bursts: list[list[int]]) -> dict:
    """Amplitude near each engine order that the broadcast rate can resolve."""
    import numpy as np
    f, a = spectrum(bursts)
    rot = statistics.mean(r for b in bursts for r in b) / 60          # crank rotations per second
    def band(lo, hi):
        m = (f >= lo) & (f <= hi)
        return float(np.sqrt((a[m] ** 2).sum()))
    background = float(np.median(a[(f > 3) & (f < 9) & (np.abs(f - rot / 2) > 0.6)]))
    return {
        "rotation_hz": rot,
        "below_2hz": band(0.1, 2.0),
        "half_order": band(rot / 2 - 0.4, rot / 2 + 0.4),
        "half_order_peak": float(a[np.abs(f - rot / 2) < 0.4].max()),
        "first_order": band(rot - 0.4, rot + 0.4),
        "background_3_to_9hz": background,
    }


def plots(bursts: list[list[int]], outdir: str):
    """Write three SVG charts: trace, histogram, spectrum."""
    import collections
    import os
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(outdir, exist_ok=True)
    blue, ink, muted, grid = "#2a78d6", "#12161b", "#5d6772", "#e3e7eb"
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": grid, "axes.labelcolor": muted, "text.color": ink,
                         "xtick.color": muted, "ytick.color": muted, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.grid": True, "grid.color": grid, "svg.fonttype": "none"})
    flat = [r for b in bursts for r in b]
    mean = statistics.mean(flat)

    fig, ax = plt.subplots(figsize=(9, 3))
    t = [i * 10 + j / len(b) * 10 for i, b in enumerate(bursts) for j in range(len(b))]
    ax.plot(t, flat, color=blue, lw=0.7)
    ax.axhline(mean, color=ink, lw=0.8, ls="--")
    ax.annotate(f"mean {mean:.0f} rpm", (t[-1], mean), xytext=(0, 22), textcoords="offset points", ha="right", color=ink)
    ax.set(xlabel="seconds (bursts shown end to end)", ylabel="rpm", ylim=(min(flat) - 20, max(flat) + 20), xlim=(0, t[-1]))
    ax.set_title("Engine speed at warm idle, from CAN frame 0618A001", loc="left", fontweight="bold")
    fig.savefig(f"{outdir}/idle-trace.svg", bbox_inches="tight", facecolor="white"); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 2.8))
    h = collections.Counter(flat)
    ax.bar(list(h), list(h.values()), width=0.8, color=blue)
    ax.grid(axis="x", visible=False)
    ax.set(xlabel="rpm", ylabel="frames")
    ax.set_title("Distribution of idle speed", loc="left", fontweight="bold")
    fig.savefig(f"{outdir}/idle-histogram.svg", bbox_inches="tight", facecolor="white"); plt.close(fig)

    f, a = spectrum(bursts)
    keep = (f >= 0.1) & (f <= 12.5)
    rot = mean / 60
    fig, ax = plt.subplots(figsize=(9, 3))
    ax.fill_between(f[keep], a[keep], color=blue, alpha=0.15)
    ax.plot(f[keep], a[keep], color=blue, lw=1.6)
    peak = float(a[abs(f - rot / 2) < 0.4].max())
    ax.annotate(f"half engine order, {rot / 2:.1f} Hz", (rot / 2, peak), xytext=(0, 26), textcoords="offset points",
                ha="center", color=ink, arrowprops={"arrowstyle": "-", "color": ink, "lw": 0.8})
    ax.annotate("idle speed control", (0.3, float(a[keep].max())), xytext=(14, -2), textcoords="offset points", color=ink)
    ax.set(xlabel="frequency of the speed fluctuation, Hz", ylabel="amplitude, ± rpm", xlim=(0, 12.5), ylim=(0, None))
    ax.set_title("Spectrum of idle speed", loc="left", fontweight="bold")
    fig.savefig(f"{outdir}/idle-spectrum.svg", bbox_inches="tight", facecolor="white"); plt.close(fig)
