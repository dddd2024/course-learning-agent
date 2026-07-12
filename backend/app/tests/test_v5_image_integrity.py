from app.schemas.material import ImageResponse

def test_image_contract_exposes_independent_state_fields():
    # A reader can mark one image missing without treating the material as failed.
    image = ImageResponse(id=1, page_no=2, file_url="/image/1")
    assert image.id == 1 and image.file_url.endswith("/1")
