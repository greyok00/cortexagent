#!/usr/bin/env bash
# cortexagent time guard — sync the clock over HTTPS.
#
# Why this exists: this box has no RTC coin cell (the clock is lost on power
# loss) and UDP/123 (NTP) is walled by the network, so nothing corrects the
# clock after a deep power drain — the system boots at an old date and stays
# there ("everything resets to days ago"). Port 443 works, so read the HTTP
# `Date:` response header instead and set the clock from it.
#
# Installed to /usr/local/sbin/ and run by time-sync-https.{service,timer}.
# Safe to run manually: `sudo /usr/local/sbin/time-sync-https.sh`.
set -u

sources=(
  "https://www.cloudflare.com"
  "https://www.google.com"
  "https://api.github.com"
)

for url in "${sources[@]}"; do
  for _try in 1 2 3; do
    hdr="$(curl -sI --max-time 8 "$url" 2>/dev/null | sed -n 's/^[Dd]ate: //p' | tr -d '\r' | head -n1)"
    if [ -n "$hdr" ] && date -d "$hdr" >/dev/null 2>&1; then
      date -s "$hdr" >/dev/null 2>&1 || exit 1
      hwclock --systohc >/dev/null 2>&1 || true
      logger -t time-sync-https "clock set from ${url}: ${hdr}"
      exit 0
    fi
    sleep 2
  done
done

logger -t time-sync-https "FAILED: no source returned a valid Date header"
exit 1
