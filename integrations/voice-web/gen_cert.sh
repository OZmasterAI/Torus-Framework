#!/usr/bin/env bash
# Generate self-signed cert with SAN for the VPS IP.
# Required: Safari needs HTTPS for Web Speech API.
set -euo pipefail

CERT_DIR="$(dirname "$0")/certs"
IP="${1:-YOUR_SERVER_IP}"
mkdir -p "$CERT_DIR"

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$CERT_DIR/key.pem" \
  -out "$CERT_DIR/cert.pem" \
  -days 365 \
  -subj "/CN=torus-voice" \
  -addext "subjectAltName=IP:${IP}"

echo "Certs written to $CERT_DIR/cert.pem and $CERT_DIR/key.pem"
