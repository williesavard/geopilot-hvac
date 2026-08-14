from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_foundation_directories_exist() -> None:
    expected = {
        "backend",
        "docs",
        "firmware",
        "hardware",
        "homeassistant",
        "tests",
        "tools",
    }

    missing = [name for name in sorted(expected) if not (ROOT / name).is_dir()]

    assert missing == []


def test_required_foundation_documents_exist() -> None:
    expected = {
        "README.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "LICENSE",
        "docs/PRODUCT.md",
        "docs/ARCHITECTURE.md",
        "docs/roadmap.md",
        "docs/PROTOTYPES.md",
    }

    missing = [path for path in sorted(expected) if not (ROOT / path).is_file()]

    assert missing == []


def test_local_secrets_and_generated_artifacts_are_ignored() -> None:
    ignore_patterns = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "esphome/secrets.yaml" in ignore_patterns
    assert "__pycache__/" in ignore_patterns
    assert "*.egg-info/" in ignore_patterns
    assert ".env" in ignore_patterns
    assert ".env.*" in ignore_patterns
