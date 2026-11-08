#!/usr/bin/env python3
"""Daily NextDNS website report, emailed to you.

Pulls the last 24 hours of DNS logs from the NextDNS API, groups them by
device, drops common background noise, and emails a plain-text summary.
Standard library only, so nothing to install.

Required environment variables:
  NEXTDNS_API_KEY     your key from my.nextdns.io -> Account
  NEXTDNS_PROFILE_ID  the 6-character configuration ID (shown on Setup tab)
  SMTP_USER           the email address you send from (e.g. your Gmail)
  SMTP_PASS           an app password (NOT your normal password)
Optional:
  MAIL_TO             where to send the report (default: SMTP_USER)
  SMTP_HOST           default smtp.gmail.com
  TOP_N               sites to list per device (default 25)
"""
import json
import os
import smtplib
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from email.message import EmailMessage

API_KEY = os.environ["NEXTDNS_API_KEY"]
PROFILE = os.environ["NEXTDNS_PROFILE_ID"]
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
MAIL_TO = os.environ.get("MAIL_TO", SMTP_USER)
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
TOP_N = int(os.environ.get("TOP_N", "25"))

# Background / infrastructure domains that clutter the report.
# Edit freely. Anything matched here is counted but not listed.
NOISE_SUFFIXES = (
    "apple.com", "icloud.com", "mzstatic.com", "apple-dns.net",
    "gstatic.com", "googleapis.com", "googleusercontent.com",
    "gvt1.com", "gvt2.com", "doubleclick.net", "google-analytics.com",
    "microsoft.com", "windows.com", "windowsupdate.com", "msftconnecttest.com",
    "akamaiedge.net", "akamai.net", "cloudfront.net", "fastly.net",
    "cloudflare.com", "amazonaws.com", "nextdns.io", "ntp.org",
)


def fetch_logs():
    rows, cursor = [], None
    for _ in range(50):  # safety cap: 50 pages x 1000 rows
        params = {"from": "-24h", "limit": "1000"}
        if cursor:
            params["cursor"] = cursor
        url = (
            f"https://api.nextdns.io/profiles/{PROFILE}/logs?"
            + urllib.parse.urlencode(params)
        )
        req = urllib.request.Request(url, headers={"X-Api-Key": API_KEY})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
        rows.extend(body.get("data", []))
        cursor = ((body.get("meta") or {}).get("pagination") or {}).get("cursor")
        if not cursor:
            break
    return rows


def is_noise(domain):
    return domain.endswith(NOISE_SUFFIXES)


def build_report(rows):
    visited = defaultdict(Counter)   # device -> site -> count
    blocked = defaultdict(Counter)   # device -> site -> count
    noise_count = Counter()          # device -> hidden background queries

    for r in rows:
        device = (r.get("device") or {}).get("name") or r.get("clientIp") or "Unknown device"
        site = r.get("root") or r.get("domain") or "?"
        if r.get("status") == "blocked":
            blocked[device][site] += 1
        elif is_noise(site):
            noise_count[device] += 1
        else:
            visited[device][site] += 1

    lines = [f"DNS report, last 24 hours ({len(rows)} total queries)", ""]
    devices = sorted(set(visited) | set(blocked) | set(noise_count))
    if not devices:
        lines.append("No activity found. If that seems wrong, check that logging is on in NextDNS.")
    for device in devices:
        lines.append(f"=== {device} ===")
        top = visited[device].most_common(TOP_N)
        if top:
            lines.append("Sites visited:")
            lines += [f"  {site}  ({n})" for site, n in top]
        else:
            lines.append("Sites visited: none beyond background traffic")
        if blocked[device]:
            lines.append("Blocked attempts:")
            lines += [f"  {site}  ({n})" for site, n in blocked[device].most_common(15)]
        lines.append(f"(Background queries hidden: {noise_count[device]})")
        lines.append("")
    return "\n".join(lines)


def send_email(text):
    msg = EmailMessage()
    msg["Subject"] = f"Daily DNS report {datetime.now(timezone.utc):%Y-%m-%d}"
    msg["From"] = SMTP_USER
    msg["To"] = MAIL_TO
    msg.set_content(text)
    with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=30) as smtp:
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(msg)


if __name__ == "__main__":
    report = build_report(fetch_logs())
    print(report)
    send_email(report)
