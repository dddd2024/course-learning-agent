from app.schemas.knowledge_point import GenerateKnowledgePointsResponse


def test_knowledge_generation_contract_exposes_grounding_drop_statistics():
    payload = GenerateKnowledgePointsResponse(knowledge_points=[], requested=3, generated=1, dropped=2, drop_reasons=["unverified_or_inactive_source"])
    assert payload.model_dump()["dropped"] == 2
    assert payload.drop_reasons == ["unverified_or_inactive_source"]
