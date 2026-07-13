# V7.5.0 Scope Lock

## In scope

- PDF page-level rendering, embedded-image occurrence integrity, page/block
  layout mapping, original-page-first reading, document-fidelity tests, and a
  reproducible local RC evidence bundle.
- Correcting the false V7.4.4 closure claim before a new `v1.0.0-rc1`
  candidate is considered.

## Out of scope

- New chat, planning, mobile, cloud deployment, V7.6 functionality, final
  design-report material, and creating the formal `v1.0.0` tag.

## Evidence discipline

Page images are the visual source of truth; text blocks and chunks are a
separate searchable derivation. A ready asset must be physically readable by
the authenticated API and an image decoder. Every release assertion must run
against tracked code and leave a manifest that a fresh clone can verify.
