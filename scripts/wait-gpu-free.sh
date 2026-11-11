#!/bin/bash
# wait-gpu-free.sh — poll until no compute process holds >=1GiB on the GPU.
# Prints each check's status; exits 0 the moment the GPU is free so the
# caller (the session that schedules it) can continue the build.
while true; do
  LINE=$(nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader 2>/dev/null | head -1)
  MB=$(echo "$LINE" | awk -F', ' '{print $2}' | tr -dc '0-9')
  if [ -z "$MB" ] || [ -z "${MB//[!0-9]/}" ]; then
    echo "GPU FREE (no compute holders)"
    exit 0
  fi
  if [ "$MB" -lt 1024 ]; then
    echo "GPU FREE (residue: ${MB}MiB from ${LINE})"
    exit 0
  fi
  echo "waiting: holder=${LINE}"
  sleep 20
done