"""stealth — driver/CDP-level anti-fingerprinting for CortexAgent browser automation.

Three pieces, all driven by a single per-profile deterministic seed so the
synthetic fingerprint is internally coherent (one believable device) and
session-stable (repeated renders get the SAME noise, so multi-render
consistency checks used by detection scripts do not flag naive per-call noise):

  seed.py        stable seed derivation (hash of profile name -> 32-bit int)
  profiles.py    table of coherent real device profiles; seed -> profile
  init_script.py builds the JS injected via CDP Page.addScriptToEvaluateOnNewDocument

Why CDP init scripts, not a recompiled Brave: Brave ships as a prebuilt binary,
so build-level patching is not realistic. addScriptToEvaluateOnNewDocument runs
at document creation, BEFORE any page script, so the overrides are in place
before the page can read navigator.webdriver / canvas / WebGL. This is the same
mechanism undetected-chromedriver / patchright use at the driver layer; it is
not a page-level Object.defineProperty that page scripts observe being applied.
"""
from .seed import profile_seed
from .profiles import derive_profile, list_profiles
from .init_script import build_init_script

__all__ = ["profile_seed", "derive_profile", "list_profiles", "build_init_script"]