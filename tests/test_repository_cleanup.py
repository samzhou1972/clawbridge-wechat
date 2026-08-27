from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deprecated_extension_route_is_absent() -> None:
    for relative in (
        "extension",
        "src/clawbridge/adapters/chatgpt_web.py",
        "tests/test_chatgpt_web.py",
        "tests/chatgpt_background_test.js",
        "tests/chatgpt_content_test.js",
    ):
        assert not (ROOT / relative).exists()


def test_public_runtime_surface_has_no_deprecated_extension_references() -> None:
    public_files = [
        *ROOT.glob("src/**/*.py"),
        *ROOT.glob("docs/**/*.md"),
        ROOT / "README.md",
        ROOT / "SECURITY.md",
    ]
    content = "\n".join(path.read_text(encoding="utf-8") for path in public_files)
    for forbidden in ("8778", "chrome-extension://", "chatgpt_web", "chat-target"):
        assert forbidden not in content
