#!/usr/bin/env sh
# Separate project, broker, network and volumes; never touch the running demo.
set -eu
export MQTT_PORT="${TEST_MQTT_PORT:-18883}"
cleanup() { docker compose -p iot-ops-test --profile test down -v; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
docker compose -p iot-ops-test --profile test run --build --rm tests
