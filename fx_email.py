import os
import sys
import json
import smtplib
import html as html_lib
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

def fmt_rate(x: float) -> str:
    return f"{x:,.2f}"

def fmt_pct_html(x: float) -> str:
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.2f}%"

def pct_class(x: float) -> str:
    return "pos" if x >= 0 else "neg"


def build_fx_html_table(spot_date: date, rates: dict) -> str:
    rows = []

    for ccy in CURRENCIES:
        spot = rates["D-1"][ccy]
        r2 = rates["D-2"][ccy]
        r7 = rates["D-7"][ccy]
        r30 = rates["D-30"][ccy]
        r365 = rates["D-365"][ccy]

        ch_1d = pct_change(spot, r2)
        ch_7d = pct_change(spot, r7)
        ch_1m = pct_change(spot, r30)
        ch_1y = pct_change(spot, r365)

        # Row 1: rates
        rows.append(f"""
<tr>
  <td class="ccy">{html_lib.escape(ccy)}</td>
  <td class="num">{fmt_rate(spot)}</td>
  <td class="num">{fmt_rate(r2)}</td>
  <td class="num">{fmt_rate(r7)}</td>
  <td class="num">{fmt_rate(r30)}</td>
  <td class="num">{fmt_rate(r365)}</td>
</tr>
""".strip())

        # Row 2: trends
        rows.append(f"""
<tr class="trend-row">
  <td></td>
  <td class="trend-label">% change</td>
  <td class="num {pct_class(ch_1d)}">{fmt_pct_html(ch_1d)}</td>
  <td class="num {pct_class(ch_7d)}">{fmt_pct_html(ch_7d)}</td>
  <td class="num {pct_class(ch_1m)}">{fmt_pct_html(ch_1m)}</td>
  <td class="num {pct_class(ch_1y)}">{fmt_pct_html(ch_1y)}</td>
</tr>
""".strip())

    return f"""\
<html>
  <body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;color:#111;">
    <div style="padding:16px;">
      <div style="font-size:16px;font-weight:700;margin-bottom:6px;">
        Daily FX (base {BASE})
      </div>
      <div style="font-size:13px;margin-bottom:12px;">
        Spot date: <b>{spot_date.isoformat()}</b> (previous day)
      </div>

      <table style="border-collapse:collapse;font-size:13px;min-width:680px;">
        <thead>
          <tr>
            <th class="h left">CCY</th>
            <th class="h">Spot</th>
            <th class="h">D-2</th>
            <th class="h">D-7</th>
            <th class="h">D-30</th>
            <th class="h">D-365</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows)}
        </tbody>
      </table>

      <div style="font-size:11px;color:#777;margin-top:10px;">
        Rates shown to 2 decimal places. Trends are % change vs comparison date.
      </div>
    </div>

    <style>
      .h {{ text-align:right; padding:8px 10px; border-bottom:1px solid #ddd; font-weight:700; }}
      .left {{ text-align:left; }}
      .ccy {{ padding:8px 10px; border-bottom:1px solid #f0f0f0; font-weight:700; }}
      .num {{ padding:6px 10px; border-bottom:1px solid #f0f0f0; text-align:right; white-space:nowrap; }}
      .trend-row td {{ padding-top:0; padding-bottom:10px; }}
      .trend-label {{ padding:0 10px 10px 10px; color:#666; font-size:12px; text-align:right; border-bottom:1px solid #f0f0f0; white-space:nowrap; }}
      .pos {{ color:#137333; font-weight:700; }}
      .neg {{ color:#a50e0e; font-weight:700; }}
    </style>
  </body>
</html>
""".strip()




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

    header = (
        f"{'CCY':<5} "
        f"{'Spot':>12} "
        f"{'D-2':>12} "
        f"{'D-7':>12} "
        f"{'D-30':>12} "
        f"{'D-365':>12}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    for ccy in CURRENCIES:
        spot = rates["D-1"][ccy]
        r2 = rates["D-2"][ccy]
        r7 = rates["D-7"][ccy]
        r30 = rates["D-30"][ccy]
        r365 = rates["D-365"][ccy]

        ch_1d = pct_change(spot, r2)
        ch_7d = pct_change(spot, r7)
        ch_1m = pct_change(spot, r30)
        ch_1y = pct_change(spot, r365)

        # Row 1: rates
        lines.append(
            f"{ccy:<5} "
            f"{spot:>12,.2f} "
            f"{r2:>12,.2f} "
            f"{r7:>12,.2f} "
            f"{r30:>12,.2f} "
            f"{r365:>12,.2f}"
        )

        # Row 2: trends
        lines.append(
            f"{'':<5} "
            f"{'':>12} "
            f"{fmt_pct(ch_1d):>12} "
            f"{fmt_pct(ch_7d):>12} "
            f"{fmt_pct(ch_1m):>12} "
            f"{fmt_pct(ch_1y):>12}"
        )

        lines.append("")  # blank line between currencies

    body_text = "\n".join(lines)
    
    body_html = build_fx_html_table(d_1, rates)

    # Compose email
    subject = f"Daily FX: USD vs KES/UGX/NGN/TZS (spot {d_1.isoformat()})"

    msg = MIMEMultipart("alternative")
    msg["From"] = email_from
    msg["To"] = email_to
    msg["Subject"] = subject

    msg.attach(MIMEText(body_text, "plain"))   # fallback
    msg.attach(MIMEText(body_html, "html"))    # aligned version

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
