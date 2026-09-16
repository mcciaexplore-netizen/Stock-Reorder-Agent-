# Website typography reference

Checked on 16 September 2026 against [MCCIA's official website](https://mcciapune.com/)
and its [main stylesheet](https://mcciapune.com/static/assets/scss/main.css).

| Element on MCCIA's website | Declared font family |
| --- | --- |
| General text, forms and captions | Candara, sans-serif |
| Main heading (`.head-text`) and buttons | Segoe, sans-serif |
| Navigation links and lower footer | Segoe UI, sans-serif |
| Multi-select filter list links | Roboto, sans-serif |

Stocklist uses Candara for general text and Segoe / Segoe UI for headings through
Streamlit's native theme settings in `.streamlit/config.toml`. Segoe UI and the
browser's sans-serif font provide fallbacks when a preferred font is unavailable.
Candara is installed on the Windows computer used to verify this change.

The typography refinement uses a 17 px body baseline, 15 px captions and form labels,
and 600-weight headings. Navigation uses Segoe UI; buttons and stock metrics use
Segoe / Segoe UI with aligned numerals. Captions use an explicit dark text colour at
full opacity so Streamlit's default caption fading does not reduce readability.
This keeps MCCIA's font roles while adapting text sizes for a working inventory app.

The inspected MCCIA stylesheet contains no `@font-face` definitions or font-file
downloads. It references fonts installed on the visitor's device. No proprietary
font binaries have been copied into this project; appearance on another device
depends on its installed fonts.

The MCCIA wordmark is served as a [logo image](https://mcciapune.com/static/assets/images/logos/logo-mccia-white-blue-new.png).
The lettering in the supplied logo screenshot has not been identified as an
installable font. Website typography and logo artwork are separate assets.

## Local logo assets

Downloaded directly from the live site's image references on 16 September 2026.
The original PNG files are retained without recoloring, cropping or redrawing:

| Local file in `static/branding/` | Official source |
| --- | --- |
| `logo-mccia-white-blue-new.png` | [Header logo](https://mcciapune.com/static/assets/images/logos/logo-mccia-white-blue-new.png) |
| `logo-mccia-white.png` | [Footer variant](https://mcciapune.com/static/assets/images/logos/logo-mccia-white.png) |

The header logo is used on the sign-in page and through Streamlit's native app
logo in the authenticated workspace. It is served locally, so it remains usable
when the MCCIA website is unavailable. Source SHA-256 for the header PNG:
`62bd20d96aee7b44780f142447a9ba669c9cc75b399b8dee46dd2c84e9bb38bc`.

## Interface design

- Native theme: MCCIA blue `#146CAA`, cool neutral surfaces, green status accents,
  Candara body text and Segoe / Segoe UI headings.
- Sign-in: responsive brand introduction, native account forms and all four demo
  access buttons. The illustrative process diagram describes capabilities; it
  does not present fabricated business statistics.
- Workspace: logo, icon navigation, current-page context, stock summary cards,
  shortcut buttons, and an attention panel derived from unacknowledged alerts.
- Shared forms and tables: readable spacing, consistent borders and type sizes,
  fixed header/data row heights, and controlled scrolling for wider datasets.
- Presentation helpers live in `frontend.py`; layout refinements live in
  `assets/brand.css`. Native controls retain their labels and keyboard behavior.
  CSS uses named container hooks and Streamlit 1.59 widget test IDs, with reduced
  motion and mobile layout rules. No external UI library or JavaScript is added.

## Verification

Verified against Streamlit 1.59 on 16 September 2026:

- All nine existing UI workflow tests and the four-role demo UI test passed.
  The owner setup/sign-in test also passed after the final feedback refinement.
- Browser checks passed for the four demo accounts, sign-out, loaded logo,
  manufacturing and report screens, and persistence of the local offline queue.
- Desktop (1365 px), tablet (768 px), and phone (390 px) checks found no page
  overflow or clipped metric values. Keyboard navigation and overview shortcuts
  were exercised in the browser.
- Browser font inspection confirmed Candara body text and Segoe UI Bold headings
  on this Windows device. Other devices use the documented font fallbacks.

Typography follow-up: fetched the official stylesheet again and confirmed the same
font declarations, including Segoe buttons at 500 weight and Segoe headings at 600.
Stocklist now renders its headings with Segoe UI Semibold. Desktop, tablet and phone
checks (1365, 768 and 390 px) found no page overflow or clipped stock metrics.
