# HW8 shortcuts (run from the repo root)
.PHONY: verify-hw08 hw08-up hw08-topics hw08-part3 hw08-test hw08-down

verify-hw08:
	python scripts/verify_hw08.py

hw08-up:
	docker compose -f docker-compose.kafka.yml up -d --build

hw08-topics:
	bash scripts/hw08_create_topics.sh

hw08-part3:
	python scripts/run_hw08_part3.py all

hw08-test:
	python tests/test_hw08_kafka.py

hw08-down:
	docker compose -f docker-compose.kafka.yml down

# HW9 shortcuts (run from the repo root)
.PHONY: verify-hw09

verify-hw09:
	python scripts/verify_hw09.py

# HW10 shortcuts (run from the repo root)
.PHONY: verify-hw10 hw10-test hw10-dashboard

verify-hw10:
	python scripts/verify_hw10.py

hw10-test:
	python tests/test_hw10.py

hw10-dashboard:
	streamlit run hw10/dashboard.py --server.port 8676
