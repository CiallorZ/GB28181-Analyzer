import logging

from app.core.config import settings
from app.core.logging import configure_logging


def test_configure_logging_writes_rotating_file(tmp_path):
    path = configure_logging(tmp_path, force=True)
    try:
        logging.getLogger('gb28181.test').error('disk evidence')
        for handler in logging.getLogger().handlers:
            handler.flush()
        text = path.read_text(encoding='utf-8')
        assert 'gb28181.test' in text
        assert 'disk evidence' in text
    finally:
        configure_logging(settings.LOG_DIR, force=True)
