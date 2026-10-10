import os

from django.core.wsgi import get_wsgi_application

from config.runtime import declare_process

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
# Unconditional: the web entry point is always enforced, whatever CATALYST_PROCESS says (config.runtime).
declare_process("web")
application = get_wsgi_application()
