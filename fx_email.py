import os
import sys
import json
import smtplib
from datetime import date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests

CURRENCIES = ["KES", "UGX", "NGN", "TZS"]
BASE = "USD"


def get_rates_for_day(app_id: str, day: date) -> dict:
    # Open Exchange Rates historical endpoint: /historical/YYYY-MM-DD.json
    url = f"https://openexchangerates.org/api/historical/{day.isoformat()}.json"
    params = {"app_id": app_id, "symbols": ",".join(CURRENCIES)}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    # rates are quoted as 1 USD = X CCY
    return data["rates"]


def pct_change(new: float, old: float) -> float:
    return (new / old - 1.0) * 100.0


def fmt_pct(x: float) -> str:
    return f"{x:+.2f}%"


def build_email_body(anchor: date, rates: dict) -> str:
    """
    rates: dict keyed by label -> {currency -> rate}
    labels: "D-1" (yesterday), "D-7", "D-30", "D-365"
    """
    y = rates["D-1"]
    d7 = rates["D-7"]
    d30 = rates["D-30"]
    d365 = rates["D-365"]

    lines = []
    lines.append(f"FX summary (base {BASE}) for {anchor.isoformat()} (previous day spot)")
    lines.append("")
    lines.append("Quoted as: 1 USD = X CCY")
    lines.append("")
    header = f"{'CCY':<5} {'Spot':>14} {'1D':>10} {'7D':>10} {'1M':>10} {'1Y':>10}"
    lines.append(header)
    lines.append("-" * len(header))

    for ccy in CURRENCIES:
        spot = y[ccy]
        ch_1d = pct_change(y[ccy], d7[ccy]) if False else pct_change(y[ccy], rates["D-2"][ccy])  # replaced below

    return "\n".join(lines)


def main():
    # Required env vars
    app_id = os.environ["OXR_APP_ID"]

    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]

    email_from = os.environ["EMAIL_FROM"]
    email_to = os.environ["EMAIL_TO"]

    # "Previous day spot rate" relative to run date
    run_day = date.today()
    d_1 = run_day - timedelta(days=1)
    d_2 = run_day - timedelta(days=2)
    d_7 = run_day - timedelta(days=7)
    d_30 = run_day - timedelta(days=30)
    d_365 = run_day - timedelta(days=365)

    # Fetch rates (4–5 calls/day). We need D-2 to compute the 1-day trend of the "previous day spot".
    rates = {
        "D-1": get_rates_for_day(app_id, d_1),
        "D-2": get_rates_for_day(app_id, d_2),
        "D-7": get_rates_for_day(app_id, d_7),
        "D-30": get_rates_for_day(app_id, d_30),
        "D-365": get_rates_for_day(app_id, d_365),
    }

    # Build plain text body
    lines = []
    lines.append(f"FX summary (base {BASE})")
    lines.append(f"Spot date: {d_1.isoformat()} (previous day)")
    lines.append("")
    lines.append("Quoted as: 1 USD = X CCY")
    lines.append("")
    header = f"{'CCY':<5} {'Spot':>14} {'1D':>10} {'7D':>10} {'1M':>10} {'1Y':>10}"
    lines.append(header)
    lines.append("-" * len(header))

    for ccy in CURRENCIES:
        spot = rates["D-1"][ccy]
        ch_1d = pct_change(rates["D-1"][ccy], rates["D-2"][ccy])
        ch_7d = pct_change(rates["D-1"][ccy], rates["D-7"][ccy])
        ch_1m = pct_change(rates["D-1"][ccy], rates["D-30"][ccy])
        ch_1y = pct_change(rates["D-1"][ccy], rates["D-365"][ccy])

        lines.append(
            f"{ccy:<5} {spot:>14,.4f} {fmt_pct(ch_1d):>10} {fmt_pct(ch_7d):>10} {fmt_pct(ch_1m):>10} {fmt_pct(ch_1y):>10}"
        )

    body = "\n".join(lines)

    # Compose email
    subject = f"Daily FX: USD vs KES/UGX/NGN/TZS (spot {d_1.isoformat()})"
    msg = MIMEMultipart()
    msg["From"] = email_from
    msg["To"] = email_to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    # Send
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)

    print("Email sent.")


if __name__ == "__main__":
    try:
        main()
    except KeyError as e:
        print(f"Missing environment variable: {e}", file=sys.stderr)
        sys.exit(2)
