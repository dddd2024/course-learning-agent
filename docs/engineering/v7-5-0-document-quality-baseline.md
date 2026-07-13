# V7.5.0 Document Quality Baseline

Baseline commit: `63a2a176e891059023c4dd2bad630c5c9a0218bc`.

The prior `v1.0.0-rc1` tag is not accepted as a release conclusion for this
round. Its execution state still records unresolved evidence blockers, and the
learning reader has not proved that PDF visual content remains readable.

Automated acceptance is self-contained: it generates vector-graphics,
embedded-bitmap, multi-column, and scanned-page PDFs at test time. It does not
assume that a current course PDF exists in the repository, database, or upload
directory. A reported 40-page course-PPT PDF, 23 missing extracted images, or
a flattened page-9 diagram may be recorded as optional manual evidence when
the source is supplied, but their absence cannot manufacture a result or block
the automated release closure. The release contract measures page coverage,
decodable page assets, HTTP readability, image-asset integrity, chunk
provenance, duplicate-image occurrences, and text coverage separately. A page
fallback is usable evidence; an absent embedded bitmap is not automatically a
reader failure.

The fixture suite generates vector, embedded-image, multi-column, and scanned
PDFs. Additional course-PPT, long-table, and plain-text PDFs are optional
manual material. OCR is a marked fallback only for a page without a usable
text layer.
