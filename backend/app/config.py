"""
Configuration management.
Loads local .env for development and environment variables in production.
"""

import os
from dotenv import load_dotenv

project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')
if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    load_dotenv(override=True)


class Config:
    """Flask configuration."""

    SECRET_KEY = os.environ.get('SECRET_KEY', 'mirofish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    JSON_AS_ASCII = False

    # Optional HTTP Basic Auth for public deployments.
    BASIC_AUTH_USERNAME = os.environ.get('MIROFISH_USERNAME')
    BASIC_AUTH_PASSWORD = os.environ.get('MIROFISH_PASSWORD')

    # OpenAI-compatible LLM configuration.
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')

    ZEP_API_KEY = os.environ.get('ZEP_API_KEY')

    # All runtime state can be redirected to one directory. This is useful
    # with persistent/external storage and keeps projects/simulations/reports
    # under a single root.
    DEFAULT_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../uploads'))
    DATA_DIR = os.path.abspath(os.environ.get('MIROFISH_DATA_DIR', DEFAULT_DATA_DIR))
    UPLOAD_FOLDER = DATA_DIR

    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}

    DEFAULT_CHUNK_SIZE = 500
    DEFAULT_CHUNK_OVERLAP = 50

    OASIS_DEFAULT_MAX_ROUNDS = int(os.environ.get('OASIS_DEFAULT_MAX_ROUNDS', '10'))
    OASIS_SIMULATION_DATA_DIR = os.path.join(DATA_DIR, 'simulations')

    OASIS_TWITTER_ACTIONS = [
        'CREATE_POST', 'LIKE_POST', 'REPOST', 'FOLLOW', 'DO_NOTHING', 'QUOTE_POST'
    ]
    OASIS_REDDIT_ACTIONS = [
        'LIKE_POST', 'DISLIKE_POST', 'CREATE_POST', 'CREATE_COMMENT',
        'LIKE_COMMENT', 'DISLIKE_COMMENT', 'SEARCH_POSTS', 'SEARCH_USER',
        'TREND', 'REFRESH', 'DO_NOTHING', 'FOLLOW', 'MUTE'
    ]

    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))

    @classmethod
    def validate(cls) -> list[str]:
        errors: list[str] = []
        if not cls.LLM_API_KEY:
            errors.append('LLM_API_KEY is not configured')
        if not cls.ZEP_API_KEY:
            errors.append('ZEP_API_KEY is not configured')
        if os.environ.get('ZEP_API_URL'):
            errors.append('ZEP_API_URL is unsupported; MiroFish connects to Zep Cloud')
        if cls.DEBUG:
            import warnings
            warnings.warn('Flask DEBUG mode is enabled. Do not use in production.', RuntimeWarning)
        if cls.SECRET_KEY == 'mirofish-secret-key' and os.environ.get('RENDER'):
            errors.append('SECRET_KEY must be changed for a public Render deployment')
        return errors
