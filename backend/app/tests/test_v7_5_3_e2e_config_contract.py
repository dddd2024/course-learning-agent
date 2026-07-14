from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[3]
CONFIG = PROJECT_DIR / "frontend" / "playwright.config.ts"
RUNTIME = PROJECT_DIR / "frontend" / "tests" / "e2e" / "e2e-runtime.ts"
SETUP = PROJECT_DIR / "frontend" / "tests" / "e2e" / "global-setup.ts"
TEARDOWN = PROJECT_DIR / "frontend" / "tests" / "e2e" / "global-teardown.ts"


def test_playwright_never_reuses_existing_services() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    assert text.count("reuseExistingServer: false") == 3
    assert "reuseExistingServer: !process.env.CI" not in text


def test_runtime_uses_unique_run_scoped_database_and_uploads() -> None:
    text = RUNTIME.read_text(encoding="utf-8")
    assert "randomUUID" in text
    assert "storage', 'e2e-runs', e2eRunId" in text
    assert "e2eDatabaseUrl" in text
    assert "process.env.DATABASE_URL = e2eDatabaseUrl" in text
    assert "process.env.UPLOAD_DIR = e2eUploadDir" in text


def test_global_setup_snapshots_normal_uploads_and_teardown_compares_it() -> None:
    setup = SETUP.read_text(encoding="utf-8")
    teardown = TEARDOWN.read_text(encoding="utf-8")
    assert "normal_uploads_before" in setup
    assert "snapshotDirectory(normalUploadDir)" in setup
    assert "normal_uploads_unchanged" in teardown
    assert "rmSync(e2eRunRoot" in teardown
    assert "throw new Error" in teardown


def test_config_does_not_inherit_ordinary_database_url() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    assert "process.env.DATABASE_URL ||" not in text
    assert "DATABASE_URL: e2eDatabaseUrl" in text
    assert "E2E_RUN_ID: e2eRunId" in text
