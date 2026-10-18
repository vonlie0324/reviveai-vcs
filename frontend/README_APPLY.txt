ReviveAI frontend build fix

This package contains the full current src tree plus corrected package.json, tsconfig.app.json, and vite.config.ts.

Important: the package-lock.json supplied with the project belongs to an older dependency set and does not contain three/maplibre-gl. Regenerate dependencies before building:

  rm -rf node_modules package-lock.json
  npm install
  npm run build

Windows Git Bash commands above work as-is.

Resolved build errors:
- App.tsx String.replaceAll ES2021 compatibility issue: replaced with ES2020-compatible regex replace.
- three / OrbitControls missing module: package.json now includes three and @types/three.
- maplibre-gl missing module: package.json now includes maplibre-gl.
- Diorama implicit-any errors are restored through Three.js typings instead of masking with any.
- MapValidation raw GeoJSON is strongly narrowed and cast to MapLibre's setData input type without using any.
- firebase retained because the current src imports firebase/app and firebase/auth.
