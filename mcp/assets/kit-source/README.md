# Grey kit — single source for every site theme (vendored from the retired analysis browser)

Vendored from ~/audit-site/site-kit (the compiled grey ui-framework
kit: tokens + 8 themes + document bridge + switcher). site_render.ensure_kit
refreshes assets/kit/theme.css + site-kit.js into every built site FROM HERE
on every build, so theme updates flow — the old dead-path + skip-if-exists
behavior is what froze themes.

Rebuild from the grey ui-framework source when that checkout is available:
    python3 kit_build.py     # reads ~/ui-framework (fonts/tokens/themes/switcher)
It is NOT available on this machine anymore; this compiled kit is the
effective upstream until the framework checkout is restored elsewhere.
