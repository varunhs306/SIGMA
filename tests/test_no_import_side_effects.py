import sigma.analyzer
import sigma.config


def test_config_defines_no_module_level_settings():
    assert not hasattr(sigma.config, "settings"), (
        "config.py has a module-level `settings = Settings()` again. "
        "Importing any module that uses it now reads .env and can raise."
    )


def test_analyzer_defines_no_module_level_client():
    assert not hasattr(sigma.analyzer, "client"), (
        "analyzer.py builds a Gemini client at import time. "
        "_build_prompt() is now untestable without a live API key."
    )
