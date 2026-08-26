#!/usr/bin/env python3
"""
Standalone DIESEL over/(under)-recovery card for the phone.
Runs in the cloud on GitHub Actions - completely independent of any computer.
Fetches the latest CEF daily basic fuel price PDF, extracts ONLY the diesel
over/(under)-recovery figures, and writes docs/index.html (published via
GitHub Pages). If no new file is found, it exits quietly and the page keeps
showing the last captured day.
"""
import datetime as dt
import io
import re
import sys
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent / "docs"
CEF_UPLOAD = "https://cefgroup.co.za/wp-content/uploads/{y}/{m:02d}/{name}"
LISTING_PAGES = [
    "https://cefgroup.co.za/price_type/daily-basic-fuel-price/",
    "https://cefgroup.co.za/daily-basic-fuel-price/",
]
HEADERS = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36")}
NUM = r"\(?-?[\d,]+\.\d+\)?"


def fetch_latest() -> bytes | None:
    s = requests.Session()
    s.headers.update(HEADERS)
    # try today and step back up to 6 weekdays
    d = dt.date.today()
    tried = 0
    while tried < 7:
        if d.weekday() < 5:
            for y, m in {(d.year, d.month),
                         ((d + dt.timedelta(days=31)).year, (d + dt.timedelta(days=31)).month)}:
                for name in (f"Daily-{d.day:02d}-{d.month:02d}-{d.year}.pdf",
                             f"Daily-{d.day}-{d.month}-{d.year}.pdf"):
                    try:
                        r = s.get(CEF_UPLOAD.format(y=y, m=m, name=name), timeout=30)
                        if r.ok and r.content[:5] == b"%PDF-":
                            print(f"fetched {name}")
                            return r.content
                    except requests.RequestException:
                        pass
            tried += 1
        d -= dt.timedelta(days=1)
    # fallback: scrape the listing pages for the newest Daily-*.pdf link
    rx = re.compile(r"[Dd]aily-(\d{1,2})-(\d{1,2})-(\d{4})[^\"']*\.pdf")
    found = {}
    for page in LISTING_PAGES:
        try:
            r = s.get(page, timeout=30)
            for href in re.findall(r'href=["\']([^"\']+\.pdf)["\']', r.text if r.ok else ""):
                mm = rx.search(href)
                if mm:
                    dd, mo, yy = (int(x) for x in mm.groups())
                    try:
                        found[dt.date(yy, mo, dd)] = href
                    except ValueError:
                        pass
        except requests.RequestException:
            pass
    if found:
        url = found[max(found)]
        if url.startswith("/"):
            url = "https://cefgroup.co.za" + url
        try:
            r = s.get(url, timeout=30)
            if r.ok and r.content[:5] == b"%PDF-":
                print(f"fetched via listing: {url}")
                return r.content
        except requests.RequestException:
            pass
    return None


def nums(text, label, count):
    m = re.search(label + r"[\s\-:]*((?:" + NUM + r"[\s]+){%d})" % (count - 1) + "(" + NUM + ")",
                  text, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    out = []
    for t in re.findall(NUM, m.group(0))[-count:]:
        v = float(t.strip("()").replace(",", ""))
        out.append(-v if t.startswith("(") else v)
    return out


def parse(blob: bytes) -> dict | None:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    text = re.sub(r"[ \t]+", " ", text)
    m = re.search(r"BASIC FUEL PRICE\s*-\s*(\d{2}/\d{2}/\d{4})", text)
    if not m:
        return None
    date = dt.datetime.strptime(m.group(1), "%d/%m/%Y").date()
    ur = nums(text, r"UNIT OVER/\(UNDER\) RECOVERY\s*-\s*\d{2}/\d{2}/\d{4}", 5)
    avg = nums(text, r"AVERAGE UNIT OVER/\(UNDER\) RECOVERY\s+\d{2}/\d{2}/\d{4}\s*-\s*\d{2}/\d{2}/\d{4}", 5)
    contrib = nums(text, r"CONTRIBUTION TO BFP[\s\S]{0,40}?\d{2}/\d{2}/\d{4}", 5)
    bfp = nums(text, r"BASIC FUEL PRICE\s*-\s*\d{2}/\d{2}/\d{4}", 5)
    if not (ur and avg and bfp and contrib):
        return None
    # consistency + sanity: refuse to publish nonsense
    for i in (2, 3):
        if abs((contrib[i] - bfp[i]) - ur[i]) > 0.02 or abs(ur[i]) > 1500 or abs(avg[i]) > 1500:
            print("consistency/sanity check failed - not publishing")
            return None
    return {"date": date, "d005": ur[2], "d0005": ur[3], "a005": avg[2], "a0005": avg[3]}


def card(v):
    return (f'<div class="num" style="color:{"#ff5252" if v < 0 else "#2ecc71"}">{v:,.3f}</div>'
            f'<div class="tag" style="color:{"#ff5252" if v < 0 else "#2ecc71"}">'
            f'{"UNDER" if v < 0 else "OVER"}-RECOVERY&nbsp;c/l</div>')


def publish(d: dict) -> None:
    OUT.mkdir(exist_ok=True)
    stamp = d["date"].strftime("%A %d %B %Y")
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="apple-touch-icon" href="icon.png">
<title>Diesel Recovery</title><style>
body{{background:#0f1f3d;color:#eef2f8;font-family:-apple-system,Helvetica,Arial,sans-serif;
     margin:0;padding:34px 18px;text-align:center}}
h1{{font-size:18px;font-weight:600;margin:0 0 2px;color:#9fb4d8;letter-spacing:1px}}
.d{{font-size:13px;color:#6f84a8;margin-bottom:26px}}
.card{{background:#16294f;border-radius:18px;padding:22px 12px;margin:0 0 16px}}
.grade{{font-size:15px;color:#9fb4d8;margin-bottom:8px;letter-spacing:.5px}}
.num{{font-size:46px;font-weight:700;letter-spacing:-1px}}
.tag{{font-size:11px;letter-spacing:2px;margin-top:2px}}
.row{{display:flex;gap:12px}} .row .card{{flex:1}}
.small .num{{font-size:28px}}
.sub{{font-size:12px;color:#6f84a8;margin-top:14px}}
</style></head><body>
<h1>DIESEL OVER / (UNDER) RECOVERY</h1>
<div class="d">{stamp}</div>
<div class="card"><div class="grade">DIESEL 0.05% &middot; TODAY</div>{card(d["d005"])}</div>
<div class="card"><div class="grade">DIESEL 0.005% &middot; TODAY</div>{card(d["d0005"])}</div>
<div class="row">
<div class="card small"><div class="grade">0.05% &middot; PERIOD AVG</div>{card(d["a005"])}</div>
<div class="card small"><div class="grade">0.005% &middot; PERIOD AVG</div>{card(d["a0005"])}</div>
</div>
<div class="sub">negative = under-recovery = price-increase pressure<br>
source: CEF daily basic fuel price &middot; auto-updated weekdays</div>
</body></html>"""
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"published card for {d['date']}")


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--file":       # offline test
        blob = Path(sys.argv[2]).read_bytes()
    else:
        blob = fetch_latest()
        if blob is None:
            print("no file found - keeping previous card")
            return 0
    d = parse(blob)
    if d is None:
        print("parse failed - keeping previous card")
        return 0
    publish(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
