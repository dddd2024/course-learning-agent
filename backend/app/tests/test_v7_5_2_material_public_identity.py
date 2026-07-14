"""Public material identity remains immutable while numeric routes work."""
from __future__ import annotations

from uuid import UUID

from app.tests.conftest import auth_headers, create_course


def test_uploaded_material_has_public_id_and_file_route_accepts_both_id_forms(client):
    headers = auth_headers(client, username="public-owner")
    course_id = create_course(client, headers)
    response = client.post(
        f"/api/v1/courses/{course_id}/materials",
        headers=headers,
        files={"file": ("identity.txt", b"immutable material identity", "text/plain")},
    )
    assert response.status_code == 201, response.text
    material = response.json()
    assert UUID(material["public_id"]).version == 4
    assert material["file_url"].endswith(f"/materials/{material['public_id']}/file")

    numeric = client.get(f"/api/v1/materials/{material['id']}/file", headers=headers)
    public = client.get(f"/api/v1/materials/{material['public_id']}/file", headers=headers)
    assert numeric.status_code == public.status_code == 200
    assert numeric.content == public.content == b"immutable material identity"


def test_public_material_identity_keeps_ownership_filter(client):
    owner_headers = auth_headers(client, username="public-owner-2")
    owner_course = create_course(client, owner_headers)
    response = client.post(
        f"/api/v1/courses/{owner_course}/materials",
        headers=owner_headers,
        files={"file": ("secret.txt", b"not another user", "text/plain")},
    )
    assert response.status_code == 201
    public_id = response.json()["public_id"]
    other_headers = auth_headers(client, username="public-other")
    assert client.get(f"/api/v1/materials/{public_id}/file", headers=other_headers).status_code == 404
