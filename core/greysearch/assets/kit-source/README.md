# Grey kit — single source for every greysearch site theme

The compiled theme kit: design tokens, 16 selectable `data-theme` palettes in
`theme.css` (17 blocks as counted by `greysearch doctor`: the default plus the
16), the document bridge, and the
theme switcher. `site_render.ensure_kit` refreshes `assets/kit/theme.css` and
`site-kit.js` into every built site from this directory on every build, so a theme
change reaches new output without touching the renderer.

`kit_build.py` regenerates the bundle from the theme sources:

```console
$ python3 kit_build.py     # writes theme.css from fonts/tokens/themes + the bridge
```

If the theme sources are not present, the checked-in `theme.css` is the working
copy and nothing needs to be rebuilt.
