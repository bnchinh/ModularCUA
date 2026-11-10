# Package contents

Curated source bundle for ModularCUA. Updated 2026-11-10 (Asia/Seoul).

Included: ModularCUA source, configs, prompts/schemas/skills, local tests, utilities, essential OSWorld integration patch, and selected implementation/results reports.
Excluded: virtual environments, model weights, API keys, VM disks, Docker storage, raw per-episode event logs/screenshots, OSWorld evaluator modifications, and unrelated experiments.
The local checkpoint path in the reference manifest is redacted.

## Files and SHA256

- `.gitignore` — `4ec5e9f99099c7928fba450f26f084d0a787a0ccc7df402597e423f6e0ab3107`
- `ARCHITECTURE.md` — `44f760f0a77385df408865867fc0b96c40b7cc69e32f422c58705730e81dc077`
- `IMPLEMENTATION_STATUS.md` — `51348685afdc3a7c4ff8d9f51c29455c0299a994613721c5e033b92f9394bfc1`
- `LICENSE` — `98e34fd5ae7f951537798471058854a9e7490c392d64af94e69a6ec9ccafb263`
- `PRIME_COMPONENT_MAPPING.md` — `09ee407bb2209b32935bdcfef93e0c31d795dd6eec758d299bb826a5aee0de8e`
- `README.md` — `d28f44034c5000b0ae2122ebb491e17f2148104f21c70cbc044614788bb6a8fc`
- `configs/core_v0.yaml` — `26811891736c54939df74bafb6b113b607ace7439727678b01849f9888064ffc`
- `configs/egc_observe_only.yaml` — `9884e4fe26dc77c3848775a6041ef079d073105c862c17b60ae4c699fa73640c`
- `configs/egc_task013_observe_only.yaml` — `3463c98a6aa4b7958b705e71bacd24e11470812ef9c240ebf5c5bf097059041e`
- `configs/reference_manifest.json` — `9f304510f81837f2e2887ab51094f63b97e8b8860e21257654342977c078806e`
- `configs/verified_v1.yaml` — `2183c34c491d324f8133ece9fc88c14cf232fea2b24014105c392ce5ad263cab`
- `egc/prompts/contract_updater.md` — `e9229a1bb323ed9e09e9e61d76843dcce8f99a0d28a6bce009de7f6d93f87ce7`
- `egc/prompts/history_summarizer.md` — `60aea6060990400eec75b705862f4d6af91d934747c3743c2f81e4320e0a9f9c`
- `egc/prompts/recovery_planner.md` — `e2afba59a8b876ec2773c78e3f3de7df0839b1782e70c4e6e596d8b6714280ce`
- `egc/prompts/requirement_extractor.md` — `ebf8f79674387421b72423df3b249453807e772e6f9b454c38831187e578717e`
- `egc/prompts/self_verifier.md` — `30f50c562f60a509e8c6abfebeb907558d16ed92ddbbd095f33f9841335e3665`
- `egc/prompts/visual_state_interpreter.md` — `96ae79eb73e64c6f09a7f568aed41b3d958086dd5932f65bf19eaa9b05929f77`
- `egc/schemas/recovery.schema.json` — `2866b3d427790a4f208e4d11e93b780c16cd0b505e204281ac7f63030cb2b605`
- `egc/schemas/requirement.schema.json` — `4d2ade27834caa3b01a132ce7b4dd1d5e466bcb14d7647a385628ed5bf3ddffd`
- `egc/schemas/state_update.schema.json` — `10f9335b505ff33b8350f9d71932b476b7f38e7b1b3490a8bcd9c2a14d49f793`
- `egc/schemas/verdict.schema.json` — `2ca252581afa66205e6fc750aca8af3168ad685dc3bd42bc37acfa212fbca600`
- `egc/skills/history_summary/SKILL.md` — `92a2f3900f1988dfd163c1cd02f0266ce17228fe2048a7aa470f14a2c34c9ea2`
- `egc/skills/recovery_controller/SKILL.md` — `5c3fa08f4f566c431bedbe3891f543091b4e512bb9bccbd41903e9a7fc7d59a3`
- `egc/skills/requirement_contracts/SKILL.md` — `51da04f67c4c8361590ce01d25ef846ec9564f46696e86d1f7f6b86d47eba6fa`
- `egc/skills/self_verifier/SKILL.md` — `ebd9b603c5eb789960dc53b17cae60f51bfd99614da86466a17e4a5cfcb47a20`
- `egc/skills/structured_state/SKILL.md` — `fd7ece55eaf3e6b91dc5701100e8e54c96fc3dd231c815d5e6e7781c812c51a6`
- `integration/osworld_v2_modularcua.patch` — `f5bdb83285c4993813f23e181169e35185874f7436ff4d4256166660f2ab2ccd`
- `prompts/osworld_ipython_system.md` — `dd1f7782bf2cca14a1a39c34723eb12392149da3bbd5df4dfb6d48b8ae8291f4`
- `pyproject.toml` — `7411f6531375fe2e77cd7c885d820abd18de659580fc61176959fec6c744c435`
- `reports/P0_FIVE_TASK_RESULTS.md` — `3afe917229854f26d0f5785639030d094d8284c56636da9f8ca7b689bda71000`
- `reports/P0_VS_P1_COMPARISON.md` — `97b076b77d66f2c5ab44591b059cdfe60f21e700831e075ac17850b7726b9960`
- `reports/P1_ALL_TASKS_FULL_REPORT.docx` — `35c8888c99d1730755d3c2e30b90be07d505c3efd6faa557d70222735008ee29`
- `reports/P1_EGC_MODULE_AUDIT.md` — `fc95390d35844b2026c8c045a2ffc6e8ff1e2f08ba37bb4c23fcb71eb99dfa20`
- `reports/P1_FIVE_TASK_RESULTS.md` — `ff871faf8174456d39cdf5e419cb807fdd213914450a87b47240d0afd3f615e8`
- `reports/known_limitations.md` — `54528a335202066092c06fe2d19495cd3a6671e9744c14ea1f02ffd24e74ae05`
- `requirements.lock` — `0a4a635f987f512d73fe73eb97f0ce98549de50f32a3a11cc5ed54d99b7cff5c`
- `scripts/audit_episode.py` — `7fa71aa106dbc9b497dcd6016fcfdbc9cb07dce61a4b81380078645e30906776`
- `scripts/diagnose_gui_execution.py` — `3e4d29ff84c8ba11462e5daac4c60280809c31a44a044b0f13dc89ccd7cd202a`
- `scripts/run_p0_five_tasks.sh` — `80e38d13507095075abbe5d700a82cec91b0e49d1ce38b4dddc42ae32c5ae620`
- `src/modularcua/__init__.py` — `7b750cc32a2fa8c5519f8e918c3cc1441e383917fda648d28015ce17644b76af`
- `src/modularcua/egc/audit.py` — `bdf3ada0731adb138c02ce857feaf42dbf2f427f1cd46abdae6f03295667a86c`
- `src/modularcua/egc/runtime.py` — `b616f977a2c8e1ce48f2f0219ff8020c2271fcd2f4bdff1c25cac8e7cbe4131d`
- `src/modularcua/environments/osworld_v2/__init__.py` — `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `src/modularcua/environments/osworld_v2/runner.py` — `061a6daed474fa344d3dbb4216364bb2c4ff3c7b14195b647e1d2a7f70ac720d`
- `src/modularcua/host/__init__.py` — `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `src/modularcua/host/agent.py` — `257243c6dacd71996e04fd58a76f6579dfb590e24e952611f70a97f36564bc79`
- `src/modularcua/host/budget.py` — `199ee65d51d4f7a9dbb97bad044788d948288ec2dc73faf09260a12b1eb3c59c`
- `src/modularcua/host/capabilities.py` — `2fa7074af04912f1b6164e5f410e115a357da3563b2168818f48f9b8ef051386`
- `src/modularcua/host/context.py` — `b3f8cd29effcdfd3e65b910e10e66b25b0b065a1e184d0e88d83140861dbd2c9`
- `src/modularcua/host/journal.py` — `92e5a5f9bf0c75c00bade4ab2cd7e0a163b804453682cc492f53af0032de09d8`
- `src/modularcua/host/kernel.py` — `fd06143fa65b4445d28d4351073c6fca63e529e1f054da42b55071be774e48b0`
- `src/modularcua/host/model.py` — `76d19c1410cec18d37f0c97446d21a41846d62cad27167cdbe0f02d567914674`
- `src/modularcua/host/modules.py` — `3dc50ed87742a77df97ddec7b012da72b651660e38f6f2ce0cf807904eb1cb0d`
- `src/modularcua/host/prompt.py` — `2e3175281b1bbc66459b4674e519882adbdf0b07883df7bf203de59acb112ec4`
- `src/modularcua/host/registry.py` — `46e475e0c0faf361db8bb2c85481d62cc29529922f034688b3cf64991412eab3`
- `src/modularcua/modules/__init__.py` — `e6219095c73c25acba1ca6d69de3fa2dc5f3d0a112e483bc24ddaf8cd5cb1e65`
- `src/modularcua/modules/verified.py` — `c7267ac5b89ea345dc04419d3e1322d460981106c37ead3ef29e416d9a4cb0e9`
- `src/modularcua/types.py` — `65574575a5c56778e76f42b9509b9a097a3ea93c0da45895f7bf84c249fa436f`
- `tests/test_core.py` — `8063ff7d84a16c26c1bbd77e13662683173a2a4ef304752cb3291b195f49e03c`
- `tests/test_egc_runtime.py` — `fd0c9d7b7b902b91f0fe02d0d8cf7dc1b797b2487f1be580e849e9f8472e4d45`
- `uv.lock` — `1c9058f263ee67fe737e64a981bb249c98f10045b256c063e71a048453df23af`

