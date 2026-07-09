# PDF 图片提取与展示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从PDF资料中提取嵌入图片，存储到磁盘，通过API提供给前端，在学习文档页面中展示图片。

**Architecture:** 使用 PyMuPDF(fitz) 替代 pypdf 提取PDF中的嵌入图片。新增 `MaterialImage` 数据模型记录图片元数据（页码、文件路径、宽高）。在 `parse_with_retry` 解析流程中插入图片提取步骤。在 `main.py` 挂载静态文件服务提供图片HTTP访问。扩展 `ChunkResponse` 包含同页图片列表。前端 `LearnView.vue` 在chunk卡片下方展示关联图片。

**Tech Stack:** PyMuPDF(fitz), Pillow, FastAPI StaticFiles, SQLAlchemy, Vue 3 + Element Plus

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/requirements.txt` | Modify | 添加 PyMuPDF + Pillow |
| `backend/app/models/material_image.py` | Create | MaterialImage 数据模型 |
| `backend/app/models/__init__.py` | Modify | 注册 MaterialImage |
| `backend/app/db/migrations.py` | Modify | 添加 ensure_material_images_table |
| `backend/app/retrieval/image_extractor.py` | Create | PDF 图片提取核心逻辑 |
| `backend/app/services/material_parser.py` | Modify | 在解析流程中调用图片提取 |
| `backend/app/schemas/material.py` | Modify | 扩展 ChunkResponse + 新增 ImageResponse |
| `backend/app/api/v1/endpoints/parse.py` | Modify | chunks API 返回关联图片 |
| `backend/app/main.py` | Modify | 挂载 /uploads 静态文件 |
| `backend/app/tests/test_image_extractor.py` | Create | 图片提取单元测试 |
| `frontend/src/api/material.ts` | Modify | Chunk 类型添加 images 字段 |
| `frontend/src/views/LearnView.vue` | Modify | 展示图片 |

---

### Task 1: 安装依赖 + 数据模型 + 迁移

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/app/models/material_image.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/db/migrations.py`

- [ ] **Step 1: 安装 PyMuPDF 和 Pillow**

```bash
cd f:\course-learning-agent\backend
.venv\Scripts\pip install PyMuPDF Pillow
```

在 `requirements.txt` 末尾添加:
```
PyMuPDF>=1.24.0
Pillow>=10.0.0
```

- [ ] **Step 2: 创建 MaterialImage 模型**

Create `backend/app/models/material_image.py`:
```python
"""MaterialImage model — stores metadata for images extracted from PDF materials."""
from sqlalchemy import Column, Integer, String, ForeignKey, Float
from app.models.base import Base, TimestampMixin


class MaterialImage(Base, TimestampMixin):
    __tablename__ = "material_images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(Integer, ForeignKey("materials.id"), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    chunk_id = Column(Integer, ForeignKey("material_chunks.id"), nullable=True, index=True)
    page_no = Column(Integer, nullable=False)
    image_filename = Column(String(255), nullable=False)
    image_path = Column(String(500), nullable=False)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    format = Column(String(10), default="png")
```

- [ ] **Step 3: 注册模型**

在 `backend/app/models/__init__.py` 中添加:
```python
from app.models.material_image import MaterialImage
```

- [ ] **Step 4: 添加迁移函数**

在 `backend/app/db/migrations.py` 末尾添加:
```python
def ensure_material_images_table(engine: Engine) -> None:
    """Create material_images table if it doesn't exist (for legacy databases)."""
    from app.models.material_image import MaterialImage
    MaterialImage.__table__.create(bind=engine, checkfirst=True)
```

在 `run_migrations` 函数中调用它（在现有 `ensure_*` 调用之后）。

- [ ] **Step 5: 验证模型加载**

```bash
cd f:\course-learning-agent\backend
.venv\Scripts\python -c "from app.models.material_image import MaterialImage; print('OK:', MaterialImage.__tablename__)"
```
Expected: `OK: material_images`

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/app/models/material_image.py backend/app/models/__init__.py backend/app/db/migrations.py
git commit -m "feat: add MaterialImage model and PyMuPDF/Pillow dependencies"
```

---

### Task 2: PDF 图片提取函数 (TDD)

**Files:**
- Create: `backend/app/tests/test_image_extractor.py`
- Create: `backend/app/retrieval/image_extractor.py`

- [ ] **Step 1: 写失败测试**

Create `backend/app/tests/test_image_extractor.py`:
```python
"""Tests for PDF image extraction."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from app.retrieval.image_extractor import extract_images_from_pdf, ImageInfo


class TestImageInfo:
    def test_image_info_creation(self):
        info = ImageInfo(page_no=1, image_bytes=b"\x89PNG", width=100, height=200, format="png")
        assert info.page_no == 1
        assert info.width == 100
        assert info.height == 200
        assert info.format == "png"


class TestExtractImagesFromPdf:
    def test_returns_empty_list_for_nonexistent_file(self):
        result = extract_images_from_pdf("/nonexistent/file.pdf")
        assert result == []

    def test_extracts_images_from_real_pdf(self):
        """Integration test: extract images from a real PDF file."""
        # Find any existing PDF in storage
        storage = Path("../storage/uploads")
        pdfs = list(storage.rglob("*.pdf"))
        if not pdfs:
            pytest.skip("No PDF files found in storage")
        result = extract_images_from_pdf(str(pdfs[0]))
        # Should return a list of ImageInfo objects
        assert isinstance(result, list)
        for img in result:
            assert isinstance(img, ImageInfo)
            assert img.page_no >= 1
            assert len(img.image_bytes) > 0

    def test_handles_pdf_with_no_images(self):
        """A text-only PDF should return an empty list."""
        storage = Path("../storage/uploads")
        pdfs = list(storage.rglob("*.pdf"))
        if not pdfs:
            pytest.skip("No PDF files found in storage")
        # This test just verifies no crash; result may or may not be empty
        result = extract_images_from_pdf(str(pdfs[0]))
        assert isinstance(result, list)
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd f:\course-learning-agent\backend
.venv\Scripts\python -m pytest app/tests/test_image_extractor.py -v --tb=short 2>&1 | Select-Object -Last 10
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.retrieval.image_extractor'`

- [ ] **Step 3: 实现 image_extractor.py**

Create `backend/app/retrieval/image_extractor.py`:
```python
"""Extract embedded images from PDF files using PyMuPDF (fitz)."""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ImageInfo:
    """Metadata for a single extracted image."""
    page_no: int
    image_bytes: bytes
    width: Optional[int] = None
    height: Optional[int] = None
    format: str = "png"
    xref: Optional[int] = None


def extract_images_from_pdf(file_path: str, *, min_size: int = 50) -> List[ImageInfo]:
    """Extract embedded images from a PDF file.

    Args:
        file_path: Absolute path to the PDF file.
        min_size: Minimum width/height in pixels to include (filters out tiny icons/logos).

    Returns:
        List of ImageInfo objects, one per extracted image.
    """
    path = Path(file_path)
    if not path.exists():
        logger.warning("PDF file not found: %s", file_path)
        return []

    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("PyMuPDF (fitz) is not installed. Run: pip install PyMuPDF")
        return []

    images: List[ImageInfo] = []
    try:
        doc = fitz.open(str(path))
    except Exception as e:
        logger.error("Failed to open PDF %s: %s", file_path, e)
        return []

    try:
        for page_index in range(len(doc)):
            page = doc[page_index]
            page_no = page_index + 1
            image_list = page.get_images(full=True)

            for img_info in image_list:
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    if not base_image or not base_image.get("image"):
                        continue

                    img_bytes = base_image["image"]
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)

                    # Filter out tiny images (icons, logos, etc.)
                    if width < min_size or height < min_size:
                        continue

                    img_format = base_image.get("ext", "png")
                    # Normalize format
                    if img_format in ("jpeg", "jpg"):
                        img_format = "jpg"
                    else:
                        img_format = "png"

                    images.append(ImageInfo(
                        page_no=page_no,
                        image_bytes=img_bytes,
                        width=width,
                        height=height,
                        format=img_format,
                        xref=xref,
                    ))
                except Exception as e:
                    logger.debug("Failed to extract image xref=%s on page %d: %s", xref, page_no, e)
                    continue
    finally:
        doc.close()

    logger.info("Extracted %d images from %s", len(images), file_path)
    return images
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd f:\course-learning-agent\backend
.venv\Scripts\python -m pytest app/tests/test_image_extractor.py -v --tb=short 2>&1 | Select-Object -Last 15
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/retrieval/image_extractor.py backend/app/tests/test_image_extractor.py
git commit -m "feat: add PDF image extraction with PyMuPDF (TDD)"
```

---

### Task 3: 集成到解析流程 + 图片存储 + 静态服务

**Files:**
- Modify: `backend/app/services/material_parser.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: 在 parse_with_retry 中插入图片提取**

在 `material_parser.py` 的 `parse_with_retry` 函数中，在 chunks 创建完成后（`db.flush()` 之后），添加图片提取逻辑:

```python
# --- Image extraction (PDF only) ---
if material.file_type.lower() == "pdf":
    try:
        from app.retrieval.image_extractor import extract_images_from_pdf
        from app.models.material_image import MaterialImage

        # Delete old images for this material (idempotent re-parse)
        db.query(MaterialImage).filter(
            MaterialImage.material_id == material_id
        ).delete(synchronize_session=False)

        file_path_obj = Path(settings.UPLOAD_DIR) / material.file_path
        extracted = extract_images_from_pdf(str(file_path_obj))

        # Build a page -> chunk_id map for association
        page_to_chunk = {}
        for mc in saved_chunks:
            if mc.page_no:
                page_to_chunk.setdefault(mc.page_no, mc.id)

        # Save images to disk and create DB records
        img_dir = Path(settings.UPLOAD_DIR) / material.file_path.replace(f"original.{material.file_type}", "") / "images"
        img_dir.mkdir(parents=True, exist_ok=True)

        for idx, img in enumerate(extracted):
            img_filename = f"page{img.page_no}_{idx}.{img.format}"
            img_full_path = img_dir / img_filename
            img_full_path.write_bytes(img.image_bytes)

            # Relative path for URL serving
            rel_path = str(img_full_path.relative_to(Path(settings.UPLOAD_DIR))).replace("\\", "/")

            db.add(MaterialImage(
                material_id=material_id,
                course_id=material.course_id,
                chunk_id=page_to_chunk.get(img.page_no),
                page_no=img.page_no,
                image_filename=img_filename,
                image_path=rel_path,
                width=img.width,
                height=img.height,
                format=img.format,
            ))
        db.flush()
        logger.info("Saved %d images for material %s", len(extracted), material_id)
    except Exception as e:
        logger.warning("Image extraction failed for material %s: %s", material_id, e)
        # Non-fatal: text chunks are still usable without images
```

- [ ] **Step 2: 在 main.py 挂载静态文件服务**

在 `backend/app/main.py` 的路由注册之后添加:

```python
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from pathlib import Path

upload_dir = Path(settings.UPLOAD_DIR)
upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(upload_dir)), name="uploads")
```

- [ ] **Step 3: 验证静态服务**

```bash
# Restart backend, then check a known uploaded file
curl -I http://127.0.0.1:8000/uploads/
```
Expected: HTTP 200 or 404 (not connection refused)

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/material_parser.py backend/app/main.py
git commit -m "feat: integrate image extraction into parse pipeline + static file serving"
```

---

### Task 4: API 端点 + Schema 扩展

**Files:**
- Modify: `backend/app/schemas/material.py`
- Modify: `backend/app/api/v1/endpoints/parse.py`

- [ ] **Step 1: 扩展 Schema**

在 `backend/app/schemas/material.py` 中添加:

```python
class ImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    page_no: int
    image_path: str
    width: Optional[int] = None
    height: Optional[int] = None
    format: str = "png"
```

修改 `ChunkResponse` 添加 images 字段:
```python
class ChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    material_id: int
    chunk_index: int
    text: str
    title: Optional[str] = None
    page_no: Optional[int] = None
    token_count: Optional[int] = None
    images: List[ImageResponse] = []
```

- [ ] **Step 2: 修改 chunks API 返回关联图片**

在 `parse.py` 的 `list_chunks` 函数中，在返回 chunks 之前查询关联图片:

```python
from app.models.material_image import MaterialImage
from app.schemas.material import ImageResponse

# After fetching chunks, load images for those chunks
chunk_ids = [c.id for c in items]
page_nos = list(set(c.page_no for c in items if c.page_no))

images_db = db.query(MaterialImage).filter(
    MaterialImage.material_id == material_id,
    MaterialImage.page_no.in_(page_nos) if page_nos else False,
).all() if page_nos else []

# Group images by page_no
from collections import defaultdict
images_by_page = defaultdict(list)
for img in images_db:
    images_by_page[img.page_no].append(img)

# Attach images to chunks
chunk_responses = []
for c in items:
    chunk_dict = ChunkResponse.model_validate(c).model_dump()
    if c.page_no and c.page_no in images_by_page:
        chunk_dict["images"] = [ImageResponse.model_validate(img) for img in images_by_page[c.page_no]]
    chunk_responses.append(ChunkResponse(**chunk_dict))
```

- [ ] **Step 3: 验证 API**

```bash
# Restart backend, then call chunks API
curl -s http://127.0.0.1:8000/api/v1/materials/10/chunks?page=1\&page_size=2 -H "Authorization: Bearer <token>" | python -m json.tool | Select-Object -First 30
```
Expected: chunks have `images` field (may be empty if not yet re-parsed)

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas/material.py backend/app/api/v1/endpoints/parse.py
git commit -m "feat: extend ChunkResponse with images and serve via API"
```

---

### Task 5: 前端 LearnView 展示图片

**Files:**
- Modify: `frontend/src/api/material.ts`
- Modify: `frontend/src/views/LearnView.vue`

- [ ] **Step 1: 扩展 Chunk 类型**

在 `frontend/src/api/material.ts` 的 `Chunk` interface 中添加:

```typescript
export interface ChunkImage {
  id: number
  page_no: number
  image_path: string
  width?: number
  height?: number
  format: string
}

export interface Chunk {
  id: number
  chunk_index: number
  title: string
  page_no: number
  text: string
  keyword_text?: string
  images?: ChunkImage[]
}
```

- [ ] **Step 2: 在 LearnView.vue 展示图片**

在 `.doc-chunk-text` 之后添加图片展示区域:

```html
<div v-if="chunk.images && chunk.images.length > 0" class="doc-chunk-images">
  <div
    v-for="img in chunk.images"
    :key="img.id"
    class="doc-chunk-image-item"
  >
    <el-image
      :src="`http://127.0.0.1:8000/uploads/${img.image_path}`"
      :preview-src-list="[`http://127.0.0.1:8000/uploads/${img.image_path}`]"
      fit="contain"
      style="max-width: 100%; max-height: 400px; border-radius: 6px;"
      loading="lazy"
    >
      <template #placeholder>
        <div class="image-placeholder">图片加载中...</div>
      </template>
      <template #error>
        <div class="image-error">图片加载失败</div>
      </template>
    </el-image>
  </div>
</div>
```

添加样式:
```css
.doc-chunk-images {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.doc-chunk-image-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  overflow: hidden;
  background: #fafafa;
}

.image-placeholder,
.image-error {
  padding: 20px;
  text-align: center;
  color: #909399;
  font-size: 13px;
}
```

- [ ] **Step 3: 构建前端**

```bash
cd f:\course-learning-agent\frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/material.ts frontend/src/views/LearnView.vue
git commit -m "feat: display extracted images in learn view"
```

---

### Task 6: 重新解析资料 + agent-browser 验证

- [ ] **Step 1: 重启后端 + 重新解析一份PDF**

```bash
# Restart backend
# Then trigger re-parse via API
curl -X POST http://127.0.0.1:8000/api/v1/materials/10/parse -H "Authorization: Bearer <token>"
```

- [ ] **Step 2: 验证图片已提取**

```bash
# Check material_images table
.venv\Scripts\python -c "
from app.core.database import SessionLocal
from app.models.material_image import MaterialImage
db = SessionLocal()
imgs = db.query(MaterialImage).filter(MaterialImage.material_id == 10).all()
print(f'Found {len(imgs)} images')
for img in imgs[:5]:
    print(f'  page={img.page_no}, path={img.image_path}, {img.width}x{img.height}')
"
```

- [ ] **Step 3: agent-browser 验证学习页面**

```bash
agent-browser open http://localhost:5173/courses/5/learn
agent-browser wait --load networkidle
agent-browser screenshot learn_with_images.png
```
Expected: Document chunks show images below text content.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete PDF image extraction and display pipeline"
git push origin main
```
