# Comprehensive UX Review & Improvement Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the course-learning-agent from "functional" to "genuinely user-friendly" by fixing critical bugs, improving visual design consistency, enhancing workflow guidance, and polishing every major view.

**Architecture:** Frontend-only changes (Vue 3 + Element Plus). No backend changes needed. Focus on: design tokens, route meta, dashboard redesign, empty states, loading states, and view-specific polish.

**Tech Stack:** Vue 3 Composition API, Element Plus, TypeScript, Vite, vis-network

---

## Issue Summary (from browser review)

### P0 - Critical Bugs
1. **Missing `User` icon import** in MainLayout.vue line 6 — profile menu icon is broken
2. **Knowledge graph not rendering** — `v-show` hides the canvas container before vis-network initializes, causing 0-dimension rendering

### P1 - High-Impact UX
3. **Brittle page title logic** — hardcoded if/else chain instead of route meta
4. **No design token system** — every view re-declares the same hex colors
5. **Dashboard "Agent 运行" confuses users** — no explanation of what this means
6. **Profile page "未配置" has no CTA** — users don't know they need to configure LLM
7. **LogsView diagnostic panels always visible** — overwhelming for regular users
8. **No loading skeleton states** — pages show blank content while loading
9. **Empty states lack actionable guidance** — "暂无数据" without next steps

### P2 - Polish
10. **Sidebar lacks visual hierarchy** — flat menu, no section grouping
11. **Course detail page is sparse** — only 4 entry cards, no progress
12. **No LLM config status indicator** in dashboard/sidebar

---

## Task 1: Fix Critical Bugs (P0)

**Files:**
- Modify: `frontend/src/layouts/MainLayout.vue` (add User import)
- Modify: `frontend/src/views/KnowledgeGraphView.vue` (fix v-show → v-if for graph container)

- [ ] **Step 1:** Add `User` to the icon import in MainLayout.vue
- [ ] **Step 2:** Fix KnowledgeGraphView.vue — change `v-show` to always render the canvas, use a loading overlay instead
- [ ] **Step 3:** Verify both fixes in browser

## Task 2: Design Token System & Route Meta

**Files:**
- Modify: `frontend/src/styles/main.css` (add CSS variables)
- Modify: `frontend/src/router/index.ts` (add meta.title to all routes)
- Modify: `frontend/src/layouts/MainLayout.vue` (use route.meta.title, apply design tokens)

- [ ] **Step 1:** Add CSS custom properties to main.css (colors, spacing, shadows)
- [ ] **Step 2:** Add `meta: { title: '...' }` to all route definitions
- [ ] **Step 3:** Replace pageTitle if/else with `route.meta.title`
- [ ] **Step 4:** Apply design tokens to MainLayout sidebar/header

## Task 3: Dashboard Redesign

**Files:**
- Modify: `frontend/src/views/DashboardView.vue`

- [ ] **Step 1:** Replace "Agent 运行" stat with "学习进度" or more user-friendly metric
- [ ] **Step 2:** Add LLM config status banner when unconfigured
- [ ] **Step 3:** Improve quick actions with better icons and descriptions
- [ ] **Step 4:** Add "学习指南" section for first-time users
- [ ] **Step 5:** Improve empty states with actionable CTAs

## Task 4: Profile Page LLM Config Guidance

**Files:**
- Modify: `frontend/src/views/ProfileView.vue`

- [ ] **Step 1:** Add prominent CTA when LLM is "未配置"
- [ ] **Step 2:** Add explanation of Mock vs Real mode
- [ ] **Step 3:** Improve LLM config dialog with better field descriptions

## Task 5: LogsView Simplification

**Files:**
- Modify: `frontend/src/views/LogsView.vue`

- [ ] **Step 1:** Collapse diagnostic panels by default (use el-collapse)
- [ ] **Step 2:** Make log table the primary focus
- [ ] **Step 3:** Add clear empty state with guidance

## Task 6: Loading States & Empty States

**Files:**
- Modify: multiple views (CoursesView, MaterialsView, TodosView, PlansView, QuizView)

- [ ] **Step 1:** Add v-loading directives where missing
- [ ] **Step 2:** Improve empty states with helpful CTAs across views
- [ ] **Step 3:** Add loading skeletons for data-heavy views

## Task 7: Course Detail Enhancement

**Files:**
- Modify: `frontend/src/views/CourseDetailView.vue`

- [ ] **Step 1:** Add learning progress indicator
- [ ] **Step 2:** Improve module cards with status badges
- [ ] **Step 3:** Add "最近活动" section

## Task 8: Sidebar & Navigation Polish

**Files:**
- Modify: `frontend/src/layouts/MainLayout.vue`

- [ ] **Step 1:** Group sidebar items into sections (学习, 工具, 设置)
- [ ] **Step 2:** Add subtle hover effects and active indicators
- [ ] **Step 3:** Improve sidebar header with app branding
