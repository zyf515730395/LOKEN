# Learning topics and detail tags

Approved 2026-09-06. Navigation order: Image Gen&Edit, Video Gen&Edit, 3D Gen&Recon, World Model, Relighting, Depth Estimation. Unified Model has no navigation or collection topic. Old archive records and summary URLs remain intact; aliases merge the two old 3D views without deleting papers.

## Collection and publication

Collection searches title and abstract with broad synonyms, abbreviations, task and method families. No subject-category restriction or ten-result truncation. UTC lookback defaults to seven days, overlap to two days; successful topic cursors advance independently. All API pages in each bounded keyword query are consumed. This improves recall but cannot guarantee retrieval of papers whose titles/abstracts contain none of the configured terms or that arXiv has not indexed yet.

New candidates stay in the ledger until the existing local curation workflow accepts and promotes them. Only new candidates collected since the configured rollout timestamp require acceptance for public lists, statistics and search. Per the user's correction, historical records are not re-screened, removed or bulk reclassified.

## Tag dimensions

`topics` controls navigation; `tags` contains only the configured method, task and representation terms. A paper may use multiple method families; mentioning a method as a baseline does not qualify. Missing evidence permits empty tags. All model outputs are validated against the configured vocabulary.

| Research area | Method families covered | Source |
| --- | --- | --- |
| Image / video generation and editing | Diffusion, autoregressive, flow matching, masked modeling, GAN, VAE, consistency models | [Autoregressive survey](https://arxiv.org/abs/2411.05902), [Diffusion survey](https://arxiv.org/abs/2209.00796), [Flow Matching survey, author-uploaded preprint](https://www.researchgate.net/publication/407042767_Flow_Matching_for_Visual_Generation_A_Comprehensive_Survey/download) |
| 3D generation / reconstruction | Generative families, score distillation, differentiable/inverse rendering; NeRF, Gaussian, mesh and implicit representations are separate tags | [Advances in Neural Rendering](https://arxiv.org/abs/2111.05849), [3D/4D World Modeling survey](https://worldbench.github.io/survey) |
| World models | Autoregressive, diffusion/flow, latent dynamics and joint embedding prediction | [3D/4D survey](https://worldbench.github.io/survey), [World-model survey by its authors](https://www.chefrobotics.ai/post/world-models-and-world-action-models-an-accessible-and-comprehensive-survey) |
| Relighting | Inverse rendering, differentiable rendering and generative methods | [Illumination and Relighting survey](https://diglib.eg.org/items/bb70977e-9af7-49ca-bc2b-e446bc2401e4) |
| Depth estimation | Direct regression, geometric matching and generative methods | [Comprehensive Depth Estimation survey](https://doi.org/10.1145/3677327) |

This vocabulary is an engineering synthesis of the cited sources, not a verbatim taxonomy from a single survey. Runtime prompts receive the configured descriptions, not external web content.

The task whitelist is deliberately small: Relighting, Depth Estimation, Neural Rendering, 3D Reconstruction. Do not add every conditioning mode, application or dataset as another task. Image/video topic names are not detail tags.

Representation tags are included because they answer a different question from generation methods. Potential later dimensions are learning strategy (self-supervision, distillation, preference optimization) and contribution type (method, dataset, benchmark). Avoid quality rankings or unsupported efficiency labels. The existing paper/survey distinction remains.

## Institutions and reading

Use explicit author-affiliation HTML markup or citation institution metadata. Preserve multiple institutions, deduplicate them, discard email-only text. Ambiguous or unavailable affiliation evidence—including unstructured PDF author text—remains empty and renders as `-`. Do not guess from names. Existing historical papers are not downloaded or annotated in bulk as part of this change.

The right panel continues to load only the selected paper's article. Remove the complete-summary link and its fallback message. Historical summary documents remain available through their existing URLs.

## Operations

The supported `papers.annotations run` command defaults to newly accepted papers since the rollout timestamp. Explicit `--paper` is the opt-in path for a selected historical paper. The local weekday runtime runs annotation after summarization and stages only the validated public annotation catalog alongside generated pages. Source evidence, model responses and operational scripts remain local.
