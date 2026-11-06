.PHONY: help verify check ci test

help: ## Show targets
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN { FS = ":.*## " } { printf "  %-8s %s\n", $$1, $$2 }'

verify: test ## Credential-free, non-mutating gate

check: verify ## Developer gate (the same checks)

ci: verify ## CI gate

test: ## The unit tests
	python3 -m unittest discover -s .github/scripts -p 'test_*.py' -v
