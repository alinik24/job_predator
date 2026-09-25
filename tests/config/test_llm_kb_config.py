import pytest
from pathlib import Path
import yaml

CONFIG_PATH = Path("config/llm_kb_config.yaml")


@pytest.fixture
def llm_config() -> dict:
    """Load LLM KB config for tests"""
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)


def test_llm_kb_config_exists() -> None:
    """Test that LLM KB config file exists"""
    assert CONFIG_PATH.exists(), "LLM KB config file not found"


def test_llm_kb_config_has_required_fields(llm_config) -> None:
    """Test that config has all required model presets"""
    assert 'llm' in llm_config
    assert 'provider' in llm_config['llm']
    assert 'api_key_env' in llm_config['llm']
    assert 'models' in llm_config['llm']
    assert 'analysis' in llm_config['llm']['models']
    assert 'generation' in llm_config['llm']['models']
    assert 'embedding' in llm_config['llm']['models']


def test_analysis_model_config(llm_config) -> None:
    """Test analysis model has required parameters"""
    analysis = llm_config['llm']['models']['analysis']
    assert 'name' in analysis
    assert 'temperature' in analysis
    assert 'max_tokens' in analysis
    assert analysis['temperature'] <= 0.2  # Low temp for analysis


def test_generation_model_config(llm_config) -> None:
    """Test generation model has required parameters"""
    generation = llm_config['llm']['models']['generation']
    assert 'name' in generation
    assert 'temperature' in generation
    assert 'max_tokens' in generation


def test_embedding_model_config(llm_config) -> None:
    """Test embedding model has required parameters"""
    embedding = llm_config['llm']['models']['embedding']
    assert 'name' in embedding
    assert 'dimensions' in embedding
    assert embedding['dimensions'] > 0
