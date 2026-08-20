.PHONY: help assets font nerdfont verify-assets clean build build-for run test lint py-lock py-sync voices version

# =============================================================================
# Variables
# =============================================================================
APP_NAME := tiny-ai-suite
MODULE   := github.com/tanq16/tiny-ai-suite

VERSION ?= dev-build
GOOS    ?= $(shell go env GOOS)
GOARCH  ?= $(shell go env GOARCH)

# Pinned asset versions. Bump deliberately, never float.
TAILWIND_VERSION    := 4.3.3
LUCIDE_VERSION      := 1.31.0
MARKED_VERSION      := 18.0.9
HIGHLIGHTJS_VERSION := 11.12.0
NERDFONT_VERSION    := 3.5.0

STATIC_DIR := internal/server/static
JS_DIR     := $(STATIC_DIR)/js
CSS_DIR    := $(STATIC_DIR)/css
FONTS_DIR  := $(STATIC_DIR)/fonts

SCRIPTS_DIR := ai-scripts
PROJECTS    := stems denoise transcribe tts voiceclone doc2md ocr upscale

# Google Fonts serves woff2 only to a browser-shaped User-Agent; an unrecognized
# one gets ttf, which is roughly twice the bytes.
UA := Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36
# `uv tool run` is the always-present equivalent of uvx.
UVX := uv tool run

CYAN  := \033[0;36m
GREEN := \033[0;32m
NC    := \033[0m

# =============================================================================
# Help
# =============================================================================
help: ## Show this help
	@echo "$(CYAN)Available targets:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-20s$(NC) %s\n", $$1, $$2}'

.DEFAULT_GOAL := help

# =============================================================================
# Assets
# =============================================================================
assets: ## Download pinned frontend assets (never committed)
	@mkdir -p $(JS_DIR) $(CSS_DIR) $(FONTS_DIR)
	@curl -sfL "https://cdn.jsdelivr.net/npm/@tailwindcss/browser@$(TAILWIND_VERSION)" -o "$(JS_DIR)/tailwind.js"
	@curl -sfL "https://cdn.jsdelivr.net/npm/lucide@$(LUCIDE_VERSION)/dist/umd/lucide.min.js" -o "$(JS_DIR)/lucide.min.js"
	@# marked 18 dropped the prebuilt marked.min.js; the UMD bundle is the browser entry point.
	@curl -sfL "https://cdn.jsdelivr.net/npm/marked@$(MARKED_VERSION)/lib/marked.umd.js" -o "$(JS_DIR)/marked.min.js"
	@curl -sfL "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@$(HIGHLIGHTJS_VERSION)/highlight.min.js" -o "$(JS_DIR)/highlight.min.js"
	@curl -sfL "https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@$(HIGHLIGHTJS_VERSION)/styles/github-dark.min.css" -o "$(CSS_DIR)/github-dark.min.css"
	@$(MAKE) --no-print-directory font FAMILY="Inter" SLUG=inter WEIGHTS="400;500;600;700"
	@$(MAKE) --no-print-directory font FAMILY="Google+Sans" SLUG=google-sans WEIGHTS="400;500;700"
	@$(MAKE) --no-print-directory nerdfont
	@echo "$(GREEN)Assets downloaded$(NC)"

# One Google Fonts family: fetch the stylesheet, pull every woff2 it names, and
# repoint the URLs at the local copies so nothing is fetched at run time.
font:
	@curl -sfL -H "User-Agent: $(UA)" \
	  "https://fonts.googleapis.com/css2?family=$(FAMILY):wght@$(WEIGHTS)&display=swap" \
	  -o "$(CSS_DIR)/$(SLUG).css"
	@grep -o 'https://fonts.gstatic.com/[^)]*' "$(CSS_DIR)/$(SLUG).css" | sort -u | while read -r url; do \
	  curl -sfL "$$url" -o "$(FONTS_DIR)/$$(basename "$$url")"; \
	done
	@sed -i.bak -E 's|https://fonts\.gstatic\.com/[^)]*/([^/)]+)|/static/fonts/\1|g' "$(CSS_DIR)/$(SLUG).css"
	@rm -f "$(CSS_DIR)/$(SLUG).css.bak"

# The Nerd Font variant carries the extra glyphs and is not on Google Fonts, so it
# comes from the nerd-fonts release as ttf and is compressed to woff2 here.
nerdfont:
	@set -e; tmp="$$(mktemp -d)"; trap 'rm -rf "$$tmp"' EXIT; \
	curl -sfL -o "$$tmp/JetBrainsMono.zip" \
	  "https://github.com/ryanoasis/nerd-fonts/releases/download/v$(NERDFONT_VERSION)/JetBrainsMono.zip"; \
	unzip -q -j "$$tmp/JetBrainsMono.zip" \
	  JetBrainsMonoNerdFontMono-Regular.ttf JetBrainsMonoNerdFontMono-Bold.ttf -d "$$tmp"; \
	for w in Regular Bold; do \
	  $(UVX) --from "fonttools[woff]" fonttools ttLib.woff2 compress \
	    -o "$(FONTS_DIR)/JetBrainsMonoNerdFontMono-$$w.woff2" "$$tmp/JetBrainsMonoNerdFontMono-$$w.ttf"; \
	done
	@{ \
	  for pair in 400:Regular 700:Bold; do \
	    printf '@font-face{font-family:"JetBrains Mono";font-style:normal;font-weight:%s;font-display:swap;src:url("/static/fonts/JetBrainsMonoNerdFontMono-%s.woff2") format("woff2");}\n' \
	      "$${pair%%:*}" "$${pair##*:}"; \
	  done; \
	} > "$(CSS_DIR)/jetbrains-mono.css"

verify-assets: ## Fail early if the embedded tree is missing an asset
	@test -f $(JS_DIR)/tailwind.js || (echo "tailwind.js missing, run 'make assets'" && exit 1)
	@test -f $(CSS_DIR)/inter.css || (echo "inter.css missing, run 'make assets'" && exit 1)
	@test -f $(CSS_DIR)/google-sans.css || (echo "google-sans.css missing, run 'make assets'" && exit 1)
	@test -f $(CSS_DIR)/jetbrains-mono.css || (echo "jetbrains-mono.css missing, run 'make assets'" && exit 1)
	@echo "$(GREEN)Assets verified$(NC)"

# =============================================================================
# Python scripts
# =============================================================================
py-lock: ## Re-resolve every task project's lockfile
	@for p in $(PROJECTS); do \
	  echo "$(CYAN)locking $$p$(NC)"; uv lock --project "$(SCRIPTS_DIR)/$$p"; \
	done

py-sync: ## Pre-install every task environment so a first run does not stall
	@for p in $(PROJECTS); do \
	  echo "$(CYAN)syncing $$p$(NC)"; uv sync --project "$(SCRIPTS_DIR)/$$p"; \
	done
	@echo "$(GREEN)Task environments ready$(NC)"

voices: ## Render the built-in voice cloning reference clips
	@uv run --project $(SCRIPTS_DIR)/tts make-voices --outdir $(SCRIPTS_DIR)/voiceclone/voices
	@echo "$(GREEN)Reference clips written to $(SCRIPTS_DIR)/voiceclone/voices$(NC)"

lint: ## Lint the Python sources
	@uv run ruff check $(SCRIPTS_DIR)
	@uv run ruff format --check $(SCRIPTS_DIR)

# =============================================================================
# Build
# =============================================================================
# The task virtualenvs are left alone: rebuilding them costs several GB of downloads.
clean: ## Remove built binaries, downloaded assets and Python caches
	@rm -f $(APP_NAME) $(APP_NAME)-*
	@rm -rf $(JS_DIR) $(CSS_DIR) $(FONTS_DIR)
	@find $(SCRIPTS_DIR) -name __pycache__ -type d -not -path '*/.venv/*' -exec rm -rf {} + 2>/dev/null || true
	@echo "$(GREEN)Cleaned$(NC)"

build: assets verify-assets ## Build for the current platform
	@go build -ldflags="-s -w -X '$(MODULE)/cmd.AppVersion=$(VERSION)'" -o $(APP_NAME) .
	@echo "$(GREEN)Built: ./$(APP_NAME)$(NC)"

# Apple Silicon is the only target that matters: every engine here needs Metal.
build-for: verify-assets ## Build for a specific GOOS/GOARCH
	@CGO_ENABLED=0 GOOS=$(GOOS) GOARCH=$(GOARCH) go build \
	  -ldflags="-s -w -X '$(MODULE)/cmd.AppVersion=$(VERSION)'" \
	  -o $(APP_NAME)-$(GOOS)-$(GOARCH) .
	@echo "$(GREEN)Built: ./$(APP_NAME)-$(GOOS)-$(GOARCH)$(NC)"

run: build ## Build and serve on 127.0.0.1:7777
	@./$(APP_NAME) serve

test: ## Run the Go test suite
	@go test ./...

# =============================================================================
# Version
# =============================================================================
version: ## Print the next version, derived from the last commit message
	@LATEST_TAG=$$(git tag --sort=-v:refname | head -n1 || echo "0.0.0"); \
	LATEST_TAG=$${LATEST_TAG#v}; \
	MAJOR=$$(echo "$$LATEST_TAG" | cut -d. -f1); \
	MINOR=$$(echo "$$LATEST_TAG" | cut -d. -f2); \
	PATCH=$$(echo "$$LATEST_TAG" | cut -d. -f3); \
	MAJOR=$${MAJOR:-0}; MINOR=$${MINOR:-0}; PATCH=$${PATCH:-0}; \
	COMMIT_MSG="$$(git log -1 --pretty=%B)"; \
	if echo "$$COMMIT_MSG" | grep -q "\[major-release\]"; then \
		MAJOR=$$((MAJOR + 1)); MINOR=0; PATCH=0; \
	elif echo "$$COMMIT_MSG" | grep -q "\[minor-release\]"; then \
		MINOR=$$((MINOR + 1)); PATCH=0; \
	else \
		PATCH=$$((PATCH + 1)); \
	fi; \
	echo "v$${MAJOR}.$${MINOR}.$${PATCH}"
