# LedgerMatch Landing Page

A static, framework-free landing page for the LedgerMatch repository. It is intended to be hosted independently on **Cloudflare Pages**; it does not run the reconciliation application.

## Preview locally

From the repository root:

```bash
python3 -m http.server 4173 --directory landing
```

Open <http://localhost:4173>.

No build step or dependency installation is required.

## Cloudflare Pages setup

Recommended project settings:

| Setting | Value |
|---|---|
| Production branch | `landing-page` |
| Framework preset | None |
| Build command | Leave empty |
| Build output directory | `landing` |
| Root directory | `/` (repository root) |

Connect the GitHub repository, point the Pages project at the `landing-page` branch, and create the first deployment. If your workflow uses a root directory of `landing` instead, set the build output directory to `/`.

### Direct upload with Wrangler

```bash
npx wrangler pages deploy landing --project-name ledgermatch
```

Wrangler will request Cloudflare authentication if needed. Review the project name before deploying.

## Files

```text
landing/
├── index.html                 # Page structure and copy
├── styles.css                 # Responsive design system and layout
├── script.js                  # Copy-to-clipboard progressive enhancement
├── assets/
│   ├── dashboard-summary.png  # Product screenshot from the built-in demo
│   └── favicon.svg            # LM mark
├── _headers                   # Cloudflare Pages security headers
├── robots.txt
└── README.md
```

## Design notes

- Shares the app's slate-and-teal palette (`#0f172a` / `#0f766e`), light paper background, thin borders, and compact data styling.
- Uses system fonts and inline SVG icons only; there are no external font, script, or analytics requests.
- Responsive layouts are provided for desktop, tablet, and mobile.
- The screenshot opens full-size when selected so it remains inspectable on small screens.
- `prefers-reduced-motion` is respected.
- The footer credit links to <https://shakibmolla.com/>.

## Security headers

`landing/_headers` adds:

- A strict Content Security Policy.
- Frame denial.
- MIME sniffing protection.
- A strict referrer policy.
- Restricted browser permissions.

The page intentionally has no third-party scripts or tracking.

## Before publishing

1. Confirm the GitHub and documentation links.
2. Optionally add a custom domain in Cloudflare Pages and update the social preview URL if required.
3. Verify the screenshot is current if the dashboard UI changes.
4. Test the copy button over HTTPS.
5. Keep the actual Streamlit app off Cloudflare Pages; host it locally or on a protected application host.

---

Developed by [Shakib](https://shakibmolla.com/).
