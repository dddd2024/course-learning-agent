# V7.5.0 Document Quality Baseline

Baseline commit: `63a2a176e891059023c4dd2bad630c5c9a0218bc`.

The prior `v1.0.0-rc1` tag is not accepted as a release conclusion for this
round. Its execution state still records unresolved evidence blockers, and the
learning reader has not proved that PDF visual content remains readable.

The fixed acceptance sample is the reported 40-page course-PPT PDF. The
observable failure baseline is 23 independently extracted images reported as
missing and a page 9 network-layer diagram flattened into repeated text lines.
The release contract therefore measures page coverage, decodable page assets,
HTTP readability, image-asset integrity, chunk provenance, duplicate-image
occurrences, and text coverage separately. A page fallback is usable evidence;
an absent embedded bitmap is not automatically a reader failure.

The document fixture suite must include a course-PPT PDF, vector PDF, scanned
PDF, long-table PDF, and plain-text PDF. OCR is a marked fallback only for a
page without a usable text layer.
