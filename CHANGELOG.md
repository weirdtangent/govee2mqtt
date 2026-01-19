## [2.6.2](https://github.com/weirdtangent/govee2mqtt/compare/v2.6.1...v2.6.2) (2026-01-19)


### Bug Fixes

* add missing warm_mist command handler ([f24999d](https://github.com/weirdtangent/govee2mqtt/commit/f24999d64fb07a83006e7346a1eb8696723d5735))
* correct dreamView instance name for proper toggle functionality ([365d87e](https://github.com/weirdtangent/govee2mqtt/commit/365d87ec62d094d8e5714e86f63965cad2572912))

## [2.6.1](https://github.com/weirdtangent/govee2mqtt/compare/v2.6.0...v2.6.1) (2026-01-19)


### Bug Fixes

* add letter suffix support to all appliance patterns ([7c40ecb](https://github.com/weirdtangent/govee2mqtt/commit/7c40ecb1192c39f6b1b14e7c77d48aea5abe3178))
* change appliance patterns from \d+ to \d* for letter-only suffixes ([d03a42c](https://github.com/weirdtangent/govee2mqtt/commit/d03a42c786eff20eb439a08cb7b42f4db9b8c906))
* log unrecognized devices at warning level instead of debug ([a828ba7](https://github.com/weirdtangent/govee2mqtt/commit/a828ba77b0eb205c40428c9a59b1580a31041007))
* support H605C and other short SKU light models ([d5c9e7f](https://github.com/weirdtangent/govee2mqtt/commit/d5c9e7f211cca62b7885e1883838a6e4a24ed063))
* update sensor pattern for consistency with light pattern ([1b4d8eb](https://github.com/weirdtangent/govee2mqtt/commit/1b4d8eb6e63e7dc8c4663ec7fcdfc7465d938329))

# [2.6.0](https://github.com/weirdtangent/govee2mqtt/compare/v2.5.4...v2.6.0) (2026-01-06)


### Bug Fixes

* address Copilot review concerns ([1a2df6c](https://github.com/weirdtangent/govee2mqtt/commit/1a2df6c5b5b81471f23be9aa1033d94452b4eb56))
* ensure protocol_version is always a string type ([28402d3](https://github.com/weirdtangent/govee2mqtt/commit/28402d37f94c0b2375c312bf80c6ea94f535ab23))


### Features

* add support for MQTT protocol version configuration ([2c4c9f2](https://github.com/weirdtangent/govee2mqtt/commit/2c4c9f27ba53a41ed5720f79132136f53db65aaa))

## [2.5.4](https://github.com/weirdtangent/govee2mqtt/compare/v2.5.3...v2.5.4) (2025-12-30)


### Bug Fixes

* handle Govee scene state id and paramId to eliminate warnings ([4a5dea2](https://github.com/weirdtangent/govee2mqtt/commit/4a5dea233c5d7fc5c985ca46c70f5c4913754f9f))

## [2.5.3](https://github.com/weirdtangent/govee2mqtt/compare/v2.5.2...v2.5.3) (2025-12-29)


### Bug Fixes

* add exception safety and normalize RGB key aliases ([50002e8](https://github.com/weirdtangent/govee2mqtt/commit/50002e8e870d8318cbd38b336c5804e6c446b0e3))
* batch color mode commands and infer brightness from rgb_color ([c64fa00](https://github.com/weirdtangent/govee2mqtt/commit/c64fa003bd8e14a1bdac129cacd532c90e5eb8ae))
* clear pending on cancellation during sleep to prevent stuck commands ([91fd471](https://github.com/weirdtangent/govee2mqtt/commit/91fd471897a01a1de9828f13dd0d1d4132bda163))
* hold lock during API call and handle string RGB values ([9461519](https://github.com/weirdtangent/govee2mqtt/commit/9461519b7d6798082a03363c90b2e433ebd89be7))
* release lock during batch window to allow command collection ([fe70986](https://github.com/weirdtangent/govee2mqtt/commit/fe7098697da5cfc78c20bf2fb9732be6bd8a07dd))

## [2.5.2](https://github.com/weirdtangent/govee2mqtt/compare/v2.5.1...v2.5.2) (2025-12-29)


### Bug Fixes

* serialize commands per-device to prevent race conditions ([fdf35e9](https://github.com/weirdtangent/govee2mqtt/commit/fdf35e90b84c0d193f8f89b61dfb8f647624b61f))

## [2.5.1](https://github.com/weirdtangent/govee2mqtt/compare/v2.5.0...v2.5.1) (2025-12-26)


### Bug Fixes

* Sort light scene options alphabetically ([94766c4](https://github.com/weirdtangent/govee2mqtt/commit/94766c46d6598c95883316d783d3383ae3395b58))

# [2.5.0](https://github.com/weirdtangent/govee2mqtt/compare/v2.4.0...v2.5.0) (2025-12-26)


### Features

* add light scene support for Govee lights ([3c6e4af](https://github.com/weirdtangent/govee2mqtt/commit/3c6e4af6cef72212234c9c04a486742e2310e964))

# [2.4.0](https://github.com/weirdtangent/govee2mqtt/compare/v2.3.3...v2.4.0) (2025-12-23)


### Features

* add security workflow features ([eef54b7](https://github.com/weirdtangent/govee2mqtt/commit/eef54b72bd0fc6968b392d8a3b9a64f3ed6ea943))

## [2.3.3](https://github.com/weirdtangent/govee2mqtt/compare/v2.3.2...v2.3.3) (2025-11-24)


### Bug Fixes

* make sure all device_names logged are in quotes ([5212dcf](https://github.com/weirdtangent/govee2mqtt/commit/5212dcf975554cc99c810c457b60368b374b2c8a))

## [2.3.2](https://github.com/weirdtangent/govee2mqtt/compare/v2.3.1...v2.3.2) (2025-11-24)


### Bug Fixes

* always try to log device_name in preference to device_id ([a7e055c](https://github.com/weirdtangent/govee2mqtt/commit/a7e055c24ef2613867170c326d249636fb2d38de))

## [2.3.1](https://github.com/weirdtangent/govee2mqtt/compare/v2.3.0...v2.3.1) (2025-11-22)


### Bug Fixes

* special case for rgb_color in light state ([39d07cc](https://github.com/weirdtangent/govee2mqtt/commit/39d07cc1ca04e83dda5bec376a9685f92149e347))

# [2.3.0](https://github.com/weirdtangent/govee2mqtt/compare/v2.2.0...v2.3.0) (2025-11-22)


### Features

* add air purifier support; update dependencies; optimize code ([a074b3c](https://github.com/weirdtangent/govee2mqtt/commit/a074b3c43c83477ba040424607a2fc8fc5ad57e7))

# [2.2.0](https://github.com/weirdtangent/govee2mqtt/compare/v2.1.1...v2.2.0) (2025-11-20)


### Features

* add humidifier support ([b1a74d2](https://github.com/weirdtangent/govee2mqtt/commit/b1a74d21ca7dd254b5fa673c99097586791d6636))

## [2.1.1](https://github.com/weirdtangent/govee2mqtt/compare/v2.1.0...v2.1.1) (2025-11-16)


### Bug Fixes

* light name; update packages ([cd212cb](https://github.com/weirdtangent/govee2mqtt/commit/cd212cb0e23559cd7a18f6baf89549e46e46ef6c))

# [2.1.0](https://github.com/weirdtangent/govee2mqtt/compare/v2.0.7...v2.1.0) (2025-11-09)


### Features

* **mqtt:** migrate Govee devices and service discovery to new 2024 “device” schema ([04b1687](https://github.com/weirdtangent/govee2mqtt/commit/04b1687dab4e2c26f5e2854203463e2c26815bfd))

## [2.0.7](https://github.com/weirdtangent/govee2mqtt/compare/v2.0.6...v2.0.7) (2025-11-07)


### Bug Fixes

* availability topic, mqtt subscribes, messages ([68613ed](https://github.com/weirdtangent/govee2mqtt/commit/68613edb244e35f790792e443a974125fdd75705))

## [2.0.6](https://github.com/weirdtangent/govee2mqtt/compare/v2.0.5...v2.0.6) (2025-11-03)


### Bug Fixes

* error introduced from wild package changes ([02a115b](https://github.com/weirdtangent/govee2mqtt/commit/02a115bd53f63452b6c8e20f6d1b788a9a031c6c))

## [2.0.5](https://github.com/weirdtangent/govee2mqtt/compare/v2.0.4...v2.0.5) (2025-11-03)


### Bug Fixes

* fix type hint for last_call_date ([84641d3](https://github.com/weirdtangent/govee2mqtt/commit/84641d39c99e403277c2b8daa80907389091e1ba))

## [2.0.4](https://github.com/weirdtangent/govee2mqtt/compare/v2.0.3...v2.0.4) (2025-10-19)


### Bug Fixes

* cleanup and getting modes to work ([9d9b82d](https://github.com/weirdtangent/govee2mqtt/commit/9d9b82d0a59c942dba56b0c0fd1b0660b2a9d152))

## [2.0.3](https://github.com/weirdtangent/govee2mqtt/compare/v2.0.2...v2.0.3) (2025-10-17)


### Bug Fixes

* publish discovery for modes; fix naming ([4ee15db](https://github.com/weirdtangent/govee2mqtt/commit/4ee15db9f1a3af9557f5c564b3368eb5bb5ee274))

## [2.0.2](https://github.com/weirdtangent/govee2mqtt/compare/v2.0.1...v2.0.2) (2025-10-15)


### Bug Fixes

* test to use renamed legacy method ([286ea19](https://github.com/weirdtangent/govee2mqtt/commit/286ea196a4ab14c14b4661b00dce19fffaebbe0b))
* using semantic-release plugin to update VERSION ([d57569c](https://github.com/weirdtangent/govee2mqtt/commit/d57569c70e2708ac98f3139dd53e2858d66a92b3))

## [2.0.1](https://github.com/weirdtangent/govee2mqtt/compare/v2.0.0...v2.0.1) (2025-10-15)


### Bug Fixes

* why didn't github action update this ([d403f6f](https://github.com/weirdtangent/govee2mqtt/commit/d403f6f4dd767d75009441993c6bcd2b14f737b2))

# [2.0.0](https://github.com/weirdtangent/govee2mqtt/compare/v1.0.3...v2.0.0) (2025-10-15)


* refactor!: correct MQTT discovery and refactor everything! ([ed70562](https://github.com/weirdtangent/govee2mqtt/commit/ed70562154d158e8d260acd3a47d1778b12fe014))


### Bug Fixes

* remove github action requirement for now ([c6cb35c](https://github.com/weirdtangent/govee2mqtt/commit/c6cb35cd76445a5af5d680244f34953050602990))


### BREAKING CHANGES

* unique_id values changed. Home Assistant will create new entities.

## [1.0.3](https://github.com/weirdtangent/govee2mqtt/compare/v1.0.2...v1.0.3) (2025-10-10)


### Bug Fixes

* improve startup flow and configuration handling ([1292fdf](https://github.com/weirdtangent/govee2mqtt/commit/1292fdf5767a12dc57263088c3067f2c86253417))

## [1.0.2](https://github.com/weirdtangent/govee2mqtt/compare/v1.0.1...v1.0.2) (2025-10-09)


### Bug Fixes

* tls_set call for ssl mqtt connections ([39db41e](https://github.com/weirdtangent/govee2mqtt/commit/39db41eed4d7e0810300eda9f09166c0fd35edf4))

## [1.0.1](https://github.com/weirdtangent/govee2mqtt/compare/v1.0.0...v1.0.1) (2025-10-09)


### Bug Fixes

* one more .gitignore ([6fd55c3](https://github.com/weirdtangent/govee2mqtt/commit/6fd55c3ff4c58de95473b02ef2298356c20e6085))

# 1.0.0 (2025-10-09)


### Features

* semantic versioning, github action features, writes a version file, and tags Docker images ([34ebf18](https://github.com/weirdtangent/govee2mqtt/commit/34ebf18945f39667ea2317e58e8cd5d8a5c33ede))
