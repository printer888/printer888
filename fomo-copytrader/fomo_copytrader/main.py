"""ASGI entry point: ``uvicorn fomo_copytrader.main:app``."""
import logging

from .api.app import create_app
from .config import get_settings

_s = get_settings()
logging.basicConfig(level=_s.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app(settings=_s)
