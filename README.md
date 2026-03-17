# MSP - ANC Flight Price Tracker

Automated flight price tracking for **Minneapolis (MSP) to Anchorage (ANC)**, July 11-17, 2026.

Uses [fast-flights](https://github.com/AWeirdDev/flights) to scrape Google Flights every 6 hours via GitHub Actions, logging prices and Google's embedded ~60-day price history.

## Live Dashboard

View the price tracker dashboard at the GitHub Pages site for this repo.

## How It Works

- **GitHub Actions** runs `track_flights.py` every 6 hours on a cron schedule
- The script scrapes current flight prices and Google's price insight label (low/typical/high)
- Results are appended to `data/price_history.csv` and committed back to the repo
- Google's embedded ~60-day historical prices are saved to `data/google_history_*.csv`
- **GitHub Pages** serves a dashboard (`docs/index.html`) that visualizes the CSV data

## Local Usage

```bash
pip install -r requirements.txt

python track_flights.py                # Single price check
python track_flights.py --history      # Show tracked price log
python track_flights.py --google-history  # Show Google's ~60-day history
```

## Configuration

Edit the top of `track_flights.py` to change dates, airports, or passenger count.

## Setup

1. Push this repo to GitHub as a public repo
2. Go to **Settings > Pages** and set source to "Deploy from a branch", branch `main`, folder `/docs`
3. The Actions workflow will start running automatically on the cron schedule
4. You can also trigger it manually from **Actions > Track Flight Prices > Run workflow**
