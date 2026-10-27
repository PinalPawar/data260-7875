#!/usr/bin/env bash
# HW8: create the s7875 Kafka topics with the Kafka CLI inside the s7875_kafka container.
#   bash scripts/hw08_create_topics.sh
# Safe to re-run (--if-not-exists). The two Part 1 topics are also made by kafka-init in
# docker-compose.kafka.yml; this script makes the Part 2/3 ones and describes all of them.
set -eu
KT="docker exec s7875_kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092"

echo "===== Pinal Pawar | SID4 7875 | PREFIX s7875 | creating HW8 topics ====="
create() {  # name partitions
  echo "+ kafka-topics --create --topic $1 --partitions $2 --replication-factor 1"
  # kafka-topics warns about '_' in names (metric-name collision with '.'); hide that line
  $KT --create --if-not-exists --topic "$1" --partitions "$2" --replication-factor 1 2>&1 \
    | grep -v "WARNING: Due to limitations in metric names" || true
}
create s7875_notice_requests 1
create s7875_notice_responses 1
create s7875_inbox 1
create s7875_tasks 2
create s7875_drafts 1
create s7875_final 1
create s7875_dead_letter 1

echo
echo "+ kafka-topics --list"
$KT --list | grep '^s7875_'
echo
echo "+ kafka-topics --describe (s7875_*)"
for t in s7875_notice_requests s7875_notice_responses s7875_inbox s7875_tasks s7875_drafts \
         s7875_final s7875_dead_letter; do
  $KT --describe --topic "$t" | grep '^Topic:' || true
done
