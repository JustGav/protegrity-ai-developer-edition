"""
Unit tests for the orchestration layer.

Runs WITHOUT live Protegrity services, LLM APIs, or ChromaDB.
All external dependencies are mocked.

Usage:
    cd /home/azure_usr/protegrity_ai_integrations/protegrity_demo/orchestration/BankingPortalChatbot
    pip install pytest networkx
    python -m pytest tests/test_orchestration.py -v
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Check optional deps
try:
    import networkx as nx
    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False


# ═══════════════════════════════════════════════════════════════════════
# 1. orchestration_config tests
# ═══════════════════════════════════════════════════════════════════════

class TestOrchestrationConfig:

    def test_default_orchestrator(self):
        import config.orchestration_config as cfg
        assert cfg.ORCHESTRATOR in ("langgraph", "crewai", "llamaindex")

    def test_default_llm_provider(self):
        import config.orchestration_config as cfg
        assert cfg.LLM_PROVIDER == "ollama"

    def test_get_model_name_default(self):
        import config.orchestration_config as cfg
        model = cfg.get_model_name()
        assert isinstance(model, str) and len(model) > 0

    def test_default_models_all_providers(self):
        import config.orchestration_config as cfg
        for provider in ("ollama", "openai", "anthropic", "grok"):
            assert provider in cfg.DEFAULT_MODELS
            assert provider in cfg.LLM_PROVIDERS

    def test_gate_settings_types(self):
        import config.orchestration_config as cfg
        assert isinstance(cfg.SKIP_PROTEGRITY_GATES, bool)
        assert isinstance(cfg.SKIP_SEMANTIC_GUARDRAIL, bool)
        assert 0.0 <= cfg.PII_DISCOVERY_THRESHOLD <= 1.0
        assert 0.0 <= cfg.GUARDRAIL_RISK_THRESHOLD <= 1.0

    def test_rag_settings(self):
        import config.orchestration_config as cfg
        assert isinstance(cfg.USE_KNOWLEDGE_GRAPH, bool)
        assert isinstance(cfg.USE_CHROMADB, bool)
        assert cfg.RAG_TOP_K > 0


# ═══════════════════════════════════════════════════════════════════════
# 1b. LLM API keys tests
# ═══════════════════════════════════════════════════════════════════════

class TestLLMApiKeys:

    def test_mask_api_key(self):
        from config.llm_api_keys import mask_api_key
        assert mask_api_key("") == ""
        assert mask_api_key("short") == "••••••••"
        assert mask_api_key("sk-abcdefghijklmnop") == "sk-a••••mnop"

    def test_set_and_get_api_key(self, tmp_path, monkeypatch):
        import config.llm_api_keys as keys

        monkeypatch.setattr(keys, "KEYS_FILE", tmp_path / "llm_api_keys.local.json")
        keys._runtime_keys.clear()
        keys._initialized = False

        keys.set_api_key("openai", "sk-test-key-12345")
        assert keys.get_api_key("openai") == "sk-test-key-12345"
        assert os.environ.get("OPENAI_API_KEY") == "sk-test-key-12345"

        status = keys.get_keys_status()
        assert status["openai"]["configured"] is True
        assert "sk-t" in status["openai"]["masked"]


# ═══════════════════════════════════════════════════════════════════════
# 2. Base orchestrator tests
# ═══════════════════════════════════════════════════════════════════════

class TestBaseOrchestrator:

    def test_pipeline_result_dataclass(self):
        from orchestrators.base import PipelineResult
        result = PipelineResult(answer="Hello")
        assert result.answer == "Hello"
        assert result.blocked is False
        assert result.rag_context == []
        assert result.kg_context == {}

    def test_pipeline_result_blocked(self):
        from orchestrators.base import PipelineResult
        result = PipelineResult(answer="Blocked", blocked=True, block_reason="injection")
        assert result.blocked is True
        assert "injection" in result.block_reason

    def test_base_orchestrator_is_abstract(self):
        from orchestrators.base import BaseOrchestrator
        with pytest.raises(TypeError):
            BaseOrchestrator()


# ═══════════════════════════════════════════════════════════════════════
# 3. Knowledge Graph tests
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(not HAS_NETWORKX, reason="networkx not installed")
class TestKnowledgeGraph:

    def test_query_customer_empty_graph(self):
        import common.knowledge_graph as kg
        kg._GRAPH = nx.DiGraph()
        result = kg.query_customer("CUST-999999")
        assert result == {}
        kg._GRAPH = None

    def test_query_customer_found(self):
        import common.knowledge_graph as kg

        G = nx.DiGraph()
        G.add_node("CUST-100000", node_type="Customer", name="[PERSON]Xk9[/PERSON]")
        G.add_node("ACC-001", node_type="Account", balance=5000)
        G.add_edge("CUST-100000", "ACC-001", relation="HAS_ACCOUNT")
        kg._GRAPH = G

        result = kg.query_customer("CUST-100000")
        assert result["customer_id"] == "CUST-100000"
        assert "[PERSON]" in result["name"]
        assert "HAS_ACCOUNT" in result["relations"]
        assert len(result["relations"]["HAS_ACCOUNT"]) == 1
        kg._GRAPH = None

    def test_search_nodes_with_type(self):
        import common.knowledge_graph as kg

        G = nx.DiGraph()
        G.add_node("CUST-100000", node_type="Customer", name="[PERSON]Xk9[/PERSON]")
        G.add_node("CUST-100001", node_type="Customer", name="[PERSON]Ab3[/PERSON]")
        G.add_node("ACC-001", node_type="Account", balance=5000)
        kg._GRAPH = G

        results = kg.search_nodes("Xk9", node_type="Customer")
        assert len(results) == 1
        assert results[0]["id"] == "CUST-100000"
        kg._GRAPH = None

    def test_search_nodes_no_type_filter(self):
        import common.knowledge_graph as kg

        G = nx.DiGraph()
        G.add_node("CUST-100000", node_type="Customer", name="test")
        G.add_node("ACC-001", node_type="Account", balance=5000, note="test")
        kg._GRAPH = G

        results = kg.search_nodes("test")
        assert len(results) == 2
        kg._GRAPH = None


# ═══════════════════════════════════════════════════════════════════════
# 4. RAG retriever tests (mocked ChromaDB)
# ═══════════════════════════════════════════════════════════════════════

class TestRAGRetriever:

    def test_retrieve_with_mock(self):
        import common.rag_retriever as rag

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [["Doc about CUST-100000", "Doc about CUST-100001"]],
            "metadatas": [[{"customer_id": "CUST-100000"}, {"customer_id": "CUST-100001"}]],
            "distances": [[0.1, 0.5]],
        }
        rag._COLLECTION = mock_collection

        results = rag.retrieve("billing question", top_k=2)
        assert len(results) == 2
        assert results[0]["text"] == "Doc about CUST-100000"
        assert results[0]["distance"] == 0.1
        rag._COLLECTION = None

    def test_retrieve_empty(self):
        import common.rag_retriever as rag

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }
        rag._COLLECTION = mock_collection

        results = rag.retrieve("nonexistent")
        assert results == []
        rag._COLLECTION = None


# ═══════════════════════════════════════════════════════════════════════
# 5. LLM provider factory tests (mocked)
# ═══════════════════════════════════════════════════════════════════════

class TestLLMProviderFactory:

    def test_ollama_factory(self):
        import llm_providers.factory as fac

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "message": {"content": "Local!"}
        }

        original = fac.requests
        try:
            fac.requests = MagicMock()
            fac.requests.post.return_value = mock_response
            with patch("llm_providers.factory.get_ollama_base_url", return_value="http://localhost:11434"):
                llm = fac._ollama_llm("qwen3.5:0.8b")
                result = llm([{"role": "user", "content": "Hi"}])
            assert result == "Local!"
            payload = fac.requests.post.call_args.kwargs["json"]
            assert payload["think"] is False
        finally:
            fac.requests = original

    def test_openai_factory(self):
        import llm_providers.factory as fac

        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Hello from GPT"))]
        )

        original_openai = fac.openai
        try:
            fac.openai = mock_openai
            with patch("llm_providers.factory.get_api_key", return_value="sk-test"):
                llm = fac._openai_llm("gpt-4o-mini")
                result = llm([{"role": "user", "content": "Hi"}])
            assert result == "Hello from GPT"
        finally:
            fac.openai = original_openai

    def test_anthropic_separates_system(self):
        import llm_providers.factory as fac

        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client
        mock_client.messages.create.return_value = MagicMock(
            content=[MagicMock(text="Claude says hi")]
        )

        original_anthropic = fac.anthropic
        try:
            fac.anthropic = mock_anthropic
            with patch("llm_providers.factory.get_api_key", return_value="sk-ant-test"):
                llm = fac._anthropic_llm("claude-test")
                result = llm([
                    {"role": "system", "content": "Be helpful."},
                    {"role": "user", "content": "Hi"},
                ])
            assert result == "Claude says hi"
            call_kwargs = mock_client.messages.create.call_args.kwargs
            assert "Be helpful." in call_kwargs["system"]
            assert call_kwargs["messages"] == [{"role": "user", "content": "Hi"}]
        finally:
            fac.anthropic = original_anthropic

    def test_grok_factory(self):
        import llm_providers.factory as fac

        mock_openai = MagicMock()
        mock_client = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Grok says hi"))]
        )

        original_openai = fac.openai
        try:
            fac.openai = mock_openai
            with patch("llm_providers.factory.get_api_key", return_value="xai-test"):
                llm = fac._grok_llm("grok-3-mini")
                result = llm([{"role": "user", "content": "Hi"}])
            assert result == "Grok says hi"
            mock_openai.OpenAI.assert_called_with(api_key="xai-test", base_url="https://api.x.ai/v1")
        finally:
            fac.openai = original_openai

    def test_openai_missing_key_raises(self):
        import llm_providers.factory as fac

        with patch("llm_providers.factory.get_api_key", return_value=""):
            with pytest.raises(ValueError, match="OpenAI API key not configured"):
                fac._openai_llm("gpt-4o-mini")


# ═══════════════════════════════════════════════════════════════════════
# 6. Orchestrator factory test
# ═══════════════════════════════════════════════════════════════════════

class TestOrchestratorFactory:

    def test_factory_invalid(self):
        from orchestrators import factory as orch_factory
        original = orch_factory.ORCHESTRATOR
        try:
            orch_factory.ORCHESTRATOR = "invalid"
            with pytest.raises(ValueError, match="Unknown orchestrator"):
                orch_factory.get_orchestrator()
        finally:
            orch_factory.ORCHESTRATOR = original


# ═══════════════════════════════════════════════════════════════════════
# 7. Gate skip-mode tests (no Protegrity needed)
# ═══════════════════════════════════════════════════════════════════════

class TestGateSkipMode:

    def test_gate1_skip_passthrough(self):
        mock_guard_module = MagicMock()
        with patch.dict(sys.modules, {"services": MagicMock(), "services.protegrity_guard": mock_guard_module}):
            if "common.protegrity_gates" in sys.modules:
                del sys.modules["common.protegrity_gates"]
            from common.protegrity_gates import gate1_protect
            g1 = gate1_protect("Hello John Smith", skip_gates=True)
            assert g1.protected_text == "Hello John Smith"
            assert g1.blocked is False
            assert g1.risk_score == 0.0

    def test_gate2_skip_passthrough(self):
        mock_guard_module = MagicMock()
        with patch.dict(sys.modules, {"services": MagicMock(), "services.protegrity_guard": mock_guard_module}):
            if "common.protegrity_gates" in sys.modules:
                del sys.modules["common.protegrity_gates"]
            from common.protegrity_gates import gate2_unprotect
            g2 = gate2_unprotect("Hello [PERSON]Xk9[/PERSON]", skip_gates=True)
            assert g2.restored_text == "Hello [PERSON]Xk9[/PERSON]"


# ═══════════════════════════════════════════════════════════════════════
# 8. Structural import tests
# ═══════════════════════════════════════════════════════════════════════

class TestStructuralImports:

    def test_import_config(self):
        import config.orchestration_config as orchestration_config
        assert hasattr(orchestration_config, "ORCHESTRATOR")
        assert hasattr(orchestration_config, "LLM_PROVIDER")

    def test_import_base(self):
        from orchestrators.base import BaseOrchestrator, PipelineResult
        assert PipelineResult is not None

    def test_import_rag(self):
        from common.rag_retriever import retrieve, rebuild_index
        assert callable(retrieve)

    @pytest.mark.skipif(not HAS_NETWORKX, reason="networkx not installed")
    def test_import_kg(self):
        from common.knowledge_graph import get_graph, query_customer, search_nodes
        assert callable(query_customer)

    def test_import_llm_factory(self):
        from llm_providers.factory import get_llm, get_llm_for_langchain
        assert callable(get_llm)

    def test_import_orch_factory(self):
        from orchestrators.factory import get_orchestrator
        assert callable(get_orchestrator)
