dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

install:
	pip3 install -r requirements.txt

test:
	python3 -m pytest tests/ -v

docker-up:
	docker compose up --build

docker-down:
	docker compose down

.PHONY: dev install test docker-up docker-down
