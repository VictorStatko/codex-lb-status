.DEFAULT_GOAL := help

PYTHON ?= python3
PYTEST ?= pytest
RUFF ?= ruff
UV ?= uv

.PHONY: help check test-ui package prepare-release release-check

help:
	@printf '%s\n' \
		'make check                         Run the standard developer checks' \
		'make test-ui                       Run Qt UI tests with Xvfb and D-Bus' \
		'make package                       Build and inspect the Debian package' \
		'make prepare-release VERSION=x.y.z Prepare all version metadata' \
		'make release-check VERSION=x.y.z   Verify all version metadata'

check:
	$(PYTHON) -m compileall -q src
	$(UV) lock --check
	$(RUFF) check .
	$(RUFF) format --check .
	PYTHONWARNINGS=error QT_QPA_PLATFORM=offscreen $(PYTEST) -q \
		--cov=codex_lb_status \
		--cov-report=term-missing

test-ui:
	dbus-run-session -- xvfb-run -a $(PYTEST) -q \
		tests/test_ui.py \
		tests/test_settings_ui.py \
		tests/test_login_ui.py \
		tests/test_indicator.py \
		tests/test_single_instance.py

package:
	dpkg-buildpackage -us -uc -b
	@set -eu; \
		package_version="$$(dpkg-parsechangelog -S Version)"; \
		package_path="../codex-lb-status_$${package_version}_all.deb"; \
		lintian --fail-on error "$${package_path}"; \
		dpkg-deb --info "$${package_path}"; \
		dpkg-deb --contents "$${package_path}"

prepare-release:
	@test -n "$(VERSION)" || { echo 'VERSION is required; use make prepare-release VERSION=x.y.z' >&2; exit 2; }
	$(PYTHON) scripts/release.py prepare "$(VERSION)"
	$(UV) lock
	$(PYTHON) scripts/release.py check "$(VERSION)"
	@printf 'Release %s is prepared. Review the changes, run make check, commit, merge, and push tag v%s.\n' "$(VERSION)" "$(VERSION)"

release-check:
	@test -n "$(VERSION)" || { echo 'VERSION is required; use make release-check VERSION=x.y.z' >&2; exit 2; }
	$(PYTHON) scripts/release.py check "$(VERSION)"
