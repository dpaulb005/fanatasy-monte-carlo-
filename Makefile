PYTHON ?= python3

.PHONY: snapshot integrate test test-sim test-app

snapshot:
	$(PYTHON) -m nflsim app-export --teams 12 --scoring ppr \
		--out artifacts/application-snapshot.json

integrate: snapshot
	cd fantasy_analysis_app/backend && .venv/bin/python manage.py migrate --noinput
	cd fantasy_analysis_app/backend && .venv/bin/python manage.py import_nflsim \
		../../artifacts/application-snapshot.json

test: test-sim test-app

test-sim:
	$(PYTHON) -m pytest -q

test-app:
	cd fantasy_analysis_app/backend && .venv/bin/python -m pytest -q
	cd fantasy_analysis_app/frontend && npm test -- --run
	cd fantasy_analysis_app/frontend && npm run build
