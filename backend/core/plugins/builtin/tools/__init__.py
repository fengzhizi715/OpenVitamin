from .file.plugin import register as register_file
from .python.plugin import register as register_python
from .web.plugin import register as register_web
from .sql.plugin import register as register_sql
from .http.plugin import register as register_http
from .text.plugin import register as register_text
from .time.plugin import register as register_time
from .system.plugin import register as register_system
from .vision.plugin import register as register_vision  # vision.detect_objects
from .vlm.plugin import register as register_vlm  # vlm.generate
from .image.plugin import register as register_image  # image.generate
from .shell.plugin import register as register_shell  # shell.run
from .project.plugin import register as register_project  # V2.2 project.detect

def bootstrap_tools():
    """Register all built-in tools into the global ToolRegistry."""
    register_file()
    register_python()
    register_web()
    register_sql()
    register_http()
    register_text()
    register_time()
    register_system()
    register_vision()
    register_vlm()
    register_image()
    register_shell()  # V2.2
    register_project()  # V2.2
