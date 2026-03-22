.PHONY: test lint quickstart-client aws-build aws-push aws-deploy k8s-apply k8s-delete k8s-logs

# ── AWS deployment helpers ───────────────────────────────────────────────────
# Prerequisites: AWS CLI configured, Terraform installed, ECR repos created
# Usage:
#   make aws-build                    # build images locally
#   AWS_REGION=us-east-1 make aws-push ECR_API=<uri> ECR_WORKER=<uri>
#   cd deploy/aws && terraform apply  # provision EC2 + S3 + ECR

AWS_REGION   ?= us-east-1
ECR_API      ?= $(shell cd deploy/aws && terraform output -raw ecr_api_uri 2>/dev/null)
ECR_WORKER   ?= $(shell cd deploy/aws && terraform output -raw ecr_worker_uri 2>/dev/null)

aws-build:
	docker build -t docextract-api:latest -f Dockerfile .
	docker build -t docextract-worker:latest -f Dockerfile.worker .

aws-push: aws-build
	aws ecr get-login-password --region $(AWS_REGION) \
	  | docker login --username AWS --password-stdin $(shell echo $(ECR_API) | cut -d/ -f1)
	docker tag docextract-api:latest $(ECR_API):latest
	docker tag docextract-worker:latest $(ECR_WORKER):latest
	docker push $(ECR_API):latest
	docker push $(ECR_WORKER):latest

aws-deploy:
	cd deploy/aws && terraform init && terraform apply -auto-approve

test:
	pytest -v

lint:
	ruff check app worker tests

# ── Kubernetes helpers ───────────────────────────────────────────────────────
# Prerequisites: kubectl + kustomize installed, kubeconfig pointing at target cluster
# Usage:
#   make k8s-apply                    # deploy base manifests
#   K8S_ENV=production make k8s-apply # deploy production overlay

K8S_ENV ?= base

k8s-apply:
ifeq ($(K8S_ENV),production)
	kubectl apply -k deploy/k8s/overlays/production/
else
	kubectl apply -k deploy/k8s/
endif

k8s-delete:
	kubectl delete -k deploy/k8s/ --ignore-not-found=true

k8s-logs:
	kubectl logs -n docextract -l app.kubernetes.io/name=docextract --all-containers=true --prefix=true -f

quickstart-client:
	@echo "Quickstart checklist for new DocExtract client"
	@echo "1) cp .env.example .env"
	@echo "2) Set database_url, redis_url, anthropic_api_key"
	@echo "3) docker compose up -d db redis"
	@echo "4) uvicorn app.main:app --reload"
	@echo "5) POST /api/v1/reports/generate after first run"
