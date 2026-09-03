# OBX Dawn Patrol

A daily Outer Banks surf report. Every break from Corolla to Ocracoke, scored for
your skill level and your home base, with hour-by-hour conditions and two
recommended windows a day.

The site is a single static page. A scheduled job fetches fresh data three times
a day, writes `data.json`, and commits it. The page loads that file in the
browser. **No servers, no accounts, no cost.**

## Setup, about ten minutes

1. **Create a repository.** On GitHub, New repository → name it `obx-dawn-patrol`
   → Public → Create. (It must be public for free GitHub Pages.)
2. **Upload these files.** On the empty repo page click *uploading an existing file*,
   drag in everything from this folder — `index.html`, `data.json`, `build.py`,
   `favicon.svg`, `README.md`, and the `.github` folder — then Commit.
   If the `.github` folder does not survive the drag, create it by hand:
   *Add file → Create new file*, name it `.github/workflows/update.yml`, and paste
   the contents of that file in.
3. **Turn on Pages.** Settings → Pages → Source: *Deploy from a branch* →
   Branch: `main`, folder `/ (root)` → Save. After a minute your site is at
   `https://<your-username>.github.io/obx-dawn-patrol/`
4. **Allow the job to commit.** Settings → Actions → General → Workflow permissions
   → *Read and write permissions* → Save. Without this the job runs but cannot
   save what it fetched.
5. **Run it once now.** Actions tab → *Update surf data* → *Run workflow*.
   Give it a minute, then reload the site.

## How it works

`build.py` pulls from five sources and degrades gracefully — if one fails, that
section keeps the previous values and the page shows a banner saying which data
is stale. It never publishes silently-wrong numbers.

| Source | What it gives |
|---|---|
| Open-Meteo Marine | **hourly** wave height, period and direction, 8 days |
| Open-Meteo Forecast | hourly wind speed, direction, gusts, heat index |
| NWS surf zone forecasts (Newport + Wakefield) | official rip current risk per zone |
| NOAA CO-OPS station 8652587 | tide times and heights, 15 days |
| NDBC buoy 44100 (Duck) | live observed wave height, period, direction, water temp |
| National Hurricane Center | tropical outlook |

Everything else — ratings, the two daily windows, drive times, the hourly
conditions curve — is computed in the page from those inputs.

## Changing things

- **Schedule:** edit the `cron` line in `.github/workflows/update.yml`.
- **Home bases:** the `BASES` array near the top of the `<script>` in `index.html`.
- **Spots:** the `SPOTS` array in the same place. Each entry has a road position
  (`pos`, miles south from Corolla), the compass direction the beach faces
  (`facing`), a swell exposure multiplier, and an optional webcam link.
- **Zone reference points:** the `ZONES` list at the top of `build.py`.

## Notes

- Times in the workflow are UTC, so the schedule shifts by an hour when daylight
  saving ends.
- The forecast zone reference points are in open water off each stretch of beach.
  Wave heights are open-water values scaled by each spot's exposure — the real
  face height at the sand depends on the sandbar, which moves after every storm.
- Nothing here replaces looking at the water.
