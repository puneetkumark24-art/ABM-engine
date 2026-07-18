# Terraform skeleton — DRIP enterprise infra (Sprint 1, S1-05).
# Provisions the managed dependencies the K8s workloads expect: a Postgres 16
# (multi-AZ, PITR), a Redis, and a Kubernetes cluster. Cloud-agnostic shape;
# swap the module sources for your provider (this example targets AWS).
#
#   terraform init && terraform plan -var-file=prod.tfvars
#
# NOTE: this is infrastructure-as-code scaffolding to be completed with your
# account, region, VPC, and backend. It is intentionally minimal + reviewable.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  # backend "s3" { bucket = "drip-tfstate" key = "prod/terraform.tfstate" region = var.region }
}

provider "aws" { region = var.region }

variable "region"        { default = "me-south-1" }   # Bahrain (KSA data residency)
variable "env"           { default = "prod" }
variable "db_password"   { sensitive = true }
variable "vpc_id"        {}
variable "subnet_ids"    { type = list(string) }

# --- PostgreSQL 16 (system of record; multi-AZ + PITR for DR) ---
resource "aws_db_instance" "drip" {
  identifier              = "drip-${var.env}"
  engine                  = "postgres"
  engine_version          = "16"
  instance_class          = "db.r6g.large"
  allocated_storage       = 100
  max_allocated_storage   = 1000
  multi_az                = true
  storage_encrypted       = true
  backup_retention_period = 14          # PITR window (DR)
  deletion_protection     = true
  username                = "postgres"
  password                = var.db_password
  db_name                 = "drip"
  skip_final_snapshot     = false
  performance_insights_enabled = true
}

# --- Redis (cache + rate limits + future streams) ---
resource "aws_elasticache_replication_group" "drip" {
  replication_group_id = "drip-${var.env}"
  description          = "DRIP cache"
  engine              = "redis"
  engine_version      = "7.1"
  node_type           = "cache.t4g.small"
  num_cache_clusters  = 2                # primary + replica (HA)
  automatic_failover_enabled = true
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
}

# --- EKS cluster (runs api/worker/scheduler from deploy/k8s/) ---
module "eks" {
  source          = "terraform-aws-modules/eks/aws"
  version         = "~> 20.0"
  cluster_name    = "drip-${var.env}"
  cluster_version = "1.30"
  vpc_id          = var.vpc_id
  subnet_ids      = var.subnet_ids
  eks_managed_node_groups = {
    default = { instance_types = ["m6g.large"], min_size = 3, max_size = 12, desired_size = 4 }
  }
}

output "db_endpoint"    { value = aws_db_instance.drip.address }
output "redis_endpoint" { value = aws_elasticache_replication_group.drip.primary_endpoint_address }
output "eks_cluster"    { value = module.eks.cluster_name }
