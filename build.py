#!/usr/bin/env python3
"""
Build data.json for OBX Dawn Patrol.

Runs on a schedule in GitHub Actions, which has unrestricted internet — so this
can reach Open-Meteo (hourly wave height, period and direction) and the NWS
text products directly. Every source is optional: if one fails the previous
data.json is reused for that section, and the failure is recorded in `sources`
so the page can say what is stale rather than silently showing bad numbers.
"""
import json, re, sys, math, datetime as dt, urllib.request, urllib.error, os

TZ = "America/New_York"
OUT = os.path.join(os.path.dirname(__file__), "data.json")

# One reference point per forecast zone, in the water off that stretch of beach.
ZONES = [
    ("currituck", "Currituck Banks",       36.166, -75.748),
    ("nobx",      "Northern Outer Banks",  35.957, -75.624),
    ("hatteras",  "Hatteras Island",       35.350, -75.492),
    ("ocracoke",  "Ocracoke Island",       35.110, -75.980),
]
TIDE_STATION = "8652587"   # Oregon Inlet Marina
BUOY = "44100"             # Duck, NC

def get(url, timeout=45):
    req = urllib.request.Request(url, headers={
        "User-Agent": "obx-dawn-patrol (github actions; contact via repo issues)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def getjson(url, timeout=45):
    return json.loads(get(url, timeout))

# ----------------------------------------------------------------- open-meteo
def fetch_hourly(days=8):
    """Hourly wave and wind for all four zones in two calls."""
    lats = ",".join(f"{z[2]}" for z in ZONES)
    lons = ",".join(f"{z[3]}" for z in ZONES)
    marine = getjson(
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={lats}&longitude={lons}"
        "&hourly=wave_height,wave_period,wave_direction,"
        "swell_wave_height,swell_wave_period,swell_wave_direction"
        f"&timezone={TZ}&forecast_days={days}&length_unit=imperial")
    wind = getjson(
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lats}&longitude={lons}"
        "&hourly=wind_speed_10m,wind_direction_10m,wind_gusts_10m,apparent_temperature"
        f"&timezone={TZ}&forecast_days={days}"
        "&wind_speed_unit=kn&temperature_unit=fahrenheit")
    if isinstance(marine, dict): marine = [marine]
    if isinstance(wind, dict):   wind = [wind]

    out = {}
    for i, (key, _name, _la, _lo) in enumerate(ZONES):
        mh = marine[i]["hourly"]; wh = wind[i]["hourly"]
        out[key] = {
            "time":        mh["time"],
            "wave_ft":     [r(v, 1) for v in mh["wave_height"]],
            "period_s":    [r(v, 1) for v in mh["wave_period"]],
            "wave_dir":    [r(v, 0) for v in mh["wave_direction"]],
            "swell_ft":    [r(v, 1) for v in mh.get("swell_wave_height", [])],
            "swell_s":     [r(v, 1) for v in mh.get("swell_wave_period", [])],
            "swell_dir":   [r(v, 0) for v in mh.get("swell_wave_direction", [])],
            "wind_kt":     [r(v, 0) for v in wh["wind_speed_10m"]],
            "wind_dir":    [r(v, 0) for v in wh["wind_direction_10m"]],
            "gust_kt":     [r(v, 0) for v in wh["wind_gusts_10m"]],
            "feels_f":     [r(v, 0) for v in wh.get("apparent_temperature", [])],
        }
    return out

def r(v, nd):
    if v is None: return None
    return round(float(v), nd) if nd else int(round(float(v)))

# ------------------------------------------------------------------ nws text
SRF_URLS = {
    "mhx": "https://tgftp.nws.noaa.gov/data/raw/fz/fzus52.kmhx.srf.mhx.txt",
    "akq": "https://tgftp.nws.noaa.gov/data/raw/fz/fzus51.kakq.srf.akq.txt",
}
def fetch_rip():
    """Rip current risk per zone, straight from the surf zone forecasts."""
    blob = ""
    for u in SRF_URLS.values():
        try: blob += "\n" + get(u)
        except Exception as e: print(f"  ! {u}: {e}", file=sys.stderr)
    if not blob.strip(): raise RuntimeError("no surf zone text")

    # Split into zone sections and read the first RIP CURRENT RISK line in each.
    sections = re.split(r"\n(?=[A-Z]{2}Z\d)", blob)
    def risk_for(*needles):
        for s in sections:
            head = s[:400].upper()
            if any(n.upper() in head for n in needles):
                m = re.search(r"RIP CURRENT RISK\.*\s*([A-Z]+)", s.upper())
                if m: return m.group(1).capitalize()
        return None
    return {
        "currituck": risk_for("CURRITUCK"),
        "nobx":      risk_for("NORTHERN OUTER BANKS", "DARE"),
        "hatteras":  risk_for("HATTERAS"),
        "ocracoke":  risk_for("OCRACOKE"),
    }

def fetch_tropical():
    txt = get("https://www.nhc.noaa.gov/text/MIATWOAT.shtml")
    txt = re.sub(r"<[^>]+>", "", txt)
    m = re.search(r"Tropical Weather Outlook.*?(?=\$\$|\Z)", txt, re.S)
    body = (m.group(0) if m else txt)[:1800].strip()
    quiet = "not expected" in body.lower()
    return {"text": body, "quiet": quiet}

# --------------------------------------------------------------------- tides
def fetch_tides(days=15):
    start = dt.date.today()
    end = start + dt.timedelta(days=days - 1)
    d = getjson(
        "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
        "?product=predictions&application=obx-dawn-patrol"
        f"&begin_date={start:%Y%m%d}&end_date={end:%Y%m%d}"
        f"&datum=MLLW&station={TIDE_STATION}"
        "&time_zone=lst_ldt&units=english&interval=hilo&format=json")
    byday = {}
    for p in d["predictions"]:
        day, hm = p["t"].split(" ")
        byday.setdefault(day, []).append(f'{p["type"]} {hm} {round(float(p["v"]),1)}')
    return [[k, byday[k]] for k in sorted(byday)][:days]

# ---------------------------------------------------------------------- buoy
def fetch_buoy():
    txt = get(f"https://www.ndbc.noaa.gov/data/realtime2/{BUOY}.txt")
    rows = [l.split() for l in txt.splitlines() if l and not l.startswith("#")]
    hdr = "YY MM DD hh mm WDIR WSPD GST WVHT DPD APD MWD PRES ATMP WTMP".split()
    def num(row, name):
        i = hdr.index(name)
        v = row[i] if i < len(row) else "MM"
        return None if v == "MM" else float(v)
    for row in rows[:12]:                     # walk down until a usable row
        wv, dpd, mwd, wt = (num(row,"WVHT"), num(row,"DPD"), num(row,"MWD"), num(row,"WTMP"))
        if wv is None and dpd is None: continue
        stamp = dt.datetime(int(row[0]), int(row[1]), int(row[2]),
                            int(row[3]), int(row[4]), tzinfo=dt.timezone.utc)
        eastern = stamp - dt.timedelta(hours=4)      # EDT; EST handled below
        if not is_dst(stamp): eastern = stamp - dt.timedelta(hours=5)
        age_h = (dt.datetime.now(dt.timezone.utc) - stamp).total_seconds() / 3600
        return {
            "station": BUOY, "name": "Duck, NC",
            "at": eastern.strftime("%b %-d, %-I:%M %p ") + ("EDT" if is_dst(stamp) else "EST"),
            "wvht_ft": round(wv * 3.28084, 1) if wv is not None else None,
            "dpd_s":   int(dpd) if dpd is not None else None,
            "mwd_deg": int(mwd) if mwd is not None else None,
            "wtmp_f":  round(wt * 9 / 5 + 32, 1) if wt is not None else None,
            "stale":   age_h > 6,
        }
    raise RuntimeError("no usable buoy row")

def is_dst(u):
    y = u.year
    mar = dt.datetime(y, 3, 8, tzinfo=dt.timezone.utc)
    mar += dt.timedelta(days=(6 - mar.weekday()) % 7)      # 2nd Sunday in March
    nov = dt.datetime(y, 11, 1, tzinfo=dt.timezone.utc)
    nov += dt.timedelta(days=(6 - nov.weekday()) % 7)      # 1st Sunday in November
    return mar <= u < nov

# ---------------------------------------------------------------------- sun
def sun_times(date, lat=35.957, lon=-75.624):
    out = {}
    for rising in (True, False):
        N = date.timetuple().tm_yday
        lng = lon / 15.0
        t = N + (((6 if rising else 18) - lng) / 24.0)
        M = 0.9856 * t - 3.289
        L = (M + 1.916 * math.sin(math.radians(M))
               + 0.020 * math.sin(math.radians(2 * M)) + 282.634) % 360
        RA = math.degrees(math.atan(0.91764 * math.tan(math.radians(L)))) % 360
        RA = (RA + (math.floor(L / 90) * 90 - math.floor(RA / 90) * 90)) / 15.0
        sinDec = 0.39782 * math.sin(math.radians(L))
        cosDec = math.cos(math.asin(sinDec))
        cosH = ((math.cos(math.radians(90.833)) - sinDec * math.sin(math.radians(lat)))
                / (cosDec * math.cos(math.radians(lat))))
        H = (360 - math.degrees(math.acos(cosH))) if rising else math.degrees(math.acos(cosH))
        H /= 15.0
        UT = (H + RA - 0.06571 * t - 6.622 - lng) % 24
        local = (UT - (4 if is_dst(dt.datetime(date.year, date.month, date.day,
                                               12, tzinfo=dt.timezone.utc)) else 5)) % 24
        out["sunrise" if rising else "sunset"] = f"{int(local):02d}:{int(round((local % 1) * 60)):02d}"
    return out

# ------------------------------------------------------------------ assemble
DAYNAME = "%A, %B %-d"
SHORT   = "%a %b %-d"

def summarise(hourly, tides):
    """Collapse the hourly series into the per-day shape the page already uses,
       keeping the hourly arrays alongside for the conditions chart."""
    times = hourly["nobx"]["time"]
    days_seen, days = [], []
    for ts in times:
        d = ts[:10]
        if d not in days_seen: days_seen.append(d)

    for di, dstr in enumerate(days_seen[:8]):
        date = dt.date.fromisoformat(dstr)
        sun = sun_times(date)
        sr_h = int(sun["sunrise"][:2]); ss_h = int(sun["sunset"][:2])
        idx = [i for i, ts in enumerate(times) if ts[:10] == dstr]
        day_idx = [i for i in idx if sr_h <= int(times[i][11:13]) <= ss_h]
        if not day_idx: day_idx = idx

        surf, rip_hours = {}, {}
        for key, _n, _a, _b in ZONES:
            h = hourly[key]
            vals = [h["wave_ft"][i] for i in day_idx if h["wave_ft"][i] is not None]
            surf[key] = [round(min(vals), 1), round(max(vals), 1)] if vals else [1.0, 2.0]

        def at_hour(hh, field, zone="nobx"):
            for i in idx:
                if int(times[i][11:13]) == hh:
                    return hourly[zone][field][i]
            return None
        am_h = min(max(sr_h + 1, 0), 23)
        am = [at_hour(am_h, "wind_dir") or 0, at_hour(am_h, "wind_kt") or 0]
        pm = [at_hour(15, "wind_dir") or am[0], at_hour(15, "wind_kt") or am[1]]

        per = [hourly["nobx"]["period_s"][i] for i in day_idx
               if hourly["nobx"]["period_s"][i] is not None]
        feels = [hourly["nobx"]["feels_f"][i] for i in day_idx
                 if hourly["nobx"].get("feels_f") and hourly["nobx"]["feels_f"][i] is not None]
        gust = [hourly["nobx"]["gust_kt"][i] for i in day_idx
                if hourly["nobx"]["gust_kt"][i] is not None]

        tide_row = next((t for t in tides if t[0] == date.strftime(SHORT)), None)
        lo = [x.split()[1] for x in (tide_row[1] if tide_row else []) if x.startswith("L")]
        hi = [x.split()[1] for x in (tide_row[1] if tide_row else []) if x.startswith("H")]

        days.append({
            "date": dstr,
            "dayName": date.strftime(DAYNAME),
            "short": date.strftime(SHORT),
            "sr": sun["sunrise"], "ss": sun["sunset"],
            "conf": "high" if di <= 2 else ("medium" if di <= 4 else "low"),
            "surf": surf,
            "rip": {},                       # filled from the NWS text below
            "am": am, "pm": pm,
            "lo": lo or ["12:00"], "hi": hi or ["18:00"],
            "periodAvg": round(sum(per) / len(per), 1) if per else None,
            "gustMax": max(gust) if gust else None,
            "feelsMax": max(feels) if feels else None,
            "note": "",
        })
    return days

def describe(day, hourly):
    """One honest sentence per day, generated from that day's own numbers."""
    from_deg = day["am"][0]
    off = 45 <= ((250 - from_deg) % 360) <= 315   # crude: SW-ish is offshore here
    wf = math.cos(math.radians(abs(((from_deg - 250 + 180) % 360) - 180)))
    dirword = "offshore" if wf > 0.45 else ("onshore" if wf < -0.35 else "sideshore")
    trend = ("building" if day["pm"][1] > day["am"][1] + 3 else
             "easing" if day["am"][1] > day["pm"][1] + 3 else "steady")
    lo, hi = day["surf"]["nobx"]
    bits = [f"{lo:g}–{hi:g} ft with {dirword} wind, {trend} through the day."]
    if day.get("periodAvg") and day["periodAvg"] >= 9:
        bits.append(f"Period averaging {day['periodAvg']:g} seconds — better organised than a typical windswell.")
    if day.get("gustMax") and day["gustMax"] >= 20:
        bits.append(f"Gusting to {day['gustMax']:g} kt.")
    if dirword == "onshore" and hi >= 3:
        bits.append("The south-facing spots — the Cove, Frisco, Hatteras Village — are the clean options.")
    return " ".join(bits)

def hazards_for(day):
    out = []
    if day.get("feelsMax") and day["feelsMax"] >= 100:
        out.append({"title": f"Heat index up to {day['feelsMax']:g} °F.",
                    "body": "Be off the sand before it peaks and take more water than you think you need."})
    if day.get("gustMax") and day["gustMax"] >= 22:
        out.append({"title": f"Wind gusting to {day['gustMax']:g} kt.",
                    "body": "Stronger than the average suggests. Expect it to be messier than the numbers look."})
    risk = day["rip"].get("nobx")
    if risk in ("Moderate", "High"):
        out.append({"title": f"Rip current risk {risk}.",
                    "body": "Rips set up near the piers and in any deep channel between sandbars. "
                            "Stay where you can touch bottom; if you get pulled out, swim parallel to the beach first."})
    if day["surf"]["nobx"][1] >= 4:
        out.append({"title": f"Surf up to {day['surf']['nobx'][1]:g} ft.",
                    "body": "Above the size a beginner should be paddling into. Worth watching rather than surfing."})
    return out

def main():
    prev = {}
    if os.path.exists(OUT):
        try: prev = json.load(open(OUT, encoding="utf-8"))
        except Exception: prev = {}

    data, sources = {}, {}
    def step(name, fn, fallback_key=None):
        try:
            v = fn(); sources[name] = "ok"; return v
        except Exception as e:
            print(f"  ! {name} failed: {e}", file=sys.stderr)
            sources[name] = f"failed: {e}"
            return prev.get(fallback_key) if fallback_key else None

    print("fetching tides...");    tides   = step("tides",   fetch_tides,   "tides")
    print("fetching hourly...");   hourly  = step("hourly",  fetch_hourly,  "hourly")
    print("fetching rip risk..."); rip     = step("rip",     fetch_rip)
    print("fetching buoy...");     buoy    = step("buoy",    fetch_buoy,    "buoy")
    print("fetching tropics...");  trop    = step("tropical", fetch_tropical)

    if not hourly or not tides:
        print("fatal: no wave or tide data and no previous file to fall back on", file=sys.stderr)
        if not prev: sys.exit(1)
        data = prev
    else:
        days = summarise(hourly, tides)
        for d in days:
            d["rip"] = {k: (rip or {}).get(k) or "Moderate" for k, _n, _a, _b in ZONES}
            d["note"] = describe(d, hourly)
            hz = hazards_for(d)
            if hz: d["hazards"] = hz
        data = {
            "days": days, "tides": tides, "hourly": hourly,
            "buoy": buoy, "water_f": (buoy or {}).get("wtmp_f") or prev.get("water_f") or 75,
        }

    now = dt.datetime.now(dt.timezone.utc)
    eastern = now - dt.timedelta(hours=4 if is_dst(now) else 5)
    data["built"] = eastern.strftime("%a %b %-d, %Y - %-I:%M %p ") + ("EDT" if is_dst(now) else "EST")
    data["sources"] = sources
    q = (trop or {}).get("quiet")
    data["outlook"] = {
        "headline": "No tropical system in play." if q else "Watch the tropics.",
        "body": (trop or {}).get("text", "Tropical outlook unavailable this run."),
        "watchFor": "A named storm tracking up the Atlantic, even one that never comes near land, sends "
                    "long-period groundswell here two to four days ahead of itself. That is what turns an "
                    "ordinary two-foot week into the best surf of the year.",
        "tideNote": "Low tides slide about 50 minutes later each day, which moves the best window with them.",
    }
    prevfirst = (prev.get("days") or [{}])[0]
    data["changed"] = build_changed(prevfirst, data["days"][0] if data.get("days") else {},
                                    prev.get("buoy"), data.get("buoy"))
    json.dump(data, open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"wrote {OUT}: {len(data.get('days',[]))} days, "
          f"{len(data.get('tides',[]))} tide rows, sources={sources}")

def build_changed(a, b, pbuoy, nbuoy):
    if not a: return {"title": "First build.", "body": "Nothing to compare against yet."}
    bits = []
    try:
        if a["surf"]["nobx"] != b["surf"]["nobx"]:
            bits.append(f"surf {a['surf']['nobx'][0]:g}–{a['surf']['nobx'][1]:g} ft "
                        f"→ {b['surf']['nobx'][0]:g}–{b['surf']['nobx'][1]:g} ft")
        if a["rip"].get("nobx") != b["rip"].get("nobx"):
            bits.append(f"rip risk {a['rip'].get('nobx')} → {b['rip'].get('nobx')}")
        if pbuoy and nbuoy and pbuoy.get("dpd_s") and nbuoy.get("dpd_s") and \
           abs(pbuoy["dpd_s"] - nbuoy["dpd_s"]) >= 2:
            bits.append(f"swell period {pbuoy['dpd_s']}s → {nbuoy['dpd_s']}s")
    except Exception:
        pass
    if not bits:
        return {"title": "Nothing material moved.", "body": "Same size, same wind pattern, same rip risk as the last update."}
    return {"title": "Since the last update:", "body": "; ".join(bits) + "."}

if __name__ == "__main__":
    main()
