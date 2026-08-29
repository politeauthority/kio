# Changelog

## [0.8.2](https://github.com/politeauthority/kio/compare/v0.8.1...v0.8.2) (2026-08-29)


### Bug Fixes

* **ui:** match saved URLs the way the API does, show their names in the list ([#63](https://github.com/politeauthority/kio/issues/63)) ([2cc6b31](https://github.com/politeauthority/kio/commit/2cc6b31cfa5aff4b495feb51a08be0d1e1f373a3))

## [0.8.1](https://github.com/politeauthority/kio/compare/v0.8.0...v0.8.1) (2026-08-29)


### Bug Fixes

* **ui:** reconnect the kiosk SSE stream with a fresh ticket after a drop ([#62](https://github.com/politeauthority/kio/issues/62)) ([dfa4a7d](https://github.com/politeauthority/kio/commit/dfa4a7d42943da1a7f9e81a05d83c16ce55113c7))

## [0.8.0](https://github.com/politeauthority/kio/compare/v0.7.9...v0.8.0) (2026-08-29)


### Features

* **ha:** show saved URL names for the current page and navigate by name ([#59](https://github.com/politeauthority/kio/issues/59)) ([4aa9edc](https://github.com/politeauthority/kio/commit/4aa9edc5ee45c7ef55e9574155eb472e9ee2b27a))

## [0.7.9](https://github.com/politeauthority/kio/compare/v0.7.8...v0.7.9) (2026-08-29)


### Bug Fixes

* **ha:** show kio's input names and hide hidden inputs in the display select ([#57](https://github.com/politeauthority/kio/issues/57)) ([c008ca9](https://github.com/politeauthority/kio/commit/c008ca9fd24f5c0713136247d6ca11c47a79c710))

## [0.7.8](https://github.com/politeauthority/kio/compare/v0.7.7...v0.7.8) (2026-08-29)


### Bug Fixes

* **ui:** keep the Authentik session across tabs and browser restarts ([#55](https://github.com/politeauthority/kio/issues/55)) ([13496ca](https://github.com/politeauthority/kio/commit/13496ca219139dfbbfd440bbf7624b615610775b))

## [0.7.7](https://github.com/politeauthority/kio/compare/v0.7.6...v0.7.7) (2026-08-29)


### Bug Fixes

* **pi-agent:** keep node features across self-update and detect ([#53](https://github.com/politeauthority/kio/issues/53)) ([4b20b65](https://github.com/politeauthority/kio/commit/4b20b650e300855138d55e30b00cb9230c62c377))

## [0.7.6](https://github.com/politeauthority/kio/compare/v0.7.5...v0.7.6) (2026-08-29)


### Bug Fixes

* **auth:** allow authorization_code + refresh_token grants on the Authentik provider ([#49](https://github.com/politeauthority/kio/issues/49)) ([03d9608](https://github.com/politeauthority/kio/commit/03d9608854d76bca995b3e187f99d28a9bc02cfc))

## [0.7.5](https://github.com/politeauthority/kio/compare/v0.7.4...v0.7.5) (2026-08-29)


### Bug Fixes

* **auth:** assign an RS256 signing key when setting up the Authentik provider ([#45](https://github.com/politeauthority/kio/issues/45)) ([ba21a53](https://github.com/politeauthority/kio/commit/ba21a5333386806973011d2a77abfac219d34549))

## [0.7.4](https://github.com/politeauthority/kio/compare/v0.7.3...v0.7.4) (2026-08-29)


### Dependencies

* bump the ui-deps group across 1 directory with 3 updates ([#33](https://github.com/politeauthority/kio/issues/33)) ([cf00cee](https://github.com/politeauthority/kio/commit/cf00ceed51df5c56baf0863534b27facb3bf8185))

## [0.7.3](https://github.com/politeauthority/kio/compare/v0.7.2...v0.7.3) (2026-08-29)


### Bug Fixes

* **ci:** prd-sync used a shell expansion for the Task var REV (unbound under set -u) ([#41](https://github.com/politeauthority/kio/issues/41)) ([ef58335](https://github.com/politeauthority/kio/commit/ef58335f83b4ac10a50e3be6626aba3aaf42ceb8))

## [0.7.2](https://github.com/politeauthority/kio/compare/v0.7.1...v0.7.2) (2026-08-29)


* force release v0.7.2 ([71d12b1](https://github.com/politeauthority/kio/commit/71d12b12fb3f7adcee557199430acae7ca509caf))

## [0.7.1](https://github.com/politeauthority/kio/compare/v0.7.0...v0.7.1) (2026-08-29)


### Bug Fixes

* **pi-agent:** never keep two tabs open on the same page ([#36](https://github.com/politeauthority/kio/issues/36)) ([f33734f](https://github.com/politeauthority/kio/commit/f33734ff1fc5e2e45f74194b83298ae1cf64f137))

## [0.7.0](https://github.com/politeauthority/kio/compare/v0.6.13...v0.7.0) (2026-08-29)


### Features

* **cicd:** release-please + GitOps production deploys via private-ops ([#28](https://github.com/politeauthority/kio/issues/28)) ([27b138e](https://github.com/politeauthority/kio/commit/27b138e9f872c534331db5dfac29da7752b44ec3))
