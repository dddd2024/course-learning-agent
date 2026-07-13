"""Runtime contract tests for V7.4.3 quiz generation."""
import pytest

from app.core.exceptions import BusinessException
from app.services.quiz_creation_service import _is_acceptable_item, _item_identity, resolve_quiz_contract


@pytest.mark.parametrize("count", [1, 2, 3, 5, 10, 11])
def test_default_contract_is_runtime_resolved(count):
    contract = resolve_quiz_contract(count, None, None, 60)
    assert sum(contract.difficulty_distribution.values()) == count
    assert contract.question_types


def test_explicit_contract_is_immutable_and_exact():
    contract = resolve_quiz_contract(3, ["multiple_choice"], {"easy": 1, "medium": 1, "hard": 1}, 80)
    assert contract.question_types == ("multiple_choice",)
    assert contract.pass_score == 80
    with pytest.raises(TypeError):
        contract.difficulty_distribution["easy"] = 2


def test_invalid_distribution_is_rejected_before_generation():
    with pytest.raises(BusinessException) as error:
        resolve_quiz_contract(3, ["choice"], {"easy": 1, "medium": 1, "hard": 0}, 60)
    assert error.value.status_code == 422


def test_retry_keeps_only_contract_compliant_non_duplicate_items():
    contract = resolve_quiz_contract(2, ["choice"], {"easy": 1, "medium": 1, "hard": 0}, 60)
    remaining, seen = dict(contract.difficulty_distribution), set()
    easy = {"question_text": " TCP/IP 的作用？ ", "question_type": "choice", "difficulty": 1, "knowledge_point_id": 1, "source_evidence": [{"chunk_id": 1}]}
    duplicate = {**easy, "question_text": "tcp/ip 的作用？"}
    wrong_band = {**easy, "question_text": "HTTP/2", "difficulty": 5}
    assert _is_acceptable_item(easy, contract, remaining, seen)
    seen.add(_item_identity(easy)); remaining["easy"] -= 1
    assert not _is_acceptable_item(duplicate, contract, remaining, seen)
    assert not _is_acceptable_item(wrong_band, contract, remaining, seen)
