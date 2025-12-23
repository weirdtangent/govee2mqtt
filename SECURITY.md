# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it by opening a private security advisory at:

https://github.com/weirdtangent/govee2mqtt/security/advisories/new

Please include as much information as possible to help us understand and address the issue quickly.

## Container Image Verification

All container images are signed using [Cosign](https://github.com/sigstore/cosign) with keyless signing via GitHub Actions OIDC.

### Verifying Image Signatures

To verify the signature of a container image:

```bash
cosign verify graystorm/govee2mqtt:latest \
  --certificate-identity-regexp="https://github.com/weirdtangent/govee2mqtt/.github/workflows/.*" \
  --certificate-oidc-issuer="https://token.actions.githubusercontent.com"
```

## Security Scanning

- **Trivy**: All images are scanned for vulnerabilities using [Trivy](https://github.com/aquasecurity/trivy)
- **SBOM**: Software Bill of Materials is generated for each image
- **Provenance**: Build provenance attestations are included with each image

## Security Features

- Container images are built with SBOM (Software Bill of Materials)
- Container images include provenance attestations
- Vulnerability scan results are uploaded to GitHub Security tab
- All builds are performed in GitHub Actions with minimal permissions
