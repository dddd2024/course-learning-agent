"""Tests for LLM API Key encryption-key rotation (security Task E).

The rotation helper re-encrypts every ``user_llm_configs.api_key_encrypted``
from the old Fernet secret to a new one, so a compromised key can be
rotated without losing stored API keys.
"""
from app.core import crypto
from app.core.config import settings
from app.models.llm_config import UserLLMConfig
from app.services.llm_config_security import rotate_llm_config_secret


def _make_config(db, user_id, plaintext):
    cfg = UserLLMConfig(
        user_id=user_id,
        provider="OpenAI",
        name="cfg",
        base_url="https://api.openai.com/v1",
        model="gpt-4",
        api_key_encrypted=crypto.encrypt(plaintext),
        enabled=False,
        is_default=False,
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


def test_rotate_dry_run_does_not_modify(db_session, sample_user, monkeypatch):
    """--dry-run reports the count but does not change ciphertext."""
    monkeypatch.setattr(settings, "LLM_CONFIG_SECRET_KEY", "old-secret")
    _make_config(db_session, sample_user.id, "sk-old-1111111111111111")
    _make_config(db_session, sample_user.id, "sk-old-2222222222222222")

    original = [
        c.api_key_encrypted
        for c in db_session.query(UserLLMConfig).all()
    ]

    report = rotate_llm_config_secret(
        db_session, old_secret="old-secret", new_secret="new-secret", apply=False
    )
    assert report.affected == 2
    assert report.applied is False

    after = [
        c.api_key_encrypted
        for c in db_session.query(UserLLMConfig).all()
    ]
    assert after == original


def test_rotate_apply_re_encrypts_under_new_secret(db_session, sample_user, monkeypatch):
    """--apply re-encrypts so the new secret can decrypt, old cannot."""
    monkeypatch.setattr(settings, "LLM_CONFIG_SECRET_KEY", "old-secret")
    _make_config(db_session, sample_user.id, "sk-rotate-aaaaaaaaaaaa")

    report = rotate_llm_config_secret(
        db_session, old_secret="old-secret", new_secret="new-secret", apply=True
    )
    assert report.affected == 1
    assert report.applied is True
    assert report.failed == 0

    # The ciphertext must have changed.
    cfg = db_session.query(UserLLMConfig).first()
    assert cfg.api_key_encrypted != crypto.encrypt("sk-rotate-aaaaaaaaaaaa")

    # New secret can decrypt to the original plaintext.
    monkeypatch.setattr(settings, "LLM_CONFIG_SECRET_KEY", "new-secret")
    assert crypto.decrypt(cfg.api_key_encrypted) == "sk-rotate-aaaaaaaaaaaa"

    # Old secret can no longer decrypt.
    monkeypatch.setattr(settings, "LLM_CONFIG_SECRET_KEY", "old-secret")
    try:
        crypto.decrypt(cfg.api_key_encrypted)
        decrypted_with_old = True
    except Exception:
        decrypted_with_old = False
    assert decrypted_with_old is False


def test_rotate_reports_decrypt_failures(db_session, sample_user, monkeypatch):
    """Configs that cannot be decrypted with old-secret are counted as failed."""
    monkeypatch.setattr(settings, "LLM_CONFIG_SECRET_KEY", "old-secret")
    _make_config(db_session, sample_user.id, "sk-good-3333333333333333")
    # Insert a config encrypted under a DIFFERENT secret (will fail to decrypt).
    monkeypatch.setattr(settings, "LLM_CONFIG_SECRET_KEY", "other-secret")
    _make_config(db_session, sample_user.id, "sk-bad-4444444444444444")

    report = rotate_llm_config_secret(
        db_session, old_secret="old-secret", new_secret="new-secret", apply=True
    )
    assert report.affected == 2
    assert report.failed == 1
    assert report.applied is True
