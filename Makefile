# SPDX-FileCopyrightText: 2026 Andrew Zhang <whisper67265@outlook.com>
#
# SPDX-License-Identifier: BSL-1.0

# Shared Makefile for CI scripts and CD deploys.
# Usage: make build && make up && make health

COMPOSE_FILE ?= docker/docker-compose.yml
COMPOSE_PROJECT_NAME ?= cppa-weblate-plugin
COMPOSE = docker compose -f $(COMPOSE_FILE) -p $(COMPOSE_PROJECT_NAME)
WEBLATE_PORT ?= 8080
HEALTH_TIMEOUT ?= 120

.PHONY: build up down logs health token

build:
	$(COMPOSE) build $(BUILD_ARGS)

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down -v --remove-orphans

logs:
	$(COMPOSE) logs

health:
	@elapsed=0; \
	while [ $$elapsed -lt $(HEALTH_TIMEOUT) ]; do \
		if curl -sf http://localhost:$(WEBLATE_PORT)/healthz/ > /dev/null 2>&1; then \
			echo "Weblate healthy (after $${elapsed}s)"; exit 0; \
		fi; \
		sleep 5; \
		elapsed=$$((elapsed + 5)); \
	done; \
	echo "ERROR: Weblate not healthy after $(HEALTH_TIMEOUT)s"; \
	$(COMPOSE) logs weblate | tail -40; \
	exit 1

token:
	@$(COMPOSE) exec -T weblate weblate createtoken admin | tail -1
