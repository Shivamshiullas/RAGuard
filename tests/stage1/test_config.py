import pytest

from raguard.config import FEATURES, load_settings


def test_stage_1_has_no_later_features(tmp_path):
    s = load_settings({"RAGUARD_STAGE": "1", "RAGUARD_DATA_DIR": str(tmp_path)})
    assert s.features == frozenset()
    assert s.llm_chain == ("gemini",)
    assert s.gemini_model and s.gemini_temperature == 0.1 and s.gemini_max_output_tokens > 0


def test_stage_3_turns_on_everything_but_extras(tmp_path):
    s = load_settings({"RAGUARD_STAGE": "3", "RAGUARD_DATA_DIR": str(tmp_path)})
    assert set(FEATURES) - s.features == {"extras", "vision_parser"}
    assert s.llm_chain == ("gemini", "ollama")


def test_feature_flags_override_stage(tmp_path):
    s = load_settings({"RAGUARD_STAGE": "1", "RAGUARD_DATA_DIR": str(tmp_path), "FEATURE_EXTRAS": "1",
                       "FEATURE_OCR": "true"})
    assert s.on("extras") and s.on("ocr") and not s.on("bm25")
    s3 = load_settings({"RAGUARD_STAGE": "3", "RAGUARD_DATA_DIR": str(tmp_path), "FEATURE_BM25": "0"})
    assert not s3.on("bm25") and s3.on("fallbacks")


def test_invalid_stage_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_settings({"RAGUARD_STAGE": "4", "RAGUARD_DATA_DIR": str(tmp_path)})


def test_unknown_feature_name_raises(tmp_path):
    with pytest.raises(KeyError):
        load_settings({"RAGUARD_DATA_DIR": str(tmp_path)}).on("teleport")


def test_stage_1_service_wiring(rag1):
    from raguard.answering import BasicCitations
    from raguard.retrieval import VectorRetriever

    assert isinstance(rag1.retriever, VectorRetriever)
    assert isinstance(rag1.answerer.checker, BasicCitations)
    assert rag1.bm25.size == 0  # BM25 is a Stage 3 feature
