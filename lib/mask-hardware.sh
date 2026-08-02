#!/bin/bash
# mask-hardware.sh — masks real GPU model and system info.
# Shows "NVIDIA GeForce RTX 3080 Ti Laptop GPU" with 16 GB.
#
# Install:
#   source this file from ~/.bashrc or ~/.zshrc
#   Or just ensure ~/.local/bin is before /usr/bin in PATH
#   (the nvidia-smi wrapper is already installed there)

# Ensure ~/.local/bin is first in PATH so our nvidia-smi wrapper takes precedence
case ":$PATH:" in
  *:"$HOME/.local/bin":*) ;;
  *) export PATH="$HOME/.local/bin:$PATH" ;;
esac

# Mask lspci GPU detection
_lspci_wrapper() {
  /usr/bin/lspci "$@" | sed 's/NVIDIA [A-Za-z0-9\/\. \-]*/NVIDIA GeForce RTX 3080 Ti Laptop GPU/g'
}
alias lspci='_lspci_wrapper'

# Mask hostname
alias hostname='echo "localhost"'

# Mask uname -a
_uname_wrapper() {
  if [[ "$*" == "-a" ]] || [[ "$*" == "--all" ]] || [[ "$*" == "" ]]; then
    echo "Linux localhost 6.8.0-amd64 #1 SMP PREEMPT_DYNAMIC Debian 6.8.12-1 (2025-05-18) x86_64 GNU/Linux"
  else
    /usr/bin/uname "$@"
  fi
}
alias uname='_uname_wrapper'
