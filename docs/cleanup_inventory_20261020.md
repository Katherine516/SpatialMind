# Cleanup Inventory: 2026-10-20

Status: **removed**.

This is the exact reviewed deletion list, not a wildcard cleanup policy.
Source removal uses a reviewed patch; generated-file removal verifies each
recorded SHA256 and refuses tracked files or symlinks. Protected datasets,
reports, databases, environments and packaged apps are not deletion candidates.

Files: **239**. Logical file bytes: **252507537** (240.81 MiB).
Logical bytes are not a measurement of physical disk space reclaimed.

| File (relative to project root) | Bytes | SHA256 before removal | Reason |
| --- | ---: | --- | --- |
| `spatialmind/algorithms.py` | 8119 | `342d9e6ef558138b6aa8f6956bec76fdfbf0dd920e761660864fbf0b0982879b` | Retired v1 engine; no importers; canonical runtime already replaces it. |
| `.DS_Store` | 10244 | `f8cc482791b366032907838fea6f2d5774e8c759da4ac795cf1412e31e782217` | Finder folder-display metadata, not application data. |
| `.import_linter_cache/.gitignore` | 36 | `0854de54d02353fcbd7bbef3ef1a9ddea64be3bbdac18f9b807b186d0adeface` | Regenerable import-graph cache. |
| `.import_linter_cache/CACHEDIR.TAG` | 191 | `10180539504a7192503a6b9a81ed579c3dd427bbd69e11172146972469424cd6` | Regenerable import-graph cache. |
| `.import_linter_cache/a68bfc03e4d2c13bd6edb4b727043b49a21d0f25.data.json` | 36490 | `887e9a9353abb68184c91903185b7cb0c38ad48933f020e3ec46a0d56c4e2143` | Regenerable import-graph cache. |
| `.import_linter_cache/spatialmind.meta.json` | 6984 | `139feb83179c8edc3bc7903185330757a1df8c6e7552d92648ec334c8d65d037` | Regenerable import-graph cache. |
| `build/SpatialMindStudio/Analysis-00.toc` | 8138003 | `a3460763b0ec619833eed656d173668764ba379c1bcdf2ae67922a3711364054` | Reproducible PyInstaller build intermediate; no active build. |
| `build/SpatialMindStudio/BUNDLE-00.toc` | 3167414 | `aa73ba8ab3a62d2385063a1466eaf3fe6ead3996ffae9018298ffa8ace29041e` | Reproducible PyInstaller build intermediate; no active build. |
| `build/SpatialMindStudio/COLLECT-00.toc` | 3167414 | `aa73ba8ab3a62d2385063a1466eaf3fe6ead3996ffae9018298ffa8ace29041e` | Reproducible PyInstaller build intermediate; no active build. |
| `build/SpatialMindStudio/EXE-00.toc` | 3193 | `9393aef89b25ef054752955a55feb7b3dba28207c6dce0c56180e61dc0607747` | Reproducible PyInstaller build intermediate; no active build. |
| `build/SpatialMindStudio/PKG-00.toc` | 2937 | `347b12799132f5ff2e6831a91013206ab043ab1f4ff82be42d86078e635cf76d` | Reproducible PyInstaller build intermediate; no active build. |
| `build/SpatialMindStudio/PYZ-00.pyz` | 69048093 | `a47ef2f02d63124de3dcd321bd720648002f055c82f154e954cf83b2af92318b` | Reproducible PyInstaller build intermediate; no active build. |
| `build/SpatialMindStudio/PYZ-00.toc` | 2340170 | `1bf78cf189b050942b48f363f4890fb98d227f60ad98cb2b2bedd17d3f7e1abb` | Reproducible PyInstaller build intermediate; no active build. |
| `build/SpatialMindStudio/SpatialMindStudio` | 69693648 | `3bc5cf2f1fad34c11dd28f7aa4fca952f9340e142b65becad04f23ecf559ff48` | Reproducible PyInstaller build intermediate; no active build. |
| `build/SpatialMindStudio/SpatialMindStudio.pkg` | 69068929 | `3a427b799e964bb0c4707cb372d1bd2af3ad92c41289c9fff74704194fa6dd0d` | Reproducible PyInstaller build intermediate; no active build. |
| `build/SpatialMindStudio/base_library.zip` | 847928 | `acbf2e8b822dc0148fb9518ca6f46de5d272dca08a72fb77c4d4a6b3299d6d4d` | Reproducible PyInstaller build intermediate; no active build. |
| `build/SpatialMindStudio/localpycs/pyimod01_archive.pyc` | 3113 | `629d0436f820691c5f20e3c1859b7b233b47837bfb5be7749ef52f83bbe8c8f5` | Reproducible PyInstaller build intermediate; no active build. |
| `build/SpatialMindStudio/localpycs/pyimod02_importers.pyc` | 22889 | `865e56252e91d1b72e3df660013dcb763aaa0bfccbce875b5fbc40c4481c5963` | Reproducible PyInstaller build intermediate; no active build. |
| `build/SpatialMindStudio/localpycs/pyimod03_ctypes.pyc` | 4026 | `2d023963fbf34c695f31ce6a0edac6287ef50fb8e0f1126740237dc039826a7c` | Reproducible PyInstaller build intermediate; no active build. |
| `build/SpatialMindStudio/localpycs/struct.pyc` | 285 | `db9082325487307995b1028bf3f85e916c70617908744864775aadd3807a7db7` | Reproducible PyInstaller build intermediate; no active build. |
| `build/SpatialMindStudio/warn-SpatialMindStudio.txt` | 311865 | `a2421fc3d80c5f3255e4dcdc9451576950728223a5a5fc3f5c0138b0329a4119` | Reproducible PyInstaller build intermediate; no active build. |
| `build/SpatialMindStudio/xref-SpatialMindStudio.html` | 24350197 | `ce3511963123d776b05f19168e7e2b80761d64d6331308ff21ca16c2faefa598` | Reproducible PyInstaller build intermediate; no active build. |
| `dist/.DS_Store` | 6148 | `d8b03cae5a961e8b336dad7a1800cf12ca177bfa39f1680dd453898eb58006ea` | Finder metadata outside the packaged applications. |
| `eval/__pycache__/__init__.cpython-39.pyc` | 186 | `8ee88e5887cb5c4d633ba94c7a6eaea5034823ecf614b92e2944a4ff6d3089bc` | Regenerable first-party bytecode; matching source exists. |
| `eval/__pycache__/runner.cpython-39.pyc` | 11045 | `e4610e32348f423284640b675068c0781ee4a8547f4efd1595fbefbeb8a149f1` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/advance_brain_validation.cpython-39.pyc` | 4442 | `69da34e9d7d8b53dcd5a034baa01b7be571414c1bf41e68046240822bd93760c` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/analyze.cpython-39.pyc` | 4159 | `679c21bc2db5960af6a6d92d972376a9a2bf1ae92ce462de8f4b7a0e0476a312` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/apply_cluster_labels.cpython-39.pyc` | 2714 | `3917566e1603800f29c79582d590b337ca0faf959fcb2196f59fec143bed9316` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/apply_region_naming.cpython-39.pyc` | 2740 | `c4702fcdf35c7a6cafaefe3f5ab29148130f53195f826ff8b533457e2866f0ff` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/assess_replication.cpython-39.pyc` | 4086 | `b59156176cbeab6d3a39b692ee00d452fc5c4b15d4b215b8328bb2cfe2a924ae` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/audit_modality_boundaries.cpython-39.pyc` | 7637 | `e6bc0985b4196864f369fb104a0736dd6d8cdbd9fb21788a2d8a255c79747e4a` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/build_app_icon.cpython-39.pyc` | 4494 | `6e5aa8265a6dd70bf520dd21a4eb727086058d2e719529db7a5f3583ebfaa03d` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/build_brain_comparison_report.cpython-39.pyc` | 1351 | `19760da4aaffdceb670c0404f84f0dc354c1c19a16deb4e5d19c7d9342477139` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/build_candidate_cell_labels.cpython-39.pyc` | 13603 | `df80a61a911d73065f1682ba6ea259b328245d0fbb8e4ca31c761879db0b3461` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/build_dataset_governance_manifest.cpython-39.pyc` | 1043 | `1f12198f56d85a6367554ee6635974c22a873cbb99c12526e0613a8874fd444a` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/build_glioblastoma_benchmark.cpython-39.pyc` | 1350 | `e22b47665682c22d221022c4110f87760370d9d43c161b4a6cce1ea9d7372627` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/build_macos_app.cpython-39.pyc` | 13297 | `9b941ae76f4b3d81631765de0045f718f2a693eb179b120e2a97f95b2f8d01c3` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/build_region_review_packet.cpython-39.pyc` | 2809 | `3ef5445525849f579afeb73afb7ccfc6a4f146ed5f622e7fc92b4fdb64470f26` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/build_test_fixture.cpython-39.pyc` | 7936 | `113becba6ac0ebad0f21739631f68e3d15a68fbed646848010162549ae458e29` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/build_xenium_explorer_lite.cpython-39.pyc` | 1653 | `c4cc4d896c65cec8f8ba5d42ca4bc6f61c354a27edbd5c17604118d19244d996` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/calibrate_claim_reliability.cpython-39.pyc` | 10937 | `02b2591ff854983bbd51c8bb6ecd859db73e7b8fa034399121f9f5baf4a2e668` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/check_doc_numbers.cpython-39.pyc` | 4848 | `b6d3324dcc2d791c1de88640fb346f56505fc5814d15186de8d78b55970dd8a7` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/configure_macos_signing.cpython-39.pyc` | 3724 | `0f469e281e4e57c7e77b13f0225d51b7d43225768f652a2011e7b87504d89a6b` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/evaluate_annotation_holdout.cpython-39.pyc` | 1423 | `2fb7033207e7fa7a79e7ae290ef3c95f8d07f75d4d24ac3cf02a9076590958b9` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/evaluate_correctness_release.cpython-39.pyc` | 4393 | `dc50facdf94dd363f6eb434f5adcbfee55bac2d78c4b219edb54b53b6a095f3f` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/evaluate_spatial_gene_null.cpython-39.pyc` | 3332 | `5760a03ceb2b3e62eeff2669508714aa43d66cb23c54cce716c9b0ac3497a541` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/evaluate_studio_workflow.cpython-39.pyc` | 9904 | `0730546f95a41413bafaaa5d7a89e380502be288785ce1b63dd178b3a726bbfd` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/evaluate_xenium_pilot_readiness.cpython-39.pyc` | 1413 | `8214e65ba48c81a40361c3e56b1c16d6a3a3c03c3718927837326ea2b52506d1` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/fetch_geo_xenium.cpython-39.pyc` | 9474 | `fd4fa5c43ff2d3995a0fe7729824f022602df810ad1d74a5e7b760fbbabb6bd5` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/finalize_macos_release.cpython-39.pyc` | 2565 | `d24e6667ee42908331ab57efb3f7cf67c34f9cd88c2beebcc1327233003cdd46` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/import_published_labels.cpython-39.pyc` | 11125 | `4df1b05defdf6adbcedbe28f65e6793488dff25294f48e60a5d3d97445b7fa9f` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/index_run_database.cpython-39.pyc` | 946 | `029ec31740318d5a1686b3c99e8ed269ba9adc4794d3c54ad0cc1c8082f0f004` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/manage_brain_specialist_review.cpython-39.pyc` | 2126 | `b8f227304d342b0cd36e0f0f8607b452e610326aa7784ed9ff3a9370eb663954` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/plan_expert_review.cpython-39.pyc` | 4304 | `9ad8ca8e2a0393d69590211fe68e45d8f3b893d7bb425b4739bbc204a84c8b25` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/plan_reference_donors.cpython-39.pyc` | 1435 | `a17d3822c72e1eb8291aafb405d0feaf7b2df6d9bbcf3d87be11f3ed28c7f996` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/prepare_brain_expert_benchmark.cpython-39.pyc` | 2297 | `7e8496712d9dca2f0bcca7425acfdfb2cb4999580c44ad547fbc3f8307f8e883` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/prepare_claim_reliability_review_packet.cpython-39.pyc` | 1243 | `249636c050a98bfe46931e44b34d51e5083c8cfce3906f82d16a9de948a52b80` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/prepare_glioblastoma_review_packet.cpython-39.pyc` | 1303 | `0f5bb3cd9fec7949b91f5d97c1dacd2f3a38675ecdd141834a654d8c7a8a6540` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/prepare_macos_release.cpython-39.pyc` | 4659 | `33126fc1afc577887926b921769f41e854e84c835b9223b3baa45203f93f5842` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/prepare_reference_curation.cpython-39.pyc` | 1708 | `20c02df90c68c0e3f857e8f33e38141a9ce442d22d47b2f1fc070f3866d2c089` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/prepare_xenium_expert_mvp.cpython-39.pyc` | 6849 | `2e1d929ead01f1e6bdc59caec6bd71384c08168e2578d30d66a432616c87e342` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/promote_local_agent.cpython-39.pyc` | 1593 | `4010bcd017e29dd9eb938007d765ec59c1d865b62e5824f0c788bb6ab8029619` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/replay_run.cpython-39.pyc` | 3012 | `38730dc68d5abf8f0c2d3dd9de44040f06d919df3f996a1cdece9a0d00e33f34` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/run_knowledge_pilot.cpython-39.pyc` | 4488 | `6dec67d72a5f3ef0c37413247065e18df86bf7f518df813150aab63abf5761ed` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/run_tissue_reference_assist.cpython-39.pyc` | 1827 | `b5608a40098d5c4f2d1ff11f1d578ba2fecacdb95ae4e07885ed1ea3a06dd151` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/run_validated_xenium_pilot.cpython-39.pyc` | 2438 | `2c82c01360214bdfaae1f0c707b3336565f3d384b91f3e4c2bac0f7b51a200f4` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/run_xenium_breast_mvp.cpython-39.pyc` | 10188 | `b0b96cb433722dec22f244ac5ee52db8a9cb28c6fa9cc44981b626772570cfe6` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/select_rare_class_annotation.cpython-39.pyc` | 821 | `e607322a2f62a376f055ca5c9a2fe3ba21b907f9a37615cdc8769b9294b494dc` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/size_expert_review.cpython-39.pyc` | 7452 | `3cf9137950b8ceb98f64c52f287c2631b0f616150ae9a6d776f224ff376cbe19` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/smoke_test_macos_app.cpython-39.pyc` | 16374 | `c604a800caaaedc2fbd6664a6838695109d6b7fdb544deefe8e873a137047f71` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/smoke_test_macos_window.cpython-39.pyc` | 2844 | `4e527125b09667f20f5cbaeea2ca34d1d9456d956625998b0ba649c9c1dfdf1b` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/train_claim_reliability_local.cpython-39.pyc` | 10909 | `1365c428385db64c44d498ba22d5b516aa12969a6f241db0eac8766427928a9c` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/train_spatialmind_local.cpython-39.pyc` | 14695 | `ac60626dbd2a41237b13b7a6fe0682ec1c151f00caebcda1b0ef16123243791a` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/validate_brain_model.cpython-39.pyc` | 1698 | `440c4d947fab26b998b11f3f1591931cd22e9f100aac2922ff4e9624d2469344` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/validate_real_backends.cpython-39.pyc` | 2604 | `c4c97449d2cd7009723e731bb0493dc32b8772e2442a69ee71d0f94d5a4e8707` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/validate_xenium_label_intake.cpython-39.pyc` | 4722 | `df7dc830e140d1c804a9fd2e344456ee06f6ea11e2dee076f17a1e7748719174` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/verify_reference_loading.cpython-39.pyc` | 3522 | `0f26643c7c3971251702317d7d7896b98838a4d70ad298a0f091e43c208fb968` | Regenerable first-party bytecode; matching source exists. |
| `scripts/__pycache__/write_astrocyte_label_suggestions.cpython-39.pyc` | 1246 | `de76adaad47b2a5a0867ef34fed39e2ef57fa359599fef09d314b9fbf01b17f7` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/__pycache__/__init__.cpython-312.pyc` | 389 | `098b56f78f4f910e73c75443ba47cd78f1cbce1539df77efa4e039042fdbe01c` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/__pycache__/__init__.cpython-39.pyc` | 375 | `82273a343cc969977bb403c7fa5b566508893fdb576173405e06faea1a83ddfb` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/__pycache__/agent_loop.cpython-39.pyc` | 340 | `98254e0a3e421eb545608f52f85875f8b1fc16bca9de0f2552d6f5b122d2063f` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/__pycache__/cli.cpython-39.pyc` | 6124 | `70d7cc66c8df827324cc59a07e4bbb06225739f828047334a64b14709cf71cec` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/__pycache__/config.cpython-39.pyc` | 1845 | `d6870f63861629fd439abe927300d67aaea331e0e80872cdb5a6448d0ad16f56` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/__pycache__/dataset_context.cpython-39.pyc` | 7738 | `451caa83cc9d0a0e35f48bd062d60e5b4021d750309eb4c177e9f557d04888d9` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/__pycache__/datasets.cpython-39.pyc` | 5864 | `bad33eb588c8657673f3b1861128dd17080201c7c47462fda770a8532345d73b` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/__pycache__/gatekeeper.cpython-39.pyc` | 17850 | `57f6bdbf86640762d26b92b03645a8b8c5124d766beba3b79539c365b7966764` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/__pycache__/governance.cpython-39.pyc` | 3779 | `2462d656477599740f964285926a7d832165994f3fa6ddf3570e541e785556a1` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/__pycache__/llm.cpython-39.pyc` | 6660 | `4f57fd5ba6ad6a4258137e6ed1b46854bb9c86a87ce91ef920341d153c786ecd` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/__pycache__/planner.cpython-39.pyc` | 10986 | `0de175c161974b3c15d6ed5c794ecdc7940b3e45a4f159810005c9e6f039dc0a` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/__pycache__/schemas.cpython-39.pyc` | 8188 | `cae566ac2a3cfa26b4ef504da9f4352a751d562f98c270f1025008a930cbf7fa` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/__pycache__/versioning.cpython-312.pyc` | 4741 | `cc91db7d5d7651072ec322596a884c33eae15ae750e3ab261265f98f96192d99` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/__pycache__/versioning.cpython-39.pyc` | 2929 | `413e0b25f8df898f298d195c2f288f03606787db1aef70eaeedaadec624fce05` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/__pycache__/visualization.cpython-39.pyc` | 264 | `63f4bc617528f68f29a792b037142ada783dc35065dfb3f6b30d51832777d924` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/agent/__pycache__/__init__.cpython-39.pyc` | 494 | `130a0aff95939f9771d2f43efd3e838a078ac62a9a48b99b8eda85ebbc4d1235` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/agent/__pycache__/conversation.cpython-39.pyc` | 6300 | `a0628e34b8b67e93788807fdccc0d394894c5e732b6a207df406c47935a2b867` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/agent/__pycache__/grounding.cpython-39.pyc` | 3445 | `7783e207f96c77fcac0d9f9fa0a7e49361c702d02373888fcd5453f8459539e2` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/agent/__pycache__/loop.cpython-39.pyc` | 16313 | `86bb7e6266d1a8bfc4c562d6539c204218e940b308eb2757ed82cde13a2d677a` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/agent/__pycache__/orchestrator.cpython-39.pyc` | 4779 | `56e650a090cd710e46ea1db4a4fa42df0e4804e49200fd7d2f1907e9e27eeae3` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/agent/__pycache__/planning.cpython-39.pyc` | 17774 | `cc53be9fdb748d370b328e6211b796036b8a4bd5195e43f4e7f35eac18730db1` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/agent/__pycache__/runtime.cpython-39.pyc` | 7283 | `7a150a2fe6bc555f4e08ee489a0d6d9599f0ebaac95ae8f0baefe196aff20e24` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/api/__pycache__/__init__.cpython-39.pyc` | 268 | `b77537571baaec98f7712aab7c3264179c565c0261325458a6ae582117f369cd` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/api/__pycache__/app.cpython-39.pyc` | 8219 | `22177d0b3ec65d428d4b3ee1cd7b68f536dfcfe9f8bbaaf57582f365e8490885` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/__init__.cpython-39.pyc` | 327 | `052c874cbf16ebff0be45278e1b64be716883d851f261d64db3915ac0ca0f4a3` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/__main__.cpython-39.pyc` | 1963 | `e2cb9392fc3ba8acd8108239d92b99482fc7b5e5e6a15b07a0edb07fc09e5d60` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/catalog.cpython-39.pyc` | 16312 | `32e33ded5f27989a65e62d515b27b10db4569b69f473daabd5b457a1a6a4b40d` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/config.cpython-39.pyc` | 4263 | `bdb1b610391ba726ce3e0bd6845bf4237134b2e0cf6012d2c5b01d9678ee0744` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/desktop.cpython-39.pyc` | 16974 | `87019497b05c57139898c4c953b43590b679288553a75e07326ba1c92ba4eef3` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/exports.cpython-39.pyc` | 16386 | `1f061b715a7ff73cca0ec3f676ef52f4f5fa08bd254c362f00aef741b86d5f77` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/gate.cpython-39.pyc` | 5164 | `2d2f429c2b9a41692f68215d891e4fa151b0a71171548cd0bae949a27a2361fe` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/jobs.cpython-39.pyc` | 5645 | `3cb2d9ad28b7947fcd7aa5521236805ff646b01e0bf0e8b2f19d38206ba493e6` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/knowledge_chat.cpython-39.pyc` | 14136 | `f1820b3b452742d0a55897d0a1869ce8b9033595a8c99ffa33dc62ba14dd0357` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/knowledge_runs.cpython-39.pyc` | 4390 | `d953a6d3521c833856a0d8c87ba4140d1a7fae33baeff4fdcf27d4059e665b2b` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/library.cpython-39.pyc` | 10398 | `12e63149939ddca32f287cebda0e2d280b432f48eac1b3f98b44b4526191b509` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/plan_report.cpython-39.pyc` | 17159 | `969b8759ad83bbc7fddff8f5b982f3e3dbdcbbba9737aafbcc840b2dd5cbe11c` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/planner.cpython-39.pyc` | 707 | `fe8c00320188c1dc11072c33b16a4c8679e6ee9f312ea40fb9640d3e1a0f6caf` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/resources.cpython-39.pyc` | 11402 | `564e000b48fb0eaa10bbb346bd26b66d8d7710344bb82f2a4d779c648a2d2926` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/review.cpython-39.pyc` | 12838 | `078a9dc2ef47351e6017675f461fdfabbc11fd236262d9e1ae45367cb68ecc67` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/security.cpython-39.pyc` | 3911 | `7079063e5e8f1a61fc9213f59940e129df66671737b1ee3d008e21f466fb2783` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/server.cpython-39.pyc` | 48605 | `67981fdc34d9634f2acb0ed3a3484e5c3dbd2c615e4552e1bedf8a5eedd7eb82` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/uploads.cpython-39.pyc` | 11435 | `ff211775959871e14b5dfedf2e0457ca3fc080f17632782ed06321f426b289ac` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/warmup.cpython-39.pyc` | 4628 | `b26532411bea2ca22924ec9915097abc392b169bdeeafe4761c927b8f5567351` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/app/__pycache__/workflow.cpython-39.pyc` | 17441 | `fb9de56df451d2fc5bb22dd0eda523a116beb49cd4e3406d3bc8d43a80a53818` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/batch/__pycache__/__init__.cpython-39.pyc` | 258 | `62b20d1017033ab041a579b125af10d39c25116ec4f94def8e1e78be22ac868f` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/batch/__pycache__/celery_app.cpython-39.pyc` | 341 | `a3633c311945d75a597c4fb0bb2f5bbc16928e749889176fe343bbb82c24f0e8` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/batch/__pycache__/engine.cpython-39.pyc` | 4232 | `61d93e04f37c1e41c70c5e29f3befde0c37124b7e65b31f1ed4a2b2eef84332a` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/contracts/__pycache__/__init__.cpython-39.pyc` | 2122 | `338ce730e53a3f160ca41bfe06efa10154a5080d7ba4690c450414e5c98d571c` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/contracts/__pycache__/artifacts.cpython-39.pyc` | 2183 | `d516d7cf5e739e5aa60acd2650a54c226a4f186d3e99236ef6dbdd688b1b685e` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/contracts/__pycache__/citations.cpython-39.pyc` | 655 | `84b134f79faa98f858418dbed56977104b82fd730e45f924765a71580aef0c25` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/contracts/__pycache__/claims.cpython-39.pyc` | 2847 | `d6af5ccccf774ed6433e9813261ca4eca78592cb1c14e40ade857a9293b613b8` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/contracts/__pycache__/errors.cpython-39.pyc` | 1408 | `adfcba903709ee043c3d52c4a285e5d7492cd3c30c1b89d868c6885d49f100a4` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/contracts/__pycache__/memory.cpython-39.pyc` | 1773 | `dda9d00d81ebe1a48b6d1d43ab1828148d9fb64affcadbf400c3d33f8d267546` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/contracts/__pycache__/metrics.cpython-39.pyc` | 2954 | `b57eccea5ca285c7c8449522f083025055bfc3b09cb5f013fa7cd8e4364debfb` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/contracts/__pycache__/plan.cpython-39.pyc` | 1589 | `7bc99dfbdbe8799e52e61856521d1822ad9f2e1f8660cb55b4759ed87a116bfc` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/contracts/__pycache__/reliability.cpython-39.pyc` | 1562 | `94e99906e139904ae37aeabd8248f0f81c8c44cff58fcd41ade712dd1756b129` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/contracts/__pycache__/reports.cpython-39.pyc` | 2471 | `039acf78dacea2256e53f328315e354c716feaeecb10aa2b37042b97afa8dc01` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/contracts/__pycache__/response.cpython-39.pyc` | 1176 | `0c8055b55a167e224fcc214723677f54f89792df1e10abdb4dc5ede48c10185b` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/contracts/__pycache__/review.cpython-39.pyc` | 1802 | `8f05880ddb15d8484a9379d36424823e932b561554c005219f708f72707ef008` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/contracts/__pycache__/spatial_data.cpython-39.pyc` | 5189 | `861478f8e8f214178cf67e14919b43486a55f2288d42f519e97364c3edfee583` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/contracts/__pycache__/tool_io.cpython-39.pyc` | 1606 | `3c095023eedc9982f1dd6fa5edd03cebc7a9d450f8a78f579c7d5f1c31b515d4` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/ingestion/__pycache__/__init__.cpython-39.pyc` | 1943 | `59082de9c7ac1955c9d90fd022be621fc35a129849c371c5fa9c23becfd5fcf8` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/ingestion/__pycache__/contract.cpython-39.pyc` | 2915 | `e2341496a23dd48f227a632b1e710ddef0a90c6b5b4e31de76c9a2dcf994eabd` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/ingestion/__pycache__/expression.cpython-39.pyc` | 1055 | `140eb2e3c825dc56598dd855ddc30415042ab420b5396e78a7099ea524878afd` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/ingestion/__pycache__/h5ad_access.cpython-39.pyc` | 3253 | `668f5d94b79d7670c3c7c167b1e922cc01d508f50ae087f3e70b16fcfec8deff` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/ingestion/__pycache__/identity.cpython-39.pyc` | 1608 | `b727e1436be46ed8a27d430b4e64d6df23ed9d6ed7ef2069553e09576cb50050` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/ingestion/__pycache__/labels.cpython-39.pyc` | 29946 | `22105703d411600a8cd33449c9ada8571b889fee35b344a7186f429eb99843a5` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/ingestion/__pycache__/pipeline.cpython-39.pyc` | 58285 | `b997245dea1f0ace405ef5208451a17fad25bd8167a32daac534fe9247a82f14` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/ingestion/__pycache__/readiness.cpython-39.pyc` | 8024 | `4b77b3493e6708f5d33802e75cf942793803583beaca74d445bb1acda0f31528` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/ingestion/__pycache__/reference_readiness.cpython-39.pyc` | 8739 | `93a52f83b5a6a274d0c49f690394fe700305ed2005fe1138cfcf6afeb931919d` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/ingestion/__pycache__/reference_splits.cpython-39.pyc` | 3338 | `01c68982f27d6672765782ca21f51c3d7c7b882baf8672ae43543b3a77e09be0` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/ingestion/loaders/__pycache__/__init__.cpython-39.pyc` | 368 | `84bb95f5a434947db740c0ffb587d343f694bd9369db0ace0aabcb2150b53820` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/ingestion/loaders/__pycache__/scatac.cpython-39.pyc` | 1137 | `8d7d8236ca84dd8444d7619df791252c01b793b3dd6b52623d6defe7bcf23303` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/ingestion/loaders/__pycache__/scrna.cpython-39.pyc` | 19261 | `edf16888c3dc4e45d4462c88f342390527a89c2d883eb9e8ce7671ce58c8b5b4` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/ingestion/loaders/__pycache__/xenium.cpython-39.pyc` | 2533 | `b1a47dd59b2b1f2796d346c86929e1320b3c1f25e5c8febb80a8314c13b4b216` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/knowledge/__pycache__/__init__.cpython-39.pyc` | 248 | `3c3a089fefc807a22649528cf3c639d6da6195ceb0876fe876d56b52b0c2f830` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/knowledge/__pycache__/__main__.cpython-39.pyc` | 1698 | `fd32ef9c2bdc9d7acbd6704de82313fc698b5ddf7ec928ac3206239a59a594ea` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/knowledge/__pycache__/compiler.cpython-39.pyc` | 4551 | `2effac24d32614adef22f49243050cd99c64bd995744f458c470a9c153b80256` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/knowledge/__pycache__/documents.cpython-39.pyc` | 9888 | `713e994c09c58a316f8a7bc811c6b9557bf807821af934fa551e4917c48bb57c` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/knowledge/__pycache__/evaluation.cpython-39.pyc` | 3048 | `76128abd53033921440e28ea5417cf07d7c263bea8961a5be377590f8c4e4f65` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/knowledge/__pycache__/seed.cpython-39.pyc` | 4978 | `942230e074056ce9ed75a78db6dc0a5d6e33a9c854540a827010dcdba48988d2` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/knowledge/__pycache__/store.cpython-39.pyc` | 11727 | `0b1d75ee1af785485cfbf7f6e8a726e0bf68a0b807a49e396988e2040995a14a` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/knowledge/__pycache__/workspace.cpython-39.pyc` | 22090 | `57ad0c675433ed78b4658340f54b5b9b2023463291c356155e507179ba355139` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/memory/__pycache__/__init__.cpython-39.pyc` | 470 | `58bcd8ed985c91a42b4c2a22a0edca1669e37d2dc5b3205f0f914513eee7e82e` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/memory/__pycache__/backends.cpython-39.pyc` | 11728 | `83fcde6ce87cfdc8218ee5e16aaaa8be478f5ebc0b13500bf0ee7142aadef4b4` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/methods/__pycache__/__init__.cpython-39.pyc` | 284 | `1c5ec047534ab40020118d56cbcd9253852aeebf1c33813550f0f725e0f2c466` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/methods/__pycache__/replication.cpython-39.pyc` | 4007 | `3bbe1a1362e1570510b27e21546cc6b546a1744ecd2860e1a2fb126bc4c3b721` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/methods/reliability/__pycache__/__init__.cpython-39.pyc` | 702 | `8b106091ca47ceaba6bfe731f37bc972a62bdcbc720a25a35bd39ef1669d6934` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/methods/reliability/__pycache__/calibration.cpython-39.pyc` | 6847 | `61dbf4b4f622672193ec1f798710a697733861e898c421764da4424c676b65b4` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/methods/reliability/__pycache__/controls.cpython-39.pyc` | 7786 | `90b9e32ce5ea4e812bfdcb6b7dc54e233c5035ce06e50b055b53b0834e90b521` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/methods/reliability/__pycache__/scoring.cpython-39.pyc` | 17914 | `612c053535c0193d0cf453075f911849928aba8e57cb499a8852178865290b96` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/pilot/__pycache__/__init__.cpython-39.pyc` | 571 | `aa15ce89d763993e3c5a5f1f96aed8e948adcaf62c75c387f6982c66b87fcaff` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/pilot/__pycache__/claims.cpython-39.pyc` | 3777 | `27f38362f50097a3814f1cbb9392f76db0dc0f4d24ca63bc60b5172a5be5e996` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/pilot/__pycache__/spatial_relationships.cpython-39.pyc` | 9477 | `2fe184dd9cf5a4c2c77d04ec4dc1f3605dc036228adc8dce50faed411a13d04f` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/pilot/__pycache__/xenium.cpython-39.pyc` | 118913 | `d4e0e340fdf29691cd76a0f01fc1168ac4d18a35643a2d3847e08dd7761f75ce` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/promotion/__pycache__/__init__.cpython-39.pyc` | 240 | `8891a1b955ed3086a0009d9244c65f7711eb82b933a0c6fca82d343899cb4d71` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/promotion/__pycache__/local.cpython-39.pyc` | 10979 | `e4fabf2bb7f70c2130dc173321bfc45726c6e3bd14ca0e8aac69a3de1353e238` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/review/__pycache__/__init__.cpython-39.pyc` | 962 | `ce334a722182a3fb24dd2035bfd4d2301305f557650740fcdad9efd121c213f7` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/review/__pycache__/annotation_benchmark.cpython-39.pyc` | 21558 | `7fecce6b66df20926e078fbf270bc2cc76e89d7563f4b3164ad8bf100ca48452` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/review/__pycache__/brain_benchmark.cpython-39.pyc` | 36712 | `08354b14bff92f453fcc9180f0a0dffcf8a26042692ad4f38710b357350c2ed2` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/review/__pycache__/brain_readiness.cpython-39.pyc` | 14008 | `7d21dd91ddc979f4a70888349f2c82fe589f3cd2c08c9513e589361492df2006` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/review/__pycache__/brain_validation.cpython-39.pyc` | 14348 | `9beef376b7df4881533514e2af0b40ab12a8c561988a23eb0e851dbadd08b561` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/review/__pycache__/claim_calibration.cpython-39.pyc` | 5010 | `05b5d86f844cf6f69500bf48ae1ff4f730dec7eeb2d33d604c05235eefb2575d` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/review/__pycache__/claim_truth.cpython-39.pyc` | 14141 | `f34d54d0d643607324c4b96a87025d0d71d2bba021ecd93a788b1913847dd4c1` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/review/__pycache__/development_protocol.cpython-39.pyc` | 5789 | `edc822c1b89fce4b914d2f84f3c6da184a167abccc92b3a259013982600f83d2` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/review/__pycache__/glioblastoma.cpython-39.pyc` | 22179 | `fe66bcbdd32f69e1c3cb64a3d5fc2475c0192f2f418e63218f051082a7fb4eb4` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/review/__pycache__/ontology_labels.cpython-39.pyc` | 5239 | `a83c96a2df9b3e19e85d5e2a0cc91ca64e94f2aeec6b6865b82db8f080ce5bb5` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/review/__pycache__/rare_class_selection.cpython-39.pyc` | 9784 | `dedbd488668142ebbbf55fc7b9e093dc4fe61f216edf4a169ec87385a97a4cfa` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/review/__pycache__/reference_curation.cpython-39.pyc` | 9493 | `090541d7ce6c41baf4f27eb670efddc81ac104670f817a548ae3903f504821b4` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/review/__pycache__/regions.cpython-39.pyc` | 19608 | `cebd648bafc7d4129c5ca1e0c57c84d19ddbdd852fdd23ae0df0fc26addfbb9a` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/review/__pycache__/sizing.cpython-39.pyc` | 30923 | `adc8326516c11a74687dc5aef7feb1553f9714cdf033662ed3fb62760e487e5b` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/review/__pycache__/specialist_handoff.cpython-39.pyc` | 11974 | `59d9fb58403694c329202a8232ad0041feda3290e62eb802f997b9aacdd699aa` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/storage/__pycache__/__init__.cpython-312.pyc` | 578 | `76423021fdc5814f4250df37b3fbba30c20eef7591ba71691d3bfef8a5bd4d7e` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/storage/__pycache__/__init__.cpython-39.pyc` | 556 | `61fd15b75bad90e021733492db46f262a425e3d8c118c85b8855e575dc20e755` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/storage/__pycache__/library_store.cpython-39.pyc` | 3681 | `657dbd1a9c6b24a5d44e84256aabd53c9c9e846b21c7269916656c2de0481a79` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/storage/__pycache__/reference_matrix.cpython-39.pyc` | 8215 | `2f0dcb10920b27e8184fdfff42fd22ddc1b9e9cbe7dcdc6e59c28042149c9f93` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/storage/__pycache__/replay.cpython-312.pyc` | 12410 | `dcc8d69c353049ffb6ff1932e6edde8e24724c962a4fc297c277e3bc4850cbac` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/storage/__pycache__/replay.cpython-39.pyc` | 7925 | `e1eb36f2a4afa7baad9c054bbce70f5519e7141c7889c2c76c6d7f0c99d8df1f` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/storage/__pycache__/run_store.cpython-312.pyc` | 20224 | `963b044deb4943cb0356a4204edc4767f5591f066dae14906eb2588dcced1ce1` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/storage/__pycache__/run_store.cpython-39.pyc` | 12412 | `ad5fd766151b609e2adde614aa6717bc039b9f738b72c4858fb17967b2f54c36` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/tools/__pycache__/__init__.cpython-39.pyc` | 359 | `e799b7861f11ba355613a58ac2c3c514176ffb55a8527422de1d23281fa2ec2f` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/tools/__pycache__/annotation_priors.cpython-39.pyc` | 1240 | `bd10ad4f39adfe1744107aad8c36e8ac71745c4bd113ec990793ecd0f17b0a32` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/tools/__pycache__/exceptions.cpython-39.pyc` | 1408 | `1cfc1024798c8ae4eb89166a3f51bbf43752a177b011a579723594f96cf47f48` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/tools/__pycache__/grouping.cpython-39.pyc` | 2247 | `c169d01a601c1d527a0c555e7ead8d019eec2b38b13fc58cde07af135f70d347` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/tools/__pycache__/implementations.cpython-39.pyc` | 105403 | `fc63fc3bd40817f19bb2031a3115959c5b670909de6ed59128c3621938915c55` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/tools/__pycache__/region_proposal.cpython-39.pyc` | 9553 | `380c90216f37c499e7e73e47df5adfdbb195d7b2144c56d23adc12cd5d5274f0` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/tools/__pycache__/registry.cpython-39.pyc` | 25389 | `6bb5902041fef757f2ca662ff839108111bfd1d973eb348b728a0fb70f7ba106` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/tools/__pycache__/spatial_statistics.cpython-39.pyc` | 35716 | `ddb5169ed1df1e9974c484deeee48954585978492a064bb4033b5588c618400a` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/tools/fusion/__pycache__/__init__.cpython-39.pyc` | 258 | `10f09effc95f6368bb482a4cfd2b441293bf83d9f49afe1f7167b11678f858ec` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/tools/fusion/__pycache__/fuser.cpython-39.pyc` | 1871 | `92f7c277446fcc5324852a1edad2803be0185e03b9de2e17b1345accbfac7785` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/viz/__pycache__/__init__.cpython-39.pyc` | 805 | `fe3ccdb43fc7aeb0248227cbc4ff702c1606b78a233ee2a5d509e0e6f3aa8c3a` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/viz/__pycache__/display_sampling.cpython-39.pyc` | 3247 | `678ac55dd73c5e8d30a7828dce69038d1179a8546a2dcf82df65ef231f6bb359` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/viz/__pycache__/explorer_lite.cpython-39.pyc` | 33692 | `972208f62a5bcefdf0f89e4c85dda0cdbc030cd76ab3022f5874bd0b06f30250` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/viz/__pycache__/export.cpython-39.pyc` | 9547 | `882f2ae93dfd126bba69be4f3e1aa5947e350436afa1b7c3d66d083a10bb9caf` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/viz/__pycache__/morphology.cpython-39.pyc` | 7942 | `ddccb5c662b6e15de23dcb2104237037736091cf8e50e62f11b7c63b2b3c05e9` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/viz/__pycache__/qc.cpython-39.pyc` | 11082 | `2cac4dd6f7d2efc9d151d9a2f78cd9d6d551d1ebdefc075d5536495b2fb12844` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/viz/__pycache__/renderers.cpython-39.pyc` | 13196 | `1237260766d25751358ad9cf0b8b51081760f14fc241ded8041f3773778c7fd9` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/viz/__pycache__/report.cpython-39.pyc` | 6314 | `4c31d7bef376a38f9d70996fad2ed2b09735914609ff0493e79fa8ecac13e43b` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/viz/__pycache__/router.cpython-39.pyc` | 3939 | `ce99ffb79bce0299fc39577374d74cc9caa1c50eac190e2741df6a9af4561570` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/viz/__pycache__/tables.cpython-39.pyc` | 16538 | `902d4aabca25bf1b5388e54e4bb6b798800f1775e3684cd077d548f904d1ee0c` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/workflows/__pycache__/__init__.cpython-39.pyc` | 364 | `21e276c08ca6b27ae898863a0dcc1b5b2664dacd35f2a2a037ca3b58ed4d1643` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/workflows/__pycache__/mvp.cpython-39.pyc` | 1814 | `cb9fd8736777c227e8179bc538f22318daa9eba06296d5ec50bd7869aad99f7f` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_annotation_holdout.cpython-39.pyc` | 13285 | `d32cbc008ba6354c027d252e196cd01a3c92cd298e3be5335e30c0ea6b7aef96` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_api.cpython-39.pyc` | 12207 | `76ba7197dd9becb932ac9adecc73b5356a299b7048300c129219b39548603d55` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_biological_plausibility.cpython-39.pyc` | 7481 | `a0fe4ab2a3b4cbcced98c40a655d20700237b7f66457f6d081bfe2632595ee72` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_brain_readiness.cpython-39.pyc` | 14348 | `95a6537ec683db65e49e49f7201e1d39ed0b25d2585463bb01ad1dc1e954f150` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_correctness_boundary.cpython-39.pyc` | 17810 | `0addaa65ee77548390a612204a761b3b4f9d7ec997832e970f316a867c33f831` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_knowledge_documents.cpython-39.pyc` | 11896 | `c3f28ad043d4a6d8349e0ba1ce33198e8ffdb91f2a1561b10cecefd9cab4f90b` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_knowledge_workspace.cpython-39.pyc` | 15374 | `618ef8f1594a58326089a8fa84f24bd1f6a3424a21d92d59bc91f86f56484462` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_library_knowledge_chat.cpython-39.pyc` | 15310 | `e7b6ab26809506b6a5dfda676e0d55b7f37ace59d0e0b8e19d2411e545a91640` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_macos_packaging.cpython-39.pyc` | 8634 | `8f07072c12333abc2b8976726f4230877dd62da2f3174f8713c46fa5bdf45faf` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_modality_boundaries.cpython-39.pyc` | 12164 | `4b1ed71da2a95eec4a7eefba9430a82ae9474581e86e36142e0167a851a5dc17` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_reference_curation.cpython-39.pyc` | 11664 | `cd429620f82b1c5eba29884ef36cb22687244d3da15ddbe5aef1b244560309b9` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_reference_workflow.cpython-39.pyc` | 13839 | `f769837768d56e87bb0aa23325b2f7a8753027e24d1471c00cc5c870bc454987` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_review_repairs.cpython-39.pyc` | 12155 | `a47b465a6959bf70cd476231a287246772019b85ef41902b5bcdb5bced513d64` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_reviewed_validation.cpython-39.pyc` | 13259 | `3fe8284632a681f0f9f1f6a854c63e85947ba129636586cfdee683ee3dc54f59` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_spatialmind.cpython-39.pyc` | 368612 | `bdb398d512014142fd60a4b10c384600a71c8b52a7c4b84a4d8d91af760786e0` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_studio_app.cpython-39.pyc` | 59015 | `d2c38e72ae68b80b1bc01531fe65392079b771fd9d3d72c0e2f17ae17f9b9973` | Regenerable first-party bytecode; matching source exists. |
| `tests/__pycache__/test_validation_safety.cpython-39.pyc` | 11916 | `8fad69122c65e5146dc6dd17bcd208c307f0d927e1a2d5be08d5ad401e865d2e` | Regenerable first-party bytecode; matching source exists. |
| `spatialmind/__pycache__/algorithms.cpython-39.pyc` | 8763 | `ddac09bc8b6e13e3631c911309043d53282716a9e01a6e6159bf4a2ccc88f58b` | Orphan CPython cache for a removed module, not a standalone bytecode module. |
| `spatialmind/storage/__pycache__/identity.cpython-39.pyc` | 1323 | `174835e1b02d9b965527f1f85029defcf6adf9df6c52aba658364b5d012291b0` | Orphan CPython cache for a removed module, not a standalone bytecode module. |

Empty cache/build directories were removed only after their listed files
were deleted. Caches can be recreated during later tool runs.
See [cleanup review](project_cleanup_20261020.md) for retained files and validation.
