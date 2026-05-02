.PHONY: dev install test build deploy clean

install:
	pip install -r requirements.txt

dev:
	uvicorn app.main:app --reload --port 8000

test:
	pytest tests/ -v --cov=app --cov-report=term-missing

test-fast:
	pytest tests/ -x -v -m "not slow"

build:
	docker build -t testscribe .

run:
	docker-compose up -d

stop:
	docker-compose down

migrate:
	python -c "from app.database import init_db; init_db(); print('Done')"

shell:
	python -c "from app.database import get_session_factory; db = get_session_factory()(); print('DB ready')"

deploy:
	fly deploy

secrets:
	fly secrets list

lint:
	ruff check app/ tests/

fmt:
	black app/ tests/ && isort app/ tests/

clean:
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	rm -f testscribe.db
