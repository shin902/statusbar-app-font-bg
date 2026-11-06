#!/usr/bin/env python3
"""Icon pipeline for sketchybar-app-font-bg.

  icons.py missing                      open apps (from SketchyBar) with no mapping
  icons.py make <slug> --app <App.app>  fetch icon -> monochrome target -> potrace SVG -> compare
  icons.py apply <slug> "App Name"...   copy the passing SVG to svgs/ and write mappings/
  icons.py verify <slug>...             compare glyphs inside the built TTF (run after pnpm run build)

Work files go to .icon-work/<slug>/ (gitignored). Requires: resvg, potrace, swiftc, Pillow, numpy, fontTools.
"""
import argparse, fnmatch, json, os, re, shlex, shutil, subprocess, sys, tempfile
import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "../.."))
WORK = os.path.join(ROOT, ".icon-work")
TEMPLATE = os.path.join(ROOT, "assets/template/template.svg")
FONT = os.path.join(ROOT, "public/dist/sketchybar-app-font-bg.ttf")
SKETCHYBAR = os.environ.get("SKETCHYBAR_CONFIG", os.path.expanduser("~/.config/sketchybar"))
HEADER = ('<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" '
          'style="fill-rule:evenodd;clip-rule:evenodd;stroke-linejoin:round;stroke-miterlimit:2" '
          'viewBox="0 0 100 100">')

# PASS thresholds. SVG stage is strict; the glyph stage allows for the font's 1000-unit grid
# rounding and cubic->quadratic conversion (pure 1px edge noise, invisible at bar size).
SVG_MAX_MISMATCH, SVG_MIN_IOU = 0.5, 0.98
GLYPH_SIZE, GLYPH_MAX_MISMATCH, GLYPH_MIN_IOU = None, 1.0, 0.98  # None = target resolution


# ---------------------------------------------------------------- helpers
def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def appicon_bin():
    src = os.path.join(HERE, "appicon.swift")
    out = os.path.join(WORK, "bin", "appicon")
    if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(src):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        run(["swiftc", "-O", src, "-o", out])
    return out


def squircle(size):
    path = os.path.join(WORK, f"squircle_{size}.png")
    if not os.path.exists(path):
        os.makedirs(WORK, exist_ok=True)
        run(["resvg", "-w", str(size), "-h", str(size), TEMPLATE, path])
    return np.array(Image.open(path).convert("RGBA"))[:, :, 3] > 127


def erode(mask, r):
    if r <= 0:
        return mask
    img = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(2 * r + 1))
    return np.array(img) > 127


def otsu(values):
    hist, _ = np.histogram(values, bins=256, range=(0, 256))
    total, sum_all = values.size, np.dot(np.arange(256), hist)
    w_b = sum_b = 0.0
    best, best_t = -1.0, 128
    for t in range(256):
        w_b += hist[t]
        if w_b == 0 or w_b == total:
            continue
        sum_b += t * hist[t]
        m_b, m_f = sum_b / w_b, (sum_all - sum_b) / (total - w_b)
        var = w_b * (total - w_b) * (m_b - m_f) ** 2
        if var > best:
            best, best_t = var, t
    return best_t


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def mapping_patterns():
    pats = []
    for f in os.listdir(os.path.join(ROOT, "mappings")):
        if f.startswith("."):
            continue
        for p in open(os.path.join(ROOT, "mappings", f)).read().split("|"):
            pats.append((p.strip().strip('"'), f))
    return pats


# ---------------------------------------------------------------- missing
def cmd_missing(a):
    out = run([os.path.join(SKETCHYBAR, "helpers/window_manager.sh"), "list"],
              capture_output=True, text=True).stdout
    apps = sorted({x for line in out.splitlines() if len(line.split("\t")) >= 6
                   for x in line.split("\t")[5].split("\x1f") if x})
    running = {}
    for line in run([appicon_bin(), "list"], capture_output=True, text=True).stdout.splitlines():
        name, _, path = line.partition("\t")
        running.setdefault(name, path)
    pats = mapping_patterns()
    rows = []
    for app in apps:
        hit = [f for p, f in pats if fnmatch.fnmatchcase(app, p)]
        if hit:
            if a.all:
                print(f"ok\t{app}\t{hit[0]}")
            continue
        path = running.get(app, "")
        slug = slugify(os.path.basename(path)[:-4]) if path.endswith(".app") else slugify(app)
        rows.append({"app": app, "path": path, "slug": slug})
        print(f"missing\t{app}\t{path or '(bundle not found)'}\t{slug}")
    if a.json:
        json.dump(rows, open(a.json, "w"), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- make
def make_target(icon, d, size, threshold, edge, polarity):
    im = Image.open(icon).convert("RGBA")
    ys, xs = np.where(np.array(im)[:, :, 3] > 200)
    crop = im.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    crop = crop.resize((size, size), Image.Resampling.LANCZOS)
    crop.save(os.path.join(d, "crop.png"))
    rgba = np.array(crop).astype(float)
    lum = 0.2126 * rgba[:, :, 0] + 0.7152 * rgba[:, :, 1] + 0.0722 * rgba[:, :, 2]
    sq = squircle(size)
    e = int(round(size * edge / 100))
    inner = erode(sq, e)
    t = threshold if threshold is not None else otsu(lum[inner].astype(np.uint8))
    bg = float(np.median(lum[inner & ~erode(inner, max(4, e))]))
    if polarity == "auto":
        polarity = "dark" if bg > t else "light"
    logo = ((lum <= t) if polarity == "dark" else (lum > t)) & inner
    Image.fromarray(np.where(logo, 0, 255).astype(np.uint8)).convert("1").save(os.path.join(d, "mask.pbm"))
    Image.fromarray(np.where(sq & ~logo, 0, 255).astype(np.uint8)).save(os.path.join(d, "target.png"))
    return {"threshold": t, "background_lum": bg, "polarity": polarity,
            "logo_pct": float(logo.sum() / sq.sum() * 100)}


TOK = re.compile(r"[MmLlCcZz]|-?\d*\.?\d+(?:e-?\d+)?")


def parse_path(d, tf=(0, 0, 1, 1), k=1.0):
    """M/L/C/Z path data (abs or rel) -> subpaths of absolute segments, mapped by tf then scaled by k."""
    tx, ty, sx, sy = tf
    toks = TOK.findall(d)
    i, cur, start, cmd = 0, (0.0, 0.0), (0.0, 0.0), "M"
    subs, seg = [], None

    def pt(x, y, rel):
        return (cur[0] + x, cur[1] + y) if rel else (x, y)

    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                if seg:
                    subs.append(seg)
                seg, cur = None, start
            continue
        rel, c = cmd.islower(), cmd.lower()
        if c == "m":
            p = pt(float(toks[i]), float(toks[i + 1]), rel)
            i += 2
            if seg:
                subs.append(seg)
            seg, cur, start = [("M", [p])], p, p
            cmd = "l" if rel else "L"
        elif c == "l":
            p = pt(float(toks[i]), float(toks[i + 1]), rel)
            i += 2
            seg.append(("L", [p]))
            cur = p
        elif c == "c":
            v = [float(x) for x in toks[i:i + 6]]
            i += 6
            ps = [pt(v[0], v[1], rel), pt(v[2], v[3], rel), pt(v[4], v[5], rel)]
            seg.append(("C", ps))
            cur = ps[2]
    if seg:
        subs.append(seg)
    m = lambda p: ((tx + sx * p[0]) * k, (ty + sy * p[1]) * k)
    return [[(c, [m(p) for p in ps]) for c, ps in s] for s in subs]


def area(sub):
    pts = [sub[0][1][0]] + [ps[-1] for _, ps in sub[1:]]
    return sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts))) / 2


def reverse(sub):
    pts = [sub[0][1][0]] + [ps[-1] for _, ps in sub[1:]]
    out = [("M", [pts[-1]])]
    for j in range(len(sub) - 1, 0, -1):
        c, ps = sub[j]
        out.append(("C", [ps[1], ps[0], pts[j - 1]]) if c == "C" else ("L", [pts[j - 1]]))
    return out


def fmt(sub):
    f = lambda v: ("%.3f" % v).rstrip("0").rstrip(".")
    return "".join(c + " ".join(f"{f(x)},{f(y)}" for x, y in ps) for c, ps in sub) + "Z"


def trace(mask, out_svg, potrace_args):
    size = Image.open(mask).size[0]
    svg = run(["potrace", "-s", "-o", "-", *potrace_args, mask], capture_output=True, text=True).stdout
    tf = tuple(map(float, re.search(
        r'transform="translate\(([-\d.]+),([-\d.]+)\) scale\(([-\d.]+),([-\d.]+)\)"', svg).groups()))
    subs = [s for d in re.findall(r'\sd="([^"]+)"', svg) for s in parse_path(d, tf, 100.0 / size)]
    tpl = re.search(r'<path d="([^"]+)"', open(TEMPLATE).read()).group(1)
    tpl_sign = 1 if area(max(parse_path(tpl), key=lambda s: abs(area(s)))) > 0 else -1
    if subs:
        outer_sign = 1 if area(max(subs, key=lambda s: abs(area(s)))) > 0 else -1
        if outer_sign == tpl_sign:  # logo outer contours must oppose the squircle -> holes under nonzero
            subs = [reverse(s) for s in subs]
    open(out_svg, "w").write(f'{HEADER}<path d="{tpl}{"".join(fmt(s) for s in subs)}"/></svg>\n')
    return len(subs)


def render(svg_text, size, out):
    # force nonzero: TrueType fills nonzero, so holes must survive it
    svg_text = re.sub(r"fill-rule:\s*evenodd", "fill-rule:nonzero", svg_text)
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as f:
        f.write(svg_text)
    try:
        run(["resvg", "-w", str(size), "-h", str(size), "--background", "white", f.name, out])
    finally:
        os.unlink(f.name)
    return np.array(Image.open(out).convert("L")) < 128


def compare(d, svg_text, out_dir, size=None):
    os.makedirs(out_dir, exist_ok=True)
    timg = Image.open(os.path.join(d, "target.png")).convert("L")
    size = size or timg.size[0]
    tgt = np.array(timg.resize((size, size), Image.Resampling.LANCZOS)) < 128
    ren = render(svg_text, size, os.path.join(out_dir, "render.png"))
    extra, missing = ren & ~tgt, tgt & ~ren
    mismatch = float((extra.sum() + missing.sum()) / max(1, (tgt | ren).sum()) * 100)
    sq = squircle(size)
    lt, lr = sq & ~tgt, sq & ~ren
    iou = float((lt & lr).sum() / max(1, (lt | lr).sum()))
    diff = np.full(tgt.shape + (3,), 255, np.uint8)
    diff[tgt & ren], diff[extra], diff[missing] = (60, 60, 60), (230, 30, 30), (30, 90, 240)
    Image.fromarray(diff).save(os.path.join(out_dir, "diff.png"))
    c = Image.open(os.path.join(d, "crop.png")).convert("RGBA").resize((size, size))
    bg = Image.new("RGBA", c.size, (136, 136, 136, 255))
    bg.alpha_composite(c)
    tiles = [bg.convert("RGB"), Image.fromarray(np.where(tgt, 0, 255).astype(np.uint8)).convert("RGB"),
             Image.open(os.path.join(out_dir, "render.png")).convert("RGB"), Image.fromarray(diff)]
    sheet = Image.new("RGB", (size * 4 + 24, size), (255, 255, 255))
    for i, t in enumerate(tiles):
        sheet.paste(t, (i * (size + 8), 0))
    sheet.save(os.path.join(out_dir, "sheet.png"))
    return {"mismatch": mismatch, "logo_iou": iou, "extra": int(extra.sum()), "missing": int(missing.sum()),
            "sheet": os.path.join(out_dir, "sheet.png")}


def report(name, r, max_mm, min_iou):
    ok = r["mismatch"] < max_mm and r["logo_iou"] >= min_iou
    print(f"{name}: mismatch={r['mismatch']:.3f}% (<{max_mm}) logo_iou={r['logo_iou']:.4f} (>={min_iou}) "
          f"extra={r['extra']} missing={r['missing']} -> {'PASS' if ok else 'FAIL'}\n  sheet: {r['sheet']}")
    return ok


def cmd_make(a):
    d = os.path.join(WORK, a.slug)
    os.makedirs(d, exist_ok=True)
    icon = os.path.join(d, "icon.png")
    if a.icon:
        shutil.copy(a.icon, icon)
    elif a.app:
        run([appicon_bin(), "icon", a.app, icon, "1024"])
    elif not os.path.exists(icon):
        sys.exit("need --app <App.app> or --icon <png> on first run")
    info = make_target(icon, d, a.size, a.threshold, a.edge, a.polarity)
    print(f"target: threshold={info['threshold']:.1f} bg_lum={info['background_lum']:.1f} "
          f"polarity={info['polarity']} logo={info['logo_pct']:.1f}% of squircle")
    n = trace(os.path.join(d, "mask.pbm"), os.path.join(d, "cand.svg"), shlex.split(a.potrace))
    svg = open(os.path.join(d, "cand.svg")).read()
    print(f"svg: {n} logo contours, {len(svg)} bytes")
    r = compare(d, svg, os.path.join(d, "cmp"))
    ok = report(a.slug, r, SVG_MAX_MISMATCH, SVG_MIN_IOU)
    params = {k: getattr(a, k) for k in ("size", "threshold", "edge", "polarity", "potrace")}
    json.dump({"pass": ok, "params": params, "target": info, **r},
              open(os.path.join(d, "result.json"), "w"), indent=2)
    return 0 if ok else 1


# ---------------------------------------------------------------- apply / verify
def cmd_apply(a):
    d = os.path.join(WORK, a.slug)
    res = json.load(open(os.path.join(d, "result.json")))
    if not res["pass"] and not a.force:
        sys.exit(f"{a.slug}: last make did not PASS (use --force after visual review)")
    shutil.copy(os.path.join(d, "cand.svg"), os.path.join(ROOT, "svgs", f"-{a.slug}-.svg"))
    with open(os.path.join(ROOT, "mappings", f"-{a.slug}-"), "w") as f:
        f.write(" | ".join(f'"{n}"' for n in a.names))
    print(f"wrote svgs/-{a.slug}-.svg and mappings/-{a.slug}-")


def glyph_svg(ft, name):
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.svgPathPen import SVGPathPen
    gs = ft.getGlyphSet()
    hits = [g for g in ft.getGlyphOrder() if g.strip(":-") == name]
    if not hits:
        return None
    bp = BoundsPen(gs)
    gs[hits[0]].draw(bp)
    x0, y0, x1, y1 = bp.bounds
    pen = SVGPathPen(gs)
    gs[hits[0]].draw(pen)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {x1 - x0} {y1 - y0}" style="fill-rule:nonzero">'
            f'<g transform="translate({-x0},{y1}) scale(1,-1)"><path d="{pen.getCommands()}"/></g></svg>')


def cmd_verify(a):
    from fontTools.ttLib import TTFont
    ft = TTFont(FONT)
    ok_all = True
    for slug in a.slugs:
        svg_path = os.path.join(ROOT, "svgs", f"-{slug}-.svg")
        if os.path.getmtime(FONT) < os.path.getmtime(svg_path):
            sys.exit(f"{FONT} is older than {svg_path}; run pnpm run build first")
        g = glyph_svg(ft, slug)
        if g is None:
            print(f"{slug}: glyph not found in font -> FAIL")
            ok_all = False
            continue
        r = compare(os.path.join(WORK, slug), g, os.path.join(WORK, slug, "glyph"), GLYPH_SIZE)
        ok_all &= report(slug, r, GLYPH_MAX_MISMATCH, GLYPH_MIN_IOU)
    return 0 if ok_all else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("missing")
    p.add_argument("--all", action="store_true", help="also print mapped apps")
    p.add_argument("--json", help="write missing apps to this JSON file")
    p = sub.add_parser("make")
    p.add_argument("slug")
    p.add_argument("--app", help="path to App.app (first run)")
    p.add_argument("--icon", help="use this PNG instead of the app icon")
    p.add_argument("--size", type=int, default=512, help="target resolution (1024 for fine line art)")
    p.add_argument("--threshold", type=float, help="luminance threshold (default: Otsu)")
    p.add_argument("--edge", type=float, default=4.0, help="%% of size at the rim forced to background")
    p.add_argument("--polarity", default="auto", choices=["auto", "dark", "light"])
    p.add_argument("--potrace", default="", help='extra potrace args, e.g. "-t 4 -a 1.0 -O 0.2"')
    p = sub.add_parser("apply")
    p.add_argument("slug")
    p.add_argument("names", nargs="+", help="app names / bash case patterns for mappings")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("verify")
    p.add_argument("slugs", nargs="+")
    a = ap.parse_args()
    return {"missing": cmd_missing, "make": cmd_make, "apply": cmd_apply, "verify": cmd_verify}[a.cmd](a) or 0


if __name__ == "__main__":
    sys.exit(main())
