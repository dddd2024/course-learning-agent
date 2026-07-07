#!/usr/bin/env bash
# Phase 2 Engineering Bugfix Acceptance Script (Linux / macOS)
# Usage: bash ./scripts/verify_phase2_engineering.sh
#
# Mirrors scripts/verify_phase2_engineering.ps1 so the same acceptance
# checks can run on Linux CI runners (and locally on macOS/Linux).
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

failed=0
ok()   { echo "[OK] $1"; }
bad()  { echo "[FAIL] $1"; failed=1; }
step() { echo ""; echo "=== $1 ==="; }

# 1. Backend tests
step "Backend pytest"
cd "$root/backend"
if python -m pytest app/tests/ -q; then ok "backend tests passed"; else bad "backend tests failed"; fi
cd "$root"

# 2. Frontend build
step "Frontend build"
cd "$root/frontend"
if npm run build >/dev/null 2>&1; then ok "frontend build passed"; else bad "frontend build failed"; fi
cd "$root"

# 3. Subjective metric UI residue check
step "Subjective metric UI residue check"
if grep -rEn '可靠性|相关度|confidencePercent|命中率' "$root/frontend/src" --include='*.vue' --include='*.ts' 2>/dev/null; then
  bad "subjective metric UI residue found"
else
  ok "no subjective metric UI residue"
fi

# 4. algorithmic-art removed
step "algorithmic-art removal check"
if [ -d "$root/algorithmic-art" ]; then bad "algorithmic-art/ still exists"; else ok "algorithmic-art/ removed"; fi

# 5. CI workflow_dispatch trigger present
step "CI workflow_dispatch trigger check"
if grep -q 'workflow_dispatch' "$root/.github/workflows/ci.yml"; then ok "CI workflow_dispatch present"; else bad "CI workflow_dispatch missing"; fi

# 6. Production hardening check
step "Production hardening check"
main_py="$root/backend/app/main.py"
config_py="$root/backend/app/core/config.py"
if grep -q 'allow_origins=\["\*"\]' "$main_py"; then bad 'main.py hardcodes allow_origins=["*"]'; else ok "main.py uses config-driven CORS"; fi
if grep -q 'ENVIRONMENT' "$config_py" && grep -q 'CORS_ORIGINS' "$config_py" && grep -q 'def validate_prod_secrets' "$config_py"; then
  ok "config.py defines ENVIRONMENT/CORS_ORIGINS/validate_prod_secrets"
else
  bad "config.py missing hardening fields"
fi

# 7. Audit-submit-rectification checks
step "Audit-submit-rectification checks"
multi_plan="$root/backend/app/schemas/multi_plan.py"
plans_py="$root/backend/app/api/v1/endpoints/plans.py"
scheduler_py="$root/backend/app/services/multi_scheduler.py"
plan_ts="$root/frontend/src/api/plan.ts"

if grep -q 'model_validator' "$multi_plan" && grep -q 'priority' "$multi_plan"; then ok "MultiCourseInput normalizes legacy priority"; else bad "MultiCourseInput missing priority normalization"; fi
if grep -q 'user_config' "$scheduler_py"; then ok "schedule_multi_courses accepts user_config"; else bad "schedule_multi_courses missing user_config"; fi
if grep -q 'get_active_config' "$plans_py" && grep -q 'user_config=user_config' "$plans_py"; then ok "create_multi_plan passes user_config"; else bad "create_multi_plan missing user_config"; fi
if ! grep -q 'goal_ids' "$plan_ts"; then ok "frontend MultiPlanResult has no goal_ids"; else bad "frontend still has goal_ids"; fi
if grep -q '"\*" in origins' "$config_py"; then ok "config.py rejects wildcard CORS"; else bad "config.py missing wildcard rejection"; fi

# 8. Phase 0 edge-case checks
step "Phase 0 edge-case checks"
if grep -q 'is not None' "$scheduler_py" && ! grep -q 'or 0.5' "$scheduler_py"; then ok "scheduler preserves user_priority=0.0"; else bad "scheduler may still override user_priority=0.0"; fi
if grep -q 'ENVIRONMENT.lower()' "$config_py"; then ok "ENVIRONMENT check is case-insensitive"; else bad "ENVIRONMENT check is case-sensitive"; fi

echo ""
if [ "$failed" -eq 0 ]; then echo "ACCEPTANCE PASSED"; exit 0; else echo "ACCEPTANCE FAILED"; exit 1; fi
