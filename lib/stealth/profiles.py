
from __future__ import annotations

import re
from typing import Any, Dict, List



_PROFILES: Dict[str, List[Dict[str, Any]]] = {
    "linux": [
        {"platform": "Linux x86_64", "hardwareConcurrency": 8, "deviceMemory": 8,
         "webglVendor": "Google Inc. (Intel)", "webglRenderer": "ANGLE (Intel, Intel(R) UHD Graphics 630 (CFL GT2) Direct3D11 vs_5_0 ps_5_0, D3D11)",
         "screen": {"w": 1920, "h": 1080, "dpr": 1.0}, "timezone": "America/New_York",
         "maxTouchPoints": 0},
        {"platform": "Linux x86_64", "hardwareConcurrency": 12, "deviceMemory": 16,
         "webglVendor": "Google Inc. (NVIDIA)", "webglRenderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)",
         "screen": {"w": 2560, "h": 1440, "dpr": 1.0}, "timezone": "America/Chicago",
         "maxTouchPoints": 0},
        {"platform": "Linux x86_64", "hardwareConcurrency": 4, "deviceMemory": 8,
         "webglVendor": "Google Inc. (AMD)", "webglRenderer": "ANGLE (AMD, AMD Radeon RX 580 Direct3D11 vs_5_0 ps_5_0, D3D11)",
         "screen": {"w": 1920, "h": 1080, "dpr": 1.0}, "timezone": "Europe/London",
         "maxTouchPoints": 0},
    ],
    "windows": [
        {"platform": "Win32", "hardwareConcurrency": 8, "deviceMemory": 8,
         "webglVendor": "Google Inc. (Intel)", "webglRenderer": "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)",
         "screen": {"w": 1920, "h": 1080, "dpr": 1.25}, "timezone": "America/New_York",
         "maxTouchPoints": 0},
        {"platform": "Win32", "hardwareConcurrency": 16, "deviceMemory": 16,
         "webglVendor": "Google Inc. (NVIDIA)", "webglRenderer": "ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0, D3D11)",
         "screen": {"w": 2560, "h": 1440, "dpr": 1.0}, "timezone": "America/Los_Angeles",
         "maxTouchPoints": 0},
    ],
    "macos": [
        {"platform": "MacIntel", "hardwareConcurrency": 8, "deviceMemory": 8,
         "webglVendor": "Google Inc. (Apple)", "webglRenderer": "ANGLE (Apple, Apple M1, OpenGL 4.1)",
         "screen": {"w": 1680, "h": 1050, "dpr": 2.0}, "timezone": "America/New_York",
         "maxTouchPoints": 0},
        {"platform": "MacIntel", "hardwareConcurrency": 10, "deviceMemory": 16,
         "webglVendor": "Google Inc. (Apple)", "webglRenderer": "ANGLE (Apple, Apple M2 Pro, OpenGL 4.1)",
         "screen": {"w": 2560, "h": 1600, "dpr": 2.0}, "timezone": "America/Los_Angeles",
         "maxTouchPoints": 0},
    ],
}


def _os_from_ua(ua: str) -> str:

    if not ua:
        return "linux"
    if "Windows" in ua:
        return "windows"
    if "Macintosh" in ua or "Mac OS" in ua:
        return "macos"
    return "linux"


def derive_profile(seed: int, real_ua: str = "") -> Dict[str, Any]:

    osfam = _os_from_ua(real_ua)
    bucket = _PROFILES.get(osfam, _PROFILES["linux"])
    profile = dict(bucket[seed % len(bucket)])
    profile["userAgent"] = real_ua
    profile["osFamily"] = osfam
    profile["seed"] = seed
    return profile


def list_profiles() -> List[str]:
    return list(_PROFILES.keys())



UA_OS_RE = re.compile(r"(Windows|Macintosh|Mac OS|Linux|X11|Android)")


def ua_os(ua: str) -> str:
    m = UA_OS_RE.search(ua or "")
    return m.group(1) if m else "Linux"