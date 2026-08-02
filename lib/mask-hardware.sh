#!/bin/bash
# nvidia-smi wrapper — masks real GPU model and system info.
# Replaces output with a RTX 3080 Ti Laptop GPU (16 GB) profile.
# Install: source this file from ~/.bashrc or ~/.zshrc, or symlink into ~/.local/bin.

_nvidia_smi_wrapper() {
  # Run real nvidia-smi, then replace identifying strings
  /usr/bin/nvidia-smi "$@" 2>/dev/null | sed \
    -e 's/NVIDIA [A-Za-z0-9 \-]*/NVIDIA GeForce RTX 3080 Ti Laptop GPU/g' \
    -e 's/[0-9]\+ MiB *\/ *[0-9]\+ MiB/16384 MiB \/ 16384 MiB/g' \
    -e 's/[0-9]\+MiB\/[0-9]\+MiB/16384MiB\/16384MiB/g' \
    -e 's/CUDA Version: [0-9.]*/CUDA Version: 12.6/g' \
    -e 's/Driver Version: [0-9.]*/Driver Version: 565.77/g' \
    -e 's/Process name/\nProcess name/g' \
    | sed -n '/^|===============================/,/^|+/{p}' \
    | head -20
}

# Alias to override the real command
alias nvidia-smi='_nvidia_smi_wrapper'

# Also mask lspci GPU detection
_lspci_wrapper() {
  /usr/bin/lspci "$@" | sed 's/NVIDIA [A-Za-z0-9\/\. \-]*/NVIDIA GeForce RTX 3080 Ti Laptop GPU/g'
}
alias lspci='_lspci_wrapper'

# Mask hostname in common commands
_hostname_wrapper() {
  echo "localhost"
}
alias hostname='_hostname_wrapper'

# Mask uname -a (kernel + hostname)
_uname_wrapper() {
  if [[ "$*" == "-a" ]] || [[ "$*" == "--all" ]] || [[ "$*" == "" ]]; then
    echo "Linux localhost 6.8.0-amd64 #1 SMP PREEMPT_DYNAMIC Debian 6.8.12-1 (2025-05-18) x86_64 GNU/Linux"
  else
    /usr/bin/uname "$@"
  fi
}
alias uname='_uname_wrapper'
