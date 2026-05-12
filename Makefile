# Workshop convenience wrappers around the explicit commands documented
# in README.md. The README remains the source of truth; this file just
# collapses the multi-step recipes into single commands.
#
# Override defaults at the CLI:
#   make eval REGION=us-west-2
#   make teardown EVAL_STACK=my-eval-pipeline

REGION       ?= us-east-1
KB_STACK     ?= kb-provisioning
EVAL_STACK   ?= rag-eval-pipeline

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@echo "Workshop convenience targets. Override defaults at the CLI"
	@echo "(e.g. 'make eval REGION=us-west-2'). The detailed step-by-step"
	@echo "commands live in README.md."
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z][a-zA-Z_-]+:.*?## / {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: install
install: ## Install dev/test dependencies for both stacks
	pip install -r kb_provisioning/requirements-dev.txt
	pip install -r evaluation/requirements-dev.txt

.PHONY: kb
kb: ## Deploy the KB provisioning stack (prepare + build + deploy)
	python kb_provisioning/scripts/prepare_lambda_assets.py
	cd kb_provisioning && sam build && sam deploy --config-file samconfig.toml

.PHONY: prompt
prompt: ## Create or update the Bedrock-managed eval prompt (publishes a new version)
	python evaluation/scripts/create_eval_prompt.py --region $(REGION)

.PHONY: manual-assets
manual-assets: ## Provision the workshop bucket for the manual-eval demo step
	python evaluation/scripts/setup_manual_eval_assets.py --region $(REGION)

.PHONY: eval
eval: ## Deploy the evaluation pipeline stack (prepare + build + deploy)
	python evaluation/scripts/prepare_lambda_assets.py
	cd evaluation && sam build && sam deploy --config-file samconfig.toml

.PHONY: trigger
trigger: ## Re-trigger the eval pipeline by publishing a new prompt version
	python evaluation/scripts/create_eval_prompt.py --region $(REGION)

.PHONY: test
test: ## Run pytest for both stacks
	pytest evaluation/tests/ -v
	pytest kb_provisioning/tests/ -v

.PHONY: teardown
teardown: teardown-eval teardown-kb ## Delete both stacks (eval first, then KB)

.PHONY: teardown-eval
teardown-eval: ## Delete only the evaluation stack
	cd evaluation && sam delete --stack-name $(EVAL_STACK) --region $(REGION)

.PHONY: teardown-kb
teardown-kb: ## Delete only the KB provisioning stack
	cd kb_provisioning && sam delete --stack-name $(KB_STACK) --region $(REGION)
