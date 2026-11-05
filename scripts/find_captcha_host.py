from pathlib import Path
import sys, time
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'lib'))
import browser_control as bc

SKIP = ('twitch.tv', 'gemini.google', 'youtube.com/embed')
tabs = bc.list_tabs()
print(f'scanning {len(tabs)} tabs (skipping media)...', flush=True)
host = None
for t in tabs:
    u = t.get('url', '')
    if any(s in u for s in SKIP):
        print(f'  skip {t["id"][:8]} {u[:50]}', flush=True); continue
    t0 = time.time()
    try:
        has = bc._eval(t['id'], """(() => {
          const f=[...document.querySelectorAll('iframe')].some(i=>/recaptcha|hcaptcha|turnstile/i.test(i.src||''));
          const s=!!document.querySelector('script[src*=recaptcha],.g-recaptcha,.cf-turnstile,.h-captcha');
          const g=!!(window.___grecaptcha_cfg||window.grecaptcha||window.turnstile||window.hcaptcha);
          return f||s||g;
        })()""", timeout=4)
    except Exception:
        has = 'ERR'
    dt = time.time() - t0
    print(f'  {t["id"][:8]} has={has} ({dt:.1f}s) {u[:48]}', flush=True)
    if has is True and not host:
        host = t['id']
if host:
    print(f'\nCLOSING host {host[:10]}', flush=True)
    print('  result:', bc.close_tab(host), flush=True)
else:
    print('\nNO captcha host found in non-media tabs', flush=True)
