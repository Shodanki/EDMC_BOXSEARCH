# Three.js - third-party code, shipped unchanged

* Project: three.js - https://threejs.org - https://github.com/mrdoob/three.js
* Licence: MIT, see `LICENSE` in this folder ("Copyright © 2010-2024 three.js authors")
* Version: 0.170.0 (r170), taken from the npm package
  https://registry.npmjs.org/three/-/three-0.170.0.tgz
  integrity sha512-FQK+LEpYc0fBD+J8g6oSEyyNzjp+Q7Ks1C568WWaoMRLW+TkNNWmenWeGgJjV105Gd+p/2ql1ZcjYvNiPZBhuQ==
  (checked against the npm registry when copied, 10.11.2026)
* Files: `build/three.module.js` -> `three.module.js`,
  `examples/jsm/controls/OrbitControls.js` -> `addons/controls/OrbitControls.js`

Shipped with SHBOX FIS so the 3D views work without internet and the browser
does not ask a CDN on every page load. To update: replace both files with the
same version of one npm package and change the version here.
