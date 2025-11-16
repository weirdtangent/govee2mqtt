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
