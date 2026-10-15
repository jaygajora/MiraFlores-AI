#!/usr/bin/env sh
# Build the React + Tailwind front end into static/app/.
#   npm install && npm run build      (normal)
# Without npm (offline), point TAILWIND at a standalone Tailwind 3.4 binary:
#   TAILWIND=/path/to/tailwindcss-linux-x64 scripts/build_frontend.sh
set -eu
cd "$(dirname "$0")/.."
BIN=node_modules/.bin
TSC="${TSC:-node node_modules/typescript/bin/tsc}"
ESBUILD="${ESBUILD:-node_modules/esbuild/bin/esbuild}"
TAILWIND="${TAILWIND:-$BIN/tailwindcss}"
mkdir -p static/app
$TSC -p web --noEmit
$ESBUILD web/src/main.tsx --bundle --minify --sourcemap --format=esm --target=es2020 --jsx=automatic \
  --define:process.env.NODE_ENV='"production"' --outfile=static/app/main.js --log-level=warning
$TAILWIND -c tailwind.config.cjs -i web/styles.css -o static/app/app.css --minify
ls -l static/app
