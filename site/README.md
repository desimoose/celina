# site/

The marketing landing page (`index.html`), self-hosted Manrope + wordmark to
match the app. Not under `docs/` — that folder already holds tracked internal
planning docs (`docs/superpowers/`), and GitHub Pages' folder-deploy mode can
only serve `/` or `/docs`, so pointing Pages there would publish those too.

**To go live once the GitHub repo exists:** either push this to a `gh-pages`
branch (root of that branch, standard GitHub Pages convention) or use
"GitHub Actions" deploy mode pointed at this folder — either avoids touching
`docs/`. Then replace every `OWNER/REPO` placeholder in `index.html` with the
real path.
