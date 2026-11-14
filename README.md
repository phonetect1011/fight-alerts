# Fight Alerts

Android app listing upcoming UFC, PFL, BKFC, ONE and RAF cards, with notifications before they start.

- `scraper/scrape.py` pulls fight data from next-fight.com every 6 hours (GitHub Actions: **Update fight data**) into `data/events.json`.
- If the scraper breaks, the workflow opens a GitHub issue and the app shows a warning banner.
- **Build APK** workflow builds the app; download the APK from the run's Artifacts.
