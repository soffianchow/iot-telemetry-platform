#!/usr/bin/env sh
# Mutual-TLS broker with one certificate per device and isolated publish topics,
# client ID forced to the certificate name, publish allowed only on the device's own topic.
# Throwaway CA and keys live in an ignored temp directory and are deleted on exit.
set -eu
umask 077
PORT="${TLS_TEST_PORT:-18884}"
NAME="iot-ops-tls-test-$$"
CONTAINER_ID=""
mkdir -p data
DIR=$(mktemp -d "$PWD/data/tls.XXXXXX")
cleanup() {
  if [ -n "$CONTAINER_ID" ]; then docker rm -f "$CONTAINER_ID" >/dev/null 2>&1 || true; fi
  rm -rf "$DIR"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

cat > "$DIR/ext.cnf" <<'EOF'
[ca]
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
[server]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
subjectAltName = DNS:localhost, IP:127.0.0.1
[client]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = clientAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
EOF

openssl req -newkey rsa:2048 -nodes -subj "/CN=iot-ops-test-ca" -keyout "$DIR/ca.key.pem" -out "$DIR/ca.csr" 2>/dev/null
openssl x509 -req -in "$DIR/ca.csr" -signkey "$DIR/ca.key.pem" -days 2 \
  -extfile "$DIR/ext.cnf" -extensions ca -out "$DIR/ca.pem" 2>/dev/null
issue() {  # name, extension section
  openssl req -newkey rsa:2048 -nodes -subj "/CN=$1" -keyout "$DIR/$1.key.pem" -out "$DIR/$1.csr" 2>/dev/null
  openssl x509 -req -in "$DIR/$1.csr" -CA "$DIR/ca.pem" -CAkey "$DIR/ca.key.pem" -CAcreateserial -CAserial "$DIR/ca.srl" -days 2 \
    -extfile "$DIR/ext.cnf" -extensions "$2" -out "$DIR/$1.cert.pem" 2>/dev/null
}
openssl req -x509 -newkey rsa:2048 -nodes -days 2 -subj "/CN=untrusted-test-ca" \
  -keyout "$DIR/untrusted-ca.key.pem" -out "$DIR/untrusted-ca.pem" 2>/dev/null
issue server server
for id in plot-01 plot-02 observer; do issue "$id" client; done
openssl verify -CAfile "$DIR/ca.pem" "$DIR/server.cert.pem" "$DIR/plot-01.cert.pem" >/dev/null

cat > "$DIR/acl" <<'EOF'
pattern write iot-ops/devices/%u/telemetry
user observer
topic read iot-ops/devices/+/telemetry
EOF
cat > "$DIR/mosquitto.conf" <<'EOF'
listener 8883
cafile /certs/ca.pem
certfile /certs/server.cert.pem
keyfile /certs/server.key.pem
tls_version tlsv1.2
require_certificate true
use_identity_as_username true
use_username_as_clientid true
allow_anonymous false
acl_file /certs/acl
log_dest stdout
EOF
# Mount only broker material; client and CA private keys never enter the container.
rm -f "$DIR"/ca.key.pem "$DIR"/untrusted-ca.key.pem "$DIR"/*.csr "$DIR"/ca.srl
chmod 600 "$DIR"/*.key.pem
mkdir "$DIR/broker"
for file in ca.pem server.cert.pem server.key.pem acl mosquitto.conf; do
  cp "$DIR/$file" "$DIR/broker/$file"
done

# Exact Mosquitto 2.0.22 image, shared by local ARM64 and CI AMD64 tests.
CONTAINER_ID=$(docker run -d --name "$NAME" \
  --user "$(id -u):$(id -g)" --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true --tmpfs /tmp \
  -p "127.0.0.1:$PORT:8883" -v "$DIR/broker:/certs:ro" \
  eclipse-mosquitto@sha256:adc7caf1ca9fb4cd5a0a222d60a63951db593fb055d69a2d17369510a7955983 \
  mosquitto -c /certs/mosquitto.conf)
i=0
until docker logs "$CONTAINER_ID" 2>&1 | grep -q "running"; do
  i=$((i + 1)); [ "$i" -lt 50 ] || { docker logs "$CONTAINER_ID"; exit 1; }; sleep 0.2
done
MQTT_TLS_TEST_DIR="$DIR" MQTT_HOST=localhost MQTT_PORT="$PORT" \
  uv run --frozen --extra dev --python 3.11 pytest -q tests/integration/test_mqtt_tls.py
