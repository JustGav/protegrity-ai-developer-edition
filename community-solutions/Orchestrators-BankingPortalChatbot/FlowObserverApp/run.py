#!/usr/bin/env python3
"""FlowObserverApp — standalone launcher."""
import os
import sys
from pathlib import Path

_PARENT = str(Path(__file__).resolve().parent.parent)
_LOCAL = str(Path(__file__).resolve().parent)
os.chdir(_PARENT)
sys.path.insert(0, _LOCAL)
sys.path.insert(1, _PARENT)

try:
    from dotenv import load_dotenv
    load_dotenv(Path(_PARENT) / ".env", override=True)
except ImportError:
    pass

import app as app_module

app_module.app.template_folder = os.path.join(_LOCAL, "templates")
app_module.app.static_folder = os.path.join(_LOCAL, "static")

if __name__ == "__main__":
    port = int(os.environ.get("OBSERVER_PORT", 5004))
    print(f"[FlowObserverApp] Pipeline Observer on port {port}")
    app_module.app.run(host="0.0.0.0", port=port, debug=False)
